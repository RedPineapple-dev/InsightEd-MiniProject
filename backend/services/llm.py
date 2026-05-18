"""Gemini LLM client with retries, structured output, validation, and a
circuit breaker.

Replaces ad-hoc `genai.GenerativeModel(...).generate_content(...)` calls with a
single class that:

  * configures the API key once, lazily
  * forces JSON output using `response_mime_type='application/json'`
  * retries with exponential backoff on transient errors (5xx, per-minute rate)
  * fails *fast* on daily-quota exhaustion (no point retrying for 24h)
  * trips a circuit breaker after N consecutive quota errors so the rest of a
    long pipeline run skips the LLM and uses fallbacks instead of hammering
    the API for hundreds of segments
  * validates the parsed JSON against a Pydantic schema when provided
"""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass
from typing import Any, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

from config import settings


T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    pass


class _CircuitBreaker:
    """Per-process breaker that opens after repeated quota errors.

    Once open, calls return immediately without hitting the API. Half-opens
    after `cooldown_seconds` so a long-running app can recover when the
    daily window rolls over.
    """

    def __init__(self, threshold: int = 3, cooldown_seconds: int = 600):
        self.threshold = threshold
        self.cooldown_seconds = cooldown_seconds
        self._failures = 0
        self._opened_at: Optional[float] = None
        self._reason: str = ""

    def record_failure(self, reason: str) -> None:
        self._failures += 1
        if self._failures >= self.threshold and self._opened_at is None:
            self._opened_at = time.monotonic()
            self._reason = reason
            print(
                f"[LLM] CIRCUIT OPEN — {self._failures} consecutive quota errors. "
                f"Suppressing LLM calls for {self.cooldown_seconds}s. "
                f"Last reason: {reason[:200]}"
            )

    def record_success(self) -> None:
        self._failures = 0
        if self._opened_at is not None:
            print("[LLM] CIRCUIT CLOSED — recovered.")
        self._opened_at = None
        self._reason = ""

    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        if time.monotonic() - self._opened_at > self.cooldown_seconds:
            print("[LLM] circuit half-open — allowing one probe call.")
            self._opened_at = None
            self._failures = self.threshold - 1  # one more failure reopens it
            return False
        return True

    @property
    def reason(self) -> str:
        return self._reason


def _is_daily_quota_error(message: str) -> bool:
    """Distinguish daily-quota (won't recover in seconds) from per-minute.

    Daily quota signals from Google: `GenerateRequestsPerDay`,
    `free_tier_requests`, `PerDayPerProject`. These should NOT be retried —
    they reset at midnight UTC.
    """
    m = message.lower()
    return any(s in m for s in (
        "generaterequestsperday",
        "perdayperproject",
        "free_tier_requests",
        "requestperdaypermodel",
    ))


def _is_transient_error(message: str) -> bool:
    """Per-minute rate, transient 5xx, deadline, network — worth retrying."""
    m = message.lower()
    return any(s in m for s in (
        "rate", "503", "504", "deadline", "timeout", "unavailable", "internal error"
    ))


@dataclass
class LLMResponse:
    text: str
    parsed: Optional[Any] = None
    model: str = ""
    attempts: int = 1


class LLMClient:
    """Thin retryable wrapper around `google.generativeai`.

    Singleton-style — call `get_llm()` to share one instance across the app.
    """

    def __init__(self, api_key: Optional[str] = None, default_model: Optional[str] = None):
        self.api_key = api_key or settings.gemini_api_key
        self.default_model = default_model or settings.gemini_model
        # Fallback model chain — first entry is the primary, rest are tried only
        # on quota errors. Pick models with progressively higher free-tier limits.
        self.model_chain: list[str] = _build_model_chain(self.default_model)
        self._configured = False
        self._genai = None
        self._breaker = _CircuitBreaker()
        # Lightweight per-process metrics (used by /llm/status)
        self.metrics = {
            "calls": 0,
            "cache_hits": 0,
            "successes": 0,
            "failures": 0,
            "circuit_short_circuits": 0,
        }

    def _ensure_configured(self) -> None:
        if self._configured:
            return
        if not self.api_key:
            raise LLMError("GEMINI_API_KEY is not configured")

        # Imported lazily so the rest of the app boots without the SDK installed.
        import google.generativeai as genai  # type: ignore

        genai.configure(api_key=self.api_key)
        self._genai = genai
        self._configured = True

    def is_available(self) -> bool:
        return bool(self.api_key) and not self._breaker.is_open()

    @property
    def status(self) -> dict:
        return {
            "configured": bool(self.api_key),
            "default_model": self.default_model,
            "model_chain": self.model_chain,
            "circuit_open": self._breaker.is_open(),
            "circuit_reason": self._breaker.reason if self._breaker.is_open() else "",
            "metrics": dict(self.metrics),
        }

    def log_summary(self, prefix: str = "[LLM]") -> None:
        """Single-line dump of cumulative LLM activity.

        Call this at the end of a pipeline stage or run so quota usage is
        explainable from stdout alone. Counters are cumulative since the
        process started — diff them yourself if you want per-stage deltas.
        """
        m = self.metrics
        hit_rate = (
            m["cache_hits"] / m["calls"] if m["calls"] else 0.0
        )
        print(
            f"{prefix} model={self.default_model} "
            f"calls={m['calls']} ok={m['successes']} fail={m['failures']} "
            f"cache_hits={m['cache_hits']} ({hit_rate * 100:.0f}%) "
            f"short_circuits={m['circuit_short_circuits']} "
            f"breaker_open={self._breaker.is_open()}"
        )

    # ── Core call with retry + fallback chain ──────────────────────────────
    def generate(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_output_tokens: Optional[int] = None,
        json_mode: bool = False,
        max_retries: int = 3,
    ) -> LLMResponse:
        self._ensure_configured()

        if self._breaker.is_open():
            self.metrics["circuit_short_circuits"] += 1
            raise LLMError(f"LLM circuit open: {self._breaker.reason or 'rate-limited'}")

        gen_config: dict[str, Any] = {"temperature": temperature}
        if max_output_tokens:
            gen_config["max_output_tokens"] = max_output_tokens
        if json_mode:
            gen_config["response_mime_type"] = "application/json"

        # If caller asked for a specific model, use just that. Otherwise walk
        # the fallback chain only on daily-quota errors.
        chain = [model] if model else list(self.model_chain)

        last_error: Optional[Exception] = None
        for model_name in chain:
            for attempt in range(1, max_retries + 1):
                self.metrics["calls"] += 1
                try:
                    local_model = self._genai.GenerativeModel(model_name)
                    response = local_model.generate_content(prompt, generation_config=gen_config)
                    text = (response.text or "").strip()
                    self._breaker.record_success()
                    self.metrics["successes"] += 1
                    return LLMResponse(text=text, model=model_name, attempts=attempt)
                except Exception as exc:
                    last_error = exc
                    msg = str(exc)
                    self.metrics["failures"] += 1

                    if _is_daily_quota_error(msg):
                        # Don't retry the same model — try next in chain
                        print(f"[LLM] daily quota exhausted on {model_name}; trying next fallback")
                        self._breaker.record_failure(msg)
                        break  # break attempt loop, advance model

                    if _is_transient_error(msg):
                        sleep_for = (2 ** (attempt - 1)) * 0.6 + random.uniform(0, 0.4)
                        print(
                            f"[LLM] transient error on {model_name} "
                            f"attempt {attempt}/{max_retries}; retrying in {sleep_for:.1f}s: "
                            f"{msg.splitlines()[0][:200]}"
                        )
                        time.sleep(sleep_for)
                        continue

                    # Non-retryable, non-quota → bail entirely
                    self._breaker.record_failure(msg)
                    raise LLMError(f"LLM call failed: {msg}") from exc

        # Fell through every model in the chain
        raise LLMError(f"All Gemini fallbacks exhausted: {last_error}")

    # ── Structured output (with optional MongoDB cache) ────────────────────
    def generate_json(
        self,
        prompt: str,
        schema: Type[T],
        *,
        model: Optional[str] = None,
        temperature: float = 0.1,
        max_retries: int = 3,
        cache_key: Optional[str] = None,
        cache_namespace: str = "default",
        skip_cache: bool = False,
    ) -> Optional[T]:
        """Call the LLM with JSON mode, validate against `schema`.

        If `cache_key` (or `prompt+schema` hash) hits the MongoDB cache, the
        cached response is returned without an API call. Cache writes happen
        only on validated successes.
        """
        from .llm_cache import compute_cache_key, get_cached, set_cached  # local to avoid cycle

        key = cache_key or compute_cache_key(prompt, schema.__name__, model or self.default_model)

        if not skip_cache:
            cached = get_cached(cache_namespace, key)
            if cached is not None:
                try:
                    parsed = schema.model_validate(cached)
                    self.metrics["cache_hits"] += 1
                    return parsed
                except ValidationError:
                    pass  # cached value is stale/invalid — re-fetch

        if self._breaker.is_open():
            self.metrics["circuit_short_circuits"] += 1
            return None  # callers must already cope with None

        try:
            res = self.generate(
                prompt,
                model=model,
                temperature=temperature,
                json_mode=True,
                max_retries=max_retries,
            )
        except LLMError as exc:
            print(f"[LLM] generate_json failed: {exc}")
            return None

        text = _strip_json_fences(res.text)
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            print(f"[LLM] JSON parse failed: {exc}; first 200 chars: {text[:200]!r}")
            return None

        try:
            parsed = schema.model_validate(data)
        except ValidationError as exc:
            print(f"[LLM] schema validation failed: {exc}")
            return None

        if not skip_cache:
            set_cached(cache_namespace, key, data)
        return parsed


def _build_model_chain(primary: str) -> list[str]:
    """Pick a sensible fallback chain given a primary model.

    The order is roughly "highest free-tier RPD first" so we degrade to more
    permissive models when the primary's daily limit is exhausted.
    """
    candidates = [
        primary,
        "gemini-2.5-flash-lite",
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
    ]
    seen: set[str] = set()
    out: list[str] = []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _strip_json_fences(text: str) -> str:
    s = text.strip()
    if s.startswith("```json"):
        s = s[len("```json"):].strip()
    elif s.startswith("```"):
        s = s[len("```"):].strip()
    if s.endswith("```"):
        s = s[: -len("```")].strip()
    return s


_SINGLETON: Optional[LLMClient] = None


def get_llm() -> LLMClient:
    global _SINGLETON
    if _SINGLETON is None:
        _SINGLETON = LLMClient()
    return _SINGLETON

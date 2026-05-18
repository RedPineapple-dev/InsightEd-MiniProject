"""Gemini LLM client with multi-key rotation, retries, structured output, and
validation.

Replaces ad-hoc ``genai.GenerativeModel(...).generate_content(...)`` calls
with a single class that:

  * holds a pool of API keys and rotates through them automatically
  * cools down keys that hit a quota/rate-limit error
  * retries with exponential backoff on transient errors (5xx, deadline)
  * fails *fast* when every key is simultaneously cooling down
  * forces JSON output via ``response_mime_type='application/json'``
  * validates the parsed JSON against a Pydantic schema when provided

Backward compatibility
----------------------
The legacy ``gemini_api_key`` setting is still honoured — when populated
and ``gemini_api_keys`` is empty, the manager treats it as a one-element
pool. Existing callers (alignment, annotation, etc.) need no changes.
"""

from __future__ import annotations

import json
import random
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

from config import settings
from .ai.key_manager import (
    GeminiKeyManager,
    is_quota_or_rate_error,
    is_transient_error,
)


T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    pass


@dataclass
class LLMResponse:
    text: str
    parsed: Optional[Any] = None
    model: str = ""
    attempts: int = 1
    key_index: int = 0


class LLMClient:
    """Retryable Gemini wrapper backed by a rotating key pool.

    Singleton-style — call :func:`get_llm` to share one instance across the
    process so the key-pool state is consistent.
    """

    def __init__(
        self,
        keys: Optional[list[str]] = None,
        default_model: Optional[str] = None,
        max_retries: Optional[int] = None,
        key_cooldown: Optional[int] = None,
    ):
        configured_keys = keys if keys is not None else settings.gemini_keys
        self.default_model = default_model or settings.gemini_model
        self.max_retries = int(max_retries or settings.gemini_max_retries or 4)
        self.cooldown_seconds = int(key_cooldown or settings.gemini_key_cooldown or 300)

        # Model fallback chain — only walked when *every* key has hit the
        # primary model's daily cap. With multiple keys this rarely fires.
        self.model_chain: list[str] = _build_model_chain(self.default_model)

        # Process-wide key pool.
        self.key_manager = GeminiKeyManager(
            configured_keys, cooldown_seconds=self.cooldown_seconds
        )

        # ``google.generativeai`` configures keys on a *module-global* client.
        # Concurrent generate calls with different keys must therefore be
        # serialised; this lock guards configure+generate. In practice the
        # per-call latency dominates and serialisation is fine for our scale.
        self._configure_lock = threading.Lock()
        self._genai = None
        self._current_key: Optional[str] = None  # last key passed to configure()

        # Per-process metrics surfaced on /llm/status.
        self.metrics = {
            "calls": 0,
            "cache_hits": 0,
            "successes": 0,
            "failures": 0,
            "key_rotations": 0,
            "short_circuits": 0,
        }

    # ── Configuration ───────────────────────────────────────────────────

    def _ensure_imported(self) -> None:
        if self._genai is None:
            import google.generativeai as genai  # type: ignore
            self._genai = genai

    def _configure_key(self, key: str) -> None:
        """Point google-generativeai at the supplied key.

        Cheap when the key hasn't changed (skipped), otherwise a single
        module-global ``configure`` call.
        """
        self._ensure_imported()
        if key != self._current_key:
            self._genai.configure(api_key=key)
            self._current_key = key

    # ── Public status ───────────────────────────────────────────────────

    def is_available(self) -> bool:
        """True when at least one key is currently available."""
        return self.key_manager.available_now() > 0

    @property
    def status(self) -> dict:
        km = self.key_manager.status_snapshot()
        return {
            "configured": km["total"] > 0,
            "default_model": self.default_model,
            "model_chain": self.model_chain,
            "circuit_open": km["total"] > 0 and km["available_now"] == 0,
            "circuit_reason": (
                "all keys cooling down"
                if km["total"] > 0 and km["available_now"] == 0
                else ""
            ),
            "metrics": dict(self.metrics),
            "keys": km,
        }

    def log_summary(self, prefix: str = "[LLM]") -> None:
        """Single-line dump of cumulative LLM activity (called per pipeline)."""
        m = self.metrics
        hit_rate = m["cache_hits"] / m["calls"] if m["calls"] else 0.0
        km = self.key_manager.status_snapshot()
        print(
            f"{prefix} model={self.default_model} "
            f"calls={m['calls']} ok={m['successes']} fail={m['failures']} "
            f"cache_hits={m['cache_hits']} ({hit_rate * 100:.0f}%) "
            f"rotations={m['key_rotations']} "
            f"keys={km['available_now']}/{km['total']} available"
        )

    # ── Core call with retry + key rotation + model fallback ───────────

    def generate(
        self,
        prompt: str,
        *,
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_output_tokens: Optional[int] = None,
        json_mode: bool = False,
        max_retries: Optional[int] = None,
    ) -> LLMResponse:
        if not self.key_manager.has_keys():
            raise LLMError("No Gemini API keys configured")

        gen_config: dict[str, Any] = {"temperature": temperature}
        if max_output_tokens:
            gen_config["max_output_tokens"] = max_output_tokens
        if json_mode:
            gen_config["response_mime_type"] = "application/json"

        chain = [model] if model else list(self.model_chain)
        attempt_budget = int(max_retries if max_retries is not None else self.max_retries)
        last_error: Optional[Exception] = None

        for model_name in chain:
            for attempt in range(1, attempt_budget + 1):
                key_state = self.key_manager.acquire()
                if key_state is None:
                    # Every key is currently cooling. No point spinning —
                    # this is a hard fail-fast condition.
                    self.metrics["short_circuits"] += 1
                    print(
                        f"[Gemini] all {self.key_manager.total_keys} keys cooling; "
                        f"giving up (attempt {attempt}/{attempt_budget})"
                    )
                    break

                self.metrics["calls"] += 1
                try:
                    with self._configure_lock:
                        self._configure_key(key_state.key)
                        gmodel = self._genai.GenerativeModel(model_name)
                        response = gmodel.generate_content(
                            prompt, generation_config=gen_config
                        )
                    text = (response.text or "").strip()
                    self.key_manager.report_success(key_state)
                    self.metrics["successes"] += 1
                    if attempt > 1:
                        print(
                            f"[Gemini] key#{key_state.index} model={model_name} "
                            f"recovered on attempt {attempt}"
                        )
                    return LLMResponse(
                        text=text,
                        model=model_name,
                        attempts=attempt,
                        key_index=key_state.index,
                    )

                except Exception as exc:
                    last_error = exc
                    msg = str(exc)
                    self.metrics["failures"] += 1

                    if is_quota_or_rate_error(msg):
                        # Per-key fault. Cool down + rotate immediately.
                        self.key_manager.report_quota_failure(key_state, msg)
                        self.metrics["key_rotations"] += 1
                        if self.key_manager.available_now() == 0:
                            # No point retrying within this model — try next
                            # one in the chain (often a more permissive tier).
                            print(
                                f"[Gemini] all keys cooling on {model_name}; "
                                f"advancing model chain"
                            )
                            break
                        # Otherwise loop continues with next acquire()
                        continue

                    if is_transient_error(msg):
                        # Network/5xx — same key, exponential backoff.
                        sleep_for = (2 ** (attempt - 1)) * 0.5 + random.uniform(0, 0.3)
                        print(
                            f"[Gemini] key#{key_state.index} transient on "
                            f"{model_name} (attempt {attempt}/{attempt_budget}); "
                            f"retrying in {sleep_for:.1f}s: {msg.splitlines()[0][:160]}"
                        )
                        self.key_manager.report_transient_failure(key_state, msg)
                        time.sleep(sleep_for)
                        continue

                    # Non-retryable, non-quota → bail entirely.
                    self.key_manager.report_transient_failure(key_state, msg)
                    raise LLMError(f"LLM call failed: {msg}") from exc

        raise LLMError(f"All Gemini retries exhausted: {last_error}")

    # ── Structured output (with MongoDB cache) ──────────────────────────
    def generate_json(
        self,
        prompt: str,
        schema: Type[T],
        *,
        model: Optional[str] = None,
        temperature: float = 0.1,
        max_retries: Optional[int] = None,
        cache_key: Optional[str] = None,
        cache_namespace: str = "default",
        skip_cache: bool = False,
    ) -> Optional[T]:
        """Call the LLM with JSON mode and validate against ``schema``.

        Cache hits short-circuit before any network call.
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

        if not self.is_available():
            self.metrics["short_circuits"] += 1
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

    Order is roughly "highest free-tier RPD first" so we degrade to more
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
    s = (text or "").strip()
    if s.startswith("```json"):
        s = s[len("```json"):].strip()
    elif s.startswith("```"):
        s = s[len("```"):].strip()
    if s.endswith("```"):
        s = s[: -len("```")].strip()
    return s


_SINGLETON: Optional[LLMClient] = None
_SINGLETON_LOCK = threading.Lock()


def get_llm() -> LLMClient:
    global _SINGLETON
    if _SINGLETON is None:
        with _SINGLETON_LOCK:
            if _SINGLETON is None:
                _SINGLETON = LLMClient()
                km = _SINGLETON.key_manager
                if km.total_keys:
                    print(
                        f"[Gemini] key pool initialized: {km.total_keys} key(s), "
                        f"cooldown={_SINGLETON.cooldown_seconds}s, "
                        f"max_retries={_SINGLETON.max_retries}, "
                        f"model={_SINGLETON.default_model}"
                    )
                else:
                    print("[Gemini] WARNING: no API keys configured")
    return _SINGLETON

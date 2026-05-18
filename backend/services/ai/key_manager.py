"""Thread-safe Gemini API-key pool with cooldown and round-robin rotation.

Why this module exists
----------------------
Gemini's free tier enforces per-key daily and per-minute limits. Burning
quota on one key historically killed the whole pipeline. This module lets
the backend pass an *array* of keys and:

  - rotate through them on each request
  - mark a key on cooldown when it hits a quota/rate-limit error
  - automatically re-include cooled-down keys after a timeout
  - skip keys that have failed too recently

Concurrency
-----------
A single ``threading.Lock`` guards mutations of key state. The acquire path
is short (O(N keys)) and the keys themselves are not contended — the lock
exists only to keep counters and the round-robin cursor coherent under
FastAPI's threadpool (where blocking work runs via ``run_in_executor``).

The Gemini library itself is configured process-globally via
``genai.configure(api_key=...)`` — callers that mix keys must hold an
external lock around configure + generate, since the underlying client
shares process state. The LLM client in ``services/llm.py`` does this.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class KeyState:
    """Mutable per-key health record.

    ``index`` is the 1-based position from the configured order — useful in
    logs so we never have to print the secret itself. ``cooldown_until`` is
    a ``time.monotonic()`` timestamp; a key is healthy when
    ``cooldown_until <= now``.
    """

    key: str
    index: int  # 1-based
    cooldown_until: float = 0.0
    successes: int = 0
    failures: int = 0
    last_error: str = ""
    last_used_at: float = 0.0


class GeminiKeyManager:
    """Round-robin key pool with per-key cooldown."""

    def __init__(self, keys: List[str], cooldown_seconds: int = 300):
        self.cooldown_seconds = max(1, int(cooldown_seconds))
        self._lock = threading.Lock()
        cleaned: List[KeyState] = []
        for i, k in enumerate(keys or []):
            k = (k or "").strip()
            if k:
                cleaned.append(KeyState(key=k, index=i + 1))
        self._states: List[KeyState] = cleaned
        self._cursor: int = 0

    # ── Introspection ────────────────────────────────────────────────────

    @property
    def total_keys(self) -> int:
        return len(self._states)

    def has_keys(self) -> bool:
        return bool(self._states)

    def available_now(self) -> int:
        now = time.monotonic()
        with self._lock:
            return sum(1 for s in self._states if s.cooldown_until <= now)

    # ── Acquire / report ─────────────────────────────────────────────────

    def acquire(self) -> Optional[KeyState]:
        """Return the next healthy key, advancing the round-robin cursor.

        Returns ``None`` when every key is currently on cooldown — the
        caller should fail fast or wait, not spin.
        """
        if not self._states:
            return None
        now = time.monotonic()
        with self._lock:
            n = len(self._states)
            for offset in range(n):
                idx = (self._cursor + offset) % n
                st = self._states[idx]
                if st.cooldown_until <= now:
                    st.last_used_at = now
                    self._cursor = (idx + 1) % n
                    return st
            return None

    def report_success(self, state: KeyState) -> None:
        with self._lock:
            state.successes += 1
            state.cooldown_until = 0.0
            state.last_error = ""

    def report_quota_failure(self, state: KeyState, reason: str) -> None:
        """A quota/rate-limit hit — cool this key down."""
        with self._lock:
            state.failures += 1
            state.cooldown_until = time.monotonic() + self.cooldown_seconds
            state.last_error = (reason or "")[:240]
        print(
            f"[Gemini] Key #{state.index} quota exceeded — cooling for "
            f"{self.cooldown_seconds}s. reason={(reason or '')[:120]}"
        )

    def report_transient_failure(self, state: KeyState, reason: str) -> None:
        """Network/5xx/timeout — bump the failure counter but don't cool the key.

        Transient errors aren't a quota signal; the same key may succeed on
        the very next attempt. Use ``report_quota_failure`` when the failure
        is clearly per-key.
        """
        with self._lock:
            state.failures += 1
            state.last_error = (reason or "")[:240]

    # ── Public status snapshot (safe to expose; never includes the key) ─

    def status_snapshot(self) -> dict:
        now = time.monotonic()
        with self._lock:
            keys_info = [
                {
                    "index": s.index,
                    "successes": s.successes,
                    "failures": s.failures,
                    "cooling_down": s.cooldown_until > now,
                    "cooldown_remaining_s": max(0, int(s.cooldown_until - now)),
                    "last_error": s.last_error[:160] if s.last_error else "",
                    "preview": _mask(s.key),
                }
                for s in self._states
            ]
            return {
                "total": len(self._states),
                "available_now": sum(1 for s in self._states if s.cooldown_until <= now),
                "cooldown_seconds": self.cooldown_seconds,
                "keys": keys_info,
            }


def _mask(key: str) -> str:
    """Return a logging-safe preview of an API key (first 4 + last 4 chars)."""
    if not key:
        return ""
    if len(key) <= 10:
        return "***"
    return f"{key[:4]}…{key[-4:]}"


# ── Failure classification helpers (re-used by the LLM client) ───────────


def is_quota_or_rate_error(message: str) -> bool:
    """Distinguish a per-key quota/rate hit from a transient network blip.

    Treats per-day, per-minute, RPM/TPM, and explicit ``429`` signals as
    "rotate-the-key" errors. Anything else (5xx, deadline, timeout) is a
    transient retryable error that doesn't justify cooldown.
    """
    m = (message or "").lower()
    quota_markers = (
        "generaterequestsperday",
        "perdayperproject",
        "free_tier_requests",
        "requestperdaypermodel",
        "quota",
        "exceeded",
        "rate",
        "429",
        "resource_exhausted",
        "resource exhausted",
    )
    return any(s in m for s in quota_markers)


def is_transient_error(message: str) -> bool:
    m = (message or "").lower()
    return any(s in m for s in (
        "503", "504", "500", "deadline", "timeout", "unavailable", "internal error", "connection",
    ))

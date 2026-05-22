"""MongoDB-backed LLM response cache.

Idea: many LLM calls in this app are deterministic given the same prompt and
schema (e.g. annotating the same transcript chunk twice). Caching the parsed
JSON eliminates redundant calls — the biggest single win against rate limits.

Key shape: SHA-256(`prompt | schema_name | model_name`).
TTL: 30 days (the response stops being useful long before then).
Failure mode: any DB hiccup is silently swallowed — cache is best-effort.

The cache is a no-op when MongoDB isn't connected, so the legacy file-only
mode keeps working unchanged.
"""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from db import get_db, is_connected


CACHE_TTL_DAYS = 30
COLLECTION = "llm_cache"

# In-process LRU as a fast hop in front of Mongo. Bounded so it can't grow.
_INMEM: dict[str, Any] = {}
_INMEM_KEYS: list[str] = []
_INMEM_MAX = 256


def compute_cache_key(prompt: str, schema_name: str, model_name: str) -> str:
    h = hashlib.sha256()
    h.update(prompt.encode("utf-8", errors="replace"))
    h.update(b"|")
    h.update(schema_name.encode("utf-8"))
    h.update(b"|")
    h.update(model_name.encode("utf-8"))
    return h.hexdigest()


async def _async_ensure_indexes() -> None:
    coll = get_db()[COLLECTION]
    await coll.create_index("expires_at", expireAfterSeconds=0)
    await coll.create_index([("namespace", 1), ("key", 1)], unique=True)


def _ensure_index_once() -> None:
    """Create the TTL index lazily (idempotent — Motor swallows duplicates)."""
    if not is_connected():
        return
    if getattr(_ensure_index_once, "_done", False):
        return
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(_async_ensure_indexes(), loop)
        else:
            loop.run_until_complete(_async_ensure_indexes())
    except Exception as exc:
        print(f"[llm_cache] could not ensure indexes: {exc}")
    setattr(_ensure_index_once, "_done", True)


# ── Sync API used by the LLM client (which is itself called from worker
#    threads via run_in_executor). We bridge to Motor by submitting coroutines
#    to the running loop with `asyncio.run_coroutine_threadsafe`.
def get_cached(namespace: str, key: str) -> Optional[Any]:
    composite = f"{namespace}|{key}"
    if composite in _INMEM:
        return _INMEM[composite]

    if not is_connected():
        return None
    _ensure_index_once()

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            coro = _async_get(namespace, key)
            future = asyncio.run_coroutine_threadsafe(coro, loop)
            doc = future.result(timeout=4)
        else:
            doc = loop.run_until_complete(_async_get(namespace, key))
    except Exception as exc:
        print(f"[llm_cache] get failed: {exc}")
        return None

    if doc is None:
        return None

    value = doc.get("value")
    _push_inmem(composite, value)
    return value


def set_cached(namespace: str, key: str, value: Any) -> None:
    composite = f"{namespace}|{key}"
    _push_inmem(composite, value)

    if not is_connected():
        return
    _ensure_index_once()

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.run_coroutine_threadsafe(
                _async_set(namespace, key, value), loop
            )
        else:
            loop.run_until_complete(_async_set(namespace, key, value))
    except Exception as exc:
        print(f"[llm_cache] set failed: {exc}")


# ── Async primitives (for use from FastAPI/Motor contexts directly) ────────
async def _async_get(namespace: str, key: str) -> Optional[dict]:
    return await get_db()[COLLECTION].find_one({"namespace": namespace, "key": key})


async def _async_set(namespace: str, key: str, value: Any) -> None:
    now = datetime.now(timezone.utc)
    expires = now + timedelta(days=CACHE_TTL_DAYS)
    await get_db()[COLLECTION].update_one(
        {"namespace": namespace, "key": key},
        {
            "$set": {
                "namespace": namespace,
                "key": key,
                "value": value,
                "updated_at": now,
                "expires_at": expires,
            }
        },
        upsert=True,
    )


def _push_inmem(composite: str, value: Any) -> None:
    if composite in _INMEM:
        return
    _INMEM[composite] = value
    _INMEM_KEYS.append(composite)
    if len(_INMEM_KEYS) > _INMEM_MAX:
        old = _INMEM_KEYS.pop(0)
        _INMEM.pop(old, None)


async def stats() -> dict:
    """Used by the /llm/status endpoint."""
    out = {
        "in_memory_entries": len(_INMEM_KEYS),
        "in_memory_max": _INMEM_MAX,
        "ttl_days": CACHE_TTL_DAYS,
    }
    if is_connected():
        try:
            count = await get_db()[COLLECTION].estimated_document_count()
            out["mongo_entries"] = count
        except Exception:
            out["mongo_entries"] = None
    return out

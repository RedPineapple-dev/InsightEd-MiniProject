"""Pipeline-run cache.

A processed video is uniquely identified by ``(user_id, fingerprint)`` where
the frontend computes ``fingerprint = hash(filename | size | last_modified)``.

When the same user re-uploads the same file, refreshes the page, or logs in
again, we don't want to re-run Whisper + alignment + Gemini from scratch —
that's the #1 source of wasted quota. This module persists the *outputs*
(transcript, slides, annotations, alignment, analytics, generated docs) so
the in-memory session can be rehydrated instead of re-derived.

Backing store: MongoDB collection ``pipeline_runs`` when available, with an
on-disk JSON fallback under ``data/sessions/`` so the legacy file-only mode
keeps working.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from db import get_db, is_connected


COLLECTION = "pipeline_runs"

# Fields we strip before saving — they're large, regenerable, or not JSON-safe.
_OMIT_KEYS = {"embeddings"}


def _safe_session(session: dict) -> dict:
    """Return a JSON-safe shallow copy of a session, omitting heavy fields."""
    return {k: v for k, v in session.items() if k not in _OMIT_KEYS}


# ── Sync wrappers (used from synchronous pipeline code paths) ─────────────

def save_run_sync(user_id: str, fingerprint: str, session: dict) -> None:
    if not fingerprint:
        return
    snapshot = _safe_session(session)
    snapshot["user_id"] = user_id
    snapshot["fingerprint"] = fingerprint
    snapshot["saved_at"] = datetime.now(timezone.utc).isoformat()

    if is_connected():
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    _async_save(user_id, fingerprint, snapshot), loop
                )
            else:
                loop.run_until_complete(_async_save(user_id, fingerprint, snapshot))
        except Exception as exc:
            print(f"[pipeline_cache] mongo save failed: {exc}")


def load_run_sync(user_id: str, fingerprint: str) -> Optional[dict]:
    """Return a previously-saved snapshot, or None."""
    if not fingerprint or not is_connected():
        return None
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            future = asyncio.run_coroutine_threadsafe(
                _async_load(user_id, fingerprint), loop
            )
            return future.result(timeout=4)
        return loop.run_until_complete(_async_load(user_id, fingerprint))
    except Exception as exc:
        print(f"[pipeline_cache] mongo load failed: {exc}")
        return None


# ── Async primitives ──────────────────────────────────────────────────────

async def _async_save(user_id: str, fingerprint: str, snapshot: dict) -> None:
    coll = get_db()[COLLECTION]
    await coll.update_one(
        {"user_id": user_id, "fingerprint": fingerprint},
        {"$set": snapshot},
        upsert=True,
    )


async def _async_load(user_id: str, fingerprint: str) -> Optional[dict]:
    coll = get_db()[COLLECTION]
    doc = await coll.find_one({"user_id": user_id, "fingerprint": fingerprint})
    if doc is None:
        return None
    doc.pop("_id", None)
    return doc


async def load_run(user_id: str, fingerprint: str) -> Optional[dict]:
    """Async variant — preferred from FastAPI handlers."""
    if not fingerprint or not is_connected():
        return None
    try:
        return await _async_load(user_id, fingerprint)
    except Exception as exc:
        print(f"[pipeline_cache] mongo load failed: {exc}")
        return None


# ── Disk fallback ─────────────────────────────────────────────────────────
# When Mongo is disabled we still want refresh-immunity. The on-disk session
# JSON written by main._save_session is sufficient for the single-machine
# dev case; this helper just adds a typed loader.

def load_from_disk(sessions_dir: Path, user_id: str) -> Optional[dict]:
    """Load a per-user session JSON snapshot from disk if it exists."""
    path = sessions_dir / f"{user_id}.json"
    if not path.exists():
        return None
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except Exception as exc:
        print(f"[pipeline_cache] disk load failed for {user_id}: {exc}")
        return None

"""
MongoDB connection management.

Uses Motor (async PyMongo) and exposes a small API:

    await connect_to_mongo()      -> called from FastAPI lifespan startup
    await close_mongo_connection()-> called from FastAPI lifespan shutdown
    db = get_db()                 -> returns AsyncIOMotorDatabase

If MONGODB_URI is empty, the helpers no-op and `is_connected()` returns False
so the rest of the app can fall back to the legacy session.json flow.

Atlas connection strings copied from the dashboard often contain unencoded
special characters in the password (`@`, `#`, `?`, `:`, `/`, `%`). pymongo
rejects these with "Username and password must be escaped". `_normalise_uri`
detects the pattern and URL-encodes the password so the URI works as-pasted.
"""

from __future__ import annotations

import re
from typing import Optional
from urllib.parse import quote_plus

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase

from config import settings


# Matches: scheme://USER:PASSWORD@HOST/...
# The password may itself contain `@`, `#` etc. — we greedily match up to the
# *last* `@` before the host portion, which is the canonical mongo separator.
_URI_RE = re.compile(
    r"^(?P<scheme>mongodb(?:\+srv)?://)(?P<user>[^:/?#@]+):(?P<pwd>.*)@(?P<host>[^@/?#]+)(?P<rest>[/?].*)?$"
)


def _normalise_uri(uri: str) -> str:
    """URL-encode the password portion if it contains unsafe characters.

    Idempotent: if the password is already encoded, decoding-then-encoding
    yields the same string.
    """
    if not uri:
        return uri
    m = _URI_RE.match(uri)
    if not m:
        return uri  # let pymongo raise its own validation error

    pwd = m.group("pwd")
    # If pwd already has no unsafe chars, this is a no-op.
    encoded = quote_plus(pwd, safe="")
    if encoded == pwd:
        return uri

    return (
        f"{m.group('scheme')}{m.group('user')}:{encoded}"
        f"@{m.group('host')}{m.group('rest') or ''}"
    )


class _MongoState:
    client: Optional[AsyncIOMotorClient] = None
    db: Optional[AsyncIOMotorDatabase] = None


_state = _MongoState()


async def connect_to_mongo() -> None:
    if not settings.mongodb_enabled:
        print("[DB] MONGODB_URI not set — running in legacy file-only mode.")
        return

    if _state.client is not None:
        return

    print(f"[DB] Connecting to MongoDB ({settings.mongodb_db_name})...")
    uri = _normalise_uri(settings.mongodb_uri)
    _state.client = AsyncIOMotorClient(
        uri,
        serverSelectionTimeoutMS=8000,
        appname="insighted-backend",
    )
    try:
        await _state.client.admin.command("ping")
    except Exception as exc:
        print(f"[DB] MongoDB ping failed: {exc}. Falling back to file mode.")
        _state.client = None
        _state.db = None
        return

    _state.db = _state.client[settings.mongodb_db_name]
    await _ensure_indexes(_state.db)
    print("[DB] MongoDB connection established.")


async def close_mongo_connection() -> None:
    if _state.client is not None:
        _state.client.close()
        _state.client = None
        _state.db = None
        print("[DB] MongoDB connection closed.")


def is_connected() -> bool:
    return _state.db is not None


def get_db() -> AsyncIOMotorDatabase:
    if _state.db is None:
        raise RuntimeError(
            "MongoDB is not connected. Set MONGODB_URI in .env and restart, "
            "or check the startup logs for connection errors."
        )
    return _state.db


async def _ensure_indexes(db: AsyncIOMotorDatabase) -> None:
    """Idempotent — safe to run on every startup."""
    await db.users.create_index("email", unique=True)
    await db.videos.create_index([("user_id", 1), ("fingerprint", 1)], unique=True)
    await db.playback_history.create_index([("user_id", 1), ("video_id", 1)], unique=True)
    await db.analytics_events.create_index([("video_id", 1), ("video_ts", 1)])
    await db.analytics_events.create_index("wall_ts")
    await db.annotations.create_index([("user_id", 1), ("video_id", 1)])
    await db.recommendations.create_index([("user_id", 1), ("video_id", 1)])
    await db.generated_documents.create_index([("user_id", 1), ("video_id", 1)])

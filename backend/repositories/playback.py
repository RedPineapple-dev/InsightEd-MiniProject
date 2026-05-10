"""Continue-watching repository."""

from typing import Optional

from db import get_db
from models.common import utcnow


class PlaybackRepo:
    @staticmethod
    def _coll():
        return get_db().playback_history

    @classmethod
    async def upsert(
        cls,
        user_id: str,
        video_id: str,
        fingerprint: str,
        last_position_seconds: float,
        duration_seconds: Optional[float] = None,
        completed: bool = False,
    ) -> dict:
        now = utcnow()
        await cls._coll().update_one(
            {"user_id": user_id, "video_id": video_id},
            {
                "$set": {
                    "fingerprint": fingerprint,
                    "last_position_seconds": last_position_seconds,
                    "duration_seconds": duration_seconds,
                    "completed": completed,
                    "updated_at": now,
                },
                "$inc": {"watch_count": 1},
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )
        return await cls.find(user_id, video_id)

    @classmethod
    async def find(cls, user_id: str, video_id: str) -> Optional[dict]:
        return await cls._coll().find_one({"user_id": user_id, "video_id": video_id})

    @classmethod
    async def find_by_fingerprint(cls, user_id: str, fingerprint: str) -> Optional[dict]:
        return await cls._coll().find_one({"user_id": user_id, "fingerprint": fingerprint})

    @classmethod
    async def list_recent(cls, user_id: str, limit: int = 10) -> list[dict]:
        cursor = (
            cls._coll()
            .find({"user_id": user_id, "completed": False})
            .sort("updated_at", -1)
            .limit(limit)
        )
        return [d async for d in cursor]

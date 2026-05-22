"""Recommendation cache."""

from typing import Optional

from db import get_db
from models.common import utcnow


class RecommendationRepo:
    @staticmethod
    def _coll():
        return get_db().recommendations

    @classmethod
    async def upsert(
        cls,
        video_id: str,
        concept: str,
        resources: list[dict],
        user_id: Optional[str] = None,
    ) -> dict:
        now = utcnow()
        await cls._coll().update_one(
            {"video_id": video_id, "concept": concept.lower()},
            {
                "$set": {
                    "user_id": user_id,
                    "resources": resources,
                    "updated_at": now,
                },
                "$setOnInsert": {"created_at": now, "concept": concept.lower(), "video_id": video_id},
            },
            upsert=True,
        )
        return await cls._coll().find_one({"video_id": video_id, "concept": concept.lower()})

    @classmethod
    async def get(cls, video_id: str, concept: str) -> Optional[dict]:
        return await cls._coll().find_one({"video_id": video_id, "concept": concept.lower()})

    @classmethod
    async def list_for_video(cls, video_id: str, limit: int = 50) -> list[dict]:
        cursor = cls._coll().find({"video_id": video_id}).sort("updated_at", -1).limit(limit)
        return [d async for d in cursor]

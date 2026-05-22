"""Video metadata collection (NO video bytes are ever stored here)."""

from typing import Optional

from bson import ObjectId

from db import get_db
from models.common import utcnow


class VideoRepo:
    @staticmethod
    def _coll():
        return get_db().videos

    @classmethod
    async def upsert(
        cls,
        user_id: str,
        fingerprint: str,
        filename: str,
        size_bytes: int,
        last_modified_ms: int,
        duration_seconds: Optional[float] = None,
        document_filename: Optional[str] = None,
    ) -> dict:
        now = utcnow()
        update = {
            "$set": {
                "user_id": user_id,
                "fingerprint": fingerprint,
                "filename": filename,
                "size_bytes": size_bytes,
                "last_modified_ms": last_modified_ms,
                "duration_seconds": duration_seconds,
                "document_filename": document_filename,
                "updated_at": now,
            },
            "$setOnInsert": {"created_at": now},
        }
        await cls._coll().update_one(
            {"user_id": user_id, "fingerprint": fingerprint},
            update,
            upsert=True,
        )
        return await cls.find(user_id, fingerprint)

    @classmethod
    async def find(cls, user_id: str, fingerprint: str) -> Optional[dict]:
        return await cls._coll().find_one(
            {"user_id": user_id, "fingerprint": fingerprint}
        )

    @classmethod
    async def get(cls, video_id: str) -> Optional[dict]:
        if not ObjectId.is_valid(video_id):
            return None
        return await cls._coll().find_one({"_id": ObjectId(video_id)})

    @classmethod
    async def list_for_user(cls, user_id: str, limit: int = 50) -> list[dict]:
        cursor = cls._coll().find({"user_id": user_id}).sort("updated_at", -1).limit(limit)
        return [d async for d in cursor]

    @classmethod
    async def update_processing_stats(
        cls,
        video_id: str,
        transcript_segment_count: Optional[int] = None,
        slide_count: Optional[int] = None,
    ) -> None:
        if not ObjectId.is_valid(video_id):
            return
        update: dict = {"updated_at": utcnow()}
        if transcript_segment_count is not None:
            update["transcript_segment_count"] = transcript_segment_count
        if slide_count is not None:
            update["slide_count"] = slide_count
        await cls._coll().update_one({"_id": ObjectId(video_id)}, {"$set": update})

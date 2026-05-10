"""Annotation repository."""

from typing import Optional

from bson import ObjectId

from db import get_db
from models.common import utcnow


class AnnotationRepo:
    @staticmethod
    def _coll():
        return get_db().annotations

    @classmethod
    async def create(
        cls,
        user_id: str,
        video_id: str,
        timestamp_seconds: float,
        concept: str,
        note: str = "",
        importance: str = "medium",
        end_seconds: Optional[float] = None,
        tags: Optional[list[str]] = None,
        source: str = "user",
    ) -> dict:
        now = utcnow()
        doc = {
            "user_id": user_id,
            "video_id": video_id,
            "timestamp_seconds": timestamp_seconds,
            "end_seconds": end_seconds,
            "concept": concept,
            "note": note,
            "importance": importance,
            "tags": tags or [],
            "source": source,
            "created_at": now,
            "updated_at": now,
        }
        result = await cls._coll().insert_one(doc)
        doc["_id"] = result.inserted_id
        return doc

    @classmethod
    async def list_for_video(cls, user_id: str, video_id: str) -> list[dict]:
        cursor = (
            cls._coll()
            .find({"user_id": user_id, "video_id": video_id})
            .sort("timestamp_seconds", 1)
        )
        return [d async for d in cursor]

    @classmethod
    async def update(cls, annotation_id: str, user_id: str, **fields) -> Optional[dict]:
        if not ObjectId.is_valid(annotation_id):
            return None
        allowed = {"concept", "note", "importance", "tags"}
        update = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not update:
            return await cls._coll().find_one({"_id": ObjectId(annotation_id), "user_id": user_id})
        update["updated_at"] = utcnow()
        await cls._coll().update_one(
            {"_id": ObjectId(annotation_id), "user_id": user_id},
            {"$set": update},
        )
        return await cls._coll().find_one({"_id": ObjectId(annotation_id), "user_id": user_id})

    @classmethod
    async def delete(cls, annotation_id: str, user_id: str) -> bool:
        if not ObjectId.is_valid(annotation_id):
            return False
        result = await cls._coll().delete_one(
            {"_id": ObjectId(annotation_id), "user_id": user_id}
        )
        return result.deleted_count > 0

    @classmethod
    async def search(cls, user_id: str, query: str, video_id: Optional[str] = None) -> list[dict]:
        pattern = {"$regex": query, "$options": "i"}
        q: dict = {
            "user_id": user_id,
            "$or": [{"concept": pattern}, {"note": pattern}, {"tags": pattern}],
        }
        if video_id:
            q["video_id"] = video_id
        cursor = cls._coll().find(q).sort("timestamp_seconds", 1).limit(200)
        return [d async for d in cursor]

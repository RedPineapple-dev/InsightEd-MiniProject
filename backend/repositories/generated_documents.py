"""AI-generated PDF/PPTX document records."""

from typing import Optional

from bson import ObjectId

from db import get_db
from models.common import utcnow


class GeneratedDocumentRepo:
    @staticmethod
    def _coll():
        return get_db().generated_documents

    @classmethod
    async def create(
        cls,
        user_id: str,
        video_id: str,
        format: str,
        title: str,
        outline: list[dict],
        file_path: str,
        download_url: str,
    ) -> dict:
        now = utcnow()
        doc = {
            "user_id": user_id,
            "video_id": video_id,
            "format": format,
            "title": title,
            "outline": outline,
            "file_path": file_path,
            "download_url": download_url,
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
            .sort("created_at", -1)
        )
        return [d async for d in cursor]

    @classmethod
    async def get(cls, doc_id: str, user_id: str) -> Optional[dict]:
        if not ObjectId.is_valid(doc_id):
            return None
        return await cls._coll().find_one({"_id": ObjectId(doc_id), "user_id": user_id})

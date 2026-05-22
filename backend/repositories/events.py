"""Analytics events repository."""

from datetime import datetime, timedelta
from typing import Optional

from db import get_db
from models.common import utcnow


class EventRepo:
    @staticmethod
    def _coll():
        return get_db().analytics_events

    @classmethod
    async def insert(
        cls,
        student_name: str,
        video_id: str,
        video_ts: float,
        event_type: str,
        wall_ts: datetime,
        user_id: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> dict:
        doc = {
            "user_id": user_id,
            "student_name": student_name,
            "video_id": video_id,
            "video_ts": video_ts,
            "event_type": event_type,
            "wall_ts": wall_ts,
            "metadata": metadata,
            "created_at": utcnow(),
        }
        result = await cls._coll().insert_one(doc)
        doc["_id"] = result.inserted_id
        return doc

    @classmethod
    async def insert_many(cls, events: list[dict]) -> int:
        if not events:
            return 0
        now = utcnow()
        for e in events:
            e.setdefault("created_at", now)
        result = await cls._coll().insert_many(events)
        return len(result.inserted_ids)

    @classmethod
    async def list_for_video(
        cls,
        video_id: str,
        since: Optional[datetime] = None,
        limit: int = 5000,
        user_id: Optional[str] = None,
    ) -> list[dict]:
        query: dict = {"video_id": video_id}
        if user_id:
            query["user_id"] = user_id
        if since is not None:
            query["wall_ts"] = {"$gte": since}
        cursor = cls._coll().find(query).sort("wall_ts", 1).limit(limit)
        return [d async for d in cursor]

    @classmethod
    async def list_recent(
        cls,
        video_id: str,
        minutes: int = 60,
        user_id: Optional[str] = None,
    ) -> list[dict]:
        since = utcnow() - timedelta(minutes=minutes)
        return await cls.list_for_video(video_id, since=since, user_id=user_id)

    @classmethod
    async def count_for_video(cls, video_id: str, user_id: Optional[str] = None) -> int:
        query: dict = {"video_id": video_id}
        if user_id:
            query["user_id"] = user_id
        return await cls._coll().count_documents(query)

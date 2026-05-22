"""Cross-session analytics events endpoints (Part 3)."""

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from auth.dependencies import get_current_user
from db import is_connected
from models.event import AnalyticsEventCreate
from models.user import UserPublic
from repositories.events import EventRepo


router = APIRouter(prefix="/analytics", tags=["analytics"])


class IngestEnvelope(BaseModel):
    events: List[AnalyticsEventCreate] = Field(default_factory=list)


def _require_db() -> None:
    if not is_connected():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Analytics persistence requires MongoDB. Configure MONGODB_URI.",
        )


def _serialise(e: dict) -> dict:
    out = {**e}
    out["_id"] = str(out.get("_id"))
    for k in ("wall_ts", "created_at"):
        if k in out and out[k] is not None and not isinstance(out[k], str):
            out[k] = out[k].isoformat()
    return out


@router.post("/events")
async def ingest_events(
    payload: IngestEnvelope,
    user: UserPublic = Depends(get_current_user),
):
    _require_db()
    if not payload.events:
        return {"ingested": 0}

    docs = []
    for e in payload.events:
        docs.append(
            {
                "user_id": user.id,
                "student_name": e.student_name,
                "video_id": e.video_id,
                "video_ts": float(e.video_ts),
                "event_type": e.event_type,
                "wall_ts": e.wall_ts,
                "metadata": e.metadata,
            }
        )

    inserted = await EventRepo.insert_many(docs)
    return {"ingested": inserted}


@router.get("/events")
async def list_events(
    video_id: str = Query(...),
    since_ms: Optional[int] = Query(default=None, description="Unix ms — only return events newer than this"),
    user: UserPublic = Depends(get_current_user),
):
    _require_db()
    since: Optional[datetime] = None
    if since_ms:
        since = datetime.fromtimestamp(since_ms / 1000, tz=timezone.utc)

    events = await EventRepo.list_for_video(video_id, since=since, user_id=user.id)
    fetched_at_ms = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    return {
        "video_id": video_id,
        "events": [_serialise(e) for e in events],
        "fetched_at_ms": fetched_at_ms,
    }


@router.get("/summary")
async def summary(
    video_id: str = Query(...),
    user: UserPublic = Depends(get_current_user),
):
    _require_db()
    events = await EventRepo.list_for_video(video_id, user_id=user.id)

    # 10s buckets
    buckets: dict[int, dict] = {}
    students: set[str] = set()
    for e in events:
        bucket = int((e.get("video_ts") or 0) // 10) * 10
        b = buckets.setdefault(bucket, {"bucket": bucket, "replay": 0, "pause": 0, "students": set()})
        if e.get("event_type") == "replay":
            b["replay"] += 1
        elif e.get("event_type") == "pause":
            b["pause"] += 1
        b["students"].add(e.get("student_name") or "unknown")
        students.add(e.get("student_name") or "unknown")

    bucket_list = []
    for b in sorted(buckets.values(), key=lambda x: x["bucket"]):
        bucket_list.append(
            {
                "bucket": b["bucket"],
                "replay": b["replay"],
                "pause": b["pause"],
                "unique_students": len(b["students"]),
                "students": sorted(b["students"]),
                "total": b["replay"] + b["pause"],
            }
        )

    top_replayed = sorted(bucket_list, key=lambda x: (x["replay"], x["total"]), reverse=True)[:5]
    # Auto-detect difficult buckets from the active user's own interactions:
    # replays are the strongest confusion signal, pauses weaker.
    for b in bucket_list:
        b["difficulty"] = b["replay"] * 2 + b["pause"]
    difficult = sorted(
        (b for b in bucket_list if b["difficulty"] >= 2),
        key=lambda x: x["difficulty"],
        reverse=True,
    )

    return {
        "video_id": video_id,
        "buckets": bucket_list,
        "top_replayed": top_replayed,
        "difficult_segments": difficult,
        "totals": {
            "events": len(events),
            "replays": sum(1 for e in events if e.get("event_type") == "replay"),
            "pauses": sum(1 for e in events if e.get("event_type") == "pause"),
            "unique_students": len(students),
        },
    }

"""Continue-Watching playback endpoints (Part 4)."""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from auth.dependencies import get_current_user
from db import is_connected
from models.user import UserPublic
from repositories.playback import PlaybackRepo
from repositories.videos import VideoRepo


router = APIRouter(prefix="/playback", tags=["playback"])


class PlaybackUpsert(BaseModel):
    fingerprint: str
    last_position_seconds: float = Field(ge=0)
    duration_seconds: Optional[float] = None
    completed: bool = False
    # Optional metadata if it's a new video
    filename: Optional[str] = None
    size_bytes: Optional[int] = None
    last_modified_ms: Optional[int] = None


def _serialise(doc: dict) -> dict:
    if not doc:
        return {}
    out = {**doc}
    out["_id"] = str(out.get("_id"))
    if "created_at" in out and out["created_at"] is not None:
        out["created_at"] = out["created_at"].isoformat()
    if "updated_at" in out and out["updated_at"] is not None:
        out["updated_at"] = out["updated_at"].isoformat()
    return out


def _require_db() -> None:
    if not is_connected():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Playback history requires MongoDB. Configure MONGODB_URI.",
        )


@router.post("")
async def upsert_playback(
    payload: PlaybackUpsert,
    user: UserPublic = Depends(get_current_user),
):
    _require_db()

    video = await VideoRepo.upsert(
        user_id=user.id,
        fingerprint=payload.fingerprint,
        filename=payload.filename or "video",
        size_bytes=payload.size_bytes or 0,
        last_modified_ms=payload.last_modified_ms or 0,
        duration_seconds=payload.duration_seconds,
    )
    if not video:
        raise HTTPException(status_code=500, detail="Could not record video metadata")

    history = await PlaybackRepo.upsert(
        user_id=user.id,
        video_id=str(video["_id"]),
        fingerprint=payload.fingerprint,
        last_position_seconds=payload.last_position_seconds,
        duration_seconds=payload.duration_seconds,
        completed=payload.completed,
    )
    return {"history": _serialise(history), "video": _serialise(video)}


@router.get("")
async def get_playback(
    fingerprint: str = Query(...),
    user: UserPublic = Depends(get_current_user),
):
    _require_db()
    history = await PlaybackRepo.find_by_fingerprint(user.id, fingerprint)
    return _serialise(history) if history else {}


@router.get("/recent")
async def list_recent(user: UserPublic = Depends(get_current_user), limit: int = 10):
    _require_db()
    items = await PlaybackRepo.list_recent(user.id, limit=limit)

    # Hydrate with filename from videos collection
    enriched = []
    for h in items:
        video = await VideoRepo.get(h.get("video_id", ""))
        enriched.append(
            {
                **_serialise(h),
                "filename": (video or {}).get("filename"),
            }
        )
    return {"items": enriched}

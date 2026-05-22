"""Continue-watching state."""

from typing import Optional

from pydantic import BaseModel, Field

from .common import TimestampedModel


class PlaybackUpdate(BaseModel):
    fingerprint: str
    last_position_seconds: float = Field(ge=0)
    duration_seconds: Optional[float] = None
    completed: bool = False


class PlaybackHistory(TimestampedModel):
    user_id: str
    video_id: str  # Mongo _id of Video doc
    fingerprint: str
    last_position_seconds: float = 0.0
    duration_seconds: Optional[float] = None
    completed: bool = False
    watch_count: int = 1

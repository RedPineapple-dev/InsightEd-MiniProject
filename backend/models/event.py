"""Video interaction analytics events (replay, pause, seek, etc.)."""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

from .common import TimestampedModel, utcnow

EventType = Literal["replay", "pause", "play", "seek", "rate_change", "completed"]


class AnalyticsEventCreate(BaseModel):
    student_name: str = Field(min_length=1, max_length=120)
    video_id: str = Field(description="Video filename or fingerprint")
    video_ts: float = Field(ge=0, description="Position in video, seconds")
    event_type: EventType
    wall_ts: datetime = Field(default_factory=utcnow)
    metadata: Optional[dict] = None


class AnalyticsEvent(TimestampedModel):
    user_id: Optional[str] = None  # may be anonymous
    student_name: str
    video_id: str
    video_ts: float
    event_type: EventType
    wall_ts: datetime
    metadata: Optional[dict] = None

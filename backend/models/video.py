"""Video metadata. Note: we never store video bytes in MongoDB."""

from typing import Optional

from pydantic import BaseModel, Field

from .common import TimestampedModel


class VideoCreate(BaseModel):
    fingerprint: str
    filename: str
    size_bytes: int
    last_modified_ms: int
    duration_seconds: Optional[float] = None
    document_filename: Optional[str] = None


class Video(TimestampedModel):
    user_id: str
    fingerprint: str = Field(description="hash(filename|size|lastModified)")
    filename: str
    size_bytes: int
    last_modified_ms: int
    duration_seconds: Optional[float] = None
    document_filename: Optional[str] = None
    transcript_segment_count: int = 0
    slide_count: int = 0

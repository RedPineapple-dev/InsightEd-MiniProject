"""AI-generated learning documents (PDF/PPTX) created from video transcripts."""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from .common import TimestampedModel

DocumentFormat = Literal["pdf", "pptx"]


class SlideOutline(BaseModel):
    title: str
    bullets: List[str] = Field(default_factory=list)
    timestamp_seconds: Optional[float] = None
    section: Optional[str] = None


class GeneratedDocumentCreate(BaseModel):
    video_id: str
    format: DocumentFormat
    title: str
    outline: List[SlideOutline]


class GeneratedDocument(TimestampedModel):
    user_id: str
    video_id: str
    format: DocumentFormat
    title: str
    outline: List[SlideOutline]
    file_path: str  # path on disk under generated/
    download_url: str  # served via /generated mount

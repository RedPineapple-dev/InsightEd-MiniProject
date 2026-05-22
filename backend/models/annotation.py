"""User-authored + AI-suggested annotations."""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from .common import TimestampedModel

AnnotationSource = Literal["user", "ai", "live"]
Importance = Literal["high", "medium", "low"]


class AnnotationCreate(BaseModel):
    video_id: str
    timestamp_seconds: float = Field(ge=0)
    end_seconds: Optional[float] = None
    concept: str
    note: str = ""
    importance: Importance = "medium"
    tags: List[str] = Field(default_factory=list)
    source: AnnotationSource = "user"


class AnnotationUpdate(BaseModel):
    concept: Optional[str] = None
    note: Optional[str] = None
    importance: Optional[Importance] = None
    tags: Optional[List[str]] = None


class Annotation(TimestampedModel):
    user_id: str
    video_id: str
    timestamp_seconds: float
    end_seconds: Optional[float] = None
    concept: str
    note: str = ""
    importance: Importance = "medium"
    tags: List[str] = Field(default_factory=list)
    source: AnnotationSource = "user"

"""Recommended learning resources surfaced for a video/concept."""

from typing import List, Literal, Optional

from pydantic import BaseModel, Field, HttpUrl

from .common import TimestampedModel

ResourceCategory = Literal[
    "article",
    "documentation",
    "research_paper",
    "youtube",
    "course",
    "tutorial",
    "github",
    "book",
]


class RecommendedResource(BaseModel):
    title: str
    url: str
    category: ResourceCategory
    source: str = ""  # e.g. "arXiv", "MDN", "YouTube"
    description: str = ""
    thumbnail_url: Optional[str] = None
    tags: List[str] = Field(default_factory=list)
    relevance_score: float = Field(default=0.0, ge=0.0, le=1.0)


class RecommendationCreate(BaseModel):
    video_id: str
    concept: str
    resources: List[RecommendedResource]


class Recommendation(TimestampedModel):
    user_id: Optional[str] = None
    video_id: str
    concept: str
    resources: List[RecommendedResource]

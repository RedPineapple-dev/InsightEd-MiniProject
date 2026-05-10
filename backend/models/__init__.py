"""Pydantic data models for MongoDB collections + API payloads."""

from .common import PyObjectId, TimestampedModel
from .user import User, UserCreate, UserPublic, UserLogin
from .video import Video, VideoCreate
from .playback import PlaybackHistory, PlaybackUpdate
from .event import AnalyticsEvent, AnalyticsEventCreate
from .annotation import Annotation, AnnotationCreate, AnnotationUpdate
from .recommendation import Recommendation, RecommendationCreate
from .generated_document import GeneratedDocument, GeneratedDocumentCreate

__all__ = [
    "PyObjectId",
    "TimestampedModel",
    "User",
    "UserCreate",
    "UserPublic",
    "UserLogin",
    "Video",
    "VideoCreate",
    "PlaybackHistory",
    "PlaybackUpdate",
    "AnalyticsEvent",
    "AnalyticsEventCreate",
    "Annotation",
    "AnnotationCreate",
    "AnnotationUpdate",
    "Recommendation",
    "RecommendationCreate",
    "GeneratedDocument",
    "GeneratedDocumentCreate",
]

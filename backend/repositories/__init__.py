"""MongoDB repository layer.

Each repository wraps a single collection with typed async methods.
Routes/services depend on these instead of touching Motor directly.
"""

from .users import UserRepo
from .videos import VideoRepo
from .playback import PlaybackRepo
from .events import EventRepo
from .annotations import AnnotationRepo
from .recommendations import RecommendationRepo
from .generated_documents import GeneratedDocumentRepo

__all__ = [
    "UserRepo",
    "VideoRepo",
    "PlaybackRepo",
    "EventRepo",
    "AnnotationRepo",
    "RecommendationRepo",
    "GeneratedDocumentRepo",
]

"""Feature routers, mounted from main.py."""

from .analytics import router as analytics_router
from .playback import router as playback_router
from .annotations import router as annotations_router
from .documents import router as documents_router
from .llm_status import router as llm_status_router

__all__ = [
    "analytics_router",
    "playback_router",
    "annotations_router",
    "documents_router",
    "llm_status_router",
]

"""Health/status endpoint for the LLM subsystem.

Frontend reads this to render banners like "AI quota tripped — using
fallbacks" without crashing the page.
"""

from __future__ import annotations

from fastapi import APIRouter

from services.llm import get_llm
from services.llm_cache import stats as cache_stats


router = APIRouter(prefix="/llm", tags=["llm"])


@router.get("/status")
async def llm_status():
    llm = get_llm()
    return {
        **llm.status,
        "cache": await cache_stats(),
    }

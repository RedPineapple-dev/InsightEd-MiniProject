"""User-authored annotation CRUD + NLP enrichments (Part 7).

Adds on top of the existing CRUD:

  * /annotations/list now returns `frequent_terms` (YAKE-extracted) for the
    given video_id, using the in-memory pipeline session transcript when the
    video_id matches the active session.
  * /annotations/suggest — generate AI annotation suggestions at a timestamp
    on demand (used by the workspace "Suggest concepts" button).
  * /annotations/export — download a markdown bundle of saved annotations.
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from auth.dependencies import get_current_user
from db import is_connected
from llm_engine import generate_annotations as llm_generate_annotations
from models.annotation import AnnotationCreate, AnnotationUpdate
from models.user import UserPublic
from repositories.annotations import AnnotationRepo
from services.text_processing import join_segments
from services.topic_extraction import extract_keywords


router = APIRouter(prefix="/annotations", tags=["annotations"])


def _require_db() -> None:
    if not is_connected():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Annotations persistence requires MongoDB.",
        )


def _serialise(doc: dict) -> dict:
    out = {**doc}
    out["_id"] = str(out.get("_id"))
    for k in ("created_at", "updated_at"):
        if k in out and out[k] is not None and not isinstance(out[k], str):
            out[k] = out[k].isoformat()
    return out


def _session_transcript_text(user_id: str) -> str:
    """Best-effort access to the user's in-memory pipeline transcript."""
    try:
        from main import get_user_session  # local import to avoid cycle

        session = get_user_session(user_id)
        return join_segments(session.get("transcript") or [])
    except Exception:
        return ""


def _frequent_terms_for(user_id: str, video_id: str) -> List[dict]:
    text = _session_transcript_text(user_id)
    if not text:
        return []
    return extract_keywords(text, max_n=12)


# ── CRUD ──────────────────────────────────────────────────────────────────


@router.get("/list")
async def list_annotations(
    video_id: str = Query(...),
    user: UserPublic = Depends(get_current_user),
):
    _require_db()
    items = await AnnotationRepo.list_for_video(user.id, video_id)
    return {
        "items": [_serialise(i) for i in items],
        "frequent_terms": _frequent_terms_for(user.id, video_id),
    }


@router.post("/list", status_code=201)
async def create_annotation(
    payload: AnnotationCreate,
    user: UserPublic = Depends(get_current_user),
):
    _require_db()
    doc = await AnnotationRepo.create(
        user_id=user.id,
        video_id=payload.video_id,
        timestamp_seconds=payload.timestamp_seconds,
        end_seconds=payload.end_seconds,
        concept=payload.concept,
        note=payload.note,
        importance=payload.importance,
        tags=payload.tags,
        source=payload.source,
    )
    return _serialise(doc)


@router.patch("/list/{annotation_id}")
async def update_annotation(
    annotation_id: str,
    payload: AnnotationUpdate,
    user: UserPublic = Depends(get_current_user),
):
    _require_db()
    doc = await AnnotationRepo.update(
        annotation_id,
        user.id,
        concept=payload.concept,
        note=payload.note,
        importance=payload.importance,
        tags=payload.tags,
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Annotation not found")
    return _serialise(doc)


@router.delete("/list/{annotation_id}")
async def delete_annotation(
    annotation_id: str,
    user: UserPublic = Depends(get_current_user),
):
    _require_db()
    ok = await AnnotationRepo.delete(annotation_id, user.id)
    if not ok:
        raise HTTPException(status_code=404, detail="Annotation not found")
    return {"deleted": True}


@router.get("/search")
async def search_annotations(
    q: str = Query(...),
    video_id: Optional[str] = Query(default=None),
    user: UserPublic = Depends(get_current_user),
):
    _require_db()
    items = await AnnotationRepo.search(user.id, q, video_id)
    return {"items": [_serialise(i) for i in items]}


# ── NLP enrichments ───────────────────────────────────────────────────────


class SuggestRequest(BaseModel):
    video_id: str
    timestamp_seconds: float = Field(ge=0)
    window_seconds: float = Field(default=20, ge=5, le=120)


@router.post("/suggest")
async def suggest_annotations(
    payload: SuggestRequest,
    user: UserPublic = Depends(get_current_user),
):
    """Generate AI suggestions at the given timestamp using the active transcript."""
    try:
        from main import get_user_session  # local import to avoid cycle
        session = get_user_session(user.id)
    except Exception:
        raise HTTPException(status_code=500, detail="Session unavailable")

    transcript = session.get("transcript") or []
    if not transcript:
        return {"suggestions": [], "reason": "No active transcript."}

    lo = payload.timestamp_seconds - payload.window_seconds / 2
    hi = payload.timestamp_seconds + payload.window_seconds / 2
    window = [
        s for s in transcript
        if (s.get("end") or s.get("start", 0)) >= lo and (s.get("start") or 0) <= hi
    ]
    text = join_segments(window) or join_segments(transcript[:5])

    concepts = llm_generate_annotations(text)
    return {
        "suggestions": [
            {
                "concept": c.get("concept", "").strip(),
                "explanation": c.get("explanation", "").strip(),
                "importance": c.get("importance", "medium"),
                "timestamp_seconds": payload.timestamp_seconds,
            }
            for c in concepts
        ],
        "window": {"start": lo, "end": hi},
    }


@router.get("/frequent-terms")
async def frequent_terms(
    video_id: str = Query(...),
    user: UserPublic = Depends(get_current_user),
):
    return {"terms": _frequent_terms_for(user.id, video_id)}


@router.get("/export", response_class=PlainTextResponse)
async def export_annotations(
    video_id: str = Query(...),
    format: str = Query(default="markdown", pattern="^(markdown|md)$"),
    user: UserPublic = Depends(get_current_user),
):
    _require_db()
    items = await AnnotationRepo.list_for_video(user.id, video_id)
    if not items:
        return PlainTextResponse("# No annotations\n", media_type="text/markdown")

    lines: List[str] = [f"# Annotations — {video_id}", ""]
    for it in items:
        ts = float(it.get("timestamp_seconds") or 0)
        m, s = divmod(int(ts), 60)
        lines.append(f"## [{m:02d}:{s:02d}] {it.get('concept') or 'Note'}")
        if it.get("importance"):
            lines.append(f"*Importance:* **{it['importance']}**")
        if it.get("note"):
            lines.append("")
            lines.append(it["note"])
        if it.get("tags"):
            lines.append("")
            lines.append("Tags: " + ", ".join(f"`{t}`" for t in it["tags"]))
        lines.append("")
    return PlainTextResponse("\n".join(lines), media_type="text/markdown")

"""Generated learning documents.

Endpoints:

    POST /documents/generate
        Body: {video_id, format: "pdf"|"pptx", title?, force?: bool}
        Returns the download URL for the requested format. If the pipeline
        already auto-generated the file (the usual case), the existing
        URL is returned without re-running generation. Set ``force: true``
        to regenerate.

    GET /documents/latest
        Returns the URLs of the most recently generated PDF + PPTX for
        the active session (used by the frontend's Export button to drive
        a direct download).

    GET /documents?video_id=...
        Historical list from Mongo (unchanged).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from auth.dependencies import get_current_user
from config import settings
from db import is_connected
from models.user import UserPublic
from repositories.generated_documents import GeneratedDocumentRepo
from services.slide_generator import generate_documents
from services.topic_segmentation import overall_topic_signature


router = APIRouter(prefix="/documents", tags=["documents"])


class GenerateRequest(BaseModel):
    video_id: str
    format: Literal["pdf", "pptx"] = "pdf"
    title: Optional[str] = None
    force: bool = False


def _session(user_id: str) -> dict:
    """Return this user's pipeline session dict, or an empty one."""
    try:
        from main import get_user_session  # local import — avoid import cycle
    except Exception:
        return {}
    return get_user_session(user_id)


def _existing_url(session: dict, fmt: str) -> Optional[str]:
    files = ((session.get("generated_documents") or {}).get("files") or {})
    entry = files.get(fmt)
    if not entry:
        return None
    url = entry.get("download_url")
    if not url:
        return None
    # Resolve relative URL against the local /generated mount.
    name = entry.get("filename") or Path(url).name
    if (settings.generated_dir / name).exists():
        return url
    return None


@router.get("/latest")
async def latest_documents(user: UserPublic = Depends(get_current_user)):
    """Return the most recently auto-generated PDF + PPTX URLs."""
    session = _session(user.id)
    generated = session.get("generated_documents") or {}
    files = generated.get("files") or {}
    return {
        "status": session.get("documents_status", "idle"),
        "error": session.get("documents_error", ""),
        "files": {
            "pdf": files.get("pdf"),
            "pptx": files.get("pptx"),
        },
        "outline": generated.get("outline") or {},
        "notes_count": generated.get("notes_count", 0),
        "chunks_count": generated.get("chunks_count", 0),
    }


@router.post("/generate", status_code=200)
async def generate_document(
    payload: GenerateRequest,
    user: UserPublic = Depends(get_current_user),
):
    session = _session(user.id)

    # Fast path — the pipeline already auto-generated this format and the
    # file is still on disk. No need to spend LLM budget regenerating it.
    if not payload.force:
        url = _existing_url(session, payload.format)
        if url:
            return {
                "status": "ready",
                "format": payload.format,
                "download_url": url,
                "source": "cached",
            }

    transcript = session.get("transcript") or []
    if not transcript:
        raise HTTPException(
            status_code=400,
            detail="No active transcript. Run /process first.",
        )

    chunks = session.get("topic_chunks") or None
    notes = session.get("structured_notes") or None
    canonical = overall_topic_signature(chunks) if chunks else []
    title = payload.title or _fallback_title(session, notes, canonical)

    try:
        result = generate_documents(
            transcript,
            title=title,
            formats=[payload.format],
            output_dir=settings.generated_dir,
            chunks=chunks,
            notes=notes,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Generation failed: {exc}")

    files = result.get("files") or {}
    file_path = files.get(payload.format)
    if not file_path:
        raise HTTPException(status_code=500, detail="Renderer produced no file")

    file_path = Path(file_path)
    download_url = f"/generated/{file_path.name}"

    # Update the session's cached entry so subsequent GET /documents/latest
    # and /status reflect the new file.
    serialized = session.setdefault("generated_documents", {})
    serialized.setdefault("files", {})
    serialized["files"][payload.format] = {
        "filename": file_path.name,
        "download_url": download_url,
        "format": payload.format,
    }
    if "outline" not in serialized and result.get("outline"):
        serialized["outline"] = result["outline"]
    session["documents_status"] = "ready"

    if is_connected():
        try:
            await GeneratedDocumentRepo.create(
                user_id=user.id,
                video_id=payload.video_id,
                format=payload.format,
                title=title,
                outline=(result.get("outline") or {}).get("slides", []),
                file_path=str(file_path),
                download_url=download_url,
            )
        except Exception as exc:
            print(f"[documents] Mongo persist skipped: {exc}")

    return {
        "status": "ready",
        "format": payload.format,
        "title": title,
        "download_url": download_url,
        "outline": result.get("outline") or {},
        "source": "fresh",
    }


@router.get("")
async def list_documents(
    video_id: str = Query(...),
    user: UserPublic = Depends(get_current_user),
):
    if not is_connected():
        return {"items": []}
    items = await GeneratedDocumentRepo.list_for_video(user.id, video_id)
    return {
        "items": [
            {**i, "_id": str(i.get("_id"))} for i in items
        ]
    }


def _fallback_title(session: dict, notes, canonical) -> str:
    if notes:
        best = max(
            (n for n in notes if not n.get("off_topic") and n.get("topic")),
            key=lambda n: float(n.get("confidence") or 0.0),
            default=None,
        )
        if best and best.get("topic"):
            return str(best["topic"])[:80]
    if canonical:
        return f"{canonical[0]} — Lecture Notes"
    video_path = session.get("video_path") or ""
    if video_path:
        stem = Path(video_path).stem.replace("_", " ")
        return (stem.replace("video ", "").strip() or "Lecture Notes")[:80]
    return "Lecture Notes"

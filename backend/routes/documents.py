"""Generated learning documents (Part 5).

POST /documents/generate — produces a PDF or PPTX from the active session
                           transcript using services.slide_generator.
GET  /documents           — lists previously-generated documents for a user.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from auth.dependencies import get_current_user
from config import settings
from db import is_connected
from models.user import UserPublic
from repositories.generated_documents import GeneratedDocumentRepo
from services.slide_generator import generate_documents


router = APIRouter(prefix="/documents", tags=["documents"])


class GenerateRequest(BaseModel):
    video_id: str
    format: Literal["pdf", "pptx"] = "pdf"
    title: str | None = None


def _session_transcript(user_id: str) -> list[dict]:
    try:
        from main import get_user_session  # local import to avoid cycle
    except Exception:
        return []
    return get_user_session(user_id).get("transcript") or []


@router.post("/generate", status_code=201)
async def generate_document(
    payload: GenerateRequest,
    user: UserPublic = Depends(get_current_user),
):
    transcript = _session_transcript(user.id)
    if not transcript:
        raise HTTPException(
            status_code=400,
            detail="No active transcript. Run /process or /analyze first.",
        )

    title = payload.title or "Lecture Notes"
    try:
        result = generate_documents(
            transcript,
            title=title,
            formats=[payload.format],
            output_dir=settings.generated_dir,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Generation failed: {exc}")

    file_path: Path = result["files"][payload.format]
    download_url = f"/generated/{file_path.name}"

    record = {
        "format": payload.format,
        "title": title,
        "outline": result["outline"]["slides"],
        "file_path": str(file_path),
        "download_url": download_url,
    }

    # Persist if Mongo is enabled — otherwise just return the file URL.
    if is_connected():
        await GeneratedDocumentRepo.create(
            user_id=user.id,
            video_id=payload.video_id,
            format=payload.format,
            title=title,
            outline=result["outline"]["slides"],
            file_path=str(file_path),
            download_url=download_url,
        )

    return {
        "status": "ok",
        "format": payload.format,
        "title": title,
        "download_url": download_url,
        "outline": result["outline"],
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

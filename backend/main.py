"""
InsightEd – AI-Powered Video Annotation and Adaptive Learning System
Main FastAPI Application
"""

import json
import shutil
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, Dict, Any

from fastapi import FastAPI, File, UploadFile, HTTPException, BackgroundTasks, Depends, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from auth import auth_router
from auth.dependencies import get_current_user
from config import settings
from db import close_mongo_connection, connect_to_mongo, is_connected
from models.user import UserPublic
from routes import (
    analytics_router,
    annotations_router,
    documents_router,
    llm_status_router,
    playback_router,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect_to_mongo()
    yield
    await close_mongo_connection()


app = FastAPI(title="InsightEd API", version="2.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins + ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = settings.upload_dir
STATIC_DIR = settings.static_dir
DATA_DIR = settings.data_dir
GENERATED_DIR = settings.generated_dir
SESSIONS_DIR = DATA_DIR / "sessions"

for d in [UPLOAD_DIR, STATIC_DIR, DATA_DIR, GENERATED_DIR, SESSIONS_DIR]:
    d.mkdir(exist_ok=True, parents=True)

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
app.mount("/uploads", StaticFiles(directory=str(UPLOAD_DIR)), name="uploads")
app.mount("/generated", StaticFiles(directory=str(GENERATED_DIR)), name="generated")

app.include_router(auth_router)
app.include_router(playback_router)
app.include_router(analytics_router)
app.include_router(annotations_router)
app.include_router(documents_router)
app.include_router(llm_status_router)


# ── Per-user pipeline sessions ───────────────────────────────────────────────
# Each authenticated user has their own in-memory session dict so that
# uploading on account A does not bleed into account B.

def _new_session() -> Dict[str, Any]:
    return {
        "video_path": None,
        "document_path": None,
        # Fingerprint of the active video. The frontend hashes (filename|size|
        # last_modified) and sends it on upload; we echo it back in /status
        # so the analytics page can rebind to the right video_id after a
        # re-login.
        "fingerprint": None,
        "transcript": [],
        "slides": [],
        "embeddings": {},
        "annotations": [],
        "alignment": [],
        "analytics": {},
        "behavior_logs": [],
        "processing_status": "idle",
        "processing_progress": 0,
        "processing_error": "",
    }


_user_sessions: Dict[str, Dict[str, Any]] = {}


def get_user_session(user_id: str) -> Dict[str, Any]:
    """Return (creating if necessary) the in-memory session for this user."""
    s = _user_sessions.get(user_id)
    if s is None:
        s = _new_session()
        _user_sessions[user_id] = s
    return s


def _user_upload_dir(user_id: str) -> Path:
    p = UPLOAD_DIR / user_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def _save_session(user_id: str) -> None:
    try:
        session = _user_sessions.get(user_id) or {}
        out = {k: v for k, v in session.items() if k != "embeddings"}
        with open(SESSIONS_DIR / f"{user_id}.json", "w") as f:
            json.dump(out, f, indent=2)
    except Exception as e:
        print(f"[Pipeline] Could not save session: {e}")


class BehaviorEvent(BaseModel):
    event_type: str
    timestamp: float
    value: Optional[float] = None

class QueryRequest(BaseModel):
    query: str

class RecommendRequest(BaseModel):
    concept: Optional[str] = None
    timestamp: Optional[float] = None

# ── Lazy module loaders ──────────────────────────────────────────────────────

_video_processor = None
_doc_processor = None
_embed_engine = None
_annotation_engine = None
_analytics_engine = None
_search_engine = None

def get_video_processor():
    global _video_processor
    if _video_processor is None:
        from video_processor import VideoProcessor
        _video_processor = VideoProcessor()
    return _video_processor

def get_doc_processor():
    global _doc_processor
    if _doc_processor is None:
        from document_processor import DocumentProcessor
        _doc_processor = DocumentProcessor()
    return _doc_processor

def get_embed_engine():
    global _embed_engine
    if _embed_engine is None:
        from embedding_engine import EmbeddingEngine
        _embed_engine = EmbeddingEngine()
    return _embed_engine

def get_annotation_engine():
    global _annotation_engine
    if _annotation_engine is None:
        from annotation_engine import AnnotationEngine
        _annotation_engine = AnnotationEngine(get_embed_engine())
    return _annotation_engine

def get_analytics_engine():
    global _analytics_engine
    if _analytics_engine is None:
        from analytics_engine import AnalyticsEngine
        _analytics_engine = AnalyticsEngine()
    return _analytics_engine

def get_search_engine():
    global _search_engine
    if _search_engine is None:
        from search_engine import SearchEngine
        _search_engine = SearchEngine(get_embed_engine())
    return _search_engine

# ── Pipeline ─────────────────────────────────────────────────────────────────

def _update(user_id: str, status=None, progress=None):
    session = get_user_session(user_id)
    if status:
        session["processing_status"] = status
    if progress is not None:
        session["processing_progress"] = progress

async def run_pipeline(user_id: str):
    session = get_user_session(user_id)
    try:
        _update(user_id, "processing", 5)
        loop = asyncio.get_event_loop()

        # Step 1: Video
        if session["video_path"]:
            _update(user_id, progress=10)
            print(f"[Pipeline:{user_id}] Step 1: Video processing")
            vp = get_video_processor()
            transcript = await loop.run_in_executor(None, vp.process, session["video_path"])
            session["transcript"] = transcript or []
            print(f"[Pipeline:{user_id}] Transcript: {len(session['transcript'])} segments")
            _update(user_id, progress=35)

        # Step 2: Document
        if session["document_path"]:
            _update(user_id, progress=40)
            print(f"[Pipeline:{user_id}] Step 2: Document processing")
            dp = get_doc_processor()
            slides = await loop.run_in_executor(None, dp.process, session["document_path"])
            session["slides"] = slides or []
            print(f"[Pipeline:{user_id}] Slides: {len(session['slides'])}")
            _update(user_id, progress=55)

        # If no real content, use mocks (instance methods → use the singletons)
        if not session["transcript"]:
            session["transcript"] = get_video_processor()._mock_transcript("")
        if not session["slides"]:
            session["slides"] = get_doc_processor()._mock_slides()

        # Step 3: Embeddings
        _update(user_id, progress=60)
        print(f"[Pipeline:{user_id}] Step 3: Embeddings")
        ee = get_embed_engine()
        embeddings = await loop.run_in_executor(
            None, ee.compute_all, session["transcript"], session["slides"]
        )
        session["embeddings"] = embeddings
        _update(user_id, progress=72)

        # Step 4: Annotations
        print(f"[Pipeline:{user_id}] Step 4: Annotations")
        ae = get_annotation_engine()
        annotations = await loop.run_in_executor(
            None, ae.annotate_transcript, session["transcript"], embeddings
        )
        session["annotations"] = annotations or []
        _update(user_id, progress=82)

        # Step 5: Alignment (Hybrid Embedding + LLM)
        print(f"[Pipeline:{user_id}] Step 5: Alignment (hybrid embedding + Gemini LLM)")
        from alignment_engine import link_segments_to_documents
        alignment = await loop.run_in_executor(
            None, link_segments_to_documents, session["transcript"], session["slides"], True
        )
        print(f"[Pipeline:{user_id}] Alignment complete: {len(alignment)} matched segments")

        session["alignment"] = alignment or []
        _update(user_id, progress=92)

        # Step 6: Analytics
        print(f"[Pipeline:{user_id}] Step 6: Analytics")
        an = get_analytics_engine()
        analytics = await loop.run_in_executor(
            None, an.generate, session["behavior_logs"], session["alignment"], session["transcript"]
        )
        session["analytics"] = analytics or {}

        _update(user_id, "done", 100)
        print(f"[Pipeline:{user_id}] ✓ Complete!")
        _save_session(user_id)

    except Exception as e:
        import traceback
        print(f"[Pipeline:{user_id}] ERROR: {e}")
        traceback.print_exc()
        session["processing_status"] = "error"
        session["processing_error"] = str(e)

# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"message": "InsightEd API running", "version": app.version}


@app.get("/health")
def health():
    return {
        "status": "ok",
        "mongo": "connected" if is_connected() else "disabled",
        "gemini": "configured" if settings.gemini_api_key else "missing",
    }

@app.get("/status")
def get_status(user: UserPublic = Depends(get_current_user)):
    session = get_user_session(user.id)

    # Expose LLM availability + circuit-breaker state so the frontend can
    # surface a "using fallbacks" banner instead of crashing on 503-from-quota.
    try:
        from services.llm import get_llm
        llm_state = get_llm().status
        llm_summary = {
            "available": llm_state["configured"] and not llm_state["circuit_open"],
            "circuit_open": llm_state["circuit_open"],
            "model": llm_state["default_model"],
        }
    except Exception:
        llm_summary = {"available": False, "circuit_open": False, "model": ""}

    video_path = session.get("video_path")
    doc_path = session.get("document_path")
    video_filename = Path(video_path).name if video_path else None
    doc_filename = Path(doc_path).name if doc_path else None
    # Files are stored under uploads/<user_id>/ so URLs include the user_id.
    video_url = f"/uploads/{user.id}/{video_filename}" if video_filename else None

    return {
        "status": session["processing_status"],
        "progress": session["processing_progress"],
        "error": session.get("processing_error", ""),
        "has_video": video_path is not None,
        "has_document": doc_path is not None,
        "video_filename": video_filename,
        "video_url": video_url,
        "document_filename": doc_filename,
        "fingerprint": session.get("fingerprint"),
        "transcript_segments": len(session["transcript"]),
        "slides_count": len(session["slides"]),
        "annotations_count": len(session["annotations"]),
        "llm": llm_summary,
    }

@app.post("/upload-video")
async def upload_video(
    file: UploadFile = File(...),
    fingerprint: Optional[str] = Form(default=None),
    user: UserPublic = Depends(get_current_user),
):
    session = get_user_session(user.id)
    user_dir = _user_upload_dir(user.id)
    dest = user_dir / f"video_{file.filename}"
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    session["video_path"] = str(dest)
    session["processing_status"] = "idle"
    if fingerprint:
        session["fingerprint"] = fingerprint
    return {
        "message": "Video uploaded",
        "filename": file.filename,
        "stored_filename": dest.name,
        "url": f"/uploads/{user.id}/{dest.name}",
        "fingerprint": session.get("fingerprint"),
    }

@app.post("/upload-document")
async def upload_document(
    file: UploadFile = File(...),
    user: UserPublic = Depends(get_current_user),
):
    session = get_user_session(user.id)
    user_dir = _user_upload_dir(user.id)
    dest = user_dir / f"doc_{file.filename}"
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)
    session["document_path"] = str(dest)
    return {"message": "Document uploaded", "filename": file.filename}

@app.post("/process")
async def process(
    background_tasks: BackgroundTasks,
    user: UserPublic = Depends(get_current_user),
):
    session = get_user_session(user.id)
    if session["processing_status"] == "processing":
        return {"message": "Already processing"}
    session["processing_status"] = "queued"
    session["processing_progress"] = 0
    session["processing_error"] = ""
    background_tasks.add_task(run_pipeline, user.id)
    return {"message": "Processing started"}

@app.get("/annotations")
def get_annotations(user: UserPublic = Depends(get_current_user)):
    session = get_user_session(user.id)
    return {"annotations": session["annotations"], "total": len(session["annotations"])}

@app.get("/alignment")
def get_alignment(user: UserPublic = Depends(get_current_user)):
    session = get_user_session(user.id)
    return {"alignment": session["alignment"], "total": len(session["alignment"])}

@app.get("/analytics")
def get_analytics(user: UserPublic = Depends(get_current_user)):
    session = get_user_session(user.id)
    an = get_analytics_engine()
    updated = an.generate(session["behavior_logs"], session["alignment"], session["transcript"])
    session["analytics"] = updated
    return updated

@app.get("/slides")
def get_slides(user: UserPublic = Depends(get_current_user)):
    session = get_user_session(user.id)
    return {"slides": session["slides"], "total": len(session["slides"])}

@app.get("/transcript")
def get_transcript(user: UserPublic = Depends(get_current_user)):
    session = get_user_session(user.id)
    return {"transcript": session["transcript"], "total": len(session["transcript"])}

@app.post("/behavior")
def track_behavior(event: BehaviorEvent, user: UserPublic = Depends(get_current_user)):
    session = get_user_session(user.id)
    session["behavior_logs"].append(event.model_dump())
    return {"message": "logged"}

@app.post("/search")
def search(req: QueryRequest, user: UserPublic = Depends(get_current_user)):
    session = get_user_session(user.id)
    se = get_search_engine()
    return se.search(req.query, session["transcript"], session["slides"], session["embeddings"])

@app.post("/recommend")
def recommend(req: RecommendRequest, user: UserPublic = Depends(get_current_user)):
    session = get_user_session(user.id)
    ae = get_annotation_engine()
    results = ae.recommend(
        concept=req.concept,
        timestamp=req.timestamp,
        transcript=session["transcript"],
        slides=session["slides"],
        embeddings=session["embeddings"],
        analytics=session["analytics"],
    )
    return {
        "recommendations": results.get("recommendations", []),
        "resources": results.get("resources", []),
    }

@app.delete("/reset")
def reset_session(user: UserPublic = Depends(get_current_user)):
    """Clear this user's pipeline session AND remove their uploaded files."""
    _user_sessions[user.id] = _new_session()
    # Best-effort cleanup of stored files for this user.
    user_dir = UPLOAD_DIR / user.id
    if user_dir.exists():
        for f in user_dir.iterdir():
            try:
                f.unlink()
            except Exception:
                pass
    sess_file = SESSIONS_DIR / f"{user.id}.json"
    if sess_file.exists():
        try:
            sess_file.unlink()
        except Exception:
            pass
    return {"message": "Reset"}

# ── HYBRID ALIGNMENT ENDPOINTS (Embedding + LLM) ──────────────────────────────

@app.post("/align-hybrid")
async def align_hybrid(
    use_llm: bool = True,
    user: UserPublic = Depends(get_current_user),
):
    """
    Perform hybrid alignment (embedding + optional LLM) on already-uploaded files.
    Requires both transcript and slides to be already processed.
    """
    session = get_user_session(user.id)
    if not session.get("transcript") or not session.get("slides"):
        raise HTTPException(
            status_code=400,
            detail="Missing transcript or slides. Run /process first."
        )

    try:
        from alignment_engine import link_segments_to_documents

        print(f"[API:{user.id}] Starting hybrid alignment (use_llm={use_llm})")
        alignments = link_segments_to_documents(
            session["transcript"],
            session["slides"],
            use_llm=use_llm
        )

        session["alignment"] = alignments
        return {
            "status": "success",
            "alignments": alignments,
            "total": len(alignments),
            "method": "hybrid_llm" if use_llm else "embedding_only"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/align-direct")
async def align_direct(
    video: UploadFile = File(...),
    document: UploadFile = File(...),
    use_llm: bool = True,
):
    """
    Direct alignment endpoint: Upload video + document and get alignments in one call.
    Stateless — does not touch any user's session.
    """
    import tempfile

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = Path(tmpdir) / f"video_{video.filename}"
            doc_path = Path(tmpdir) / f"doc_{document.filename}"

            with open(video_path, "wb") as f:
                shutil.copyfileobj(video.file, f)
            with open(doc_path, "wb") as f:
                shutil.copyfileobj(document.file, f)

            print(f"[API] Direct alignment: {video.filename} + {document.filename} (llm={use_llm})")

            from alignment_engine import process_video_and_document

            alignments = process_video_and_document(
                str(video_path),
                str(doc_path),
                use_llm=use_llm
            )

            return {
                "status": "success",
                "alignments": alignments,
                "total": len(alignments),
                "method": "hybrid_llm" if use_llm else "embedding_only",
                "video_name": video.filename,
                "document_name": document.filename
            }

    except Exception as e:
        print(f"[API] Error in direct alignment: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/analyze")
async def analyze_full_pipeline(
    video: UploadFile = File(...),
    document: UploadFile = File(...)
):
    """
    Full Analysis Pipeline: Upload video + document and get full mappings and annotations.
    Stateless — does not touch any user's session.
    """
    import tempfile

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            video_path = Path(tmpdir) / f"video_{video.filename}"
            doc_path = Path(tmpdir) / f"doc_{document.filename}"

            with open(video_path, "wb") as f:
                shutil.copyfileobj(video.file, f)
            with open(doc_path, "wb") as f:
                shutil.copyfileobj(document.file, f)

            print(f"[API] Starting full analyze pipeline: {video.filename} + {document.filename}")

            vp = get_video_processor()
            dp = get_doc_processor()
            ee = get_embed_engine()
            ae = get_annotation_engine()
            from alignment_engine import link_segments_to_documents

            transcript = vp.process(str(video_path))
            if not transcript:
                transcript = vp._mock_transcript("")

            slides = dp.process(str(doc_path))
            if not slides:
                slides = dp._mock_slides()

            embeddings = ee.compute_all(transcript, slides)
            alignments = link_segments_to_documents(transcript, slides, use_llm=True)
            annotations = ae.annotate_transcript(transcript, embeddings)

            return JSONResponse(content={
                "status": "success",
                "video_name": video.filename,
                "document_name": document.filename,
                "transcript_segments_count": len(transcript),
                "slides_count": len(slides),
                "mappings": alignments,
                "annotations": annotations
            })

    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

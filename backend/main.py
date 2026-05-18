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
        # Multi-stage generation pipeline state
        "topic_chunks": [],
        "frame_ocr": [],
        "structured_notes": [],
        "generated_documents": {},   # {pdf: {download_url, outline}, pptx: {...}}
        "documents_status": "idle",  # idle | generating | ready | error
        "documents_error": "",
        "processing_status": "idle",
        "processing_progress": 0,
        "processing_error": "",
    }


_user_sessions: Dict[str, Dict[str, Any]] = {}


def _rehydrate_session(user_id: str) -> Optional[Dict[str, Any]]:
    """Try to restore a previously-saved session for this user.

    Order: Mongo pipeline_runs (latest fingerprint) → on-disk JSON snapshot.
    Returns None if nothing is recoverable. Idempotency is the goal: refresh
    / re-login should NOT trigger pipeline reruns.
    """
    try:
        from services.pipeline_cache import load_from_disk
        snap = load_from_disk(SESSIONS_DIR, user_id)
        if snap and isinstance(snap, dict):
            base = _new_session()
            base.update(snap)
            # Embeddings aren't persisted (too large); they get recomputed
            # lazily by /search and /recommend.
            base["embeddings"] = {}
            return base
    except Exception as exc:
        print(f"[Pipeline] rehydrate failed for {user_id}: {exc}")
    return None


def get_user_session(user_id: str) -> Dict[str, Any]:
    """Return (creating if necessary) the in-memory session for this user.

    On first access in a new process we attempt to rehydrate from disk so a
    refresh or re-login doesn't lose the previous pipeline outputs.
    """
    s = _user_sessions.get(user_id)
    if s is None:
        s = _rehydrate_session(user_id) or _new_session()
        _user_sessions[user_id] = s
    return s


def _user_upload_dir(user_id: str) -> Path:
    p = UPLOAD_DIR / user_id
    p.mkdir(parents=True, exist_ok=True)
    return p


def _save_session(user_id: str) -> None:
    """Persist this user's session to disk and (when available) Mongo.

    Two stores on purpose: disk JSON keeps single-machine dev refresh-immune,
    Mongo enables multi-instance and survives container restarts.
    """
    try:
        session = _user_sessions.get(user_id) or {}
        out = {k: v for k, v in session.items() if k != "embeddings"}
        with open(SESSIONS_DIR / f"{user_id}.json", "w") as f:
            json.dump(out, f, indent=2)
    except Exception as e:
        print(f"[Pipeline] Could not save session to disk: {e}")

    fingerprint = (session or {}).get("fingerprint")
    if fingerprint:
        try:
            from services.pipeline_cache import save_run_sync
            save_run_sync(user_id, fingerprint, session)
        except Exception as e:
            print(f"[Pipeline] Could not save session to Mongo: {e}")


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
    """End-to-end pipeline.

    Stages (video is the only required input — slides/PDF/PPT are derived
    from the video itself):

        1. Transcript (Whisper)
        2. Frame OCR     (optional, gracefully degrades)
        3. Embeddings
        4. Topic segmentation (semantic chunks)
        5. Structured notes   (per chunk, grounded)
        6. Annotations        (per chunk, semantic-deduped)
        7. Slides             (from uploaded doc OR auto-built from chunks)
        8. Alignment          (transcript -> slides)
        9. Analytics
       10. Auto-generated PDF + PPTX (from structured notes)
    """
    session = get_user_session(user_id)
    try:
        _update(user_id, "processing", 5)
        loop = asyncio.get_event_loop()

        # ── Step 0: Check Mongo for a cached run ────────────────────
        # If we processed this same file before (same fingerprint) we can
        # restore the outputs directly and skip the whole pipeline.
        fingerprint = session.get("fingerprint")
        if fingerprint:
            try:
                from services.pipeline_cache import load_run_sync
                snap = load_run_sync(user_id, fingerprint)
            except Exception as exc:
                snap = None
                print(f"[Pipeline:{user_id}] cache lookup failed: {exc}")
            if snap and snap.get("processing_status") == "done":
                preserve = {"video_path", "document_path", "fingerprint"}
                for k, v in snap.items():
                    if k in preserve:
                        continue
                    session[k] = v
                session["embeddings"] = {}
                _update(user_id, "done", 100)
                print(f"[Pipeline:{user_id}] ✓ Restored cached run (fingerprint={fingerprint[:12]})")
                return

        # ── Step 1: Video transcript ────────────────────────────────
        if session["video_path"]:
            _update(user_id, progress=8)
            print(f"[Pipeline:{user_id}] Step 1: Video transcript")
            vp = get_video_processor()
            transcript = await loop.run_in_executor(None, vp.process, session["video_path"])
            session["transcript"] = transcript or []
            print(f"[Pipeline:{user_id}] Transcript: {len(session['transcript'])} segments")
            _update(user_id, progress=25)

        # ── Step 2: Frame OCR (optional) ────────────────────────────
        if session["video_path"]:
            print(f"[Pipeline:{user_id}] Step 2: Frame OCR (optional)")
            try:
                from services.frame_ocr import extract_frame_ocr
                ocr = await loop.run_in_executor(
                    None, extract_frame_ocr, session["video_path"]
                )
                session["frame_ocr"] = ocr or []
                print(f"[Pipeline:{user_id}] Frame OCR rows: {len(session['frame_ocr'])}")
            except Exception as exc:
                print(f"[Pipeline:{user_id}] OCR skipped: {exc}")
                session["frame_ocr"] = []
        _update(user_id, progress=35)

        # ── Step 3: Optional uploaded slides (if user provided them) ─
        if session["document_path"]:
            print(f"[Pipeline:{user_id}] Step 3a: User-provided slides")
            dp = get_doc_processor()
            slides = await loop.run_in_executor(None, dp.process, session["document_path"])
            session["slides"] = slides or []
            print(f"[Pipeline:{user_id}] Slides from upload: {len(session['slides'])}")

        # If no real transcript, use the mock so downstream stages don't crash.
        if not session["transcript"]:
            session["transcript"] = get_video_processor()._mock_transcript("")
        _update(user_id, progress=42)

        # ── Step 4: Embeddings ──────────────────────────────────────
        print(f"[Pipeline:{user_id}] Step 4: Embeddings")
        ee = get_embed_engine()
        embeddings = await loop.run_in_executor(
            None, ee.compute_all, session["transcript"], session["slides"]
        )
        session["embeddings"] = embeddings
        _update(user_id, progress=50)

        # ── Step 5: Topic segmentation ──────────────────────────────
        print(f"[Pipeline:{user_id}] Step 5: Topic segmentation")
        from services.topic_segmentation import segment_transcript
        chunks = await loop.run_in_executor(
            None,
            lambda: segment_transcript(
                session["transcript"],
                encode_fn=lambda texts: ee.encode(list(texts)),
                ocr_records=session.get("frame_ocr") or [],
            ),
        )
        session["topic_chunks"] = chunks
        print(f"[Pipeline:{user_id}] Topic chunks: {len(chunks)}")
        _update(user_id, progress=60)

        # ── Step 6: Structured notes ────────────────────────────────
        print(f"[Pipeline:{user_id}] Step 6: Structured notes")
        from services.structured_notes import generate_notes
        notes = await loop.run_in_executor(None, generate_notes, chunks)
        session["structured_notes"] = notes
        _update(user_id, progress=70)

        # ── Step 7: Annotations (chunk-aware) ───────────────────────
        print(f"[Pipeline:{user_id}] Step 7: Annotations")
        ae = get_annotation_engine()
        annotations = await loop.run_in_executor(
            None,
            lambda: ae.annotate_transcript(
                session["transcript"], embeddings, chunks=chunks
            ),
        )
        session["annotations"] = annotations or []
        _update(user_id, progress=78)

        # ── Step 8: Slides — auto-derive when no upload ─────────────
        if not session["slides"]:
            print(f"[Pipeline:{user_id}] Step 8a: Auto-deriving slides from chunks")
            session["slides"] = _slides_from_chunks(chunks, notes)

        # ── Step 9: Alignment ───────────────────────────────────────
        print(f"[Pipeline:{user_id}] Step 9: Alignment")
        from alignment_engine import link_segments_to_documents
        alignment = await loop.run_in_executor(
            None,
            link_segments_to_documents,
            session["transcript"],
            session["slides"],
            True,
        )
        session["alignment"] = alignment or []
        print(f"[Pipeline:{user_id}] Alignment: {len(alignment)} matched")
        _update(user_id, progress=87)

        # ── Step 10: Analytics ──────────────────────────────────────
        print(f"[Pipeline:{user_id}] Step 10: Analytics")
        an = get_analytics_engine()
        analytics = await loop.run_in_executor(
            None,
            an.generate,
            session["behavior_logs"],
            session["alignment"],
            session["transcript"],
        )
        session["analytics"] = analytics or {}
        _update(user_id, progress=92)

        # ── Step 11: Auto-generate PDF + PPTX ───────────────────────
        print(f"[Pipeline:{user_id}] Step 11: Auto-generating PDF + PPTX")
        session["documents_status"] = "generating"
        try:
            from services.slide_generator import generate_documents
            from services.topic_segmentation import overall_topic_signature

            canon_terms = overall_topic_signature(chunks)
            title = _derive_lecture_title(notes, canon_terms, session)
            result = await loop.run_in_executor(
                None,
                lambda: generate_documents(
                    session["transcript"],
                    title=title,
                    formats=["pdf", "pptx"],
                    chunks=chunks,
                    notes=notes,
                ),
            )
            session["generated_documents"] = _serialize_documents(result, user_id=user_id)
            session["documents_status"] = "ready"
            print(
                f"[Pipeline:{user_id}] Docs ready: "
                f"{list(session['generated_documents'].get('files', {}).keys())}"
            )
        except Exception as exc:
            import traceback
            traceback.print_exc()
            session["documents_status"] = "error"
            session["documents_error"] = str(exc)
            print(f"[Pipeline:{user_id}] Doc generation failed: {exc}")

        _update(user_id, "done", 100)
        print(f"[Pipeline:{user_id}] ✓ Complete!")
        try:
            from services.llm import get_llm
            get_llm().log_summary(prefix=f"[LLM:{user_id}]")
        except Exception:
            pass
        _save_session(user_id)

    except Exception as e:
        import traceback
        print(f"[Pipeline:{user_id}] ERROR: {e}")
        traceback.print_exc()
        session["processing_status"] = "error"
        session["processing_error"] = str(e)


# ── Pipeline helpers ─────────────────────────────────────────────────────


def _slides_from_chunks(
    chunks: list, notes: list
) -> list:
    """When the user didn't upload a deck, build a slide list directly from
    topic chunks so alignment + the SlideViewer still have something to
    show. The slides mirror the structured-notes content so the right-hand
    annotation panel and the rendered PDF/PPTX stay in sync.
    """
    by_id = {n.get("chunk_id"): n for n in notes if n.get("chunk_id") is not None}
    slides: list = []
    for i, c in enumerate(chunks):
        n = by_id.get(c.get("chunk_id"))
        title = (n.get("topic") if n else None) or c.get("title_hint") or f"Topic {i + 1}"
        bullets: list[str] = []
        if n:
            bullets.extend((n.get("important_points") or [])[:3])
            for d in (n.get("definitions") or [])[:1]:
                if isinstance(d, dict) and d.get("term") and d.get("definition"):
                    bullets.append(f"{d['term']}: {d['definition']}")
            bullets.extend((n.get("examples") or [])[:1])
        if not bullets:
            bullets = [(c.get("text") or "")[:240]]
        text = title + ". " + ". ".join(bullets)
        slides.append(
            {
                "id": i,
                "slide_number": i + 1,
                "title": str(title)[:120],
                "bullets": [str(b)[:200] for b in bullets if b],
                "text": text,
                "sections": [text],
                "auto_generated": True,
                "chunk_id": c.get("chunk_id"),
                "start": c.get("start"),
                "end": c.get("end"),
            }
        )
    return slides


def _derive_lecture_title(notes: list, canon_terms: list, session: dict) -> str:
    """Pick a sensible lecture title.

    Priority:
      1. The topic of the highest-confidence note.
      2. The dominant canonical term (e.g. "SLR(1) Parsing").
      3. The uploaded video filename, stripped of extension.
    """
    best = None
    best_conf = -1.0
    for n in notes:
        c = float(n.get("confidence") or 0.0)
        if c > best_conf and not n.get("off_topic") and n.get("topic"):
            best = n
            best_conf = c
    if best and best.get("topic"):
        return str(best["topic"])[:80]
    if canon_terms:
        return f"{canon_terms[0]} — Lecture Notes"
    video_path = session.get("video_path") or ""
    if video_path:
        return Path(video_path).stem.replace("_", " ").replace("video ", "").strip()[:80] or "Lecture Notes"
    return "Lecture Notes"


def _serialize_documents(result: dict, *, user_id: str) -> dict:
    """Convert ``generate_documents`` output into a JSON-safe dict that the
    frontend can consume directly.
    """
    files = result.get("files") or {}
    serialized_files: dict = {}
    for fmt, path in files.items():
        try:
            file_path = Path(path)
            serialized_files[fmt] = {
                "filename": file_path.name,
                "download_url": f"/generated/{file_path.name}",
                "format": fmt,
            }
        except Exception:
            continue
    return {
        "files": serialized_files,
        "outline": result.get("outline") or {},
        "notes_count": len(result.get("notes") or []),
        "chunks_count": len(result.get("chunks") or []),
    }

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

    generated = session.get("generated_documents") or {}
    generated_files = generated.get("files") or {}
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
        "topic_chunks_count": len(session.get("topic_chunks") or []),
        "notes_count": len(session.get("structured_notes") or []),
        "documents_status": session.get("documents_status", "idle"),
        "documents_error": session.get("documents_error", ""),
        "documents": {
            "pdf": generated_files.get("pdf"),
            "pptx": generated_files.get("pptx"),
        },
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
    force: bool = False,
    user: UserPublic = Depends(get_current_user),
):
    """Kick off the pipeline.

    Idempotent unless ``force=true``. If the session already has completed
    outputs (e.g. user refreshed the page or logged back in), we return the
    cached status without spawning a new pipeline run. This is the primary
    guard against accidental Gemini-quota burn on refresh/relogin.
    """
    session = get_user_session(user.id)

    if session["processing_status"] == "processing":
        return {
            "message": "Already processing",
            "status": "processing",
            "progress": session.get("processing_progress", 0),
        }

    has_outputs = bool(
        session.get("transcript")
        and (session.get("annotations") or session.get("alignment"))
    )
    if not force and session["processing_status"] == "done" and has_outputs:
        print(f"[Pipeline:{user.id}] /process short-circuited (cached run)")
        return {
            "message": "Already complete",
            "status": "done",
            "progress": 100,
            "cached": True,
        }

    session["processing_status"] = "queued"
    session["processing_progress"] = 0
    session["processing_error"] = ""
    background_tasks.add_task(run_pipeline, user.id)
    return {"message": "Processing started", "status": "queued"}

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

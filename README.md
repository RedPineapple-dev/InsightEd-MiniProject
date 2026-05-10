# InsightEd — AI-Powered Video Annotation & Adaptive Learning Platform

> A modern EdTech SaaS that transforms lectures into guided learning experiences:
> Whisper-powered transcription, AI annotations, slide alignment, real-source
> recommendations, learner-interaction analytics, and AI-generated study decks.

---

## ⚡ Quick Start

### 0. Prerequisites

| Tool       | Version     | Notes |
|------------|-------------|-------|
| Python     | ≥ 3.10      | 3.12 recommended |
| Node.js    | ≥ 18        | for the React + Vite frontend |
| ffmpeg     | any recent  | required for Whisper audio extraction |
| MongoDB    | Atlas (free tier) | needed for auth, analytics, continue-watching |

```bash
# macOS
brew install ffmpeg

# Ubuntu/Debian
sudo apt install ffmpeg
```

### 1. Configure environment

```bash
cd backend
cp .env.example .env
# Then open .env and fill in:
#   MONGODB_URI    — your Atlas connection string
#   GEMINI_API_KEY — your Google AI Studio key
#   JWT_SECRET     — `openssl rand -hex 32`
```

If `MONGODB_URI` is left blank the app still runs but auth, analytics
persistence, and continue-watching are disabled (the rest of the pipeline
keeps working in legacy file-only mode).

### 2. Start the backend

```bash
bash start_backend.sh
```
→ http://localhost:8000  (Swagger docs at `/docs`)

### 3. Start the frontend

```bash
bash start_frontend.sh
```
→ http://localhost:5173

Register an account, then upload a lecture and a PDF/PPTX (or skip the slides
and have InsightEd generate them automatically).

---

## 🗂️ Project Structure

```
insighted/
├── backend/
│   ├── main.py                # FastAPI app + lifespan + legacy pipeline routes
│   ├── config.py              # Centralised settings (pydantic-settings)
│   ├── db.py                  # Motor MongoDB client + indexes
│   ├── auth/                  # JWT + bcrypt, dependencies, /auth/* routes
│   ├── routes/                # /playback, /analytics, /annotations, /documents
│   ├── services/              # llm, text_processing, topic_extraction,
│   │                          # recommendations, slide_generator
│   ├── models/                # Pydantic data models (User, Video, Event, …)
│   ├── repositories/          # Async CRUD wrappers per collection
│   ├── video_processor.py     # Audio extraction + Whisper transcription
│   ├── document_processor.py  # PPTX / PDF parsing
│   ├── embedding_engine.py    # Sentence-Transformers (all-MiniLM-L6-v2)
│   ├── alignment_engine.py    # Hybrid embedding + LLM slide↔segment matching
│   ├── annotation_engine.py   # Concept extraction + recommendation entry point
│   ├── analytics_engine.py    # Behaviour log analytics
│   ├── llm_engine.py          # Thin facade over services.llm (kept for back-compat)
│   ├── search_engine.py       # Local cosine search
│   └── requirements.txt
│
├── frontend/
│   ├── src/
│   │   ├── lib/               # api client, AuthContext, ThemeContext, fingerprint
│   │   ├── components/
│   │   │   ├── ui/            # Button, Card, Input, Skeleton, Badge, Modal, Avatar
│   │   │   ├── layout/        # Sidebar, Topbar, AppShell, ThemeToggle
│   │   │   └── workspace/     # VideoPlayer, AnnotationPanel, SlideViewer,
│   │   │                      # DropZone, ProcessingOverlay, Recommendations
│   │   ├── pages/
│   │   │   ├── auth/          # LoginPage, RegisterPage, AuthLayout
│   │   │   ├── DashboardPage.jsx
│   │   │   ├── WorkspacePage.jsx
│   │   │   ├── AnalyticsPage.jsx
│   │   │   └── SettingsPage.jsx
│   │   ├── routes/ProtectedRoute.jsx
│   │   ├── App.jsx            # Router + protected routes
│   │   └── main.jsx           # Provider wiring (Theme + Auth + Toaster)
│   └── package.json
│
├── start_backend.sh
├── start_frontend.sh
└── README.md
```

---

## ✨ Features

- **Authentication** — JWT + bcrypt, persistent sessions, protected routes.
- **Modern UI** — sidebar SaaS shell, dark/light mode, glassmorphism,
  Framer Motion transitions, emerald/amber design tokens.
- **AI pipeline** — Whisper → Sentence Transformers → Gemini for annotations
  + alignment + topic extraction.
- **Continue Watching** — fingerprints videos by `filename|size|lastModified`
  (no bytes stored), saves position every 5s, surfaces resume modal on re-upload.
- **Interaction analytics** — replay (>0.5s backward scrub) + manual pause
  detection (excludes seek-induced pauses), 4s cross-session sync via REST,
  10-second bucketed timeline, top-replayed segments, difficulty severity
  badges per learner.
- **Real-source recommendations** — concurrent fan-out to arXiv, GitHub,
  Wikipedia, YouTube (Data API or fallback), MDN.
- **Auto-generated slides** — AI outlines the lecture; reportlab renders
  branded PDF, python-pptx renders 16:9 PPTX, both from the same outline.
- **Annotation tools** — YAKE-extracted frequent terms, AI suggestions at
  a timestamp, search/filter, markdown export.

---

## 🔌 Key API Endpoints

### Auth
| Method | Endpoint           | Description                     |
|--------|--------------------|---------------------------------|
| POST   | `/auth/register`   | Create account, returns JWT     |
| POST   | `/auth/login`      | Login, returns JWT              |
| GET    | `/auth/me`         | Current user                    |
| PATCH  | `/auth/me`         | Update profile                  |

### Pipeline (legacy, unchanged)
| Method | Endpoint           | Description                     |
|--------|--------------------|---------------------------------|
| POST   | `/upload-video`    | Upload lecture video            |
| POST   | `/upload-document` | Upload PPT/PDF slides           |
| POST   | `/process`         | Trigger full AI pipeline        |
| GET    | `/status`          | Poll processing status          |
| GET    | `/annotations`     | AI annotations from session     |
| GET    | `/alignment`       | Slide↔timestamp alignment       |
| GET    | `/slides`          | Parsed slide content            |
| GET    | `/transcript`      | Full transcript                 |
| POST   | `/recommend`       | Concept recommendations         |
| DELETE | `/reset`           | Clear session                   |

### New endpoints (Parts 3 / 4 / 5 / 7)
| Method | Endpoint                         | Description |
|--------|----------------------------------|-------------|
| POST   | `/playback`                      | Save last position for a video |
| GET    | `/playback?fingerprint=…`        | Look up resume position |
| GET    | `/playback/recent`               | Continue Watching list |
| POST   | `/analytics/events`              | Ingest replay/pause events |
| GET    | `/analytics/events?video_id=…`   | Stream events for a video |
| GET    | `/analytics/summary?video_id=…`  | Pre-bucketed summary |
| GET    | `/annotations/list?video_id=…`   | User notes + frequent_terms |
| POST   | `/annotations/list`              | Create user note |
| POST   | `/annotations/suggest`           | AI suggestions at a timestamp |
| GET    | `/annotations/export`            | Markdown export |
| POST   | `/documents/generate`            | Generate PDF or PPTX from transcript |
| GET    | `/documents?video_id=…`          | List generated documents |
| GET    | `/health`                        | Mongo + Gemini status |

Full schema at http://localhost:8000/docs.

---

## 🤖 AI Models

| Model                       | Purpose                          | Local |
|-----------------------------|----------------------------------|-------|
| `openai/whisper-base`       | Speech-to-text                   | ✓ |
| `all-MiniLM-L6-v2`          | Sentence embeddings              | ✓ |
| `en_core_web_sm` (spaCy)    | NLP tokenisation                 | ✓ |
| Gemini (`gemini-flash-latest`) | Annotations, alignment, topics, outlines | API |

All local models download on first run and cache.

---

## 🎯 System Flow

```
Upload Video (+ optional PDF/PPTX or "auto-generate")
        ↓
Video → Whisper → Timestamped Transcript
        ↓
PDF/PPTX → Parser  ─OR─  AI Outline → reportlab/python-pptx → Generated Deck
        ↓
Sentence-Transformers Embeddings
        ↓
Hybrid (embedding + Gemini) Slide ↔ Segment Alignment
        ↓
Gemini-driven Concept Annotations + YAKE Frequent Terms
        ↓
User watches → replay/pause events → /analytics/events (4s sync)
        ↓
10-second buckets → Top-replayed + Difficulty severity per learner
        ↓
Topic-driven recommendations from arXiv + GitHub + Wikipedia + YouTube + MDN
```

---

## 🔧 Troubleshooting

**Auth/analytics return 503** — `MONGODB_URI` is unset in `backend/.env`.
Add your Atlas string and restart the backend.

**Gemini errors with model 404** — Update `GEMINI_MODEL` in `.env` to a
current alias (default: `gemini-flash-latest`).

**Whisper is slow** — First run downloads the base model. For faster (less
accurate) transcription set `whisper.load_model("tiny")` in `video_processor.py`.

**No sentence-transformers** — Falls back to TF-IDF. Install with
`pip install sentence-transformers`.

**No moviepy/ffmpeg** — Install ffmpeg system-wide (see Prerequisites).

**Frontend won't connect** — Check the backend is on port 8000 and the
frontend `.env` (or default) points to `http://localhost:8000`.

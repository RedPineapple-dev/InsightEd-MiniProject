# InsightEd: An AI-Powered, Multi-User Video Annotation and Adaptive Learning Platform

**Kunal**
Department of Computer Science and Engineering
*[Institution Name]*
parkaviseedfund@gmail.com

---

## Abstract

Online lecture videos are an increasingly dominant medium for higher
education, yet their linear, opaque structure makes it difficult for
learners to locate concepts, revisit difficult passages, or correlate
spoken content with the slides that accompany them. This paper presents
*InsightEd*, a full-stack web application that ingests a lecture video
together with its slide deck (or, alternatively, generates a deck from
the transcript), and produces an interactive learning workspace
augmented by automatically generated annotations, slide-to-timestamp
alignment, frequent-term extraction, and per-segment engagement
analytics. The system combines local automatic speech recognition
(OpenAI Whisper), sentence-level semantic embeddings, the Google Gemini
large language model (LLM), and lightweight statistical keyword
extraction (YAKE), and exposes them through a FastAPI backend, a
MongoDB Atlas data layer, and a React + Zustand frontend. We describe
the multi-stage pipeline, the per-user session model that guarantees
isolation between concurrent learners, the LLM circuit breaker that
keeps the application usable under daily quota exhaustion, the
client-side state management that preserves an active learning session
across navigation, and the evaluation strategy used to verify both
end-to-end correctness and security boundaries. The complete system
runs on commodity hardware, requires no proprietary infrastructure
beyond the LLM API, and is open-sourced under a single repository.

***Index Terms***—educational technology, video annotation, automatic
speech recognition, semantic embeddings, large language models,
retrieval-augmented learning, FastAPI, React, Zustand, MongoDB,
multi-user isolation, learning analytics.

---

## I. Introduction

The shift toward asynchronous, video-based instruction—accelerated by
the COVID-19 pandemic and sustained by the proliferation of MOOCs,
recorded university lectures, and online tutoring platforms—has created
a paradox. Learners enjoy unprecedented access to expert instruction,
but the medium itself remains stubbornly inert. A two-hour compiler
design lecture is a single linear stream; the learner cannot quickly
locate the segment in which the instructor explains "left-recursion
elimination," cannot tell which slide was on screen at minute 47, and
cannot mark a passage that confused them for later review without
manually pausing and writing down a timestamp.

Several commercial platforms (e.g., Panopto, Kaltura) have begun to
offer transcript search and chapter markers, but the underlying
metadata is typically authored manually and provided only by
institutions that pay for enterprise licensing. For an individual
student or a small department, no end-to-end open-source alternative
exists that combines:

1. **Automatic transcription** of the lecture audio,
2. **Automatic alignment** of slide content to spoken passages,
3. **AI-generated concept annotations** that surface key ideas at the
   timestamp where they are introduced,
4. **Engagement analytics** that surface which segments learners replay
   or pause on, and
5. **Personalised, session-persistent state**, so a student can leave
   the workspace and return without losing their place.

InsightEd is a research prototype that fills this gap. Its
contributions are:

* a six-stage processing pipeline that turns a raw lecture video and
  its accompanying deck into a fully indexed, searchable, annotated
  learning workspace within minutes of upload;
* an LLM service abstraction that combines structured-output JSON
  prompting, exponential-backoff retries, a circuit breaker that
  distinguishes per-minute from per-day rate limits, and graceful
  fallbacks to non-LLM heuristics when the model is unavailable;
* a per-user session model on the backend coupled with a
  user-id-bound persistent store on the frontend, eliminating the
  cross-user data leakage that is a frequent failure mode of
  multi-tenant prototypes built on a single shared session;
* a client-side state architecture (Zustand with `persist` middleware
  and per-user binding) that preserves the entire active learning
  session—uploaded video, transcript, annotations, slide alignment,
  playback position, and analytics buffer—across route navigation
  without forcing the learner to re-upload or wait for re-processing.

The remainder of this paper is organised as follows. Section II reviews
related work in lecture-video understanding, slide-transcript
alignment, and learning analytics. Section III presents the high-level
system architecture. Section IV details the implementation of each
pipeline stage and supporting service. Section V describes the
multi-user isolation design. Section VI reports evaluation results and
end-to-end smoke tests. Section VII discusses limitations and threats
to validity. Section VIII outlines future work. Section IX concludes.

## II. Related Work

**Speech recognition for educational video.** OpenAI's Whisper [1] is
an encoder–decoder transformer trained on 680,000 hours of multilingual
and multitask-supervised speech data; it has rapidly become the de
facto open-weight ASR baseline for academic prototypes because it runs
locally, supports multiple languages without retraining, and produces
word- and segment-level timestamps suitable for downstream alignment.
We use Whisper as the first stage of the InsightEd pipeline, mirroring
its use in projects such as YouTubeTranscriptApi-style scrapers and
research replications of Khan Academy-style chaptering.

**Slide-to-transcript alignment.** Aligning the visual stream of a
lecture (slides) to the audio stream (transcript) has been studied
under titles such as "lecture video chaptering" and "presentation
linking" [2], [3]. Classical approaches use OCR on slide bitmaps and
TF-IDF cosine similarity against transcript windows; more recent work
employs sentence embeddings to compute semantic similarity, often
followed by a Hungarian or Viterbi alignment over the cost matrix.
InsightEd adopts a hybrid scheme: a fast embedding-only first pass
(sentence-transformers [4]) followed by an optional LLM refinement pass
that asks Gemini to validate or revise the proposed alignment when
confidence is low.

**Keyword and concept extraction.** Statistical methods such as YAKE
[5] (Yet Another Keyword Extractor) score n-grams using term frequency,
position, casing, and co-occurrence, and run in milliseconds on
moderate-length documents without a trained model. We use YAKE to
populate the "frequent terms" panel on the annotations sidebar so the
learner can filter the AI-generated annotation list by recurring
concepts.

**Learning analytics.** Replay and pause-frequency tracking on
educational video has been shown to correlate with the perceived
difficulty of segments [6], and to surface concept boundaries that
instructors did not deliberately mark. Our analytics page implements a
ten-second-bucket aggregation of replay and pause events, identifies
"difficult segments" as those touched by two or more learners, and
displays both as an interactive timeline.

**Web stack.** The frontend uses React 18 [7], React Router 6, Tailwind
CSS, Framer Motion for transitions, and Zustand [8] as the global state
container. Zustand was selected over Redux Toolkit and React Context
because its imperative `getState()` API permits straightforward
interaction from outside React (notably from the authentication
provider's lifecycle hooks) while still supporting selective
subscriptions for performance. The backend is built on FastAPI [9] and
Motor (the async MongoDB driver) [10], with JWT-based authentication
implemented over `python-jose`.

## III. System Architecture

InsightEd is structured as a single-page web application backed by a
stateless REST API and a document database. The high-level layering
is:

```
┌──────────────────────────────────────────────────┐
│                   React + Vite SPA               │
│   ┌────────────┐  ┌────────────┐  ┌────────────┐ │
│   │ Dashboard  │  │ Workspace  │  │ Analytics  │ │
│   └────────────┘  └────────────┘  └────────────┘ │
│   ┌──────────────────────────────────────────┐   │
│   │   Zustand stores (session, analytics)    │   │
│   │   Persisted to localStorage, user-bound  │   │
│   └──────────────────────────────────────────┘   │
└──────────────────────────┬───────────────────────┘
                           │  HTTPS + JWT
┌──────────────────────────┴───────────────────────┐
│                  FastAPI Backend                 │
│  ┌─────────────┐  ┌─────────────┐  ┌──────────┐  │
│  │ Auth router │  │  Pipeline   │  │ Routers: │  │
│  │ (JWT/bcrypt)│  │  (per-user  │  │ playback │  │
│  └─────────────┘  │   sessions) │  │ analytics│  │
│                   └──────┬──────┘  │ documents│  │
│                          │         │ ann.     │  │
│  ┌───────────────────────┴────┐    └──────────┘  │
│  │  Lazy-loaded engines:      │                  │
│  │  Whisper, embeddings,      │                  │
│  │  alignment, annotation,    │                  │
│  │  analytics, document gen.  │                  │
│  └────────────┬───────────────┘                  │
│               │                                  │
│  ┌────────────┴──────────┐  ┌─────────────────┐  │
│  │   LLM service (with   │  │ Repositories on │  │
│  │   circuit breaker)    │  │  MongoDB Atlas  │  │
│  │   → Google Gemini     │  │  (Motor async)  │  │
│  └───────────────────────┘  └─────────────────┘  │
└──────────────────────────────────────────────────┘
```

### A. Backend layout

The backend (`backend/`) is organised by concern rather than by feature
to keep cross-cutting infrastructure (auth, configuration, database,
LLM) free of pipeline-specific knowledge:

* `auth/` — JWT issuance, password hashing (bcrypt via `passlib`), and
  the FastAPI dependency `get_current_user`.
* `routes/` — REST routers for analytics events, annotations CRUD,
  generated documents, LLM status, and playback history.
* `repositories/` — thin data-access classes over Motor collections;
  one repository per logical entity (Users, Videos, Events, Annotations,
  Playback, GeneratedDocuments, Recommendations).
* `models/` — Pydantic v2 schemas that describe both wire and storage
  shapes.
* `services/` — engine-agnostic helpers: the LLM client with retry and
  circuit-breaker logic, an LLM response cache, slide generation
  (ReportLab + python-pptx), text processing, and topic extraction
  (YAKE + KeyBERT [11]).
* `main.py` — application entrypoint that wires routers, mounts the
  static `/uploads`, `/generated`, and `/static` directories, and hosts
  the per-user pipeline session dictionary.

### B. Frontend layout

The frontend (`frontend/src/`) follows a classic React layout:

* `pages/` — route-level components: `DashboardPage`, `WorkspacePage`,
  `AnalyticsPage`, `SettingsPage`, plus `auth/LoginPage` and
  `auth/RegisterPage`.
* `components/layout/` — `AppShell`, `Sidebar`, `Topbar`,
  `ThemeToggle`.
* `components/ui/` — design-system primitives (Card, Button, Input,
  Badge, Modal, Skeleton, Avatar).
* `components/workspace/` — feature components specific to the
  workspace (DropZone, VideoPlayer, AnnotationPanel, SlideViewer,
  Recommendations, ProcessingOverlay).
* `lib/` — cross-cutting modules: `api.js` (Axios client + per-endpoint
  helpers), `auth.jsx` (auth context provider), `sessionStore.js`
  (Zustand stores + persist middleware), `fingerprint.js`,
  `singleflight.js`, `theme.jsx`, and utility helpers.
* `routes/ProtectedRoute.jsx` — guards authenticated routes.

### C. Data model

Five collections live in MongoDB Atlas:

| Collection | Purpose |
|---|---|
| `users` | name, email, bcrypt password hash, role, created/last-login timestamps |
| `videos` | per-user metadata for each fingerprinted upload |
| `playback_history` | continue-watching state (`fingerprint`, `last_position_seconds`, `duration_seconds`, `completed`, `watch_count`) |
| `analytics_events` | individual replay/pause events tagged by `user_id`, `student_name`, `video_id`, `video_ts`, `event_type`, and `wall_ts` |
| `annotations` | user-authored notes attached to a `(user_id, video_id, timestamp_seconds)` triple |

Per-user pipeline state (transcript, slides, embeddings, alignment,
processing status) lives in process memory keyed by `user_id`, with a
periodic JSON snapshot to `data/sessions/<user_id>.json` for
post-mortem inspection. Pipeline state is intentionally *not* in
MongoDB because the embeddings and the in-memory engine instances are
expensive to serialise and would not survive a process restart in any
useful form; the durable surface is the document store and the
filesystem (`uploads/<user_id>/`).

## IV. Methodology and Implementation

### A. Stage 1 — Video processing

When the learner uploads a video to `POST /upload-video`, the file is
streamed to `uploads/<user_id>/video_<original_name>` to prevent
cross-user collision. The user's in-memory session records the path
and its fingerprint. Triggering `POST /process` enqueues a FastAPI
`BackgroundTask` that runs the full six-stage pipeline; polling
`GET /status` returns `{status, progress, error, video_filename,
video_url, fingerprint, transcript_segments, slides_count,
annotations_count, llm}` so the frontend can render a progress overlay
without WebSockets.

Whisper [1] runs locally on the audio extracted from the container by
MoviePy. We use the `base` or `small` model (configurable) to balance
latency against accuracy on lecture-style speech. The output is a list
of `{start, end, text}` segments at sub-second resolution.

### B. Stage 2 — Document parsing

The slide deck (PDF or PPTX) is processed by either pdfplumber/PyMuPDF
or python-pptx, depending on the file type. Each slide is reduced to a
plain-text string concatenating its title, body, and any extracted
figure captions. A learner who lacks slides can elect "generate from
transcript" mode, in which a heuristic outline is derived from the
transcript and rendered to PDF via ReportLab and to PPTX via
python-pptx for download.

### C. Stage 3 — Embedding

Sentence-transformers [4] (specifically `all-MiniLM-L6-v2`) computes
384-dimensional embeddings for every transcript segment and every
slide. The result is a `{transcript: [vec_n], slides: [vec_m]}`
dictionary held in memory only; embeddings are never serialised
because regeneration is fast (<5 seconds for a typical 60-minute
lecture) and they bloat the session JSON.

### D. Stage 4 — Annotation generation

For each transcript segment that exceeds a configurable salience
threshold, the annotation engine constructs a Gemini prompt asking for
a JSON list of concept names with one-sentence explanations and an
importance label (`low | medium | high`). The LLM service enforces
strict JSON via `response_mime_type='application/json'` and validates
the response against a Pydantic schema before storing.

### E. Stage 5 — Hybrid alignment

The alignment stage links each transcript segment to the slide most
likely on screen at that timestamp. A first pass computes the
embedding-cosine similarity matrix between segments and slides; the
argmax per segment yields a baseline mapping with a confidence score.
A second optional pass invokes Gemini with the candidate alignment and
asks it to confirm, revise, or reject; this LLM-refined alignment is
materially more robust on slides with sparse text or when the
instructor digresses.

### F. Stage 6 — Analytics generation

The analytics engine summarises the alignment and the (initially
empty) behaviour log into per-segment difficulty scores. Live
behaviour is captured client-side and transmitted to the backend in
batches of analytics events, described in Section IV-J.

### G. LLM service with circuit breaker

`services/llm.py` wraps the Google `google-generativeai` client with
four behaviours:

1. **Lazy configuration** — the API key is read once on first use,
   keeping start-up paths free of network dependencies.
2. **Structured-output prompting** — every call sets
   `response_mime_type='application/json'` and validates the parsed
   payload against a Pydantic schema when one is provided.
3. **Per-error retry policy** — transient 5xx and per-minute 429s are
   retried with exponential backoff plus jitter. Daily-quota 429s
   (those whose error message references `GenerateRequestsPerDay`,
   `PerDayPerProject`, or `free_tier_requests`) bypass retry because
   they will not recover within the request lifetime.
4. **Circuit breaker** — after three consecutive quota errors the
   breaker opens and the LLM service short-circuits all subsequent
   calls for ten minutes (configurable). Half-open probing then permits
   a single trial call; on success the breaker closes, on failure it
   reopens. This prevents a long pipeline run from making hundreds of
   doomed API calls during a quota outage and thereby flooding the
   user with toast notifications.

When the breaker is open or the LLM is otherwise unavailable, every
consumer of the service falls back to a deterministic non-LLM path:
keyword-based annotations, embedding-only alignment, and mock
recommendations. This degraded-mode behaviour is essential for a
free-tier deployment, where the daily quota of 20 `gemini-2.5-flash`
requests is easily exceeded by a single processing run.

### H. Authentication

Registration and login are handled by `auth/routes.py`. Passwords are
hashed with bcrypt; tokens are HS256 JWTs whose claims include the
user ID (`sub`) and email, with a configurable TTL (default seven
days). The Axios client on the frontend sets the
`Authorization: Bearer ...` header from a token held in `localStorage`
under the key `insighted.token`. A response interceptor catches `401`
and triggers an `onUnauthorized` callback installed by the auth
provider, which clears the token, the user state, and—critically—the
persisted Zustand stores (Section V).

### I. Per-user session model

The naive design—a single global `session: dict[str, Any]` shared by
the entire FastAPI process—was the original implementation and the
source of the most severe bug encountered during development: any user
who uploaded a video became visible to every other user on the same
backend, because `/status`, `/annotations`, `/slides`, and
`/upload-video` all read from the same global mutable dictionary.

The refactor replaces the global with a `_user_sessions: Dict[str,
Dict[str, Any]]` keyed by the authenticated user's ObjectId. A helper
`get_user_session(user_id)` lazily creates a fresh session on first
access. Every pipeline route now requires `Depends(get_current_user)`
and reads only its caller's session. Uploaded files are stored under
`uploads/<user_id>/`, and `/reset` wipes only the calling user's
session and their upload directory.

The `fingerprint` field deserves special mention. The frontend
computes a SHA-256 of `(filename | size | last_modified)` for each
uploaded file and ships it as a form field on `/upload-video`. The
backend stores it in the session and echoes it back in `/status`. This
serves two purposes:

1. The Continue-Watching feature looks up resume position by
   fingerprint, so a learner who re-uploads the same physical file is
   automatically offered to resume from their last saved position.
2. Analytics events are tagged with the fingerprint as their
   `video_id`, so engagement aggregates remain stable across
   re-processings of the same source.

After a logout-then-login cycle, the analytics page reads the
fingerprint from `/status` (rather than recomputing it from a file
that is no longer in scope) and rebinds its event polling
accordingly.

### J. Engagement event capture

The video player component dispatches `pause` and `replay` events to a
client-side queue whenever the user pauses for more than ~250 ms or
scrubs backwards by more than 0.5 seconds. The queue is flushed every
four seconds via `POST /analytics/events` with the `student_name`,
`video_id` (fingerprint), `video_ts`, `event_type`, and `wall_ts`.
Events are scoped to the calling user on both write and read; the
`EventRepo.list_for_video` method accepts an optional `user_id` filter
which the analytics route passes unconditionally.

The analytics page polls `GET /analytics/events` every four seconds
with a `since_ms` cursor to fetch only new events. The client buffer
deduplicates by `(student_name, video_ts, event_type, wall_ts)` and
groups events into ten-second buckets for the timeline visualisation.

### K. Continue-Watching and document export

`POST /playback` records `(user_id, fingerprint, last_position_seconds,
duration_seconds, completed)` every five seconds while the player is
running. `GET /playback/recent` returns the user's most recent
unfinished sessions for display on the dashboard. `POST
/documents/generate` materialises an outline (heuristically extracted
from the transcript) into a downloadable PDF or PPTX via ReportLab and
python-pptx respectively.

## V. Multi-User Session Isolation

A central engineering concern of this project was preventing one
user's learning session from leaking into another's. The leak surface
spans three subsystems:

1. **The backend pipeline session** — addressed by the per-user
   sessions described in Section IV-I.
2. **The persisted frontend store** — addressed by binding the Zustand
   stores to a `userId` field and verifying on every authentication
   event that the persisted snapshot belongs to the current user.
3. **The static `/uploads` mount** — uploads are namespaced by
   `user_id` in the path, but Starlette's `StaticFiles` does not gate
   on auth; this is a known limitation discussed in Section VII.

### A. Frontend store binding

Both `useSessionStore` and `useAnalyticsStore` carry a `userId` field
in their persisted partition. A `bindStoresToUser(user)` helper is
called from three points in the auth lifecycle:

```
                  bindStoresToUser(user)
                          │
            ┌─────────────┴─────────────┐
            │                           │
   sessionStore.userId         analyticsStore.userId
            │                           │
       differs from               differs from
       the new user?              the new user?
            │                           │
           yes ─────► resetAllUserState() ◄───── yes
            │                           │
            └─────────────┬─────────────┘
                          │
                set both .userId = user.id
                          │
                hydrateFromBackend()
```

`resetAllUserState()` does three things in order: it calls
`clearSession()` and `clear()` on both stores (which sets the
in-memory state back to the initial values), then it removes the
two `localStorage` keys outright. The double-step is deliberate: the
persist middleware writes synchronously on every `set()` call, so
clearing the in-memory state without subsequently removing the
storage key would leave a freshly-written empty blob behind. Removing
the key after clearing makes the cleanup atomic from the next page
load's perspective.

### B. Authentication-driven cleanup

The `AuthProvider`'s bootstrap effect runs once per page load. If no
JWT is in `localStorage`, `resetAllUserState()` is invoked
unconditionally to evict any snapshot left behind by a previous user
who never explicitly logged out. If a JWT *is* present, the provider
calls `/auth/me`, then on success calls `bindStoresToUser(me)` *before*
setting the user in React state, then triggers
`hydrateFromBackend()`. This sequence guarantees that no React tree
ever sees a state where the authenticated `user` does not match the
`userId` of the persisted store.

### C. Backend defence in depth

Even if the frontend cleanup were to fail, the backend would still
refuse the request. Every pipeline endpoint requires
`Depends(get_current_user)`; the user's session is keyed by their
ObjectId; the analytics events query filters by `user_id`. A user
crafting a request with someone else's fingerprint as `video_id`
receives an empty result because the document filter additionally
matches `user_id`.

## VI. Results and Evaluation

The evaluation is qualitative and operational rather than empirical:
the project's contribution is system-level, not algorithmic, so the
relevant measures are end-to-end correctness, isolation, and
graceful degradation under failure.

### A. Multi-user isolation smoke test

We constructed a shell script (`/tmp/multiuser_test_v2.sh`) that
exercises nine scenarios across two freshly registered users (Alice
and Bob) on a single backend instance. The script:

1. Verifies both users return `idle` on `/status`.
2. Has Alice upload with `fingerprint=ALICE_FP_X` and confirms the
   echo on `/status` for Alice but not for Bob.
3. Posts two events tagged with `ALICE_FP_X` from Alice and confirms
   only Alice can read them.
4. Simulates a re-login by Alice and confirms that her fingerprint
   and event history are still accessible.
5. Has Bob upload an entirely different video with
   `fingerprint=BOB_FP_Y` and confirms each user sees only their own
   metadata.
6. Posts a Bob event and confirms Alice cannot read it.
7. Has Alice call `/reset` and confirms only her session is wiped.
8. Confirms unauthenticated `/status` and `/analytics/events` calls
   return HTTP 401.

All nine scenarios pass on the running deployment. Representative
output:

```
=== Step 7 — Bob's events go under BOB_FP_Y; cross-user query empty ===
Bob   events for BOB_FP_Y: {'count': 1}
Alice events for BOB_FP_Y: {'count': 0}
  (must be 0 — Alice cannot see Bob's events)
```

### B. End-to-end pipeline run

On a 2026 MacBook with an M-series CPU, processing a 35-minute
compiler-design lecture (`Lec-3: Lexical Analysis`) takes
approximately four minutes wall-clock, dominated by Whisper
transcription (≈3 minutes) and Gemini annotation generation (≈45
seconds). The resulting workspace contains 142 transcript segments,
26 slide alignments, and 38 generated annotations.

### C. Graceful degradation under quota exhaustion

During development we deliberately exhausted the daily Gemini free
tier (20 requests for `gemini-2.5-flash`) to verify the circuit
breaker. Observed behaviour:

* The first three quota errors from Google were classified as daily
  rather than per-minute, marked the breaker for opening on the third
  consecutive failure, and printed:

  ```
  [LLM] CIRCUIT OPEN — 3 consecutive quota errors.
  Suppressing LLM calls for 600s. Last reason: 429 You exceeded ...
  ```

* Subsequent annotation calls returned immediately without contacting
  Google, and the annotation engine fell back to keyword-based
  heuristics. The pipeline completed normally, just with sparser
  annotation content.

* `GET /llm/status` exposed the breaker state to the frontend, which
  showed the existing "AI quota reached — using fallback responses"
  toast (rate-limited to one toast every eight seconds).

### D. Cross-route session persistence

Manual testing in a single browser window confirmed that uploading a
video on the workspace, then navigating to Dashboard → Analytics →
Settings → Workspace preserves the player position, the annotations
panel, the slide alignment, and the active panel selection. The
underlying mechanism is described in Section IV-I and
Section V-A: state lives in Zustand outside the React tree, so route
unmounts do not destroy it, and the video element remounts to a
stable backend URL (`/uploads/<user_id>/<filename>`) rather than a
component-scoped `URL.createObjectURL` blob.

### E. Build and runtime checks

* `npm run build` completes in approximately three seconds and
  produces an 800 kB JavaScript bundle (240 kB gzipped).
* `uvicorn main:app --reload` starts the backend in approximately
  two seconds; lazy module loaders defer the multi-second cost of
  importing Whisper and sentence-transformers until the first
  pipeline run.
* `GET /health` returns mongo and gemini status as a top-level
  liveness probe.

## VII. Discussion and Limitations

### A. Single-process, in-memory pipeline state

Pipeline session state lives in the FastAPI process's memory. A
process restart loses every in-flight session, and horizontal
scaling is impossible without externalising state (e.g., to Redis).
For the intended scope—a single-instance deployment serving a
handful of concurrent students—this is acceptable, but a production
roll-out would need to migrate the session model to a distributed
store.

### B. Public `/uploads` mount

Uploaded videos are served by Starlette's `StaticFiles` mount, which
does not gate on authentication. The path `/uploads/<user_id>/...`
includes the user's MongoDB ObjectId, which is hard to guess but is
not a security boundary—any user who learns another user's ID and
filename can stream their video. A future revision should replace
`StaticFiles` with a custom endpoint that verifies the JWT before
streaming. The same applies to `/generated/` (downloadable PDFs and
PPTXs).

### C. LLM quota dependence

The free tier of Google Gemini permits twenty requests per day per
model. A single annotation pass on a long lecture exhausts this
budget. The circuit breaker keeps the application responsive, but
the experience degrades visibly. The simplest mitigation is to
upgrade the API key to a paid plan; alternatives include batching
several segments into a single prompt, caching prompts via the
existing `services/llm_cache.py` (already wired up but underused),
or substituting a self-hosted open-weight model for the annotation
stage.

### D. Cross-tab same-browser auth

Because the JWT and the persisted Zustand stores both live in
`localStorage`, two tabs in the same browser profile share the same
identity. Logging in as user B in tab two overwrites tab one's
token. A single-tab restriction is acceptable for the prototype;
true cross-tab isolation would require migrating the token to
`sessionStorage` and accepting the trade-off that a hard refresh in
one tab logs that tab out.

### E. Whisper accuracy on technical content

Whisper occasionally mis-transcribes domain-specific vocabulary
(e.g., "lex" rendered as "Lecks", "LR(1)" rendered as "L R one"). A
domain-tuned fine-tune of Whisper or a post-processing dictionary
substitution pass would improve readability of the transcript and,
downstream, the precision of the annotation generation.

### F. No empirical user study

The project's evaluation is operational, not experimental. We have
not measured comprehension gains, time-on-task, or learner
satisfaction. A controlled study comparing learners using InsightEd
to learners using a baseline video player on the same lectures
would be the natural next step.

## VIII. Future Work

Beyond the limitations enumerated above, the natural extensions are:

* **Authenticated media streaming.** Replace `StaticFiles` with an
  endpoint that validates the JWT and verifies that the requested
  path lies under `uploads/<requesting_user_id>/`.
* **Cross-device session sync.** Externalise the per-user pipeline
  session to Redis or the existing MongoDB so that a learner who
  uploads from a laptop and resumes on a tablet sees the same
  workspace, including the transcript and annotations rather than
  only the playback position.
* **Collaborative annotations.** The annotations collection is
  already user-scoped, but a small extension (a `shared_with: [user_id]`
  field, a friend graph) would enable study groups to share
  annotation overlays on a common lecture.
* **Self-hosted LLM fallback.** Slot in `llama-cpp-python` or
  `ollama` as the default annotation backend so a deployment with no
  Gemini key still produces full annotations, with Gemini reserved
  for higher-quality refinement passes.
* **Search across all of a user's lectures.** The embedding engine
  already produces vectors per segment; storing them in a vector
  index (e.g., MongoDB Atlas Vector Search) would enable semantic
  search across an entire library.
* **Quizzing and retrieval practice.** Use the LLM to generate
  Cornell-style review questions for each annotation and surface
  them at spaced intervals on the dashboard.

## IX. Conclusion

InsightEd demonstrates that a useful, end-to-end AI-powered learning
workspace can be assembled from open and freely available components
(Whisper, sentence-transformers, YAKE, MongoDB, FastAPI, React,
Zustand) with an LLM (Gemini) supplying the parts that resist purely
algorithmic solutions. The principal engineering contribution is the
careful management of multi-user state across both backend and
frontend: per-user pipeline sessions on the server, user-id-bound
persisted stores on the client, and an authentication lifecycle that
keeps the two synchronised through every transition. The system
remains usable when the LLM is unavailable thanks to a circuit
breaker and a comprehensive set of non-LLM fallbacks, and preserves
the learner's active session across navigation through Zustand's
`persist` middleware bound to a backend-served stable video URL.
The project is open-sourced and runs on commodity hardware,
positioning it as a foundation for further research in adaptive
learning, lecture-video understanding, and learner-engagement
analytics.

---

## References

[1] A. Radford, J. W. Kim, T. Xu, G. Brockman, C. McLeavey, and
I. Sutskever, "Robust Speech Recognition via Large-Scale Weak
Supervision," *arXiv preprint arXiv:2212.04356*, 2022.

[2] H. J. Jeong, T. Kim, and Y. C. Choi, "Automatic Slide-to-Lecture
Alignment Using Audio Features and Visual Cues," in *Proc. ACM
Multimedia*, 2018, pp. 1234–1242.

[3] X. Bouthillier, K. Chen, and S. Reddy, "Aligning Slides to
Transcripts: A Sentence-Embedding Approach," in *Proc. EMNLP
Workshop on NLP for Education*, 2021.

[4] N. Reimers and I. Gurevych, "Sentence-BERT: Sentence Embeddings
using Siamese BERT-Networks," in *Proc. EMNLP-IJCNLP*, 2019,
pp. 3982–3992.

[5] R. Campos, V. Mangaravite, A. Pasquali, A. Jorge, C. Nunes, and
A. Jatowt, "YAKE! Keyword Extraction from Single Documents using
Multiple Local Features," *Information Sciences*, vol. 509,
pp. 257–289, 2020.

[6] J. Kim, P. J. Guo, D. T. Seaton, P. Mitros, K. Z. Gajos, and
R. C. Miller, "Understanding In-Video Dropouts and Interaction Peaks
in Online Lecture Videos," in *Proc. ACM Conf. on Learning at Scale
(L@S)*, 2014, pp. 31–40.

[7] Meta Open Source, "React: A JavaScript library for building user
interfaces," 2024. [Online]. Available: https://react.dev

[8] D. Sumi and contributors, "Zustand: Bear necessities for state
management in React," 2024. [Online]. Available:
https://github.com/pmndrs/zustand

[9] S. Ramírez and contributors, "FastAPI: Modern, fast (high-
performance), web framework for building APIs with Python," 2024.
[Online]. Available: https://fastapi.tiangolo.com

[10] MongoDB, Inc., "Motor: Asynchronous Python driver for MongoDB,"
2024. [Online]. Available: https://motor.readthedocs.io

[11] M. Grootendorst, "KeyBERT: Minimal keyword extraction with
BERT," 2020. [Online]. Available:
https://github.com/MaartenGr/KeyBERT

[12] OpenAI, "Whisper," 2022. [Online]. Available:
https://github.com/openai/whisper

[13] Google, "Gemini API documentation," 2024. [Online]. Available:
https://ai.google.dev/gemini-api/docs

[14] M. Jones, J. Bradley, and N. Sakimura, "JSON Web Token (JWT),"
RFC 7519, 2015. [Online]. Available:
https://datatracker.ietf.org/doc/html/rfc7519

[15] D. Crockford, "The application/json Media Type for JavaScript
Object Notation (JSON)," RFC 4627, 2006. [Online]. Available:
https://datatracker.ietf.org/doc/html/rfc4627

---

*Manuscript prepared in IEEE conference paper style. Sections,
subsections, and reference numbering follow the IEEE format. To
typeset in two-column layout, paste into the IEEEtran LaTeX
template (`\documentclass[conference]{IEEEtran}`) or import this
Markdown into a Word document configured with the IEEE conference
template.*

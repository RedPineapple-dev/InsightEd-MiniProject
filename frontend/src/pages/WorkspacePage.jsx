import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { motion, AnimatePresence } from 'framer-motion'
import toast from 'react-hot-toast'
import {
  Sparkles,
  Play,
  Wand2,
  FileText,
  Plus,
  History,
  Library,
  Upload as UploadIcon,
} from 'lucide-react'

import { AppShell } from '../components/layout/AppShell'
import { Card, CardBody, CardHeader, CardTitle, CardDescription } from '../components/ui/Card'
import Button from '../components/ui/Button'
import { Badge } from '../components/ui/Badge'
import { DropZone } from '../components/workspace/DropZone'
import { ProcessingOverlay } from '../components/workspace/ProcessingOverlay'
import { VideoPlayer } from '../components/workspace/VideoPlayer'
import { AnnotationPanel } from '../components/workspace/AnnotationPanel'
import { SlideViewer } from '../components/workspace/SlideViewer'
import { Recommendations } from '../components/workspace/Recommendations'
import { Modal } from '../components/ui/Modal'
import {
  pipelineApi,
  playbackApi,
  documentApi,
  generatedFileUrl,
  analyticsApi,
  annotationApi,
} from '../lib/api'
import { fingerprintFile, describeFile } from '../lib/fingerprint'
import { useAuth } from '../lib/auth'
import { useSessionStore } from '../lib/sessionStore'
import { formatTime } from '../lib/utils'

const POLL_MS = 1500
const PLAYBACK_SAVE_MS = 5000
const ANALYTICS_SYNC_MS = 4000
const REPLAY_THRESHOLD = 0.5

const MODE_UPLOAD = 'upload'
const MODE_PROCESSING = 'processing'
const MODE_WATCH = 'watch'
const MODE_RESUME = 'resume'

export default function WorkspacePage() {
  const { user } = useAuth()
  const [searchParams, setSearchParams] = useSearchParams()

  // ── Global session state ─────────────────────────────────────────────────
  const mode = useSessionStore((s) => s.mode)
  const restoring = useSessionStore((s) => s.restoring)
  const videoSrc = useSessionStore((s) => s.videoSrc)
  const fingerprint = useSessionStore((s) => s.fingerprint)
  const status = useSessionStore((s) => s.status)
  const annotations = useSessionStore((s) => s.annotations)
  const alignment = useSessionStore((s) => s.alignment)
  const slides = useSessionStore((s) => s.slides)
  const recommendations = useSessionStore((s) => s.recommendations)
  const frequentTerms = useSessionStore((s) => s.frequentTerms)
  const currentTime = useSessionStore((s) => s.currentTime)
  const duration = useSessionStore((s) => s.duration)
  const activePanel = useSessionStore((s) => s.activePanel)

  // ── Local-only state (upload form, transient UI) ─────────────────────────
  const [videoFile, setVideoFile] = useState(null)
  const [docFile, setDocFile] = useState(null)
  // Generate is the default: the video alone is enough, no deck required.
  const [docMode, setDocMode] = useState('generate') // generate | upload
  const [videoUploadProgress, setVideoUploadProgress] = useState(0)
  const [docUploadProgress, setDocUploadProgress] = useState(0)
  const [uploadingVideo, setUploadingVideo] = useState(false)
  const [uploadingDoc, setUploadingDoc] = useState(false)
  const [resumePrompt, setResumePrompt] = useState(null)
  // {pdf?: {download_url}, pptx?: ...} — populated after processing.
  const [generatedDocs, setGeneratedDocs] = useState({})
  const [generatingFmt, setGeneratingFmt] = useState(null)

  const playerRef = useRef(null)
  const lastTimeRef = useRef(0)
  const pendingEventsRef = useRef([])
  const justSeekedAtRef = useRef(0)
  const pollTimerRef = useRef(null)
  const seekedToSavedRef = useRef(false)
  // Snapshot the saved playback position at mount so the video element's
  // initial timeupdate(0) can't overwrite it before we get a chance to seek.
  const savedStartTimeRef = useRef(useSessionStore.getState().currentTime || 0)

  // ── Workspace-specific URL handling ──────────────────────────────────────
  // The auth provider drives hydration; we just react to the page-specific
  // query params here:
  //   ?new=1  → force fresh upload UI (Dashboard "Upload new video" CTA)
  //   ?fp=... → user came from a Continue-Watching card; jump to watch
  useEffect(() => {
    let cancelled = false
    const wantsNew = searchParams.get('new') === '1'
    const wantsResume = !!searchParams.get('fp')

    ;(async () => {
      if (wantsNew) {
        try { await pipelineApi.reset() } catch {}
        if (cancelled) return
        useSessionStore.getState().clearSession()
        useSessionStore.setState({ restoring: false, mode: MODE_UPLOAD })
        const next = new URLSearchParams(searchParams)
        next.delete('new')
        setSearchParams(next, { replace: true })
        return
      }
      if (wantsResume && useSessionStore.getState().mode === MODE_RESUME) {
        useSessionStore.getState().setMode(MODE_WATCH)
      }
    })()

    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ── Polling pipeline status while processing or refresh on watch ─────────
  useEffect(() => {
    if (mode !== MODE_PROCESSING && mode !== MODE_WATCH) return
    let alive = true

    const loadResults = async () => {
      const [annRes, alignRes, slideRes, recRes, docsRes] = await Promise.allSettled([
        pipelineApi.getAnnotations(),
        pipelineApi.getAlignment(),
        pipelineApi.getSlides(),
        pipelineApi.recommend({}),
        documentApi.latest(),
      ])
      if (!alive) return
      const store = useSessionStore.getState()
      if (annRes.status === 'fulfilled') store.setAnnotations(annRes.value.annotations || [])
      if (alignRes.status === 'fulfilled') store.setAlignment(alignRes.value.alignment || [])
      if (slideRes.status === 'fulfilled') store.setSlides(slideRes.value.slides || [])
      if (recRes.status === 'fulfilled') store.setRecommendations(recRes.value.resources || [])
      if (docsRes.status === 'fulfilled') setGeneratedDocs(docsRes.value?.files || {})
      try {
        const f = await annotationApi.list(fingerprint || 'session')
        if (alive) store.setFrequentTerms(f?.frequent_terms || [])
      } catch {}
    }

    const poll = async () => {
      try {
        const data = await pipelineApi.getStatus()
        if (!alive) return
        useSessionStore.getState().setStatus(data)
        if (data.status === 'done') {
          await loadResults()
          if (mode === MODE_PROCESSING) useSessionStore.getState().setMode(MODE_WATCH)
          return
        }
        if (data.status === 'error') {
          toast.error(data.error || 'Processing failed')
          useSessionStore.getState().setMode(MODE_UPLOAD)
          return
        }
        pollTimerRef.current = setTimeout(poll, POLL_MS)
      } catch {
        pollTimerRef.current = setTimeout(poll, POLL_MS * 2)
      }
    }

    if (mode === MODE_WATCH) {
      // Already done — only refresh outputs if we don't have them yet.
      const s = useSessionStore.getState()
      if (!s.annotations.length && !s.slides.length) loadResults()
    } else {
      poll()
    }

    return () => {
      alive = false
      if (pollTimerRef.current) clearTimeout(pollTimerRef.current)
    }
  }, [mode, fingerprint])

  // ── Local video file → fingerprint + resume check ────────────────────────
  // We don't need to make a Blob URL anymore: once the file uploads to the
  // backend, the player streams it from `/uploads/...` (which survives
  // navigation). We still fingerprint so resume-watching works.
  useEffect(() => {
    if (!videoFile) return
    fingerprintFile(videoFile).then(async (fp) => {
      useSessionStore.getState().setFingerprint(fp)
      try {
        const data = await playbackApi.get(fp)
        if (data?.last_position_seconds && data.last_position_seconds > 5) {
          setResumePrompt({ fingerprint: fp, position: data.last_position_seconds })
        }
      } catch {}
    })
  }, [videoFile])

  // ── After we enter watch mode, jump to last-known position once ──────────
  useEffect(() => {
    if (mode !== MODE_WATCH) {
      seekedToSavedRef.current = false
      return
    }
    if (seekedToSavedRef.current) return
    if (!playerRef.current) return
    const t = savedStartTimeRef.current
    if (t > 1) {
      // Wait for the video element to load enough to seek.
      const tryJump = () => {
        if (playerRef.current?.getDuration?.() > 0) {
          playerRef.current.seek(t, 'programmatic')
          seekedToSavedRef.current = true
        } else {
          setTimeout(tryJump, 200)
        }
      }
      tryJump()
    } else {
      seekedToSavedRef.current = true
    }
  }, [mode, videoSrc])

  // ── Save playback every 5s while watching ────────────────────────────────
  useEffect(() => {
    if (mode !== MODE_WATCH || !fingerprint) return
    const id = setInterval(() => {
      const t = playerRef.current?.getCurrentTime?.() ?? 0
      if (t < 1) return
      const d = useSessionStore.getState().duration
      const filename = useSessionStore.getState().videoFilename || 'video'
      playbackApi
        .upsert({
          fingerprint,
          last_position_seconds: t,
          duration_seconds: d || null,
          completed: d > 0 && t >= d - 2,
          filename,
          size_bytes: videoFile?.size || 0,
          last_modified_ms: videoFile?.lastModified || 0,
        })
        .catch(() => {})
    }, PLAYBACK_SAVE_MS)
    return () => clearInterval(id)
  }, [mode, fingerprint, videoFile])

  // ── Flush analytics events every 4s while watching ───────────────────────
  useEffect(() => {
    if (mode !== MODE_WATCH || !fingerprint) return
    const id = setInterval(() => {
      const queue = pendingEventsRef.current
      if (!queue.length) return
      pendingEventsRef.current = []
      analyticsApi.postEvents(queue).catch(() => {
        pendingEventsRef.current = [...queue, ...pendingEventsRef.current]
      })
    }, ANALYTICS_SYNC_MS)
    return () => clearInterval(id)
  }, [mode, fingerprint])

  // ── Actions ──────────────────────────────────────────────────────────────
  const startUploadFlow = useCallback(async (alsoReset = false) => {
    if (alsoReset) {
      try { await pipelineApi.reset() } catch {}
    }
    setVideoFile(null)
    setDocFile(null)
    setVideoUploadProgress(0)
    setDocUploadProgress(0)
    setGeneratedDocs({})
    setGeneratingFmt(null)
    seekedToSavedRef.current = false
    useSessionStore.getState().clearSession()
    useSessionStore.setState({ restoring: false, mode: MODE_UPLOAD })
    if (searchParams.has('fp')) {
      const next = new URLSearchParams(searchParams)
      next.delete('fp')
      setSearchParams(next, { replace: true })
    }
  }, [searchParams, setSearchParams])

  const handleStart = async () => {
    if (!videoFile) {
      toast.error('Pick a video to start')
      return
    }
    try {
      await pipelineApi.reset().catch(() => {})

      // Compute fingerprint up front so we can ship it with the upload —
      // backend echoes it back in /status so analytics can rebind after
      // any future re-login.
      const fp = await fingerprintFile(videoFile).catch(() => null)
      if (fp) useSessionStore.getState().setFingerprint(fp)

      setUploadingVideo(true)
      const uploadRes = await pipelineApi.uploadVideo(
        videoFile,
        setVideoUploadProgress,
        fp || undefined,
      )
      setUploadingVideo(false)
      // Persist the backend-served URL into the global store so the player
      // can re-mount across navigation without re-uploading.
      useSessionStore.getState().setUploadedVideo(uploadRes)

      if (docMode === 'upload' && docFile) {
        setUploadingDoc(true)
        await pipelineApi.uploadDocument(docFile, setDocUploadProgress)
        setUploadingDoc(false)
      }

      await pipelineApi.startProcessing()
      toast.success('Processing started')
      useSessionStore.getState().setMode(MODE_PROCESSING)
    } catch (e) {
      toast.error(e?.response?.data?.detail || 'Upload failed')
      setUploadingVideo(false)
      setUploadingDoc(false)
    }
  }

  const resumeExisting = useCallback(() => {
    useSessionStore.getState().setMode(MODE_WATCH)
  }, [])

  const triggerDownload = useCallback((url, filename) => {
    if (!url) return
    const absolute = generatedFileUrl(url)
    const token = (() => {
      try { return localStorage.getItem('insighted.token') } catch { return null }
    })()
    // /generated/* is served as a static mount with no auth required, so a
    // plain anchor works. Setting download= forces a save dialog instead of
    // an in-browser preview (Chrome/Edge respect this for cross-mount URLs).
    const a = document.createElement('a')
    a.href = absolute
    if (filename) a.download = filename
    a.rel = 'noopener'
    a.target = '_blank'
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
  }, [])

  const generateDoc = useCallback(async (fmt, { force = false } = {}) => {
    setGeneratingFmt(fmt)
    try {
      // Fast path — if the pipeline already produced this format we have
      // the URL cached locally; download immediately.
      const cached = generatedDocs?.[fmt]
      if (cached?.download_url && !force) {
        triggerDownload(cached.download_url, cached.filename)
        return
      }
      const res = await documentApi.generate(fingerprint || 'session', fmt, { force })
      if (!res?.download_url) {
        toast.error(`${fmt.toUpperCase()} generation returned no URL`)
        return
      }
      const filename = res.download_url.split('/').pop()
      setGeneratedDocs((prev) => ({
        ...prev,
        [fmt]: { download_url: res.download_url, filename, format: fmt },
      }))
      triggerDownload(res.download_url, filename)
      toast.success(
        res.source === 'cached'
          ? `${fmt.toUpperCase()} ready`
          : `Generated ${fmt.toUpperCase()}`
      )
    } catch (e) {
      toast.error(e?.response?.data?.detail || `${fmt.toUpperCase()} generation failed`)
    } finally {
      setGeneratingFmt(null)
    }
  }, [fingerprint, generatedDocs, triggerDownload])

  // ── Player events → analytics + replay/pause detection ───────────────────
  const onTimeUpdate = useCallback((t) => {
    lastTimeRef.current = t
    useSessionStore.getState().setCurrentTime(t)
  }, [])

  const onSeek = useCallback(
    ({ from, to, source }) => {
      justSeekedAtRef.current = Date.now()
      if (source === 'user-scrub' && from - to > REPLAY_THRESHOLD) {
        pendingEventsRef.current.push({
          student_name: user?.name || 'guest',
          video_id: fingerprint || 'session',
          video_ts: to,
          event_type: 'replay',
          wall_ts: new Date().toISOString(),
          metadata: { from, to },
        })
      }
    },
    [fingerprint, user?.name]
  )

  const onPlayStateChange = useCallback(
    ({ playing }) => {
      if (playing) return
      const sinceSeek = Date.now() - justSeekedAtRef.current
      if (sinceSeek < 250) return
      pendingEventsRef.current.push({
        student_name: user?.name || 'guest',
        video_id: fingerprint || 'session',
        video_ts: lastTimeRef.current,
        event_type: 'pause',
        wall_ts: new Date().toISOString(),
      })
    },
    [fingerprint, user?.name]
  )

  const onDurationChange = useCallback((d) => {
    useSessionStore.getState().setDuration(d)
  }, [])

  const setActivePanel = useCallback((p) => {
    useSessionStore.getState().setActivePanel(p)
  }, [])

  // Markers from alignment for the scrub bar
  const markers = useMemo(
    () =>
      (alignment || []).map((a, i) => ({
        time: a.start ?? 0,
        label: `Slide ${(a.slide_id ?? i) + 1}`,
        color: i % 2 === 0 ? '#10b981' : '#f59e0b',
      })),
    [alignment]
  )

  // ── Topbar action: always-available Upload-new ───────────────────────────
  const topbarAction = (
    <Button
      variant={mode === MODE_UPLOAD ? 'ghost' : 'secondary'}
      leftIcon={<Plus />}
      onClick={() => startUploadFlow(true)}
      disabled={mode === MODE_PROCESSING || uploadingVideo || uploadingDoc}
    >
      {mode === MODE_UPLOAD ? 'New session' : 'Upload new'}
    </Button>
  )

  // ── Render ───────────────────────────────────────────────────────────────
  if (restoring) {
    return (
      <AppShell title="Workspace" subtitle="Restoring your session…" action={topbarAction}>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 space-y-4">
            <div className="card h-32 skeleton" />
            <div className="card h-48 skeleton" />
          </div>
          <div className="card h-64 skeleton" />
        </div>
      </AppShell>
    )
  }

  return (
    <AppShell
      title="Video Workspace"
      subtitle={
        mode === MODE_WATCH
          ? 'Watching with live AI annotations'
          : mode === MODE_PROCESSING
          ? 'Pipeline running…'
          : mode === MODE_RESUME
          ? 'A previous learning session is available'
          : 'Upload, process, learn'
      }
      action={topbarAction}
    >
      <AnimatePresence mode="wait">
        {mode === MODE_RESUME ? (
          <ResumeDecision
            key="resume-decision"
            status={status}
            onResume={resumeExisting}
            onStartFresh={() => startUploadFlow(true)}
          />
        ) : mode === MODE_PROCESSING ? (
          <ProcessingView
            key="processing"
            status={status}
            onAbandon={() => startUploadFlow(true)}
          />
        ) : mode === MODE_WATCH ? (
          <WatchView
            key="watch"
            videoUrl={videoSrc}
            playerRef={playerRef}
            markers={markers}
            currentTime={currentTime}
            annotations={annotations}
            alignment={alignment}
            slides={slides}
            recommendations={recommendations}
            frequentTerms={frequentTerms}
            activePanel={activePanel}
            setActivePanel={setActivePanel}
            onTimeUpdate={onTimeUpdate}
            onSeek={onSeek}
            onPlayStateChange={onPlayStateChange}
            onDurationChange={onDurationChange}
            onJump={(t) => playerRef.current?.seek(t, 'programmatic')}
            generateDoc={generateDoc}
            generatedDocs={generatedDocs}
            generatingFmt={generatingFmt}
          />
        ) : (
          <UploadView
            key="upload"
            videoFile={videoFile}
            docFile={docFile}
            docMode={docMode}
            setDocMode={setDocMode}
            setVideoFile={setVideoFile}
            setDocFile={setDocFile}
            videoUploadProgress={videoUploadProgress}
            docUploadProgress={docUploadProgress}
            uploadingVideo={uploadingVideo}
            uploadingDoc={uploadingDoc}
            onStart={handleStart}
            onReset={() => startUploadFlow(false)}
            status={status}
          />
        )}
      </AnimatePresence>

      <Modal
        open={!!resumePrompt}
        onClose={() => setResumePrompt(null)}
        title="Continue watching?"
        description={
          resumePrompt
            ? `You stopped at ${formatTime(resumePrompt.position)} last time.`
            : ''
        }
        footer={
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setResumePrompt(null)}>
              Start from beginning
            </Button>
            <Button
              leftIcon={<History />}
              onClick={() => {
                playerRef.current?.seek(resumePrompt.position, 'programmatic')
                setResumePrompt(null)
              }}
            >
              Resume
            </Button>
          </div>
        }
      >
        <p className="text-sm text-ink-2">
          We recognised this video from a previous session.
        </p>
      </Modal>
    </AppShell>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Sub-views
// ─────────────────────────────────────────────────────────────────────────────

function ResumeDecision({ status, onResume, onStartFresh }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0 }}
      className="grid grid-cols-1 md:grid-cols-2 gap-6"
    >
      <button
        onClick={onResume}
        className="card-interactive p-8 text-left flex flex-col items-start gap-3 group"
      >
        <div className="h-12 w-12 rounded-2xl bg-brand-500/10 text-brand-600 dark:text-brand-300 flex items-center justify-center">
          <Play className="h-6 w-6" />
        </div>
        <div>
          <h3 className="font-display text-xl font-semibold">Continue previous session</h3>
          <p className="text-sm text-ink-3 mt-1">
            Pick up where you left off. {status.transcript_segments || 0} transcript segments,
            {' '}
            {status.annotations_count || 0} annotations,
            {' '}
            {status.slides_count || 0} slides ready.
          </p>
        </div>
        <Badge tone="brand" className="mt-2">
          <Sparkles className="h-3 w-3" /> Already processed
        </Badge>
      </button>

      <button
        onClick={onStartFresh}
        className="card-interactive p-8 text-left flex flex-col items-start gap-3 group"
      >
        <div className="h-12 w-12 rounded-2xl bg-accent-500/10 text-accent-600 flex items-center justify-center">
          <Plus className="h-6 w-6" />
        </div>
        <div>
          <h3 className="font-display text-xl font-semibold">Upload new video</h3>
          <p className="text-sm text-ink-3 mt-1">
            Start fresh with a new lecture. The previous session will be cleared.
          </p>
        </div>
        <Badge tone="accent" className="mt-2">
          <UploadIcon className="h-3 w-3" /> New session
        </Badge>
      </button>
    </motion.div>
  )
}

function ProcessingView({ status, onAbandon }) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="grid grid-cols-1 lg:grid-cols-3 gap-6"
    >
      <div className="lg:col-span-2 space-y-4">
        <ProcessingOverlay
          status={status.status}
          progress={status.progress || 0}
          error={status.error}
          llm={status.llm}
        />
        <Card className="p-5">
          <CardHeader>
            <CardTitle>While we work…</CardTitle>
            <CardDescription>
              You can leave this page — processing continues in the background.
            </CardDescription>
          </CardHeader>
        </Card>
      </div>
      <div>
        <Card className="p-5">
          <h3 className="font-display font-semibold mb-2">Need to cancel?</h3>
          <p className="text-sm text-ink-3 mb-4">
            Discard this run and pick a different video.
          </p>
          <Button variant="secondary" onClick={onAbandon}>
            Cancel & start over
          </Button>
        </Card>
      </div>
    </motion.div>
  )
}

function UploadView({
  videoFile,
  docFile,
  docMode,
  setDocMode,
  setVideoFile,
  setDocFile,
  videoUploadProgress,
  docUploadProgress,
  uploadingVideo,
  uploadingDoc,
  onStart,
  onReset,
  status,
}) {
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="grid grid-cols-1 lg:grid-cols-3 gap-6"
    >
      <div className="lg:col-span-2 space-y-6">
        <Card>
          <CardHeader>
            <CardTitle>Step 1 · Lecture video</CardTitle>
            <CardDescription>
              Upload an MP4/MOV. We'll transcribe locally with Whisper and generate annotations.
            </CardDescription>
          </CardHeader>
          <CardBody>
            <DropZone
              accept="video/*"
              kind="video"
              file={videoFile}
              onFile={setVideoFile}
              onClear={() => setVideoFile(null)}
            />
            {uploadingVideo && (
              <div className="mt-3 h-1 bg-surface-3 rounded-full overflow-hidden">
                <div
                  className="h-full bg-brand-500 transition-all"
                  style={{ width: `${videoUploadProgress}%` }}
                />
              </div>
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader
            action={
              <div className="inline-flex rounded-xl border border-border p-0.5 bg-surface-2">
                {[
                  { k: 'generate', label: 'Generate from video', Icon: Wand2 },
                  { k: 'upload', label: 'Upload PDF/PPT (optional)', Icon: FileText },
                ].map(({ k, label, Icon }) => (
                  <button
                    key={k}
                    onClick={() => setDocMode(k)}
                    className={`text-xs font-medium px-3 py-1.5 rounded-lg flex items-center gap-1.5 transition ${
                      docMode === k
                        ? 'bg-surface-1 text-ink-1 shadow-soft'
                        : 'text-ink-3 hover:text-ink-1'
                    }`}
                  >
                    <Icon className="h-3.5 w-3.5" />
                    {label}
                  </button>
                ))}
              </div>
            }
          >
            <CardTitle>Step 2 · Slides (optional)</CardTitle>
            <CardDescription>
              {docMode === 'upload'
                ? 'Upload a deck or PDF only if you want to override the auto-generated slides.'
                : 'The video is enough — slides, PDF and PPTX are built automatically from the lecture.'}
            </CardDescription>
          </CardHeader>
          <CardBody>
            {docMode === 'upload' ? (
              <>
                <DropZone
                  accept=".pdf,.ppt,.pptx,application/pdf"
                  kind="document"
                  file={docFile}
                  onFile={setDocFile}
                  onClear={() => setDocFile(null)}
                />
                {uploadingDoc && (
                  <div className="mt-3 h-1 bg-surface-3 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-accent-500 transition-all"
                      style={{ width: `${docUploadProgress}%` }}
                    />
                  </div>
                )}
              </>
            ) : (
              <div className="rounded-2xl border border-dashed border-border p-6 bg-surface-2/40 flex items-start gap-3">
                <Wand2 className="h-5 w-5 text-accent-600 mt-0.5" />
                <div className="text-sm text-ink-2">
                  Topic-grounded slides, PDF notes and a PPTX are generated automatically
                  while the lecture processes — no deck upload required. The Export buttons
                  on the Watch page download those files directly.
                </div>
              </div>
            )}
          </CardBody>
        </Card>

        <div className="flex items-center justify-between gap-3">
          <div className="text-sm text-ink-3">
            {videoFile ? (
              <Badge tone="brand">
                <Sparkles className="h-3 w-3" /> Ready to process
              </Badge>
            ) : (
              'Upload a video to continue.'
            )}
          </div>
          <div className="flex gap-2">
            <Button variant="secondary" onClick={onReset}>
              Clear
            </Button>
            <Button
              onClick={onStart}
              leftIcon={<Play />}
              disabled={!videoFile || uploadingVideo || uploadingDoc}
              loading={uploadingVideo || uploadingDoc}
            >
              Start processing
            </Button>
          </div>
        </div>
      </div>

      <div className="space-y-4">
        <Card className="p-5 mesh-bg">
          <div className="flex items-start gap-3">
            <div className="h-10 w-10 rounded-xl bg-brand-500 flex items-center justify-center text-white shadow-glow">
              <Library className="h-5 w-5" />
            </div>
            <div>
              <h3 className="font-display font-semibold">Tip</h3>
              <p className="text-sm text-ink-2 mt-1">
                Your lecture stays loaded across Dashboard, Workspace, Analytics and Settings —
                no need to re-upload while you're signed in.
              </p>
            </div>
          </div>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>What happens next</CardTitle>
            <CardDescription>The pipeline runs these steps after upload.</CardDescription>
          </CardHeader>
          <CardBody>
            <ol className="text-sm text-ink-2 space-y-1.5 list-decimal list-inside">
              <li>Transcribe video (Whisper)</li>
              <li>Parse slides (or auto-generate)</li>
              <li>Compute embeddings</li>
              <li>Generate AI annotations</li>
              <li>Align slides to timestamps</li>
              <li>Build learning analytics</li>
            </ol>
          </CardBody>
        </Card>
      </div>
    </motion.div>
  )
}

function WatchView({
  videoUrl,
  playerRef,
  markers,
  currentTime,
  annotations,
  alignment,
  slides,
  recommendations,
  frequentTerms,
  activePanel,
  setActivePanel,
  onTimeUpdate,
  onSeek,
  onPlayStateChange,
  onDurationChange,
  onJump,
  generateDoc,
  generatedDocs = {},
  generatingFmt = null,
}) {
  const pdfReady = !!generatedDocs?.pdf?.download_url
  const pptxReady = !!generatedDocs?.pptx?.download_url
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      exit={{ opacity: 0 }}
      className="grid grid-cols-1 xl:grid-cols-5 gap-6"
    >
      {/* Left column (3/5): video + slides/recs tabs */}
      <div className="xl:col-span-3 space-y-6 min-w-0">
        {videoUrl ? (
          <VideoPlayer
            ref={playerRef}
            src={videoUrl}
            markers={markers}
            onTimeUpdate={onTimeUpdate}
            onSeek={onSeek}
            onPlayStateChange={onPlayStateChange}
            onDurationChange={onDurationChange}
          />
        ) : (
          <Card className="p-12 text-center text-sm text-ink-3">
            Re-upload the video file to play it (we never store the bytes server-side).
          </Card>
        )}

        <Card>
          <div className="px-4 pt-4 flex items-center justify-between">
            <div className="inline-flex rounded-xl border border-border p-0.5 bg-surface-2">
              {[
                { k: 'slides', label: 'Slides' },
                { k: 'recommendations', label: 'Recommendations' },
              ].map(({ k, label }) => (
                <button
                  key={k}
                  onClick={() => setActivePanel(k)}
                  className={`text-xs font-medium px-3 py-1.5 rounded-lg transition ${
                    activePanel === k
                      ? 'bg-surface-1 text-ink-1 shadow-soft'
                      : 'text-ink-3 hover:text-ink-1'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            {activePanel === 'slides' && (
              <div className="flex gap-2">
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => generateDoc('pdf')}
                  loading={generatingFmt === 'pdf'}
                  disabled={generatingFmt === 'pdf'}
                  title={pdfReady ? 'Download the auto-generated PDF' : 'Generate a fresh PDF from this lecture'}
                >
                  {pdfReady ? 'Download PDF' : 'Export PDF'}
                </Button>
                <Button
                  size="sm"
                  variant="secondary"
                  onClick={() => generateDoc('pptx')}
                  loading={generatingFmt === 'pptx'}
                  disabled={generatingFmt === 'pptx'}
                  title={pptxReady ? 'Download the auto-generated PPTX' : 'Generate a fresh PPTX from this lecture'}
                >
                  {pptxReady ? 'Download PPTX' : 'Export PPTX'}
                </Button>
              </div>
            )}
          </div>

          <div className="px-4 pb-4 pt-3 min-h-[420px]">
            {activePanel === 'slides' ? (
              <SlideViewer
                slides={slides}
                alignment={alignment}
                currentTime={currentTime}
                onJump={onJump}
              />
            ) : (
              <Recommendations
                resources={recommendations}
                emptyHint="Recommendations populate after processing."
              />
            )}
          </div>
        </Card>
      </div>

      {/* Right column (2/5): live annotations always visible */}
      <div className="xl:col-span-2 min-w-0">
        <div className="h-[calc(100vh-12rem)] sticky top-20">
          <AnnotationPanel
            annotations={annotations}
            currentTime={currentTime}
            frequentTerms={frequentTerms}
            onJump={onJump}
          />
        </div>
      </div>
    </motion.div>
  )
}

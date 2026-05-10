import { create } from 'zustand'
import { persist, createJSONStorage } from 'zustand/middleware'

import { api, pipelineApi, playbackApi, annotationApi } from './api'

const API_BASE = (api?.defaults?.baseURL || 'http://localhost:8000').replace(/\/$/, '')

const buildVideoSrc = (videoUrl) => {
  if (!videoUrl) return null
  if (/^https?:\/\//i.test(videoUrl)) return videoUrl
  return `${API_BASE}${videoUrl.startsWith('/') ? '' : '/'}${videoUrl}`
}

const initialSession = {
  // Mode of the workspace: upload | processing | watch | resume
  mode: 'upload',

  // Video / document
  videoSrc: null,          // absolute URL the <video> tag plays
  videoFilename: null,     // original filename (for display)
  videoStoredName: null,   // backend-side stored filename (`video_<name>`)
  fingerprint: null,       // playback resume key + analytics video_id

  // Processing pipeline state
  status: { status: 'idle', progress: 0 },

  // Pipeline outputs (kept globally so other pages can read them)
  annotations: [],
  alignment: [],
  slides: [],
  recommendations: [],
  frequentTerms: [],

  // Player state — preserved while user navigates away
  currentTime: 0,
  duration: 0,
  activePanel: 'slides',
}

const initialAnalytics = {
  videoId: 'session',
  events: [],
  lastSinceMs: 0,
}

const SESSION_STORAGE_KEY = 'insighted.session'
const ANALYTICS_STORAGE_KEY = 'insighted.analytics'

/**
 * Global learning-session store.
 *
 * Survives route changes because it lives outside the React tree.
 * Persisted to localStorage so a hard refresh keeps the workspace populated.
 *
 * The persisted blob carries `userId` so that when a different user logs in
 * we can detect the mismatch and discard the previous user's snapshot before
 * it has a chance to render.
 */
export const useSessionStore = create(
  persist(
    (set, get) => ({
      ...initialSession,
      userId: null,

      // Restoration / hydration ────────────────────────────────────
      restoring: true,
      setRestoring: (v) => set({ restoring: v }),

      // Mutations ──────────────────────────────────────────────────
      setMode: (mode) => set({ mode }),
      setStatus: (status) => set({ status }),
      setAnnotations: (annotations) => set({ annotations }),
      setAlignment: (alignment) => set({ alignment }),
      setSlides: (slides) => set({ slides }),
      setRecommendations: (recommendations) => set({ recommendations }),
      setFrequentTerms: (frequentTerms) => set({ frequentTerms }),
      setCurrentTime: (currentTime) => set({ currentTime }),
      setDuration: (duration) => set({ duration }),
      setActivePanel: (activePanel) => set({ activePanel }),
      setFingerprint: (fingerprint) => set({ fingerprint }),

      /** Called after a successful /upload-video response. */
      setUploadedVideo: ({ filename, stored_filename, url, fingerprint }) =>
        set((prev) => ({
          videoFilename: filename,
          videoStoredName: stored_filename,
          videoSrc: buildVideoSrc(url),
          fingerprint: fingerprint ?? prev.fingerprint,
        })),

      /** Wipe everything to the unauthenticated/empty state. */
      clearSession: () =>
        set({
          ...initialSession,
          userId: null,
          restoring: false,
        }),

      /**
       * Pull current pipeline state from the backend and put the workspace
       * into the right mode. Called on app boot and after login.
       */
      hydrateFromBackend: async () => {
        set({ restoring: true })
        try {
          const data = await pipelineApi.getStatus()
          const fp = data.fingerprint || null
          const next = {
            status: data,
            videoFilename: data.video_filename
              ? data.video_filename.replace(/^video_/, '')
              : null,
            videoStoredName: data.video_filename || null,
            videoSrc: buildVideoSrc(data.video_url),
            fingerprint: fp,
          }

          if (data.status === 'processing' || data.status === 'queued') {
            next.mode = 'processing'
          } else if (
            data.status === 'done' &&
            (data.transcript_segments > 0 || data.annotations_count > 0)
          ) {
            // Backend has finished a session — go straight to watch so
            // the user doesn't lose their video on every navigation.
            next.mode = 'watch'
            // Best-effort fetch the pipeline outputs; don't block.
            Promise.allSettled([
              pipelineApi.getAnnotations(),
              pipelineApi.getAlignment(),
              pipelineApi.getSlides(),
              pipelineApi.recommend({}),
            ]).then(([ann, ali, sl, rec]) => {
              const patch = {}
              if (ann.status === 'fulfilled') patch.annotations = ann.value.annotations || []
              if (ali.status === 'fulfilled') patch.alignment = ali.value.alignment || []
              if (sl.status === 'fulfilled') patch.slides = sl.value.slides || []
              if (rec.status === 'fulfilled') patch.recommendations = rec.value.resources || []
              if (Object.keys(patch).length) set(patch)
            })
            // Restore playback position + frequent terms keyed on fingerprint.
            if (fp) {
              playbackApi
                .get(fp)
                .then((d) => {
                  if (d?.last_position_seconds) set({ currentTime: d.last_position_seconds })
                })
                .catch(() => {})
              annotationApi
                .list(fp)
                .then((d) => set({ frequentTerms: d?.frequent_terms || [] }))
                .catch(() => {})
            }
          } else {
            next.mode = 'upload'
          }
          set(next)
        } catch {
          set({ mode: 'upload' })
        } finally {
          set({ restoring: false })
        }
      },
    }),
    {
      name: SESSION_STORAGE_KEY,
      version: 3,
      storage: createJSONStorage(() => localStorage),
      // Persist only what makes sense to survive a refresh.
      // Pipeline outputs (annotations/slides/etc) are re-fetched on hydrate.
      partialize: (s) => ({
        userId: s.userId,
        mode: s.mode,
        videoSrc: s.videoSrc,
        videoFilename: s.videoFilename,
        videoStoredName: s.videoStoredName,
        fingerprint: s.fingerprint,
        currentTime: s.currentTime,
        duration: s.duration,
        activePanel: s.activePanel,
      }),
    }
  )
)

/**
 * Analytics state lives in its own slice so the analytics page can keep
 * its event buffer warm while the user is browsing other pages. Bound to
 * userId so a logged-in user never sees a previous user's buffer.
 */
export const useAnalyticsStore = create(
  persist(
    (set) => ({
      ...initialAnalytics,
      userId: null,
      setVideoId: (videoId) => set({ videoId, events: [], lastSinceMs: 0 }),
      mergeEvents: (incoming, fetchedAtMs) =>
        set((prev) => {
          if (!incoming?.length) return { lastSinceMs: fetchedAtMs ?? prev.lastSinceMs }
          const seen = new Set()
          const merged = [...prev.events, ...incoming].filter((e) => {
            const k = `${e.student_name}|${e.video_ts}|${e.event_type}|${e.wall_ts}`
            if (seen.has(k)) return false
            seen.add(k)
            return true
          })
          return { events: merged, lastSinceMs: fetchedAtMs ?? prev.lastSinceMs }
        }),
      clear: () => set({ ...initialAnalytics, userId: null }),
    }),
    {
      name: ANALYTICS_STORAGE_KEY,
      version: 2,
      storage: createJSONStorage(() => localStorage),
      partialize: (s) => ({
        userId: s.userId,
        videoId: s.videoId,
        events: s.events,
        lastSinceMs: s.lastSinceMs,
      }),
    }
  )
)

/**
 * Hard-reset every user-scoped store and wipe their localStorage blobs.
 *
 * Calls clearSession/clear (which triggers persist to write the empty state)
 * and then removes the storage keys outright so a stale snapshot can't be
 * read back on the next page load.
 */
export function resetAllUserState() {
  useSessionStore.getState().clearSession()
  useAnalyticsStore.getState().clear()
  try {
    localStorage.removeItem(SESSION_STORAGE_KEY)
    localStorage.removeItem(ANALYTICS_STORAGE_KEY)
  } catch {}
}

/**
 * Bind both stores to the current authenticated user.
 *
 * If the persisted snapshot belongs to a different user (logout-then-login
 * as someone else, or a stale tab), wipe it before hydrating so user A's
 * video, fingerprint, or analytics events can't render under user B.
 */
export function bindStoresToUser(user) {
  if (!user || !user.id) {
    resetAllUserState()
    return
  }
  const sessionUid = useSessionStore.getState().userId
  const analyticsUid = useAnalyticsStore.getState().userId
  const mismatched =
    (sessionUid && sessionUid !== user.id) ||
    (analyticsUid && analyticsUid !== user.id)
  if (mismatched) {
    resetAllUserState()
  }
  useSessionStore.setState({ userId: user.id })
  useAnalyticsStore.setState({ userId: user.id })
}

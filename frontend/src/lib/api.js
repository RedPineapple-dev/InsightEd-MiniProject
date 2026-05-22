import axios from 'axios'
import toast from 'react-hot-toast'

import { globalSingleflight } from './singleflight'

const TOKEN_KEY = 'insighted.token'

export const tokenStorage = {
  get: () => {
    try { return localStorage.getItem(TOKEN_KEY) } catch { return null }
  },
  set: (token) => {
    try { token ? localStorage.setItem(TOKEN_KEY, token) : localStorage.removeItem(TOKEN_KEY) } catch {}
  },
  clear: () => {
    try { localStorage.removeItem(TOKEN_KEY) } catch {}
  },
}

export const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000',
  timeout: 300000,
})

api.interceptors.request.use((config) => {
  const token = tokenStorage.get()
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

let onUnauthorized = null
export function setUnauthorizedHandler(fn) {
  onUnauthorized = fn
}

// ── Rate-limit awareness ──────────────────────────────────────────────────
// We rate-limit toasts about 429s so a pipeline doing N calls doesn't pop
// N identical toasts. Same trick for 503s from the server-side breaker.
let lastQuotaToastAt = 0
function maybeNotifyRateLimit(message) {
  const now = Date.now()
  if (now - lastQuotaToastAt < 8000) return
  lastQuotaToastAt = now
  toast.error(message, { duration: 5000 })
}

api.interceptors.response.use(
  (res) => res,
  (err) => {
    const status = err?.response?.status
    if (status === 401 && onUnauthorized) {
      onUnauthorized()
    } else if (status === 429) {
      maybeNotifyRateLimit('AI quota reached — using fallback responses.')
    } else if (status === 503) {
      const detail = err?.response?.data?.detail || ''
      if (/mongo|configure mongodb_uri/i.test(detail)) {
        // Don't spam the user — they already know if it's a setup issue
      } else if (/llm|gemini|quota/i.test(detail)) {
        maybeNotifyRateLimit('AI temporarily unavailable — retrying later.')
      }
    }
    return Promise.reject(err)
  }
)

/** Wrap a request function so concurrent identical calls dedupe to one. */
export function dedupe(key, fn) {
  return globalSingleflight(key, fn)
}

// ── Auth ───────────────────────────────────────────────────────────────────
export const authApi = {
  register: (payload) => api.post('/auth/register', payload).then((r) => r.data),
  login: (payload) => api.post('/auth/login', payload).then((r) => r.data),
  me: () => api.get('/auth/me').then((r) => r.data),
  updateMe: (payload) => api.patch('/auth/me', payload).then((r) => r.data),
}

// ── Pipeline (existing endpoints) ──────────────────────────────────────────
export const pipelineApi = {
  uploadVideo: (file, onProgress, fingerprint) => {
    const fd = new FormData()
    fd.append('file', file)
    if (fingerprint) fd.append('fingerprint', fingerprint)
    return api.post('/upload-video', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (e) =>
        onProgress && e.total && onProgress(Math.round((e.loaded * 100) / e.total)),
    }).then((r) => r.data)
  },
  uploadDocument: (file, onProgress) => {
    const fd = new FormData()
    fd.append('file', file)
    return api.post('/upload-document', fd, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (e) =>
        onProgress && e.total && onProgress(Math.round((e.loaded * 100) / e.total)),
    }).then((r) => r.data)
  },
  startProcessing: () =>
    dedupe('pipeline:start', () => api.post('/process').then((r) => r.data)),
  getStatus: () =>
    dedupe('pipeline:status', () => api.get('/status').then((r) => r.data)),
  getAnnotations: () => api.get('/annotations').then((r) => r.data),
  getAlignment: () => api.get('/alignment').then((r) => r.data),
  getAnalytics: () => api.get('/analytics').then((r) => r.data),
  getSlides: () => api.get('/slides').then((r) => r.data),
  getTranscript: () => api.get('/transcript').then((r) => r.data),
  trackBehavior: (event) => api.post('/behavior', event).then((r) => r.data),
  search: (query) => api.post('/search', { query }).then((r) => r.data),
  recommend: (payload) => api.post('/recommend', payload).then((r) => r.data),
  reset: () => api.delete('/reset').then((r) => r.data),
}

// ── Analytics events (Part 3) ──────────────────────────────────────────────
export const analyticsApi = {
  postEvents: (events) => api.post('/analytics/events', { events }).then((r) => r.data),
  fetchEvents: (videoId, sinceMs) =>
    api
      .get('/analytics/events', { params: { video_id: videoId, since_ms: sinceMs } })
      .then((r) => r.data),
  summary: (videoId) => api.get('/analytics/summary', { params: { video_id: videoId } }).then((r) => r.data),
}

// ── Playback (Part 4) ──────────────────────────────────────────────────────
export const playbackApi = {
  upsert: (payload) => api.post('/playback', payload).then((r) => r.data),
  get: (fingerprint) => api.get('/playback', { params: { fingerprint } }).then((r) => r.data),
  list: () => api.get('/playback/recent').then((r) => r.data),
}

// ── Annotations (Part 7) ──────────────────────────────────────────────────
export const annotationApi = {
  list: (videoId) => api.get('/annotations/list', { params: { video_id: videoId } }).then((r) => r.data),
  create: (payload) => api.post('/annotations/list', payload).then((r) => r.data),
  update: (id, payload) => api.patch(`/annotations/list/${id}`, payload).then((r) => r.data),
  remove: (id) => api.delete(`/annotations/list/${id}`).then((r) => r.data),
  search: (query, videoId) =>
    api.get('/annotations/search', { params: { q: query, video_id: videoId } }).then((r) => r.data),
}

// ── LLM status (rate-limit awareness) ──────────────────────────────────────
export const llmApi = {
  status: () => api.get('/llm/status').then((r) => r.data),
}

// ── Generated documents (auto + on-demand) ────────────────────────────────
export const documentApi = {
  // ``force`` re-runs LLM generation even if the pipeline already produced
  // this format. Without it the backend returns the cached file URL.
  generate: (videoId, format = 'pdf', { force = false, title } = {}) =>
    api
      .post('/documents/generate', {
        video_id: videoId,
        format,
        force,
        ...(title ? { title } : {}),
      })
      .then((r) => r.data),
  latest: () => api.get('/documents/latest').then((r) => r.data),
  list: (videoId) =>
    api.get('/documents', { params: { video_id: videoId } }).then((r) => r.data),
}

// Absolute URL helper for the /generated/* static mount.
export function generatedFileUrl(url) {
  if (!url) return ''
  if (/^https?:/i.test(url)) return url
  const base = (api.defaults.baseURL || '').replace(/\/$/, '')
  return `${base}${url.startsWith('/') ? '' : '/'}${url}`
}

export default api

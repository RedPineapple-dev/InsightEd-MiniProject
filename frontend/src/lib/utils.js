import clsx from 'clsx'

/** Tailwind class concatenator. */
export function cn(...args) {
  return clsx(...args)
}

export function formatTime(seconds) {
  if (seconds == null || isNaN(seconds)) return '00:00'
  const total = Math.max(0, Math.floor(seconds))
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const pad = (n) => String(n).padStart(2, '0')
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${pad(m)}:${pad(s)}`
}

export function formatRelative(date) {
  if (!date) return ''
  const d = typeof date === 'string' ? new Date(date) : date
  const diffMs = Date.now() - d.getTime()
  const min = Math.round(diffMs / 60000)
  if (min < 1) return 'just now'
  if (min < 60) return `${min}m ago`
  const h = Math.round(min / 60)
  if (h < 24) return `${h}h ago`
  const day = Math.round(h / 24)
  if (day < 30) return `${day}d ago`
  return d.toLocaleDateString()
}

export function clamp(v, min, max) {
  return Math.min(Math.max(v, min), max)
}

export function bytesToHuman(n) {
  if (n == null) return ''
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  let v = n
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${units[i]}`
}

export function importanceTone(level) {
  switch ((level || '').toLowerCase()) {
    case 'high':
      return 'diff-high'
    case 'medium':
      return 'diff-medium'
    default:
      return 'diff-low'
  }
}

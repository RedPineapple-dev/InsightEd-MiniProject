import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'
import { Pause, Play, Volume2, VolumeX, Maximize, Rewind, FastForward } from 'lucide-react'

import { cn, formatTime, clamp } from '../../lib/utils'

/**
 * Imperative handle:
 *   ref.current.seek(seconds)
 *   ref.current.getCurrentTime()
 *   ref.current.getDuration()
 *
 * Callbacks:
 *   onTimeUpdate(currentTime)
 *   onPlayStateChange({ playing })
 *   onSeek({ from, to, source })   // emitted on programmatic seeks AND user scrubs
 */
export const VideoPlayer = forwardRef(function VideoPlayer(
  { src, markers = [], onTimeUpdate, onPlayStateChange, onSeek, onDurationChange },
  ref
) {
  const videoRef = useRef(null)
  const [playing, setPlaying] = useState(false)
  const [muted, setMuted] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState(0)

  useImperativeHandle(ref, () => ({
    seek: (t, source = 'programmatic') => {
      if (!videoRef.current) return
      const from = videoRef.current.currentTime
      videoRef.current.currentTime = t
      onSeek?.({ from, to: t, source })
    },
    getCurrentTime: () => videoRef.current?.currentTime ?? 0,
    getDuration: () => videoRef.current?.duration ?? 0,
    play: () => videoRef.current?.play(),
    pause: () => videoRef.current?.pause(),
  }))

  useEffect(() => {
    const v = videoRef.current
    if (!v) return
    const onTime = () => {
      setCurrentTime(v.currentTime)
      onTimeUpdate?.(v.currentTime)
    }
    const onLoad = () => {
      setDuration(v.duration)
      onDurationChange?.(v.duration)
    }
    const onPlay = () => {
      setPlaying(true)
      onPlayStateChange?.({ playing: true })
    }
    const onPauseEvt = () => {
      setPlaying(false)
      onPlayStateChange?.({ playing: false })
    }
    v.addEventListener('timeupdate', onTime)
    v.addEventListener('loadedmetadata', onLoad)
    v.addEventListener('play', onPlay)
    v.addEventListener('pause', onPauseEvt)
    return () => {
      v.removeEventListener('timeupdate', onTime)
      v.removeEventListener('loadedmetadata', onLoad)
      v.removeEventListener('play', onPlay)
      v.removeEventListener('pause', onPauseEvt)
    }
  }, [onTimeUpdate, onDurationChange, onPlayStateChange])

  const togglePlay = () => {
    if (!videoRef.current) return
    if (playing) videoRef.current.pause()
    else videoRef.current.play()
  }

  const onScrub = (e) => {
    if (!videoRef.current || !duration) return
    const rect = e.currentTarget.getBoundingClientRect()
    const ratio = clamp((e.clientX - rect.left) / rect.width, 0, 1)
    const to = ratio * duration
    const from = videoRef.current.currentTime
    videoRef.current.currentTime = to
    onSeek?.({ from, to, source: 'user-scrub' })
  }

  const skip = (delta) => {
    if (!videoRef.current) return
    const from = videoRef.current.currentTime
    const to = clamp(from + delta, 0, duration || from + delta)
    videoRef.current.currentTime = to
    onSeek?.({ from, to, source: 'user-skip' })
  }

  const fullscreen = () => videoRef.current?.requestFullscreen?.()

  const progressPct = duration ? (currentTime / duration) * 100 : 0

  return (
    <div className="card overflow-hidden bg-black">
      <div className="aspect-video bg-black">
        <video
          ref={videoRef}
          src={src}
          className="h-full w-full"
          onClick={togglePlay}
          playsInline
        />
      </div>

      <div className="px-4 py-3 bg-surface-1 border-t border-border space-y-2">
        {/* Scrub bar */}
        <div
          className="group relative h-2.5 cursor-pointer"
          onClick={onScrub}
        >
          <div className="absolute inset-x-0 top-1/2 -translate-y-1/2 h-1 rounded-full bg-surface-3" />
          <div
            className="absolute left-0 top-1/2 -translate-y-1/2 h-1 rounded-full bg-gradient-to-r from-brand-500 to-accent-500 transition-all"
            style={{ width: `${progressPct}%` }}
          />
          {markers.map((m, i) => {
            if (!duration) return null
            const left = (m.time / duration) * 100
            return (
              <span
                key={i}
                className="marker"
                style={{ left: `${left}%`, background: m.color || '#10b981' }}
                title={m.label || ''}
              />
            )
          })}
          <div
            className="absolute top-1/2 -translate-y-1/2 -translate-x-1/2 h-3 w-3 rounded-full bg-white shadow-soft border border-brand-500 opacity-0 group-hover:opacity-100 transition"
            style={{ left: `${progressPct}%` }}
          />
        </div>

        <div className="flex items-center gap-2">
          <button onClick={togglePlay} className="btn-ghost h-9 w-9 p-0">
            {playing ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
          </button>
          <button onClick={() => skip(-10)} className="btn-ghost h-9 w-9 p-0" title="Back 10s">
            <Rewind className="h-4 w-4" />
          </button>
          <button onClick={() => skip(10)} className="btn-ghost h-9 w-9 p-0" title="Forward 10s">
            <FastForward className="h-4 w-4" />
          </button>
          <button
            onClick={() => {
              const next = !muted
              setMuted(next)
              if (videoRef.current) videoRef.current.muted = next
            }}
            className="btn-ghost h-9 w-9 p-0"
            title={muted ? 'Unmute' : 'Mute'}
          >
            {muted ? <VolumeX className="h-4 w-4" /> : <Volume2 className="h-4 w-4" />}
          </button>

          <div className="text-xs font-mono tabular-nums text-ink-3 ml-1">
            {formatTime(currentTime)} <span className="opacity-50">/</span> {formatTime(duration)}
          </div>

          <button
            onClick={fullscreen}
            className="btn-ghost h-9 w-9 p-0 ml-auto"
            title="Fullscreen"
          >
            <Maximize className="h-4 w-4" />
          </button>
        </div>
      </div>
    </div>
  )
})

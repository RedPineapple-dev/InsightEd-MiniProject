import { useMemo } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Layers, ChevronLeft, ChevronRight } from 'lucide-react'

import { Badge } from '../ui/Badge'
import { formatTime } from '../../lib/utils'

/**
 * Slide viewer that stays in sync with the video timeline.
 *
 * Lookup strategy: pick the alignment record with the LARGEST `start` that is
 * still <= currentTime. This is monotonic — slides progress as time advances
 * and roll backward when the user scrubs. It handles non-contiguous alignment
 * ranges gracefully (no flicker back to slide 0 in gaps).
 */
export function SlideViewer({ slides = [], alignment = [], currentTime = 0, onJump }) {
  // Sort once, memoised. Cheap because alignment is small (< 100 entries).
  const sortedAlignment = useMemo(
    () => [...alignment].sort((a, b) => (a.start ?? 0) - (b.start ?? 0)),
    [alignment]
  )

  const currentSlide = useMemo(() => {
    if (!slides.length) return null
    if (!sortedAlignment.length) return slides[0]
    // Binary search for the rightmost alignment with start <= currentTime
    let lo = 0
    let hi = sortedAlignment.length - 1
    let pick = -1
    while (lo <= hi) {
      const mid = (lo + hi) >> 1
      const startAt = sortedAlignment[mid].start ?? 0
      if (startAt <= currentTime) {
        pick = mid
        lo = mid + 1
      } else {
        hi = mid - 1
      }
    }
    if (pick < 0) return slides[0]
    const match = sortedAlignment[pick]
    return slides.find((s) => s.id === match.slide_id) || slides[0]
  }, [slides, sortedAlignment, currentTime])

  const currentIndex = currentSlide
    ? slides.findIndex((s) => s.id === currentSlide.id)
    : 0

  // Locate the alignment record for the current slide so we can let users
  // jump backward / forward to its boundary.
  const adjacentJump = (direction) => {
    if (!onJump || !sortedAlignment.length) return
    const cur = sortedAlignment.findIndex(
      (a) => a.slide_id === currentSlide?.id
    )
    const next = cur + direction
    const target = sortedAlignment[next]
    if (target && target.start != null) onJump(target.start)
  }

  return (
    <div className="flex flex-col h-full overflow-hidden">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Layers className="h-4 w-4 text-brand-600" />
          <span className="font-display font-semibold">Slide</span>
          {currentSlide && (
            <Badge tone="brand">
              {(currentIndex + 1).toString().padStart(2, '0')} / {slides.length}
            </Badge>
          )}
        </div>
        <div className="flex items-center gap-2">
          <span className="text-xs font-mono text-ink-3">{formatTime(currentTime)}</span>
          {onJump && (
            <div className="flex">
              <button
                onClick={() => adjacentJump(-1)}
                className="btn-ghost h-7 w-7 p-0"
                aria-label="Previous slide"
                title="Previous slide"
              >
                <ChevronLeft className="h-3.5 w-3.5" />
              </button>
              <button
                onClick={() => adjacentJump(1)}
                className="btn-ghost h-7 w-7 p-0"
                aria-label="Next slide"
                title="Next slide"
              >
                <ChevronRight className="h-3.5 w-3.5" />
              </button>
            </div>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto rounded-xl bg-surface-2/50 border border-border p-5">
        <AnimatePresence mode="wait">
          <motion.div
            key={currentSlide?.id ?? 'empty'}
            initial={{ opacity: 0, x: 12 }}
            animate={{ opacity: 1, x: 0 }}
            exit={{ opacity: 0, x: -12 }}
            transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
            className="space-y-3"
          >
            {currentSlide?.title && (
              <h3 className="font-display text-2xl font-semibold leading-tight">
                {currentSlide.title}
              </h3>
            )}
            {currentSlide?.text && (
              <p className="text-sm text-ink-2 leading-relaxed whitespace-pre-line">
                {currentSlide.text}
              </p>
            )}
            {currentSlide && !currentSlide.text && !currentSlide.title && (
              <div className="text-sm text-ink-3">Empty slide.</div>
            )}
            {!currentSlide && (
              <div className="text-sm text-ink-3 text-center py-12">
                No slides loaded yet.
              </div>
            )}
          </motion.div>
        </AnimatePresence>
      </div>

      {/* Slide thumbnails strip */}
      {slides.length > 1 && (
        <div className="mt-3 flex gap-1.5 overflow-x-auto pb-1">
          {slides.map((s, i) => {
            const active = currentSlide?.id === s.id
            const align = sortedAlignment.find((a) => a.slide_id === s.id)
            return (
              <button
                key={s.id}
                onClick={() => align?.start != null && onJump?.(align.start)}
                disabled={!align}
                title={s.title || `Slide ${i + 1}`}
                className={`shrink-0 w-12 h-8 rounded-md border text-[0.65rem] font-mono tabular-nums flex items-center justify-center transition ${
                  active
                    ? 'border-brand-500 bg-brand-500/15 text-brand-700 dark:text-brand-300'
                    : 'border-border bg-surface-1 text-ink-3 hover:border-border-strong hover:text-ink-1'
                } ${!align ? 'opacity-40 cursor-not-allowed' : 'cursor-pointer'}`}
              >
                {i + 1}
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}

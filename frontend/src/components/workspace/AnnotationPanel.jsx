import { useMemo, useState } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Search, Sparkles, Hash } from 'lucide-react'

import { Input } from '../ui/Input'
import { Badge } from '../ui/Badge'
import { cn, formatTime, importanceTone } from '../../lib/utils'

export function AnnotationPanel({ annotations = [], currentTime = 0, onJump, frequentTerms = [] }) {
  const [query, setQuery] = useState('')

  const filtered = useMemo(() => {
    if (!query.trim()) return annotations
    const q = query.toLowerCase()
    return annotations.filter((a) =>
      [a.timestamp, formatTime(a.start), ...((a.concepts || []).map((c) => `${c.concept} ${c.explanation}`))]
        .join(' ')
        .toLowerCase()
        .includes(q)
    )
  }, [annotations, query])

  const activeStart = annotations.find((a) => currentTime >= a.start && currentTime < a.end)?.start

  return (
    <div className="card flex flex-col min-h-0 h-full">
      <div className="px-5 pt-4 pb-3 border-b border-border space-y-3">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Sparkles className="h-4 w-4 text-brand-600" />
            <span className="font-display font-semibold text-ink-1">Annotations</span>
            <Badge tone="brand">{annotations.length}</Badge>
          </div>
        </div>
        <Input
          placeholder="Search concepts…"
          leftIcon={<Search />}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        {frequentTerms.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {frequentTerms.slice(0, 8).map((t) => (
              <button
                key={t.term}
                onClick={() => setQuery(t.term)}
                className="tag hover:border-brand-500/40 hover:text-brand-700 dark:hover:text-brand-300"
              >
                <Hash className="h-3 w-3" />
                {t.term}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="flex-1 overflow-y-auto px-2 py-2 space-y-1.5 min-h-0">
        <AnimatePresence initial={false}>
          {filtered.map((ann, i) => {
            const isActive = ann.start === activeStart
            return (
              <motion.button
                key={`${ann.start}-${i}`}
                onClick={() => onJump?.(ann.start)}
                initial={{ opacity: 0, y: 6 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.18 }}
                className={cn(
                  'w-full text-left rounded-xl px-3 py-2.5 transition-colors',
                  isActive ? 'bg-brand-500/10 border border-brand-500/30' : 'hover:bg-surface-2 border border-transparent'
                )}
              >
                <div className="flex items-center justify-between gap-2 mb-1">
                  <span className="font-mono tabular-nums text-xs text-brand-700 dark:text-brand-300">
                    {ann.timestamp || formatTime(ann.start)}
                  </span>
                  {isActive && <Badge tone="brand">now</Badge>}
                </div>
                <div className="space-y-1.5">
                  {(ann.concepts || []).map((c, j) => (
                    <div key={j}>
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <span className="font-semibold text-sm text-ink-1">{c.concept}</span>
                        <span className={importanceTone(c.importance)}>{c.importance}</span>
                      </div>
                      <p className="text-xs text-ink-3 line-clamp-2">{c.explanation}</p>
                    </div>
                  ))}
                </div>
              </motion.button>
            )
          })}
        </AnimatePresence>
        {filtered.length === 0 && (
          <div className="text-center text-sm text-ink-3 py-8">
            {query ? 'No matching annotations.' : 'Annotations will appear here once processing finishes.'}
          </div>
        )}
      </div>
    </div>
  )
}

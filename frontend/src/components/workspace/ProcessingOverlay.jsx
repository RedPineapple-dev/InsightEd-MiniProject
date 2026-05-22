import { motion } from 'framer-motion'
import { Loader2, CheckCircle2, AlertTriangle, Zap } from 'lucide-react'

import { cn } from '../../lib/utils'

const STEPS = [
  { key: 'transcript', label: 'Transcribing video', range: [0, 35] },
  { key: 'document', label: 'Parsing slides', range: [35, 55] },
  { key: 'embeddings', label: 'Computing embeddings', range: [55, 72] },
  { key: 'annotations', label: 'Generating annotations', range: [72, 82] },
  { key: 'alignment', label: 'Linking slides to timestamps', range: [82, 92] },
  { key: 'analytics', label: 'Building learning analytics', range: [92, 100] },
]

export function ProcessingOverlay({ status, progress, error, llm }) {
  const isError = status === 'error'
  const isDone = status === 'done'
  const llmDegraded = llm && llm.available === false && status !== 'idle'
  return (
    <div className="card p-6">
      {llmDegraded && (
        <div className="mb-4 rounded-xl border border-accent-500/30 bg-accent-500/10 px-4 py-3 flex items-start gap-2.5">
          <Zap className="h-4 w-4 text-accent-600 mt-0.5 shrink-0" />
          <div className="text-sm">
            <div className="font-semibold text-ink-1">AI quota reached</div>
            <div className="text-ink-2 mt-0.5">
              We're using cached + fallback annotations for this run. Re-running later will
              pick up the live model again.
            </div>
          </div>
        </div>
      )}
      <div className="flex items-center gap-3 mb-5">
        {isError ? (
          <AlertTriangle className="h-5 w-5 text-red-500" />
        ) : isDone ? (
          <CheckCircle2 className="h-5 w-5 text-brand-600" />
        ) : (
          <Loader2 className="h-5 w-5 text-brand-600 animate-spin" />
        )}
        <div className="flex-1">
          <div className="font-display font-semibold">
            {isError ? 'Processing failed' : isDone ? 'Ready to learn' : 'AI pipeline running'}
          </div>
          <div className="text-sm text-ink-3">
            {isError ? error : isDone ? 'All systems go.' : 'This usually takes 1–3 minutes.'}
          </div>
        </div>
        <div className="font-display text-2xl font-bold tabular-nums">{progress}%</div>
      </div>

      <div className="h-2 rounded-full bg-surface-2 overflow-hidden">
        <motion.div
          className="h-full bg-gradient-to-r from-brand-500 to-accent-500"
          initial={{ width: 0 }}
          animate={{ width: `${progress}%` }}
          transition={{ duration: 0.5, ease: 'easeOut' }}
        />
      </div>

      <ul className="mt-5 space-y-2">
        {STEPS.map((step) => {
          const [from, to] = step.range
          const state =
            isError && progress >= from && progress < to
              ? 'failed'
              : progress >= to
              ? 'done'
              : progress >= from
              ? 'active'
              : 'pending'
          return (
            <li
              key={step.key}
              className={cn(
                'flex items-center gap-3 text-sm transition-colors',
                state === 'pending' && 'text-ink-3',
                state === 'active' && 'text-ink-1',
                state === 'done' && 'text-brand-600 dark:text-brand-300',
                state === 'failed' && 'text-red-500'
              )}
            >
              <span
                className={cn(
                  'h-1.5 w-1.5 rounded-full',
                  state === 'pending' && 'bg-ink-3/40',
                  state === 'active' && 'bg-brand-500 animate-pulse-soft',
                  state === 'done' && 'bg-brand-500',
                  state === 'failed' && 'bg-red-500'
                )}
              />
              {step.label}
            </li>
          )
        })}
      </ul>
    </div>
  )
}

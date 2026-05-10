import { useMemo, useState } from 'react'
import { motion } from 'framer-motion'
import { ExternalLink, Youtube, BookOpen, FileText } from 'lucide-react'

import { cn } from '../../lib/utils'
import { Badge } from '../ui/Badge'

const CATEGORIES = [
  { key: 'all', label: 'All', icon: null },
  { key: 'research_paper', label: 'Papers', icon: FileText },
  { key: 'youtube', label: 'Videos', icon: Youtube },
  { key: 'documentation', label: 'Docs', icon: BookOpen },
]

const META = {
  research_paper: { icon: FileText, label: 'Paper', tone: 'accent', surface: 'bg-accent-500/10 text-accent-700 dark:text-accent-300' },
  youtube: { icon: Youtube, label: 'Video', tone: 'danger', surface: 'bg-red-500/10 text-red-500' },
  documentation: { icon: BookOpen, label: 'Docs', tone: 'brand', surface: 'bg-brand-500/10 text-brand-600 dark:text-brand-300' },
}

function ResourceCard({ res, index }) {
  const meta = META[res.category] || META.documentation
  const Icon = meta.icon
  const score = Math.round((res.relevance_score || 0) * 100)
  return (
    <motion.a
      href={res.url}
      target="_blank"
      rel="noreferrer"
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ delay: index * 0.04 }}
      className="card-interactive p-4 flex flex-col gap-2 group"
    >
      <div className="flex items-start gap-3">
        <div className={cn('h-10 w-10 rounded-lg flex items-center justify-center shrink-0 overflow-hidden', meta.surface)}>
          {res.thumbnail_url ? (
            <img src={res.thumbnail_url} alt="" className="h-full w-full object-cover" />
          ) : (
            <Icon className="h-5 w-5" />
          )}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <Badge tone={meta.tone}>{meta.label}</Badge>
            {res.source && <span className="text-[0.7rem] text-ink-3">{res.source}</span>}
          </div>
          <h4 className="mt-1 font-semibold text-sm text-ink-1 line-clamp-2 group-hover:text-brand-700 dark:group-hover:text-brand-300">
            {res.title}
          </h4>
        </div>
        <ExternalLink className="h-4 w-4 text-ink-3 shrink-0 opacity-0 group-hover:opacity-100 transition" />
      </div>
      {res.description && (
        <p className="text-xs text-ink-3 line-clamp-2">{res.description}</p>
      )}
      <div className="flex items-center gap-2 mt-1 flex-wrap">
        {(res.tags || []).slice(0, 3).map((t) => (
          <span key={t} className="tag">
            {t}
          </span>
        ))}
        <span className="ml-auto text-[0.7rem] font-medium text-ink-3">{score}% relevant</span>
      </div>
    </motion.a>
  )
}

export function Recommendations({
  resources = [],
  emptyHint = 'Recommendations will appear here.',
}) {
  const [tab, setTab] = useState('all')

  const counts = useMemo(() => {
    const c = { all: resources.length }
    for (const r of resources) {
      const k = r.category || 'documentation'
      c[k] = (c[k] || 0) + 1
    }
    return c
  }, [resources])

  const filtered = useMemo(
    () => (tab === 'all' ? resources : resources.filter((r) => r.category === tab)),
    [resources, tab]
  )

  if (resources.length === 0) {
    return <div className="text-center text-sm text-ink-3 py-8">{emptyHint}</div>
  }

  return (
    <div className="space-y-3">
      <div className="inline-flex rounded-xl border border-border p-0.5 bg-surface-2 flex-wrap">
        {CATEGORIES.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            onClick={() => setTab(key)}
            className={cn(
              'text-xs font-medium px-3 py-1.5 rounded-lg flex items-center gap-1.5 transition',
              tab === key
                ? 'bg-surface-1 text-ink-1 shadow-soft'
                : 'text-ink-3 hover:text-ink-1'
            )}
          >
            {Icon && <Icon className="h-3.5 w-3.5" />}
            {label}
            {counts[key] > 0 && (
              <span className="text-[0.65rem] font-mono opacity-60">{counts[key]}</span>
            )}
          </button>
        ))}
      </div>

      {filtered.length === 0 ? (
        <div className="text-center text-sm text-ink-3 py-6">
          Nothing in this category yet.
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {filtered.map((res, i) => (
            <ResourceCard key={res.url} res={res} index={i} />
          ))}
        </div>
      )}
    </div>
  )
}

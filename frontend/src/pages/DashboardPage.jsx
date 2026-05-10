import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  Sparkles,
  ArrowRight,
  Clock,
  PlayCircle,
  Layers,
  BarChart3,
  TrendingUp,
} from 'lucide-react'

import { AppShell } from '../components/layout/AppShell'
import { Card, CardBody, CardHeader, CardTitle, CardDescription } from '../components/ui/Card'
import Button from '../components/ui/Button'
import { Skeleton } from '../components/ui/Skeleton'
import { Badge } from '../components/ui/Badge'
import { useAuth } from '../lib/auth'
import { playbackApi, pipelineApi } from '../lib/api'
import { formatRelative, formatTime } from '../lib/utils'

const STATS = [
  { key: 'transcript_segments', label: 'Transcript segments', icon: PlayCircle },
  { key: 'slides_count', label: 'Slides parsed', icon: Layers },
  { key: 'annotations_count', label: 'AI annotations', icon: Sparkles },
]

export default function DashboardPage() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const [status, setStatus] = useState(null)
  const [recent, setRecent] = useState([])
  const [recentLoading, setRecentLoading] = useState(true)

  useEffect(() => {
    pipelineApi.getStatus().then(setStatus).catch(() => setStatus(null))
    playbackApi
      .list()
      .then((data) => setRecent(data?.items || []))
      .catch(() => setRecent([]))
      .finally(() => setRecentLoading(false))
  }, [])

  const greeting = (() => {
    const h = new Date().getHours()
    if (h < 5) return 'Up late'
    if (h < 12) return 'Good morning'
    if (h < 18) return 'Good afternoon'
    return 'Good evening'
  })()

  return (
    <AppShell title="Dashboard" subtitle="Your learning at a glance">
      <div className="space-y-8">
        {/* Hero */}
        <motion.section
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          className="relative overflow-hidden rounded-3xl border border-border bg-surface-1 p-8 lg:p-10 mesh-bg"
        >
          <div className="relative z-10 max-w-2xl">
            <Badge tone="brand" className="mb-3">
              <Sparkles className="h-3 w-3" /> AI-powered learning
            </Badge>
            <h1 className="font-display text-3xl lg:text-4xl font-bold leading-tight">
              {greeting}, {user?.name?.split(' ')[0] || 'there'}.{' '}
              <span className="text-gradient">Let's learn something new.</span>
            </h1>
            <p className="text-ink-2 mt-3 max-w-xl">
              Upload a lecture or pick up where you left off. InsightEd will transcribe, link slides,
              and surface concepts as you watch.
            </p>
            <div className="mt-6 flex flex-wrap gap-2">
              <Button onClick={() => navigate('/workspace?new=1')} rightIcon={<ArrowRight />} size="lg">
                Upload new video
              </Button>
              <Button variant="secondary" onClick={() => navigate('/workspace')} size="lg">
                Continue learning
              </Button>
              <Button variant="ghost" onClick={() => navigate('/analytics')} size="lg">
                Analytics
              </Button>
            </div>
          </div>
        </motion.section>

        {/* Stats */}
        <section className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {STATS.map(({ key, label, icon: Icon }) => (
            <Card key={key} className="p-5">
              <div className="flex items-start justify-between">
                <div>
                  <div className="text-sm text-ink-3">{label}</div>
                  <div className="font-display text-3xl font-bold mt-1 tabular-nums">
                    {status?.[key] ?? 0}
                  </div>
                </div>
                <div className="h-10 w-10 rounded-xl bg-brand-500/10 text-brand-600 dark:text-brand-300 flex items-center justify-center">
                  <Icon className="h-5 w-5" />
                </div>
              </div>
            </Card>
          ))}
        </section>

        {/* Continue Watching */}
        <section>
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <Clock className="h-4 w-4 text-ink-2" />
              <h2 className="font-display text-lg font-semibold">Continue watching</h2>
            </div>
            <button
              onClick={() => navigate('/workspace')}
              className="text-sm text-brand-600 dark:text-brand-300 hover:underline"
            >
              All videos
            </button>
          </div>

          {recentLoading ? (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {Array.from({ length: 3 }).map((_, i) => (
                <Skeleton key={i} className="h-28" />
              ))}
            </div>
          ) : recent.length === 0 ? (
            <Card>
              <CardHeader>
                <CardTitle>No videos yet</CardTitle>
                <CardDescription>
                  Upload your first lecture in the workspace to start your learning history.
                </CardDescription>
              </CardHeader>
              <CardBody>
                <Button onClick={() => navigate('/workspace')} rightIcon={<ArrowRight />}>
                  Upload a video
                </Button>
              </CardBody>
            </Card>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
              {recent.map((it) => {
                const pct =
                  it.duration_seconds && it.last_position_seconds
                    ? Math.min(100, (it.last_position_seconds / it.duration_seconds) * 100)
                    : 0
                return (
                  <button
                    key={it._id || it.fingerprint}
                    onClick={() => navigate(`/workspace?fp=${it.fingerprint}`)}
                    className="card-interactive text-left p-4"
                  >
                    <div className="flex items-center gap-3">
                      <div className="h-12 w-12 rounded-xl bg-gradient-to-br from-brand-500 to-accent-500 flex items-center justify-center text-white">
                        <PlayCircle className="h-5 w-5" />
                      </div>
                      <div className="min-w-0">
                        <div className="font-semibold truncate">{it.filename || 'Untitled'}</div>
                        <div className="text-xs text-ink-3">
                          {formatTime(it.last_position_seconds)} · {formatRelative(it.updated_at)}
                        </div>
                      </div>
                    </div>
                    <div className="mt-3 h-1.5 bg-surface-3 rounded-full overflow-hidden">
                      <div
                        className="h-full bg-gradient-to-r from-brand-500 to-accent-500"
                        style={{ width: `${pct}%` }}
                      />
                    </div>
                  </button>
                )
              })}
            </div>
          )}
        </section>

        {/* Quick links */}
        <section className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Card interactive className="p-6 cursor-pointer" onClick={() => navigate('/analytics')}>
            <div className="flex items-start gap-4">
              <div className="h-11 w-11 rounded-xl bg-accent-500/10 text-accent-600 flex items-center justify-center">
                <BarChart3 className="h-5 w-5" />
              </div>
              <div>
                <h3 className="font-display font-semibold">Interaction analytics</h3>
                <p className="text-sm text-ink-3 mt-1">
                  See which segments confuse learners — replays, pauses, and per-student difficulty.
                </p>
              </div>
            </div>
          </Card>
          <Card interactive className="p-6 cursor-pointer" onClick={() => navigate('/workspace')}>
            <div className="flex items-start gap-4">
              <div className="h-11 w-11 rounded-xl bg-brand-500/10 text-brand-600 dark:text-brand-300 flex items-center justify-center">
                <TrendingUp className="h-5 w-5" />
              </div>
              <div>
                <h3 className="font-display font-semibold">Improve a lecture</h3>
                <p className="text-sm text-ink-3 mt-1">
                  Generate slides automatically from a video, fix slide alignment, or refresh annotations.
                </p>
              </div>
            </div>
          </Card>
        </section>
      </div>
    </AppShell>
  )
}

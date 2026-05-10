import { useEffect, useMemo, useState } from 'react'
import { motion } from 'framer-motion'
import {
  BarChart3,
  Users,
  Repeat,
  Pause as PauseIcon,
  AlertTriangle,
  Search,
  Sparkles,
  Film,
  RefreshCw,
} from 'lucide-react'
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip as ChartTooltip,
  CartesianGrid,
} from 'recharts'

import { AppShell } from '../components/layout/AppShell'
import { Card, CardBody, CardHeader, CardTitle, CardDescription } from '../components/ui/Card'
import Button from '../components/ui/Button'
import { Badge } from '../components/ui/Badge'
import { Skeleton } from '../components/ui/Skeleton'
import { Input } from '../components/ui/Input'
import { analyticsApi, pipelineApi } from '../lib/api'
import { useAnalyticsStore, useSessionStore } from '../lib/sessionStore'
import { useAuth } from '../lib/auth'
import { formatTime } from '../lib/utils'

const POLL_MS = 4000

export default function AnalyticsPage() {
  const { user } = useAuth()

  // Workspace posts events with video_id = fingerprint, falling back to the
  // literal "session" when no video is loaded. Mirror that here so the page
  // shows events for the active video without the user having to type its id.
  const sessionFingerprint = useSessionStore((s) => s.fingerprint)
  const videoFilename = useSessionStore((s) => s.videoFilename)
  const storedVideoId = useAnalyticsStore((s) => s.videoId)
  const events = useAnalyticsStore((s) => s.events)
  const setVideoId = useAnalyticsStore((s) => s.setVideoId)

  const desiredVideoId = sessionFingerprint || 'session'
  const hasActiveVideo = !!sessionFingerprint

  // Keep the analytics buffer aligned with the active learning session.
  // setVideoId clears events + lastSinceMs so we never blend two videos'
  // engagement data.
  useEffect(() => {
    if (storedVideoId !== desiredVideoId) setVideoId(desiredVideoId)
  }, [desiredVideoId, storedVideoId, setVideoId])

  const videoId = storedVideoId || desiredVideoId
  const [loading, setLoading] = useState(true)
  const [pipelineStatus, setPipelineStatus] = useState(null)

  // Reset loading whenever the videoId or current user changes — a re-login
  // or a switch to a different active video should re-show the spinner
  // until the next poll completes.
  useEffect(() => {
    setLoading(true)
  }, [videoId, user?.id])

  // Sync events from backend (the "shared storage" replacement).
  // The buffer lives in the global analytics store so leaving and returning
  // to this page doesn't drop already-seen events.
  useEffect(() => {
    let alive = true
    let timer

    const tick = async () => {
      try {
        const since = useAnalyticsStore.getState().lastSinceMs
        const data = await analyticsApi.fetchEvents(videoId, since)
        if (!alive) return
        useAnalyticsStore
          .getState()
          .mergeEvents(data?.events || [], data?.fetched_at_ms)
      } catch {
        // silently degrade — auth or DB may be off
      } finally {
        if (alive) timer = setTimeout(tick, POLL_MS)
        if (alive) setLoading(false)
      }
    }

    tick()
    return () => {
      alive = false
      clearTimeout(timer)
    }
  }, [videoId, user?.id])

  useEffect(() => {
    pipelineApi.getStatus().then(setPipelineStatus).catch(() => setPipelineStatus(null))
  }, [user?.id])

  // Bucket events into 10s segments
  const buckets = useMemo(() => {
    const map = new Map()
    for (const e of events) {
      const bucket = Math.floor((e.video_ts || 0) / 10) * 10
      const cur = map.get(bucket) || {
        bucket,
        replay: 0,
        pause: 0,
        students: new Set(),
        rows: [],
      }
      if (e.event_type === 'replay') cur.replay += 1
      if (e.event_type === 'pause') cur.pause += 1
      cur.students.add(e.student_name)
      cur.rows.push(e)
      map.set(bucket, cur)
    }
    return [...map.values()]
      .sort((a, b) => a.bucket - b.bucket)
      .map((b) => ({
        ...b,
        students: [...b.students],
        unique_students: b.students.size,
        total: b.replay + b.pause,
      }))
  }, [events])

  const topReplayed = useMemo(() => {
    return [...buckets].sort((a, b) => b.replay - a.replay || b.total - a.total).slice(0, 5)
  }, [buckets])

  const difficult = useMemo(() => {
    return buckets
      .filter((b) => b.unique_students >= 2)
      .sort((a, b) => b.total - a.total)
  }, [buckets])

  const maxTotal = Math.max(1, ...buckets.map((b) => b.total))

  const refresh = async () => {
    setLoading(true)
    try {
      const data = await analyticsApi.fetchEvents(videoId, 0)
      // Reset and rewrite the buffer.
      useAnalyticsStore.setState({ events: [], lastSinceMs: 0 })
      useAnalyticsStore.getState().mergeEvents(data?.events || [], data?.fetched_at_ms)
    } catch {}
    setLoading(false)
  }

  return (
    <AppShell title="Analytics" subtitle="How you engage with your videos">
      <div className="space-y-6">
        {/* Active-video banner */}
        <Card className="p-4 flex items-center justify-between gap-4">
          <div className="flex items-center gap-3 min-w-0">
            <div className="h-10 w-10 rounded-xl bg-brand-500/10 text-brand-600 dark:text-brand-300 flex items-center justify-center shrink-0">
              <Film className="h-5 w-5" />
            </div>
            <div className="min-w-0">
              <div className="text-xs uppercase tracking-wide text-ink-3">Active video</div>
              <div className="font-medium truncate">
                {hasActiveVideo
                  ? videoFilename || 'Untitled video'
                  : 'No video loaded — upload one in Workspace to start tracking engagement.'}
              </div>
            </div>
          </div>
          <Button size="sm" variant="secondary" leftIcon={<RefreshCw />} onClick={refresh}>
            Refresh
          </Button>
        </Card>

        <Card>
          <CardHeader
            action={
              <Input
                value={videoId}
                onChange={(e) => setVideoId(e.target.value)}
                leftIcon={<Search />}
                placeholder="video id"
                className="w-44"
              />
            }
          >
            <CardTitle>Interaction timeline</CardTitle>
            <CardDescription>
              10-second buckets · blue = replays, orange = pauses · darker means more interaction
            </CardDescription>
          </CardHeader>
          <CardBody>
            {loading && events.length === 0 ? (
              <Skeleton className="h-32" />
            ) : buckets.length === 0 ? (
              <EmptyState
                hasActiveVideo={hasActiveVideo}
                pipelineStatus={pipelineStatus}
              />
            ) : (
              <div className="space-y-4">
                <div className="flex flex-wrap gap-1.5">
                  {buckets.map((b) => {
                    const intensity = b.total / maxTotal
                    const both = b.replay > 0 && b.pause > 0
                    const bg = both
                      ? `rgba(239,68,68,${0.25 + intensity * 0.55})`
                      : b.replay > b.pause
                      ? `rgba(14,165,233,${0.2 + intensity * 0.6})`
                      : `rgba(245,158,11,${0.2 + intensity * 0.6})`
                    return (
                      <div
                        key={b.bucket}
                        title={`${formatTime(b.bucket)} — ${b.replay} replay · ${b.pause} pause · ${b.unique_students} students`}
                        className="h-9 w-9 rounded-md border border-border flex items-center justify-center text-[10px] font-mono"
                        style={{ background: bg }}
                      >
                        {b.total}
                      </div>
                    )
                  })}
                </div>
                <div className="flex items-center gap-4 text-xs text-ink-3">
                  <span className="flex items-center gap-1.5">
                    <span className="h-2.5 w-2.5 rounded-sm bg-sky-500" /> Replay
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="h-2.5 w-2.5 rounded-sm bg-accent-500" /> Pause
                  </span>
                  <span className="flex items-center gap-1.5">
                    <span className="h-2.5 w-2.5 rounded-sm bg-red-500" /> Both
                  </span>
                </div>
              </div>
            )}
          </CardBody>
        </Card>

        <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
          <Card className="xl:col-span-2">
            <CardHeader>
              <CardTitle>Most replayed segments</CardTitle>
              <CardDescription>Top 5 ranked by replay count, then total interaction.</CardDescription>
            </CardHeader>
            <CardBody>
              {topReplayed.length === 0 ? (
                <div className="text-sm text-ink-3 py-12 text-center">No replays yet.</div>
              ) : (
                <div className="h-72">
                  <ResponsiveContainer>
                    <BarChart data={topReplayed} margin={{ top: 4, right: 8, left: -16, bottom: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="rgb(var(--border))" />
                      <XAxis
                        dataKey="bucket"
                        tickFormatter={(v) => formatTime(v)}
                        stroke="rgb(var(--ink-3))"
                        tick={{ fontSize: 11 }}
                      />
                      <YAxis stroke="rgb(var(--ink-3))" tick={{ fontSize: 11 }} />
                      <ChartTooltip
                        cursor={{ fill: 'rgb(var(--surface-2))' }}
                        contentStyle={{
                          background: 'rgb(var(--surface-1))',
                          border: '1px solid rgb(var(--border))',
                          borderRadius: 12,
                        }}
                        labelFormatter={(v) => `Segment @ ${formatTime(v)}`}
                      />
                      <Bar dataKey="replay" fill="#0ea5e9" radius={[4, 4, 0, 0]} stackId="a" />
                      <Bar dataKey="pause" fill="#f59e0b" radius={[4, 4, 0, 0]} stackId="a" />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Engagement summary</CardTitle>
              <CardDescription>Across all observed events.</CardDescription>
            </CardHeader>
            <CardBody>
              <div className="space-y-3">
                <SummaryRow icon={Repeat} tone="info" label="Replays" value={events.filter((e) => e.event_type === 'replay').length} />
                <SummaryRow icon={PauseIcon} tone="accent" label="Pauses" value={events.filter((e) => e.event_type === 'pause').length} />
                <SummaryRow icon={Users} tone="brand" label="Unique learners" value={new Set(events.map((e) => e.student_name)).size} />
                <SummaryRow icon={BarChart3} tone="default" label="Active buckets" value={buckets.length} />
              </div>
            </CardBody>
          </Card>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Difficult segments</CardTitle>
            <CardDescription>
              Buckets where 2+ unique learners interacted — likely confusion points.
            </CardDescription>
          </CardHeader>
          <CardBody>
            {difficult.length === 0 ? (
              <div className="text-sm text-ink-3 py-8 text-center">
                Nothing flagged yet. Difficult segments need at least 2 distinct learners.
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-ink-3 text-xs uppercase tracking-wide">
                      <th className="text-left py-2 px-2 font-medium">Segment</th>
                      <th className="text-left py-2 px-2 font-medium">Replays</th>
                      <th className="text-left py-2 px-2 font-medium">Pauses</th>
                      <th className="text-left py-2 px-2 font-medium">Learners</th>
                      <th className="text-left py-2 px-2 font-medium">Severity</th>
                    </tr>
                  </thead>
                  <tbody>
                    {difficult.map((b) => {
                      const severe = b.total >= 6
                      return (
                        <motion.tr
                          key={b.bucket}
                          initial={{ opacity: 0 }}
                          animate={{ opacity: 1 }}
                          className="border-t border-border"
                        >
                          <td className="py-2.5 px-2 font-mono">{formatTime(b.bucket)} – {formatTime(b.bucket + 10)}</td>
                          <td className="py-2.5 px-2">{b.replay}</td>
                          <td className="py-2.5 px-2">{b.pause}</td>
                          <td className="py-2.5 px-2">
                            <div className="flex flex-wrap gap-1">
                              {b.students.slice(0, 4).map((s) => (
                                <span key={s} className="tag">{s}</span>
                              ))}
                              {b.students.length > 4 && <span className="tag">+{b.students.length - 4}</span>}
                            </div>
                          </td>
                          <td className="py-2.5 px-2">
                            {severe ? (
                              <Badge tone="danger"><AlertTriangle className="h-3 w-3" /> High difficulty</Badge>
                            ) : (
                              <Badge tone="warning">Moderate</Badge>
                            )}
                          </td>
                        </motion.tr>
                      )
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </CardBody>
        </Card>
      </div>
    </AppShell>
  )
}

function EmptyState({ hasActiveVideo, pipelineStatus }) {
  if (!hasActiveVideo) {
    return (
      <div className="text-sm text-ink-3 py-12 text-center space-y-1">
        <Sparkles className="h-5 w-5 mx-auto text-brand-600 mb-2" />
        <div className="font-medium text-ink-2">No active video</div>
        <div>Upload a lecture in Workspace, watch it, and your replays/pauses will land here.</div>
      </div>
    )
  }
  if (pipelineStatus?.status === 'processing' || pipelineStatus?.status === 'queued') {
    return (
      <div className="text-sm text-ink-3 py-12 text-center">
        Your video is still processing. Engagement will populate once playback begins.
      </div>
    )
  }
  return (
    <div className="text-sm text-ink-3 py-12 text-center">
      No interactions recorded yet. Pause or scrub on the workspace player to populate this.
    </div>
  )
}

function SummaryRow({ icon: Icon, label, value, tone }) {
  return (
    <div className="flex items-center justify-between p-3 rounded-xl bg-surface-2">
      <div className="flex items-center gap-2.5">
        <div className="h-8 w-8 rounded-lg bg-surface-1 flex items-center justify-center text-ink-2">
          <Icon className="h-4 w-4" />
        </div>
        <span className="text-sm font-medium">{label}</span>
      </div>
      <Badge tone={tone}>{value}</Badge>
    </div>
  )
}

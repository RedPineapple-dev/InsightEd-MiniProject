import { motion } from 'framer-motion'
import { Sparkles, ShieldCheck, Zap, Layers } from 'lucide-react'

const FEATURES = [
  { icon: Zap, title: 'Real-time AI annotations', desc: 'Concepts surfaced as you watch — never miss a key idea.' },
  { icon: Layers, title: 'Slides linked to playback', desc: 'PDFs and decks auto-sync to the right moment.' },
  { icon: ShieldCheck, title: 'Continue where you left off', desc: 'Re-upload the same video and resume instantly.' },
]

export function AuthLayout({ children, title, subtitle }) {
  return (
    <div className="min-h-screen grid lg:grid-cols-2">
      <div className="hidden lg:flex relative overflow-hidden mesh-bg p-12 flex-col justify-between">
        <div className="flex items-center gap-2.5">
          <div className="h-10 w-10 rounded-xl bg-gradient-to-br from-brand-500 to-accent-500 flex items-center justify-center shadow-glow">
            <Sparkles className="h-5 w-5 text-white" />
          </div>
          <div>
            <div className="font-display text-lg font-bold tracking-tight">InsightEd</div>
            <div className="text-[0.65rem] uppercase tracking-wider text-ink-3">AI Learning Platform</div>
          </div>
        </div>

        <motion.div
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
          className="space-y-8 max-w-md"
        >
          <div>
            <h2 className="font-display text-3xl font-bold leading-tight">
              Turn lectures into <span className="text-gradient">guided experiences</span>.
            </h2>
            <p className="mt-3 text-ink-2">
              Upload a video, link slides automatically, and unlock annotations, recommendations,
              and analytics that show how learners actually engage.
            </p>
          </div>

          <div className="space-y-4">
            {FEATURES.map(({ icon: Icon, title, desc }, i) => (
              <motion.div
                key={title}
                initial={{ opacity: 0, x: -8 }}
                animate={{ opacity: 1, x: 0 }}
                transition={{ delay: 0.1 + i * 0.08, duration: 0.4 }}
                className="flex items-start gap-3"
              >
                <div className="h-9 w-9 rounded-xl bg-surface-1 border border-border flex items-center justify-center shrink-0">
                  <Icon className="h-4 w-4 text-brand-600" />
                </div>
                <div>
                  <div className="font-semibold text-ink-1">{title}</div>
                  <div className="text-sm text-ink-3">{desc}</div>
                </div>
              </motion.div>
            ))}
          </div>
        </motion.div>

        <p className="text-xs text-ink-3">© {new Date().getFullYear()} InsightEd · Built for learners</p>
      </div>

      <div className="flex flex-col items-center justify-center px-6 py-10 lg:py-16">
        <motion.div
          initial={{ opacity: 0, y: 12 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.4 }}
          className="w-full max-w-sm"
        >
          <div className="lg:hidden flex items-center gap-2.5 mb-8">
            <div className="h-9 w-9 rounded-xl bg-gradient-to-br from-brand-500 to-accent-500 flex items-center justify-center shadow-glow">
              <Sparkles className="h-5 w-5 text-white" />
            </div>
            <div className="font-display text-lg font-bold">InsightEd</div>
          </div>

          <h1 className="font-display text-2xl font-bold">{title}</h1>
          {subtitle && <p className="text-ink-3 mt-1">{subtitle}</p>}

          <div className="mt-8">{children}</div>
        </motion.div>
      </div>
    </div>
  )
}

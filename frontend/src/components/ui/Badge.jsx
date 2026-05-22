import { cn } from '../../lib/utils'

const TONES = {
  default: 'bg-surface-2 text-ink-2 border-border',
  brand: 'bg-brand-500/10 text-brand-700 dark:text-brand-300 border-brand-500/30',
  accent: 'bg-accent-500/10 text-accent-700 dark:text-accent-300 border-accent-500/30',
  success: 'bg-green-500/10 text-green-700 dark:text-green-300 border-green-500/30',
  warning: 'bg-orange-500/10 text-orange-700 dark:text-orange-300 border-orange-500/30',
  danger: 'bg-red-500/10 text-red-700 dark:text-red-300 border-red-500/30',
  info: 'bg-sky-500/10 text-sky-700 dark:text-sky-300 border-sky-500/30',
}

export function Badge({ tone = 'default', className, children, ...rest }) {
  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-[0.7rem] font-medium',
        TONES[tone] || TONES.default,
        className
      )}
      {...rest}
    >
      {children}
    </span>
  )
}

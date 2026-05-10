import { cn } from '../../lib/utils'

export function Avatar({ name = '?', src, size = 36, className }) {
  const initials = (name || '?')
    .split(' ')
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0])
    .join('')
    .toUpperCase()
  return (
    <div
      className={cn(
        'inline-flex items-center justify-center rounded-full font-semibold bg-brand-500/15 text-brand-700 dark:text-brand-300 border border-brand-500/20',
        className
      )}
      style={{ width: size, height: size, fontSize: size * 0.42 }}
    >
      {src ? <img src={src} alt={name} className="h-full w-full rounded-full object-cover" /> : initials || '?'}
    </div>
  )
}

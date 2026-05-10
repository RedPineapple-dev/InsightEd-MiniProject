import { cn } from '../../lib/utils'

export function Card({ className, interactive, children, ...rest }) {
  return (
    <div className={cn(interactive ? 'card-interactive' : 'card', className)} {...rest}>
      {children}
    </div>
  )
}

export function CardHeader({ className, children, action }) {
  return (
    <div className={cn('flex items-start justify-between gap-4 px-6 pt-5 pb-3', className)}>
      <div className="space-y-0.5">{children}</div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  )
}

export function CardTitle({ className, children }) {
  return <h3 className={cn('font-display text-lg font-semibold text-ink-1', className)}>{children}</h3>
}

export function CardDescription({ className, children }) {
  return <p className={cn('text-sm text-ink-3', className)}>{children}</p>
}

export function CardBody({ className, children }) {
  return <div className={cn('px-6 pb-6', className)}>{children}</div>
}

export function CardDivider() {
  return <div className="border-t border-border" />
}

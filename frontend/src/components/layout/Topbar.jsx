import { Link } from 'react-router-dom'
import { Sparkles } from 'lucide-react'

import { useAuth } from '../../lib/auth'
import { Avatar } from '../ui/Avatar'
import { ThemeToggle } from './ThemeToggle'

export function Topbar({ title, subtitle, action }) {
  const { user } = useAuth()

  return (
    <header className="sticky top-0 z-30 h-16 border-b border-border bg-surface-1/80 backdrop-blur-xl">
      <div className="h-full px-4 lg:px-8 flex items-center justify-between gap-4">
        <div className="flex items-center gap-3 min-w-0">
          <Link to="/dashboard" className="lg:hidden flex items-center gap-2">
            <div className="h-8 w-8 rounded-lg bg-gradient-to-br from-brand-500 to-accent-500 flex items-center justify-center">
              <Sparkles className="h-4 w-4 text-white" />
            </div>
            <span className="font-display font-bold">InsightEd</span>
          </Link>
          <div className="hidden lg:block min-w-0">
            {title && <h1 className="font-display text-xl font-semibold truncate">{title}</h1>}
            {subtitle && <p className="text-sm text-ink-3 truncate">{subtitle}</p>}
          </div>
        </div>

        <div className="flex items-center gap-2">
          {action}
          <ThemeToggle />
          {user && (
            <Link to="/settings" className="ml-1">
              <Avatar name={user.name} src={user.avatar_url} size={36} />
            </Link>
          )}
        </div>
      </div>
    </header>
  )
}

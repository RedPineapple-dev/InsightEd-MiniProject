import { NavLink } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  LayoutDashboard,
  Sparkles,
  Video,
  BarChart3,
  Settings,
  LogOut,
} from 'lucide-react'

import { Avatar } from '../ui/Avatar'
import { useAuth } from '../../lib/auth'
import { cn } from '../../lib/utils'

const NAV_ITEMS = [
  { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/workspace', label: 'Workspace', icon: Video },
  { to: '/analytics', label: 'Analytics', icon: BarChart3 },
  { to: '/settings', label: 'Settings', icon: Settings },
]

export function Sidebar() {
  const { user, logout } = useAuth()

  return (
    <aside className="hidden lg:flex flex-col w-64 shrink-0 border-r border-border bg-surface-1">
      <div className="flex items-center gap-2.5 px-5 h-16 border-b border-border">
        <div className="h-9 w-9 rounded-xl bg-gradient-to-br from-brand-500 to-accent-500 flex items-center justify-center shadow-glow">
          <Sparkles className="h-5 w-5 text-white" />
        </div>
        <div className="leading-tight">
          <div className="font-display text-base font-bold tracking-tight">InsightEd</div>
          <div className="text-[0.65rem] font-medium uppercase tracking-wider text-ink-3">AI Learning</div>
        </div>
      </div>

      <nav className="flex-1 px-3 py-4 space-y-1">
        {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            className={({ isActive }) =>
              cn(
                'group relative flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-all',
                isActive
                  ? 'text-brand-700 dark:text-brand-200 bg-brand-500/10'
                  : 'text-ink-2 hover:text-ink-1 hover:bg-surface-2'
              )
            }
          >
            {({ isActive }) => (
              <>
                {isActive && (
                  <motion.span
                    layoutId="sidebar-active"
                    className="absolute left-0 top-1.5 bottom-1.5 w-1 rounded-full bg-brand-500"
                    transition={{ type: 'spring', stiffness: 400, damping: 30 }}
                  />
                )}
                <Icon className={cn('h-4 w-4', isActive && 'text-brand-600 dark:text-brand-300')} />
                <span>{label}</span>
              </>
            )}
          </NavLink>
        ))}
      </nav>

      {user && (
        <div className="px-3 py-3 border-t border-border">
          <div className="flex items-center gap-3 p-2 rounded-xl">
            <Avatar name={user.name} src={user.avatar_url} size={36} />
            <div className="flex-1 min-w-0 leading-tight">
              <div className="text-sm font-semibold truncate">{user.name}</div>
              <div className="text-xs text-ink-3 truncate">{user.email}</div>
            </div>
            <button
              onClick={logout}
              className="p-1.5 rounded-lg text-ink-3 hover:text-red-500 hover:bg-red-500/10 transition"
              aria-label="Sign out"
              title="Sign out"
            >
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        </div>
      )}
    </aside>
  )
}

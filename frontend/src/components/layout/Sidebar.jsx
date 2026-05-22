import { NavLink, useLocation, useNavigate } from 'react-router-dom'
import { motion } from 'framer-motion'
import {
  LayoutDashboard,
  Sparkles,
  Video,
  BarChart3,
  Settings,
  LogOut,
  Upload,
  PlayCircle,
} from 'lucide-react'

import { Avatar } from '../ui/Avatar'
import { useAuth } from '../../lib/auth'
import { cn } from '../../lib/utils'

const TOP_NAV = [{ to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard }]
const BOTTOM_NAV = [
  { to: '/workspace', label: 'Workspace', icon: Video },
  { to: '/analytics', label: 'Analytics', icon: BarChart3 },
  { to: '/settings', label: 'Settings', icon: Settings },
]

function SidebarLink({ to, label, icon: Icon }) {
  return (
    <NavLink
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
              className="absolute left-0 top-1.5 bottom-1.5 w-1 rounded-full bg-gradient-to-b from-emerald-400 to-lime-300 shadow-[0_0_12px_rgb(16_185_129/0.7)]"
              transition={{ type: 'spring', stiffness: 400, damping: 30 }}
            />
          )}
          <Icon className={cn('h-4 w-4', isActive && 'text-brand-600 dark:text-brand-300')} />
          <span>{label}</span>
        </>
      )}
    </NavLink>
  )
}

function ActionButton({ label, icon: Icon, onClick, isActive, iconAnim }) {
  return (
    <motion.button
      onClick={onClick}
      initial="rest"
      animate="rest"
      whileHover="hover"
      whileTap={{ scale: 0.97 }}
      transition={{ type: 'spring', stiffness: 320, damping: 22 }}
      className="group relative block w-full text-left focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/60 rounded-2xl"
      aria-label={label}
    >
      {/* Animated gradient halo (border + glow) */}
      <span
        aria-hidden
        className={cn(
          'pointer-events-none absolute -inset-[1.5px] rounded-2xl bg-gradient-to-r from-emerald-500 via-brand-400 to-lime-300 opacity-0 blur-[6px] transition-opacity duration-500 animate-gradient-pan',
          'group-hover:opacity-80',
          isActive && 'opacity-90'
        )}
      />
      {/* Solid gradient border underlay (no blur) for a crisp edge */}
      <span
        aria-hidden
        className={cn(
          'pointer-events-none absolute -inset-px rounded-2xl bg-gradient-to-r from-emerald-500/70 via-brand-400/70 to-lime-300/70 opacity-0 transition-opacity duration-500 animate-gradient-pan',
          'group-hover:opacity-100',
          isActive && 'opacity-100'
        )}
      />

      <span
        className={cn(
          'relative flex items-center gap-3 px-3 py-2.5 rounded-2xl border transition-all duration-300 backdrop-blur-md',
          isActive
            ? 'bg-gradient-to-r from-emerald-500/40 via-emerald-400/25 to-lime-300/20 border-transparent text-white shadow-[inset_0_0_0_1px_rgb(255_255_255/0.08),0_0_28px_-6px_rgb(16_185_129/0.65)]'
            : 'bg-surface-2/70 border-border text-ink-1 group-hover:bg-brand-500/10 group-hover:border-transparent group-hover:scale-[1.03] group-hover:shadow-[0_0_24px_-6px_rgb(16_185_129/0.55)]'
        )}
      >
        <motion.span
          variants={{ rest: { x: 0, y: 0 }, hover: iconAnim }}
          transition={{ type: 'spring', stiffness: 380, damping: 18 }}
          className={cn(
            'relative flex h-7 w-7 shrink-0 items-center justify-center rounded-lg transition-all duration-300',
            isActive
              ? 'bg-white/15 text-white shadow-[0_0_12px_rgb(16_185_129/0.6)]'
              : 'bg-brand-500/10 text-brand-600 dark:text-brand-300 group-hover:bg-brand-500/20 group-hover:text-brand-500 group-hover:shadow-[0_0_10px_rgb(16_185_129/0.45)]'
          )}
        >
          <Icon className="h-4 w-4" />
        </motion.span>
        <span
          className={cn(
            'text-sm font-medium tracking-tight transition-colors duration-300',
            isActive ? 'text-white' : 'text-ink-1 group-hover:text-ink-1 dark:group-hover:text-white'
          )}
        >
          {label}
        </span>
      </span>
    </motion.button>
  )
}

export function Sidebar() {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()

  const onWorkspace = location.pathname === '/workspace'
  const isUploadActive = onWorkspace && location.search.includes('new=1')
  const isContinueActive = onWorkspace && !location.search.includes('new=1')

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
        {TOP_NAV.map((item) => (
          <SidebarLink key={item.to} {...item} />
        ))}

        <div className="pt-2 pb-1 space-y-2">
          <ActionButton
            label="Upload new video"
            icon={Upload}
            onClick={() => navigate('/workspace?new=1')}
            isActive={isUploadActive}
            iconAnim={{ y: -3 }}
          />
          <ActionButton
            label="Continue learning"
            icon={PlayCircle}
            onClick={() => navigate('/workspace')}
            isActive={isContinueActive}
            iconAnim={{ x: 3 }}
          />
        </div>

        <div className="pt-1 space-y-1">
          {BOTTOM_NAV.map((item) => (
            <SidebarLink key={item.to} {...item} />
          ))}
        </div>
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

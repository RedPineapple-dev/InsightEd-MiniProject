import { Moon, Sun } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'

import { useTheme } from '../../lib/theme'
import { cn } from '../../lib/utils'

export function ThemeToggle({ className }) {
  const { theme, toggle } = useTheme()
  const isDark = theme === 'dark'
  return (
    <button
      onClick={toggle}
      aria-label="Toggle theme"
      className={cn(
        'relative h-9 w-9 rounded-lg flex items-center justify-center text-ink-2 hover:text-ink-1 hover:bg-surface-2 transition',
        className
      )}
    >
      <AnimatePresence mode="wait" initial={false}>
        <motion.span
          key={isDark ? 'moon' : 'sun'}
          initial={{ rotate: -45, opacity: 0 }}
          animate={{ rotate: 0, opacity: 1 }}
          exit={{ rotate: 45, opacity: 0 }}
          transition={{ duration: 0.18 }}
        >
          {isDark ? <Moon className="h-4 w-4" /> : <Sun className="h-4 w-4" />}
        </motion.span>
      </AnimatePresence>
    </button>
  )
}

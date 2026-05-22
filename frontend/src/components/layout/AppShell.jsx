import { motion } from 'framer-motion'

import { Sidebar } from './Sidebar'
import { Topbar } from './Topbar'

export function AppShell({ title, subtitle, action, children }) {
  return (
    <div className="flex min-h-screen bg-surface-0">
      <Sidebar />
      <div className="flex-1 min-w-0 flex flex-col">
        <Topbar title={title} subtitle={subtitle} action={action} />
        <motion.main
          key={title || 'page'}
          initial={{ opacity: 0, y: 8 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
          className="flex-1 px-4 lg:px-8 py-6 lg:py-8"
        >
          {children}
        </motion.main>
      </div>
    </div>
  )
}

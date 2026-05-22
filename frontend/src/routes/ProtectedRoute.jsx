import { Navigate, useLocation } from 'react-router-dom'
import { Loader2 } from 'lucide-react'

import { useAuth } from '../lib/auth'

export function ProtectedRoute({ children }) {
  const { isAuthed, bootstrapping } = useAuth()
  const location = useLocation()

  if (bootstrapping) {
    return (
      <div className="min-h-screen flex items-center justify-center text-ink-3">
        <Loader2 className="h-5 w-5 animate-spin" />
      </div>
    )
  }
  if (!isAuthed) {
    return <Navigate to="/login" replace state={{ from: location }} />
  }
  return children
}

import { useState } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router-dom'
import { Mail, Lock, ArrowRight } from 'lucide-react'
import toast from 'react-hot-toast'

import { Input } from '../../components/ui/Input'
import Button from '../../components/ui/Button'
import { useAuth } from '../../lib/auth'
import { AuthLayout } from './AuthLayout'

export default function LoginPage() {
  const { login, isAuthed } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState('')

  if (isAuthed) {
    const next = location.state?.from?.pathname || '/dashboard'
    return <Navigate to={next} replace />
  }

  async function onSubmit(e) {
    e.preventDefault()
    setSubmitting(true)
    setError('')
    try {
      await login(email, password)
      const next = location.state?.from?.pathname || '/dashboard'
      navigate(next, { replace: true })
    } catch (err) {
      const message =
        err?.response?.data?.detail ||
        (err?.response?.status === 503
          ? 'Authentication is unavailable — set MONGODB_URI in backend/.env'
          : 'Invalid email or password')
      setError(message)
      toast.error(message)
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AuthLayout title="Sign in" subtitle="Pick up where you left off.">
      <form onSubmit={onSubmit} className="space-y-4">
        <Input
          label="Email"
          type="email"
          autoComplete="email"
          required
          leftIcon={<Mail />}
          placeholder="you@school.edu"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
        />
        <Input
          label="Password"
          type="password"
          autoComplete="current-password"
          required
          leftIcon={<Lock />}
          placeholder="••••••••"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          error={error}
        />
        <Button type="submit" className="w-full" loading={submitting} rightIcon={<ArrowRight />}>
          Sign in
        </Button>
      </form>

      <p className="text-sm text-ink-3 text-center mt-6">
        New to InsightEd?{' '}
        <Link to="/register" className="text-brand-600 dark:text-brand-300 font-medium hover:underline">
          Create an account
        </Link>
      </p>
    </AuthLayout>
  )
}

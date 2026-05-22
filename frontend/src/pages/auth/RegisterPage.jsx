import { useState } from 'react'
import { Link, Navigate, useNavigate } from 'react-router-dom'
import { Mail, Lock, User, ArrowRight } from 'lucide-react'
import toast from 'react-hot-toast'

import { Input } from '../../components/ui/Input'
import Button from '../../components/ui/Button'
import { useAuth } from '../../lib/auth'
import { AuthLayout } from './AuthLayout'

export default function RegisterPage() {
  const { register, isAuthed } = useAuth()
  const navigate = useNavigate()
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [errors, setErrors] = useState({})

  if (isAuthed) return <Navigate to="/dashboard" replace />

  async function onSubmit(e) {
    e.preventDefault()
    setErrors({})

    const localErrors = {}
    if (name.trim().length < 2) localErrors.name = 'Please enter your name'
    if (password.length < 8) localErrors.password = 'At least 8 characters'
    if (Object.keys(localErrors).length) {
      setErrors(localErrors)
      return
    }

    setSubmitting(true)
    try {
      await register(name.trim(), email, password)
      navigate('/dashboard', { replace: true })
    } catch (err) {
      const detail = err?.response?.data?.detail
      const status = err?.response?.status
      if (status === 409) {
        setErrors({ email: 'That email is already registered' })
      } else if (status === 503) {
        toast.error('Authentication is unavailable — set MONGODB_URI in backend/.env')
      } else if (Array.isArray(detail)) {
        // pydantic validation
        const next = {}
        for (const e of detail) {
          const field = e.loc?.[e.loc.length - 1]
          if (field) next[field] = e.msg
        }
        setErrors(next)
      } else {
        toast.error(detail || 'Could not create account')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AuthLayout title="Create your account" subtitle="Free to use, takes about 30 seconds.">
      <form onSubmit={onSubmit} className="space-y-4">
        <Input
          label="Full name"
          required
          leftIcon={<User />}
          placeholder="Jane Doe"
          value={name}
          onChange={(e) => setName(e.target.value)}
          error={errors.name}
        />
        <Input
          label="Email"
          type="email"
          autoComplete="email"
          required
          leftIcon={<Mail />}
          placeholder="you@school.edu"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          error={errors.email}
        />
        <Input
          label="Password"
          type="password"
          autoComplete="new-password"
          required
          minLength={8}
          leftIcon={<Lock />}
          placeholder="At least 8 characters"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          error={errors.password}
        />
        <Button type="submit" className="w-full" loading={submitting} rightIcon={<ArrowRight />}>
          Create account
        </Button>
      </form>

      <p className="text-sm text-ink-3 text-center mt-6">
        Already have an account?{' '}
        <Link to="/login" className="text-brand-600 dark:text-brand-300 font-medium hover:underline">
          Sign in
        </Link>
      </p>
    </AuthLayout>
  )
}

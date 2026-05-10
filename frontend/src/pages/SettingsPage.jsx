import { useState } from 'react'
import { Save, LogOut, User as UserIcon } from 'lucide-react'
import toast from 'react-hot-toast'

import { AppShell } from '../components/layout/AppShell'
import { Card, CardBody, CardHeader, CardTitle, CardDescription } from '../components/ui/Card'
import Button from '../components/ui/Button'
import { Input } from '../components/ui/Input'
import { Avatar } from '../components/ui/Avatar'
import { Badge } from '../components/ui/Badge'
import { useTheme } from '../lib/theme'
import { useAuth } from '../lib/auth'

export default function SettingsPage() {
  const { user, updateProfile, logout } = useAuth()
  const { theme, setTheme } = useTheme()
  const [name, setName] = useState(user?.name || '')
  const [saving, setSaving] = useState(false)

  const onSave = async (e) => {
    e.preventDefault()
    setSaving(true)
    try {
      await updateProfile({ name })
    } catch (err) {
      toast.error(err?.response?.data?.detail || 'Could not update profile')
    } finally {
      setSaving(false)
    }
  }

  return (
    <AppShell title="Settings" subtitle="Profile and preferences">
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Profile</CardTitle>
              <CardDescription>Update how you appear across InsightEd.</CardDescription>
            </CardHeader>
            <CardBody>
              <form onSubmit={onSave} className="space-y-4">
                <div className="flex items-center gap-4">
                  <Avatar name={user?.name} src={user?.avatar_url} size={64} />
                  <div>
                    <div className="font-display font-semibold">{user?.name}</div>
                    <div className="text-sm text-ink-3">{user?.email}</div>
                    <Badge tone="brand" className="mt-1">{user?.role || 'student'}</Badge>
                  </div>
                </div>
                <Input
                  label="Display name"
                  leftIcon={<UserIcon />}
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
                <Button type="submit" leftIcon={<Save />} loading={saving}>
                  Save changes
                </Button>
              </form>
            </CardBody>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>Appearance</CardTitle>
              <CardDescription>Choose how InsightEd looks on this device.</CardDescription>
            </CardHeader>
            <CardBody>
              <div className="grid grid-cols-2 gap-3">
                {[
                  { v: 'light', label: 'Light', preview: 'from-white to-emerald-50' },
                  { v: 'dark', label: 'Dark', preview: 'from-slate-900 to-emerald-950' },
                ].map((opt) => (
                  <button
                    key={opt.v}
                    onClick={() => setTheme(opt.v)}
                    className={`relative rounded-2xl overflow-hidden border-2 transition ${
                      theme === opt.v ? 'border-brand-500 shadow-glow' : 'border-border hover:border-border-strong'
                    }`}
                  >
                    <div className={`h-24 bg-gradient-to-br ${opt.preview}`} />
                    <div className="px-4 py-2.5 text-left text-sm font-medium bg-surface-1 border-t border-border">
                      {opt.label}
                    </div>
                  </button>
                ))}
              </div>
            </CardBody>
          </Card>
        </div>

        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Session</CardTitle>
              <CardDescription>Sign out on this device.</CardDescription>
            </CardHeader>
            <CardBody>
              <Button variant="danger" onClick={logout} leftIcon={<LogOut />}>
                Sign out
              </Button>
            </CardBody>
          </Card>
        </div>
      </div>
    </AppShell>
  )
}

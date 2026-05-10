import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import toast from 'react-hot-toast'

import { authApi, setUnauthorizedHandler, tokenStorage } from './api'
import { bindStoresToUser, resetAllUserState, useSessionStore } from './sessionStore'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [bootstrapping, setBootstrapping] = useState(true)

  const logout = useCallback(() => {
    tokenStorage.clear()
    setUser(null)
    resetAllUserState()
  }, [])

  useEffect(() => {
    setUnauthorizedHandler(() => {
      tokenStorage.clear()
      setUser(null)
      resetAllUserState()
    })
  }, [])

  // Bootstrap session from a stored token if present
  useEffect(() => {
    const token = tokenStorage.get()
    if (!token) {
      // No token — make sure we're not holding onto a stale persisted snapshot
      // belonging to whoever was logged in last on this device.
      resetAllUserState()
      setBootstrapping(false)
      return
    }
    authApi
      .me()
      .then((u) => {
        // Bind first (this hard-resets the persisted stores when the user
        // identity changed since last visit), then hydrate from backend.
        bindStoresToUser(u)
        setUser(u)
        useSessionStore.getState().hydrateFromBackend()
      })
      .catch(() => {
        tokenStorage.clear()
        resetAllUserState()
      })
      .finally(() => setBootstrapping(false))
  }, [])

  const login = useCallback(async (email, password) => {
    const data = await authApi.login({ email, password })
    tokenStorage.set(data.access_token)
    bindStoresToUser(data.user)
    setUser(data.user)
    toast.success(`Welcome back, ${data.user.name.split(' ')[0]}`)
    useSessionStore.getState().hydrateFromBackend()
    return data.user
  }, [])

  const register = useCallback(async (name, email, password) => {
    const data = await authApi.register({ name, email, password })
    tokenStorage.set(data.access_token)
    bindStoresToUser(data.user)
    setUser(data.user)
    toast.success(`Welcome, ${name.split(' ')[0]}!`)
    useSessionStore.getState().hydrateFromBackend()
    return data.user
  }, [])

  const updateProfile = useCallback(async (payload) => {
    const updated = await authApi.updateMe(payload)
    setUser(updated)
    toast.success('Profile updated')
    return updated
  }, [])

  const value = useMemo(
    () => ({ user, bootstrapping, login, register, logout, updateProfile, isAuthed: !!user }),
    [user, bootstrapping, login, register, logout, updateProfile]
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}

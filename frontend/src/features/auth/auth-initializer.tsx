/**
 * AuthInitializer — restores auth state on page refresh.
 *
 * Checks localStorage for a refresh_token, calls the refresh API,
 * and either restores the session or clears stale data.
 * Shows a global spinner during initialization.
 */
import { type ReactNode, useEffect } from 'react'
import { Spin } from 'antd'

import { REFRESH_TOKEN_KEY, useAuthStore } from '../../stores/auth-store'
import { authApi } from '../../services/auth-api'
import { decodeAccessToken } from '../../lib/jwt'

export function AuthInitializer({ children }: { children: ReactNode }) {
  const isInitializing = useAuthStore((s) => s.isInitializing)
  const setInitializing = useAuthStore((s) => s.setInitializing)
  const setAuth = useAuthStore((s) => s.setAuth)
  const clearAuth = useAuthStore((s) => s.clearAuth)

  useEffect(() => {
    const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY)

    if (!refreshToken) {
      setInitializing(false)
      return
    }

    let cancelled = false

    authApi
      .refresh(refreshToken)
      .then((res) => {
        if (cancelled) return
        const { access_token, refresh_token } = res.data
        const payload = decodeAccessToken(access_token)
        if (payload) {
          setAuth(access_token, { id: payload.sub, username: payload.username, role: payload.role })
          localStorage.setItem(REFRESH_TOKEN_KEY, refresh_token)
        } else {
          clearAuth()
        }
      })
      .catch(() => {
        if (cancelled) return
        clearAuth()
      })
      .finally(() => {
        if (!cancelled) {
          setInitializing(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [setInitializing, setAuth, clearAuth])

  if (isInitializing) {
    return (
      <div className="flex items-center justify-center min-h-screen">
        <Spin size="large" />
      </div>
    )
  }

  return <>{children}</>
}

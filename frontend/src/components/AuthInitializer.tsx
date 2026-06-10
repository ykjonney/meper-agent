/**
 * AuthInitializer — app startup auth recovery.
 *
 * On mount, checks localStorage for a refresh_token. If found, silently
 * refreshes the access token to restore the session. Shows a fullscreen
 * spinner during initialization to prevent layout flash.
 */
import { useEffect, type ReactNode } from 'react'
import { Spin } from 'antd'
import { useAuthStore } from '../stores/auth-store'
import { authApi } from '../services/auth-api'
import { decodeAccessToken } from '../lib/jwt'

export function AuthInitializer({ children }: { children: ReactNode }) {
  const { isInitializing, setInitializing, setAuth, clearAuth } = useAuthStore()

  useEffect(() => {
    const refreshToken = localStorage.getItem('agentflow_refresh_token')
    if (!refreshToken) {
      setInitializing(false)
      return
    }

    authApi
      .refresh(refreshToken)
      .then((res) => {
        const { access_token, refresh_token } = res.data
        const payload = decodeAccessToken(access_token)
        if (payload) {
          setAuth(access_token, {
            id: payload.sub,
            username: payload.username,
            role: payload.role,
          })
          // refresh token rotation — store the new one
          localStorage.setItem('agentflow_refresh_token', refresh_token)
        } else {
          clearAuth()
        }
      })
      .catch(() => {
        clearAuth()
      })
      .finally(() => {
        setInitializing(false)
      })
  }, [])

  if (isInitializing) {
    return (
      <div className="flex items-center justify-center min-h-screen bg-white">
        <Spin size="large" />
      </div>
    )
  }

  return <>{children}</>
}

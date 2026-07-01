import { useState, useEffect } from 'react'
import { useRoutes } from 'react-router-dom'
import { ConfigProvider, App as AntApp, theme as antdTheme } from 'antd'
import zhCN from 'antd/locale/zh_CN'

/* @xyflow/react 画布样式 — 确保在工作流编辑器中使用 */
import '@xyflow/react/dist/style.css'

import { ThemeProvider, useTheme } from './contexts/ThemeContext'
import { AuthInitializer } from './components/AuthInitializer'
import { routes } from './routes'
import { useTaskRealtime } from './hooks/use-task-realtime'
import { wsClient } from './lib/ws-client'
import { useAuthStore } from './stores/auth-store'
import { useNotificationStore } from './stores/notification-store'

/** Hook: detect system prefers-color-scheme: dark */
function usePrefersDark(): boolean {
  const [dark, setDark] = useState(() =>
    typeof window !== 'undefined'
      ? window.matchMedia('(prefers-color-scheme: dark)').matches
      : false,
  )
  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const handler = (e: MediaQueryListEvent) => setDark(e.matches)
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [])
  return dark
}

/**
 * Inner app — has access to ThemeContext so ConfigProvider can react to theme changes.
 */
function AppInner() {
  const { t } = useTheme()
  const element = useRoutes(routes)
  const isDark = usePrefersDark()

  // Connect WebSocket when authenticated
  const isAuthenticated = useAuthStore((s) => !!s.accessToken)

  useEffect(() => {
    if (isAuthenticated) {
      wsClient.resume()
      wsClient.connect()
    } else {
      wsClient.disconnect()
    }
  }, [isAuthenticated])

  // Keep the WS connection in sync with access-token refreshes.
  //
  // Background: axios refreshes the access token lazily (only when an HTTP
  // request hits 401). The WS client reconnecting blindly after a 4401 close
  // would re-use the still-stale token in the store and loop connect→reject
  // until some unrelated HTTP request happened to refresh it. By subscribing
  // to the store's accessToken here, the moment a refresh lands we hand the
  // fresh token straight to the WS client and it reconnects immediately.
  useEffect(() => {
    let lastToken = useAuthStore.getState().accessToken
    return useAuthStore.subscribe((state) => {
      const nextToken = state.accessToken
      if (nextToken && nextToken !== lastToken) {
        lastToken = nextToken
        // Only act when authenticated — disconnect/logout clears the token and
        // the isAuthenticated effect above handles teardown.
        wsClient.reconnectWithFreshToken(nextToken)
      }
    })
  }, [])

  // Bridge WS events to TanStack Query + Notification Store
  useTaskRealtime()

  // Load initial notification data
  useEffect(() => {
    if (isAuthenticated) {
      useNotificationStore.getState().loadUnreadCount()
    }
  }, [isAuthenticated])

  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          // Primary — dynamic from theme
          colorPrimary: t.primary,
          colorPrimaryHover: t.hover,
          colorPrimaryActive: t.active,
          colorPrimaryBg: t.bg,
          // Accent — follows theme primary
          colorInfo: t.primary,
          // Semantic
          colorSuccess: '#10B981',
          colorWarning: '#F59E0B',
          colorError: '#EF4444',
          colorLink: t.primary,
          // Radius
          borderRadius: 8,
          borderRadiusLG: 10,
          borderRadiusSM: 6,
          // Font — DM Sans
          fontFamily:
            "'DM Sans', -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif",
          fontFamilyCode:
            "'JetBrains Mono', 'SF Mono', 'Menlo', 'Consolas', monospace",
          fontSize: 14,
        },
        algorithm: isDark ? antdTheme.darkAlgorithm : antdTheme.defaultAlgorithm,
        components: {
          Button: {
            borderRadius: 8,
            borderRadiusLG: 10,
            borderRadiusSM: 6,
            controlHeight: 36,
            controlHeightLG: 44,
            controlHeightSM: 28,
            paddingContentHorizontal: 16,
          },
          Card: {
            paddingLG: 20,
            borderRadiusLG: 12,
          },
          Table: {
            headerBorderRadius: 8,
          },
          Tag: {
            borderRadius: 6,
          },
          Modal: {
            borderRadiusLG: 12,
          },
          Menu: {
            itemBorderRadius: 8,
          },
        },
      }}
    >
      <AntApp>{element}</AntApp>
    </ConfigProvider>
  )
}

/**
 * Root application component.
 */
export default function App() {
  return (
    <ThemeProvider>
      <AuthInitializer>
        <AppInner />
      </AuthInitializer>
    </ThemeProvider>
  )
}

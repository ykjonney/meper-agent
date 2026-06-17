import { useState, useEffect } from 'react'
import { useRoutes } from 'react-router-dom'
import { ConfigProvider, App as AntApp, theme as antdTheme } from 'antd'
import zhCN from 'antd/locale/zh_CN'

/* @xyflow/react 画布样式 — 确保在工作流编辑器中使用 */
import '@xyflow/react/dist/style.css'

import { ThemeProvider, useTheme } from './contexts/ThemeContext'
import { AuthInitializer } from './components/AuthInitializer'
import { routes } from './routes'

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

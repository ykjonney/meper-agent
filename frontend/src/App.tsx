import { useRoutes } from 'react-router-dom'
import { ConfigProvider, App as AntApp, theme as antdTheme } from 'antd'
import zhCN from 'antd/locale/zh_CN'

import { ThemeProvider, useTheme } from './contexts/ThemeContext'
import { AuthInitializer } from './components/AuthInitializer'
import { routes } from './routes'

/**
 * Inner app — has access to ThemeContext so ConfigProvider can react to theme changes.
 */
function AppInner() {
  const { t } = useTheme()
  const element = useRoutes(routes)

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
          // Accent — Orange (for highlights)
          colorInfo: '#F97316',
          // Semantic
          colorSuccess: '#10B981',
          colorWarning: '#F59E0B',
          colorError: '#EF4444',
          colorLink: t.primary,
          // Surface — white ladder
          colorBgLayout: '#FFFFFF',
          colorBgContainer: '#FFFFFF',
          colorBgElevated: '#F8FAFC',
          // Border — subtle
          colorBorder: '#E2E8F0',
          colorBorderSecondary: '#F1F5F9',
          // Text — slate
          colorText: '#0F172A',
          colorTextSecondary: '#475569',
          colorTextTertiary: '#94A3B8',
          colorTextQuaternary: '#CBD5E1',
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
        algorithm: antdTheme.defaultAlgorithm,
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
            headerBg: '#F8FAFC',
            headerColor: '#475569',
            headerBorderRadius: 8,
            rowHoverBg: '#EFF6FF',
            borderColor: '#F1F5F9',
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

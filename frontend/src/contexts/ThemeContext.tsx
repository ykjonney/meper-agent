/**
 * ThemeContext — global theme state for the Agent Flow design system.
 *
 * Provides the current Theme object and a setter. The consuming ConfigProvider
 * in App.tsx reads from this context to apply theme tokens globally.
 */
import { createContext, useContext, useState, type ReactNode } from 'react'

/* ════════════════════════════════════════════════════════════════
   THEME DEFINITIONS
   ════════════════════════════════════════════════════════════════ */

export interface Theme {
  key: string
  name: string
  zhName: string
  primary: string
  hover: string
  active: string
  light: string
  bg: string
  bgStrong: string
  vibe: string
}

// eslint-disable-next-line react-refresh/only-export-components
export const THEMES: Theme[] = [
  { key: 'orange', name: 'Orange', zhName: '橙色', primary: '#F97316', hover: '#EA580C', active: '#C2410C', light: '#FB923C', bg: '#FFF7ED', bgStrong: '#FFEDD5', vibe: '温暖 · 活力' },
  { key: 'violet', name: 'Violet', zhName: '紫罗兰', primary: '#7C3AED', hover: '#8B5CF6', active: '#6D28D9', light: '#A78BFA', bg: '#F5F3FF', bgStrong: '#EDE9FE', vibe: 'AI · 创新' },
  { key: 'blue', name: 'Blue', zhName: '蓝色', primary: '#2563EB', hover: '#1D4ED8', active: '#1E40AF', light: '#60A5FA', bg: '#EFF6FF', bgStrong: '#DBEAFE', vibe: '信任 · 专业' },
  { key: 'emerald', name: 'Emerald', zhName: '翠绿', primary: '#10B981', hover: '#059669', active: '#047857', light: '#34D399', bg: '#ECFDF5', bgStrong: '#D1FAE5', vibe: '成长 · 清新' },
  { key: 'rose', name: 'Rose', zhName: '玫红', primary: '#F43F5E', hover: '#E11D48', active: '#BE123C', light: '#FB7185', bg: '#FFF1F2', bgStrong: '#FFE4E6', vibe: '激情 · 现代' },
  { key: 'indigo', name: 'Indigo', zhName: '深靛蓝', primary: '#4F46E5', hover: '#4338CA', active: '#3730A3', light: '#818CF8', bg: '#EEF2FF', bgStrong: '#E0E7FF', vibe: '科技 · 深度' },
]

/* ════════════════════════════════════════════════════════════════
   CONTEXT
   ════════════════════════════════════════════════════════════════ */

interface ThemeContextValue {
  theme: Theme
  setTheme: (t: Theme) => void
  t: Theme
}

const ThemeContext = createContext<ThemeContextValue | null>(null)

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(THEMES[2]) // default: blue

  return (
    <ThemeContext.Provider value={{ theme, setTheme, t: theme }}>
      {children}
    </ThemeContext.Provider>
  )
}

// eslint-disable-next-line react-refresh/only-export-components
export function useTheme(): ThemeContextValue {
  const ctx = useContext(ThemeContext)
  if (!ctx) throw new Error('useTheme must be used within ThemeProvider')
  return ctx
}

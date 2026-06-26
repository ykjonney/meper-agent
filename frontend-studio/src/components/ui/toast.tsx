/**
 * Toast —— 全局轻量提示（成功 / 错误 / 警告 / 信息）。
 *
 * 设计要点：
 * - 全局状态用 zustand（与 auth-store 一致），命令式 API `toast.success(...)`，
 *   非 React 上下文也能调（mutation onError 里直接用）。
 * - `<Toaster />` 内联渲染（非 createPortal），根元素打 `theme-${theme}` class，
 *   复用 index.css 的 `.theme-light` 覆盖，自动兼容明暗主题。
 * - 配色用项目既定硬编码 hex（#18181b / #27272a / #fafafa）+ 类型色图标（lucide）。
 */
import { useEffect, useState } from 'react'
import { create } from 'zustand'
import { CheckCircle2, XCircle, AlertTriangle, Info, X } from 'lucide-react'

export type ToastType = 'success' | 'error' | 'warning' | 'info'

export interface ToastItem {
  id: string
  type: ToastType
  message: string
  /** 自动消失毫秒，0 = 不自动消失；默认 3000，error 默认 5000 */
  duration: number
}

interface ToastState {
  toasts: ToastItem[]
  push: (t: Omit<ToastItem, 'id'>) => string
  dismiss: (id: string) => void
}

export const useToastStore = create<ToastState>((set) => ({
  toasts: [],
  push: (t) => {
    const id = `toast_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`
    set((s) => ({ toasts: [...s.toasts, { ...t, id }] }))
    if (t.duration > 0) {
      setTimeout(() => {
        useToastStore.getState().dismiss(id)
      }, t.duration)
    }
    return id
  },
  dismiss: (id) => set((s) => ({ toasts: s.toasts.filter((x) => x.id !== id) })),
}))

interface ToastOpts {
  /** 自动消失毫秒；覆盖类型默认值 */
  duration?: number
}

function push(type: ToastType, message: string, opts?: ToastOpts): string {
  const defaultDuration = type === 'error' ? 5000 : 3000
  return useToastStore.getState().push({
    type,
    message,
    duration: opts?.duration ?? defaultDuration,
  })
}

/** 命令式 API：任意位置可调（含 mutation onError）。 */
export const toast = {
  success: (message: string, opts?: ToastOpts) => push('success', message, opts),
  error: (message: string, opts?: ToastOpts) => push('error', message, opts),
  warning: (message: string, opts?: ToastOpts) => push('warning', message, opts),
  info: (message: string, opts?: ToastOpts) => push('info', message, opts),
}

/** 每种类型的图标 + 图标色 */
const TYPE_STYLE: Record<ToastType, { icon: typeof CheckCircle2; color: string }> = {
  success: { icon: CheckCircle2, color: 'text-emerald-400' },
  error: { icon: XCircle, color: 'text-rose-400' },
  warning: { icon: AlertTriangle, color: 'text-amber-400' },
  info: { icon: Info, color: 'text-indigo-400' },
}

/** 读取当前主题（App 每次 toggle 都写 localStorage('agentflow_theme')）。 */
function useThemeClass(): string {
  const [theme, setTheme] = useState<'dark' | 'light'>(() => {
    const t = typeof localStorage !== 'undefined' ? localStorage.getItem('agentflow_theme') : null
    return t === 'light' ? 'light' : 'dark'
  })
  // 监听 storage 事件 + 自定义 toast-theme 事件（同标签页切换）
  useEffect(() => {
    const sync = () => {
      const t = localStorage.getItem('agentflow_theme')
      setTheme(t === 'light' ? 'light' : 'dark')
    }
    window.addEventListener('storage', sync)
    window.addEventListener('agentflow-theme-change', sync)
    return () => {
      window.removeEventListener('storage', sync)
      window.removeEventListener('agentflow-theme-change', sync)
    }
  }, [])
  return `theme-${theme}`
}

/**
 * Toaster —— 全局唯一实例，挂在 App 根。
 * 内联渲染（fixed top-right），根打 theme class 复用明暗覆盖。
 */
export function Toaster() {
  const toasts = useToastStore((s) => s.toasts)
  const dismiss = useToastStore((s) => s.dismiss)
  const themeClass = useThemeClass()

  return (
    <div className={`fixed top-4 right-4 z-[100] flex flex-col gap-2 pointer-events-none ${themeClass}`}>
      {toasts.map((t) => {
        const { icon: Icon, color } = TYPE_STYLE[t.type]
        return (
          <div
            key={t.id}
            className="pointer-events-auto flex items-start gap-2.5 min-w-[260px] max-w-sm px-3.5 py-3 rounded-lg border border-[#27272a] bg-[#18181b] shadow-2xl animate-fade-in"
          >
            <Icon className={`w-4 h-4 shrink-0 mt-0.5 ${color}`} />
            <p className="flex-1 text-xs text-[#fafafa] leading-relaxed break-words">{t.message}</p>
            <button
              onClick={() => dismiss(t.id)}
              className="shrink-0 text-[#71717a] hover:text-[#fafafa] cursor-pointer transition-colors"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        )
      })}
    </div>
  )
}

export default Toaster

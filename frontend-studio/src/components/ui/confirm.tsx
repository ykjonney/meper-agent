/**
 * confirmDialog —— 统一确认弹窗（替代原生 window.confirm）。
 *
 * 设计要点：
 * - 命令式 `await confirmDialog({...})` 返回 Promise<boolean>，
 *   深层子组件触发的操作（如 TaskBoard 的取消/重试/删除）也能干净替换，
 *   无需侵入子组件用声明式 Popconfirm 包裹。
 * - `<ConfirmHost />` 复用现有 `<Modal>`（已内联、已兼容明暗主题）。
 * - 全局同一时刻只有一个确认窗；Esc / 点遮罩 = 取消(false)。
 */
import { useEffect } from 'react'
import { create } from 'zustand'
import { Modal } from './index'

export interface ConfirmOptions {
  title: string
  description?: string
  okText?: string
  cancelText?: string
  /** danger: 确定按钮红色（如删除确认） */
  danger?: boolean
}

interface ConfirmState {
  options: ConfirmOptions | null
  resolve: ((value: boolean) => void) | null
  open: (opts: ConfirmOptions, resolve: (v: boolean) => void) => void
  close: (result: boolean) => void
}

const useConfirmStore = create<ConfirmState>((set) => ({
  options: null,
  resolve: null,
  open: (opts, resolve) => set({ options: opts, resolve }),
  close: (result) => {
    const { resolve } = useConfirmStore.getState()
    resolve?.(result)
    set({ options: null, resolve: null })
  },
}))

/**
 * 命令式确认弹窗。返回 true=确定 / false=取消。
 * @example
 *   const ok = await confirmDialog({ title: '确定取消？', danger: true })
 *   if (!ok) return
 */
export function confirmDialog(opts: ConfirmOptions): Promise<boolean> {
  return new Promise((resolve) => {
    useConfirmStore.getState().open(opts, resolve)
  })
}

/**
 * ConfirmHost —— 全局唯一实例，挂在 App 根。订阅 store 渲染 Modal。
 */
export function ConfirmHost() {
  const options = useConfirmStore((s) => s.options)
  const close = useConfirmStore((s) => s.close)

  // Esc 关闭 = 取消
  useEffect(() => {
    if (!options) return
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') close(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [options, close])

  return (
    <Modal
      open={!!options}
      title={options?.title}
      okText={options?.okText ?? '确定'}
      cancelText={options?.cancelText ?? '取消'}
      okButtonProps={{ danger: options?.danger }}
      onOk={() => close(true)}
      onCancel={() => close(false)}
      width={420}
    >
      {options?.description && (
        <p className="text-xs text-[#a1a1aa] leading-relaxed">{options.description}</p>
      )}
    </Modal>
  )
}

export default ConfirmHost

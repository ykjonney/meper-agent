/**
 * Native Tailwind UI primitives — drop-in replacements for the antd components
 * used by the migrated workflow-editor module.
 *
 * Kept intentionally small: each mirrors only the props actually consumed by
 * the workflow editor (Input / Input.TextArea / Select / Button / Modal /
 * Table / Switch / Tag / Tooltip / Popover / Badge / Spin / Popconfirm).
 *
 * Styling is pure Tailwind className + inline styles; no antd design tokens.
 *
 * Dark-native: surfaces use the AgentForge dark palette (bg-panel /
 * bg-page / border-line / text-ink / text-slate-*). Light mode
 * is handled by the .theme-light override block in index.css, which maps these
 * same classes to light values — so no per-component theme branching is needed.
 */
import {
  useState,
  useRef,
  useEffect,
  useLayoutEffect,
  useCallback,
  forwardRef,
  type ReactNode,
  type CSSProperties,
  type InputHTMLAttributes,
  type TextareaHTMLAttributes,
  type ButtonHTMLAttributes,
  type KeyboardEvent as ReactKeyboardEvent,
  type RefObject,
} from 'react'
import { X } from 'lucide-react'
import { createPortal } from 'react-dom'

/* ─── 浮层定位（Select / Popover / Tooltip 共用） ─── */

interface PanelPlacement {
  side: 'bottom' | 'top'
  align: 'start' | 'center' | 'end'
  gap: number
  /** 面板未挂载（测不到宽）时的宽度兜底。 */
  fallbackW: number
  /** 面板宽度跟随触发器但设下限（Select：行内收缩触发器 w-fit ~70px）。 */
  minW?: number
  /** 打开期间监听 scroll(capture)/resize 实时重算（Tooltip/Popover）。 */
  follow?: boolean
}

const PANEL_MARGIN = 8

/**
 * 浮层 fixed 定位：portal 到主题根 + 按触发器矩形计算坐标。
 * 三处原实现逐像素保留，仅合一：
 * - 默认 side 方向展开；当前侧放不下且对侧够 → 翻到对侧；最后垂直夹在视口内。
 * - align: start=左缘对齐触发器左缘 / center=水平居中 / end=右缘对齐触发器右缘。
 * - left 一律夹在视口内（M=8）。
 *
 * position:fixed 是必须的：portal 目标是 theme root（h-screen flex 容器），
 * 没有 position 的 static 面板会成为 flex item 被 align-items:stretch 拉到
 * 容器满高，按这个错误高度做视口翻转会把面板推到顶部。
 *
 * Portal 到主题根而非 document.body：(a) 脱离祖先 `overflow: hidden`（如弹窗
 * 面板）避免裁剪，(b) 留在 .theme-light/.theme-dark 子树内，index.css 的主题
 * 覆写才能作用到浮层。portaling 到 body 会脱离主题作用域，亮色下浮层仍是暗色。
 *
 * 面板尺寸在本次渲染挂载前未知：coords=null 时调用方应把面板藏到屏外，
 * 并在 open 后用返回的 measure 于 useLayoutEffect 里实测重算（paint 前同步，
 * 避免闪烁）。placement 传模块级常量，保证 measure 引用稳定。
 */
function usePanelPosition(
  triggerRef: RefObject<HTMLElement | null>,
  panelRef: RefObject<HTMLElement | null>,
  open: boolean,
  placement: PanelPlacement,
) {
  const [portalTarget, setPortalTarget] = useState<HTMLElement | null>(null)
  useEffect(() => {
    setPortalTarget(document.querySelector<HTMLElement>('.theme-light, .theme-dark'))
  }, [])

  const [coords, setCoords] = useState<{ top: number; left: number; width?: number } | null>(null)

  const measure = useCallback(() => {
    const trig = triggerRef.current
    if (!trig) return
    const r = trig.getBoundingClientRect()
    let w = panelRef.current?.offsetWidth ?? placement.fallbackW
    const h = panelRef.current?.offsetHeight ?? 0
    const M = PANEL_MARGIN
    const GAP = placement.gap
    // 默认 side 展开；当前侧放不下且对侧够 → 翻到对侧
    let top: number
    if (placement.side === 'bottom') {
      top = r.bottom + GAP
      if (top + h > window.innerHeight - M && r.top - h - GAP >= M) top = r.top - h - GAP
    } else {
      top = r.top - h - GAP
      if (top < M && r.bottom + h + GAP <= window.innerHeight - M) top = r.bottom + GAP
    }
    // 垂直夹在视口内
    if (top + h > window.innerHeight - M) top = Math.max(M, window.innerHeight - h - M)
    if (top < M) top = M
    if (placement.minW) w = Math.max(r.width, placement.minW)
    let left: number
    if (placement.align === 'center') left = r.left + r.width / 2 - w / 2
    else if (placement.align === 'end') left = r.right - w
    else left = r.left
    // 水平夹在视口内
    left = Math.max(M, Math.min(left, window.innerWidth - w - M))
    setCoords(placement.minW ? { top, left, width: w } : { top, left })
  }, [triggerRef, panelRef, placement])

  // 打开期间滚动/缩放实时跟随（Select 的 scroll 走关闭逻辑，无需跟随）
  useEffect(() => {
    if (!open || !placement.follow) return
    measure()
    window.addEventListener('resize', measure)
    window.addEventListener('scroll', measure, true)
    return () => {
      window.removeEventListener('resize', measure)
      window.removeEventListener('scroll', measure, true)
    }
  }, [open, placement.follow, measure])

  return { coords, portalTarget, measure }
}

/* ─── Input ─── */

interface InputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'size'> {
  size?: 'small' | 'middle' | 'large'
  status?: 'error' | undefined
}

const SIZE_CLASS: Record<NonNullable<InputProps['size']>, string> = {
  small: 'h-7 text-xs px-2',
  middle: 'h-8 text-xs px-2.5',
  large: 'h-10 text-sm px-3',
}

function InputInner({ size = 'middle', status, className = '', ...rest }: InputProps) {
  return (
    <input
      {...rest}
      className={`w-full rounded-md border bg-page text-ink placeholder:text-ink-dim
        focus:outline-none focus:border-[#1E5EFF] focus:ring-1 focus:ring-[#1E5EFF]/30 transition-colors
        ${status === 'error' ? 'border-red-400' : 'border-line'}
        ${SIZE_CLASS[size]} ${className}`}
    />
  )
}

/* Input.TextArea — accessed as <Input.TextArea>, supports ref forwarding */
interface TextAreaProps extends Omit<TextareaHTMLAttributes<HTMLTextAreaElement>, 'size'> {
  rows?: number
}

const TextArea = forwardRef<HTMLTextAreaElement, TextAreaProps>(function TextArea(
  { rows = 3, className = '', ...rest },
  ref,
) {
  return (
    <textarea
      ref={ref}
      {...rest}
      rows={rows}
      className={`w-full rounded-md border border-line bg-page text-ink
        placeholder:text-ink-dim px-2.5 py-1.5 text-xs leading-relaxed resize-y
        focus:outline-none focus:border-[#1E5EFF] focus:ring-1 focus:ring-[#1E5EFF]/30 transition-colors
        ${className}`}
    />
  )
})

/**
 * Input — styled text input. Also exposes Input.TextArea.
 * Typed as a callable function with a TextArea static property.
 */
type InputComponent = typeof InputInner & {
  TextArea: typeof TextArea
}

const Input = InputInner as InputComponent
Input.TextArea = TextArea

export { Input }

/* ─── Select ─── */

export interface SelectOption {
  value: string
  label: ReactNode
  /** Optional leading icon. */
  icon?: ReactNode
  /** Optional subtitle / description shown beneath the label. */
  description?: string
  disabled?: boolean
}

export interface SelectOptionGroup {
  label: string
  options: SelectOption[]
}

interface SelectProps {
  value?: string | null
  onChange?: (value: string | null) => void
  /** Flat option list (mutually exclusive with `groups`). */
  options?: SelectOption[]
  /** Grouped options (mutually exclusive with `options`). */
  groups?: SelectOptionGroup[]
  placeholder?: string
  size?: 'small' | 'middle'
  className?: string
  allowClear?: boolean
  /** Inline search box in the dropdown. Defaults to `true` (post-upgrade behavior). */
  showSearch?: boolean
  filterOption?: (input: string, option: SelectOption) => boolean
  loading?: boolean
  disabled?: boolean
  /** 面板从打开变为关闭时回调（点击外部/Esc/滚动/选中均会触发）。
      行内编辑场景（如角色徽章点击变 Select）据此恢复原展示态。 */
  onClose?: () => void
}

/** Default filter: case-insensitive label substring match. */
const defaultFilter = (input: string, opt: SelectOption): boolean => {
  const label = typeof opt.label === 'string' ? opt.label : String(opt.label ?? '')
  const hay = (label + ' ' + (opt.description ?? '') + ' ' + opt.value).toLowerCase()
  return hay.includes(input.trim().toLowerCase())
}

/** Select 面板：触发器下方展开、左对齐、宽度跟随触发器（下限 160）。 */
const SELECT_PLACEMENT: PanelPlacement = { side: 'bottom', align: 'start', gap: 4, fallbackW: 160, minW: 160 }

export function Select({
  value,
  onChange,
  options = [],
  groups,
  placeholder = '请选择',
  size = 'middle',
  className = '',
  allowClear = false,
  showSearch = true,
  filterOption = defaultFilter,
  disabled = false,
  onClose,
}: SelectProps) {
  // Normalize groups + flat options into a single grouped structure for rendering.
  const sourceGroups: SelectOptionGroup[] =
    groups ?? (options.length ? [{ label: '', options }] : [])

  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [hover, setHover] = useState(false)
  const [activeIndex, setActiveIndex] = useState(-1) // keyboard highlight over the flat filtered list
  const ref = useRef<HTMLDivElement>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  const listRef = useRef<HTMLDivElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)

  const { coords: panelCoords, portalTarget, measure: measurePanel } = usePanelPosition(
    ref, panelRef, open, SELECT_PLACEMENT,
  )

  // 面板已随本次渲染挂载，实测高度后定位（屏外藏 → layoutEffect 重算）。
  useLayoutEffect(() => {
    if (!open) return
    measurePanel()
  }, [open, measurePanel])

  useEffect(() => {
    if (!open) return
    const onMouseDown = (e: MouseEvent) => {
      if (ref.current?.contains(e.target as Node)) return
      if (panelRef.current?.contains(e.target as Node)) return
      setOpen(false)
    }
    const close = () => setOpen(false)
    // Close on scroll/resize: we position the panel once on open rather than
    // tracking the trigger, so any layout shift collapses it instead of
    // leaving a detached panel. But ignore scrolls that originate *inside*
    // the panel — that's the option list scrolling (user wheel, or
    // scrollIntoView moving the highlighted option into view). Closing on
    // those would make long option lists flicker and become unselectable.
    const onScroll = (e: Event) => {
      if (panelRef.current?.contains(e.target as Node)) return
      setOpen(false)
    }
    document.addEventListener('mousedown', onMouseDown)
    window.addEventListener('scroll', onScroll, true)
    window.addEventListener('resize', close)
    return () => {
      document.removeEventListener('mousedown', onMouseDown)
      window.removeEventListener('scroll', onScroll, true)
      window.removeEventListener('resize', close)
    }
  }, [open])

  // Reset transient state whenever the panel opens/closes.
  useEffect(() => {
    if (open) {
      setSearch('')
      const flat = sourceGroups.flatMap((g) => g.options)
      const idx = flat.findIndex((o) => o.value === value)
      setActiveIndex(idx >= 0 ? idx : flat.findIndex((o) => !o.disabled))
      // focus the search input on open
      requestAnimationFrame(() => searchRef.current?.focus())
    }
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  // open true→false 时通知父组件（覆盖点击外部/Esc/滚动/选中所有关闭路径），
  // 行内编辑场景据此恢复原展示态。
  const wasOpenRef = useRef(false)
  useEffect(() => {
    if (wasOpenRef.current && !open) onClose?.()
    wasOpenRef.current = open
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  const filterFn = showSearch ? (filterOption ?? defaultFilter) : null
  const filteredGroups = filterFn
    ? sourceGroups
        .map((g) => ({ ...g, options: g.options.filter((o) => filterFn(search, o)) }))
        .filter((g) => g.options.length > 0)
    : sourceGroups
  const flatFiltered = filteredGroups.flatMap((g) => g.options)
  const hasMatch = flatFiltered.length > 0

  const selected = sourceGroups.flatMap((g) => g.options).find((o) => o.value === value)
  const displayNode = selected ? (
    <span className="flex items-center gap-1.5 min-w-0">
      {selected.icon && <span className="shrink-0">{selected.icon}</span>}
      <span className="truncate">{selected.label}</span>
    </span>
  ) : null

  const clamp = (i: number) => {
    if (flatFiltered.length === 0) return -1
    return (i + flatFiltered.length) % flatFiltered.length
  }

  const onKeyDown = (e: ReactKeyboardEvent) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      if (!open) { setOpen(true); return }
      let next = clamp(activeIndex + 1)
      // skip disabled
      while (flatFiltered[next]?.disabled && next !== activeIndex) next = clamp(next + 1)
      setActiveIndex(next)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      if (!open) { setOpen(true); return }
      let prev = clamp(activeIndex - 1)
      while (flatFiltered[prev]?.disabled && prev !== activeIndex) prev = clamp(prev - 1)
      setActiveIndex(prev)
    } else if (e.key === 'Enter' && open) {
      e.preventDefault()
      const opt = flatFiltered[activeIndex]
      if (opt && !opt.disabled) {
        onChange?.(opt.value)
        setOpen(false)
      }
    } else if (e.key === 'Escape' && open) {
      e.preventDefault()
      setOpen(false)
    }
  }

  // Scroll the active option into view as the highlight moves.
  useEffect(() => {
    if (!open || activeIndex < 0) return
    const el = listRef.current?.querySelector<HTMLElement>(`[data-idx="${activeIndex}"]`)
    el?.scrollIntoView({ block: 'nearest' })
  }, [activeIndex, open])

  return (
    <div ref={ref} className={`relative ${disabled ? 'opacity-50 pointer-events-none' : ''} ${className}`}>
      <div
        onClick={() => !disabled && setOpen((v) => !v)}
        onMouseEnter={() => setHover(true)}
        onMouseLeave={() => setHover(false)}
        onKeyDown={onKeyDown}
        tabIndex={0}
        role="combobox"
        aria-expanded={open}
        aria-haspopup="listbox"
        className={`w-full ${size === 'small' ? 'h-7 text-xs' : 'h-8 text-xs'} px-2.5
          rounded-md border border-line bg-page flex items-center justify-between gap-1 cursor-pointer
          text-ink hover:border-[#1E5EFF] focus:outline-none focus:border-[#1E5EFF] focus:ring-1 focus:ring-[#1E5EFF]/30 transition-colors`}
      >
        <span className={`flex-1 min-w-0 truncate ${value ? '' : 'text-ink-dim'}`}>
          {displayNode ?? placeholder}
        </span>
        {allowClear && hover && value ? (
          <X
            className="w-3 h-3 text-ink-dim hover:text-ink shrink-0"
            onClick={(e) => {
              e.stopPropagation()
              onChange?.(null)
              setOpen(false)
            }}
          />
        ) : (
          <svg className={`w-3 h-3 text-ink-dim shrink-0 transition-transform ${open ? 'rotate-180' : ''}`} viewBox="0 0 12 12" fill="none">
            <path d="M3 4.5L6 7.5L9 4.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        )}
      </div>
      {open && createPortal(
        <div
          ref={panelRef}
          style={panelCoords
            ? { position: 'fixed', top: panelCoords.top, left: panelCoords.left, width: panelCoords.width, zIndex: 9999 }
            : { position: 'fixed', top: -9999, left: -9999, visibility: 'hidden' }}
          className="rounded-md border border-line bg-panel shadow-lg overflow-hidden"
        >
          {showSearch && (
            <div className="p-1.5 border-b border-line">
              <input
                ref={searchRef}
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value)
                  setActiveIndex(flatFiltered.findIndex((o) => !o.disabled))
                }}
                onKeyDown={onKeyDown}
                placeholder="搜索…"
                className="w-full h-7 px-2 rounded bg-page border border-line text-xs text-ink
                  placeholder:text-ink-dim focus:outline-none focus:border-[#1E5EFF]"
              />
            </div>
          )}
          <div ref={listRef} role="listbox" className="max-h-56 overflow-y-auto py-0.5">
            {!hasMatch ? (
              <div className="px-2.5 py-2 text-[11px] text-ink-dim text-center">无匹配项</div>
            ) : (
              (() => {
                let idx = -1
                return filteredGroups.map((g, gi) => (
                  <div key={gi}>
                    {g.label && (
                      <div className="px-2.5 pt-1.5 pb-0.5 text-[11px] uppercase tracking-wider font-bold text-ink-dim">
                        {g.label}
                      </div>
                    )}
                    {g.options.map((opt) => {
                      idx += 1
                      const myIdx = idx
                      const isSelected = opt.value === value
                      const isActive = myIdx === activeIndex
                      return (
                        <div
                          key={opt.value}
                          data-idx={myIdx}
                          role="option"
                          aria-selected={isSelected}
                          onClick={() => {
                            if (opt.disabled) return
                            onChange?.(opt.value)
                            setOpen(false)
                          }}
                          onMouseEnter={() => setActiveIndex(myIdx)}
                          className={`px-2.5 py-1.5 text-xs cursor-pointer flex items-start gap-1.5 text-ink
                            ${opt.disabled ? 'opacity-40 cursor-not-allowed' : ''}
                            ${isActive && !opt.disabled ? 'bg-[#1E5EFF]/10' : ''}
                            ${isSelected ? 'text-link font-medium' : ''}`}
                        >
                          {opt.icon && <span className="shrink-0 mt-0.5">{opt.icon}</span>}
                          <span className="min-w-0 flex-1">
                            <span className="block truncate">{opt.label}</span>
                            {opt.description && (
                              <span className="block text-[11px] text-ink-dim truncate">{opt.description}</span>
                            )}
                          </span>
                          {isSelected && (
                            <svg className="w-3 h-3 text-link shrink-0 mt-0.5" viewBox="0 0 12 12" fill="none">
                              <path d="M2.5 6.5L5 9L9.5 3.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
                            </svg>
                          )}
                        </div>
                      )
                    })}
                  </div>
                ))
              })()
            )}
          </div>
        </div>,
        portalTarget ?? document.body,
      )}
    </div>
  )
}

/* ─── Button ─── */

interface ButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'type'> {
  type?: 'default' | 'primary' | 'dashed' | 'link' | 'text'
  danger?: boolean
  size?: 'small' | 'middle' | 'large'
  icon?: ReactNode
  loading?: boolean
}

const BTN_SIZE: Record<NonNullable<ButtonProps['size']>, string> = {
  small: 'h-7 text-[11px] px-2 gap-1',
  middle: 'h-8 text-xs px-3 gap-1.5',
  large: 'h-10 text-sm px-4 gap-1.5',
}

const BTN_TYPE: Record<NonNullable<ButtonProps['type']>, string> = {
  default: 'bg-panel border border-line text-ink hover:border-[#1E5EFF] hover:text-link',
  primary: 'bg-[#1E5EFF] border border-[#1E5EFF] text-white hover:bg-[#1a4fd6]',
  dashed: 'bg-panel/40 border border-dashed border-line text-ink hover:border-[#1E5EFF] hover:text-link',
  link: 'bg-transparent border-0 text-link hover:underline px-1',
  text: 'bg-transparent border-0 text-slate-400 hover:bg-page/60 px-1.5',
}

export function Button({
  type = 'default',
  danger = false,
  size = 'middle',
  icon,
  loading = false,
  className = '',
  children,
  disabled,
  ...rest
}: ButtonProps) {
  const dangerClass = danger
    ? type === 'text' || type === 'link'
      ? 'text-red-500 hover:text-red-600'
      : 'bg-red-500 border-red-500 text-white hover:bg-red-600 border-red-600'
    : ''
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={`inline-flex items-center justify-center rounded-md font-medium cursor-pointer transition-colors
        disabled:opacity-50 disabled:cursor-not-allowed select-none
        ${BTN_SIZE[size]} ${danger ? dangerClass : BTN_TYPE[type]} ${className}`}
    >
      {loading ? (
        <svg className="w-3.5 h-3.5 animate-spin" viewBox="0 0 24 24" fill="none">
          <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" strokeDasharray="40 60" />
        </svg>
      ) : (
        icon
      )}
      {children}
    </button>
  )
}

/* ─── Modal ─── */

interface ModalProps {
  open: boolean
  title?: ReactNode
  onOk?: () => void
  onCancel?: () => void
  okText?: string
  cancelText?: string
  width?: number
  /** okButtonProps.danger: 确定按钮用红色（如删除确认） */
  okButtonProps?: { disabled?: boolean; danger?: boolean }
  destroyOnClose?: boolean
  children?: ReactNode
}

export function Modal({
  open,
  title,
  onOk,
  onCancel,
  okText = '确定',
  cancelText = '取消',
  width = 420,
  okButtonProps,
  children,
}: ModalProps) {
  if (!open) return null
  // Portal 到 body：Modal 常在可点击容器内弹出（如看板卡的审批弹窗）——
  // 原地渲染时 position:fixed 只是视觉浮层，React 合成事件仍沿原 DOM 树
  // 冒泡，点击弹窗内输入框会触发宿主容器（卡片）的 onClick（误跳详情）。
  // 与本文件其他浮层组件（Select/Confirm 等）一致走 createPortal。
  // 点遮罩不关闭：只能手动关闭（✕/取消/确定），防误触丢表单内容。
  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center"
      onClick={(e) => e.stopPropagation()}
    >
      <div
        style={{ width, maxWidth: 'calc(100vw - 2rem)' }}
        className="bg-panel rounded-xl shadow-2xl max-h-[85vh] flex flex-col border border-line"
      >
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-line">
          <span className="text-sm font-medium text-ink truncate min-w-0">{title}</span>
          <X className="w-4 h-4 text-ink-dim cursor-pointer hover:text-ink" onClick={onCancel} />
        </div>
        <div className="px-5 py-4 overflow-y-auto flex-1">{children}</div>
        <div className="flex justify-end gap-2 px-5 py-3 border-t border-line">
          <Button onClick={onCancel}>{cancelText}</Button>
          <Button
            type="primary"
            onClick={onOk}
            disabled={okButtonProps?.disabled}
            danger={okButtonProps?.danger}
          >
            {okText}
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  )
}

/* ─── Switch ─── */

interface SwitchProps {
  size?: 'small' | 'default'
  checked?: boolean
  disabled?: boolean
  onChange?: (checked: boolean) => void
}

export function Switch({ size = 'default', checked = false, disabled = false, onChange }: SwitchProps) {
  const w = size === 'small' ? 'w-7 h-4' : 'w-9 h-5'
  const knob = size === 'small' ? 'w-3 h-3' : 'w-4 h-4'
  const offset = size === 'small' ? (checked ? 'translate-x-3' : 'translate-x-0.5') : (checked ? 'translate-x-4' : 'translate-x-0.5')
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => onChange?.(!checked)}
      className={`${w} rounded-full transition-colors flex items-center
        ${checked ? 'bg-[#1E5EFF]' : 'bg-line'}
        ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
    >
      {/* Knob stays white for contrast on the colored track in both themes */}
      <span className={`${knob} bg-white rounded-full shadow-sm transition-transform ${offset}`} />
    </button>
  )
}

/* ─── Tag ─── */

interface TagProps {
  color?: string
  closable?: boolean
  onClose?: () => void
  className?: string
  children?: ReactNode
  onClick?: () => void
}

const TAG_PRESETS: Record<string, string> = {
  blue: 'bg-blue-500/10 text-blue-400',
  processing: 'bg-blue-500/10 text-blue-400',
  success: 'bg-green-500/10 text-green-400',
  green: 'bg-green-500/10 text-green-400',
  warning: 'bg-amber-500/10 text-amber-400',
  error: 'bg-red-500/10 text-red-400',
  red: 'bg-red-500/10 text-red-400',
  orange: 'bg-orange-500/10 text-orange-400',
  purple: 'bg-purple-500/10 text-purple-400',
  cyan: 'bg-cyan-500/10 text-cyan-400',
  default: 'bg-panel text-slate-400',
}

export function Tag({ color, closable, onClose, className = '', children, onClick }: TagProps) {
  const preset = color && TAG_PRESETS[color] ? TAG_PRESETS[color] : ''
  // Custom hex color → inline badge style
  const isHex = color && /^#[0-9A-Fa-f]{3,8}$/.test(color)
  return (
    <span
      onClick={onClick}
      className={`inline-flex items-center gap-0.5 px-1.5 py-0 rounded text-[11px] leading-tight
        ${onClick ? 'cursor-pointer' : ''} ${preset || 'bg-panel text-slate-400'} ${className}`}
      style={
        isHex
          ? { backgroundColor: `${color}1A`, color }
          : undefined
      }
    >
      {children}
      {closable && (
        <X
          className="w-2.5 h-2.5 hover:opacity-70"
          onClick={(e) => {
            e.stopPropagation()
            onClose?.()
          }}
        />
      )}
    </span>
  )
}

/* ─── Tooltip / Popover ─── */

interface TooltipProps {
  title: ReactNode
  placement?: string
  children: ReactNode
}

/** Tooltip：触发器上方居中，跟随滚动/缩放。 */
const TOOLTIP_PLACEMENT: PanelPlacement = { side: 'top', align: 'center', gap: 6, fallbackW: 160, follow: true }

export function Tooltip({ title, children }: TooltipProps) {
  const [show, setShow] = useState(false)
  const triggerRef = useRef<HTMLSpanElement>(null)
  const tipRef = useRef<HTMLDivElement>(null)
  const { coords, portalTarget, measure } = usePanelPosition(triggerRef, tipRef, show, TOOLTIP_PLACEMENT)

  // 内容/文本变化后拿到真实尺寸再做边界翻转（paint 前同步，避免闪烁）
  useLayoutEffect(() => {
    if (!show) return
    measure()
  }, [show, measure, title])

  return (
    <span
      ref={triggerRef}
      className="relative inline-flex"
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
    >
      {children}
      {show &&
        title &&
        createPortal(
          <div
            ref={tipRef}
            style={
              coords
                ? { position: 'fixed', top: coords.top, left: coords.left, zIndex: 210 }
                : { position: 'fixed', left: -9999, top: -9999, visibility: 'hidden', zIndex: 210 }
            }
            className="px-2.5 py-1.5 rounded bg-panel border border-line text-ink
              text-[11px] whitespace-pre-wrap max-w-xs max-h-[70vh] overflow-hidden shadow-lg leading-relaxed pointer-events-none"
          >
            {title}
          </div>,
          portalTarget ?? document.body,
        )}
    </span>
  )
}

interface PopoverProps {
  content: ReactNode
  title?: ReactNode
  trigger?: 'click' | 'hover'
  open?: boolean
  onOpenChange?: (open: boolean) => void
  placement?: string
  children: ReactNode
}

/** Popover：触发器下方展开、右缘对齐，跟随滚动/缩放。 */
const POPOVER_PLACEMENT: PanelPlacement = { side: 'bottom', align: 'end', gap: 4, fallbackW: 240, follow: true }

export function Popover({ content, title, trigger = 'hover', open, onOpenChange, children }: PopoverProps) {
  const [internalOpen, setInternalOpen] = useState(false)
  const isControlled = open !== undefined
  const isOpen = isControlled ? open : internalOpen

  const triggerRef = useRef<HTMLDivElement>(null)
  const popoverRef = useRef<HTMLDivElement>(null)
  const closeTimer = useRef<number | null>(null)
  const { coords, portalTarget, measure } = usePanelPosition(triggerRef, popoverRef, isOpen, POPOVER_PLACEMENT)

  const toggle = (next: boolean) => {
    if (isControlled) onOpenChange?.(next)
    else setInternalOpen(next)
  }

  const clearCloseTimer = () => {
    if (closeTimer.current !== null) {
      clearTimeout(closeTimer.current)
      closeTimer.current = null
    }
  }
  const scheduleClose = () => {
    clearCloseTimer()
    closeTimer.current = window.setTimeout(() => toggle(false), 120)
  }

  // 浮层挂载/内容变化后拿到真实尺寸再做边界翻转（paint 前同步，避免闪烁）
  useLayoutEffect(() => {
    if (!isOpen) return
    measure()
  }, [isOpen, measure, content, title])

  useEffect(() => () => clearCloseTimer(), [])

  // click 模式：点外部关闭（portal 浮层纳入判断，避免点浮层被误判为 outside）
  useEffect(() => {
    if (!isOpen || trigger !== 'click') return
    const handler = (e: MouseEvent) => {
      const t = e.target as Node
      if (
        (triggerRef.current && triggerRef.current.contains(t)) ||
        (popoverRef.current && popoverRef.current.contains(t))
      ) {
        return
      }
      if (isControlled) onOpenChange?.(false)
      else setInternalOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [isOpen, trigger, isControlled, onOpenChange])

  const isHover = trigger === 'hover'
  const triggerProps = isHover
    ? {
        onMouseEnter: () => {
          clearCloseTimer()
          toggle(true)
        },
        onMouseLeave: scheduleClose,
      }
    : {
        onClick: (e: React.MouseEvent) => {
          // 浮层经 portal 渲染，React 合成事件仍沿虚拟树冒泡到触发器——
          // 真实 DOM 不在 triggerRef 内的点击（即浮层内部）不切换开合
          const t = e.target as Node
          if (triggerRef.current && !triggerRef.current.contains(t)) return
          toggle(!isOpen)
        },
      }

  return (
    <div ref={triggerRef} className="relative inline-flex" {...triggerProps}>
      {children}
      {isOpen &&
        createPortal(
          <div
            ref={popoverRef}
            style={
              coords
                ? { position: 'fixed', top: coords.top, left: coords.left, zIndex: 200 }
                : { position: 'fixed', left: -9999, top: -9999, visibility: 'hidden', zIndex: 200 }
            }
            className="min-w-[220px] max-w-[360px] max-h-[80vh] overflow-y-auto bg-panel rounded-lg shadow-xl border border-line"
            {...(isHover
              ? { onMouseEnter: clearCloseTimer, onMouseLeave: scheduleClose }
              : {})}
          >
            {title && (
              <div className="px-3 py-2 border-b border-line text-xs font-medium text-ink">
                {title}
              </div>
            )}
            <div className="p-2.5">{content}</div>
          </div>,
          portalTarget ?? document.body,
        )}
    </div>
  )
}

/* ─── Badge ─── */

interface BadgeProps {
  count?: number
  size?: 'small' | 'default'
  className?: string
  style?: CSSProperties
  children?: ReactNode
}

export function Badge({ count, size = 'default', className = '', style, children }: BadgeProps) {
  const dot = size === 'small' ? 'min-w-[14px] h-[14px] text-[11px]' : 'min-w-[18px] h-[18px] text-[11px]'
  return (
    <span className={`relative inline-flex ${className}`}>
      {children}
      {count !== undefined && count > 0 && (
        <span
          className={`absolute -top-1 -right-1 ${dot} px-1 flex items-center justify-center
            rounded-full text-white font-medium leading-none`}
          style={{ backgroundColor: '#3B82F6', ...style }}
        >
          {count > 99 ? '99+' : count}
        </span>
      )}
    </span>
  )
}

/* ─── Spin ─── */

interface SpinProps {
  size?: 'small' | 'default' | 'large'
  className?: string
}

export function Spin({ size = 'default', className = '' }: SpinProps) {
  const s = size === 'small' ? 'w-3.5 h-3.5' : size === 'large' ? 'w-7 h-7' : 'w-5 h-5'
  return (
    <svg className={`${s} animate-spin text-link ${className}`} viewBox="0 0 24 24" fill="none">
      <circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="3" className="opacity-25" />
      <path d="M12 2a10 10 0 0110 10" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
    </svg>
  )
}

/* ─── Popconfirm ─── */

interface PopconfirmProps {
  title: ReactNode
  description?: ReactNode
  onConfirm?: () => void
  okText?: string
  cancelText?: string
  okButtonProps?: { danger?: boolean }
  children: ReactNode
}

export function Popconfirm({
  title,
  description,
  onConfirm,
  okText = '确定',
  cancelText = '取消',
  okButtonProps,
  children,
}: PopconfirmProps) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  return (
    <div ref={ref} className="relative inline-flex w-full">
      <span onClick={() => setOpen((v) => !v)} className="inline-flex w-full">
        {children}
      </span>
      {open && (
        <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 z-40 w-56 max-h-[70vh] overflow-y-auto bg-panel rounded-lg shadow-xl border border-line">
          <div className="px-3.5 py-3">
            <div className="text-xs font-medium text-ink">{title}</div>
            {description && <div className="text-[11px] text-slate-400 mt-1">{description}</div>}
            <div className="flex justify-end gap-2 mt-3">
              <Button size="small" onClick={() => setOpen(false)}>
                {cancelText}
              </Button>
              <Button
                size="small"
                type="primary"
                danger={okButtonProps?.danger}
                onClick={() => {
                  onConfirm?.()
                  setOpen(false)
                }}
              >
                {okText}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

/* ─── Table ─── */

export interface TableColumn<T> {
  title: ReactNode
  dataIndex?: string
  key: string
  width?: number | string
  render?: (value: unknown, record: T, index: number) => ReactNode
}

interface TableProps<T> {
  dataSource: T[]
  columns: TableColumn<T>[]
  rowKey?: string | ((record: T) => string)
  pagination?: false
  size?: 'small' | 'middle'
  className?: string
  rowClassName?: (record: T, index: number) => string
}

export function Table<T extends Record<string, unknown>>({
  dataSource,
  columns,
  rowKey = 'id',
  size = 'middle',
  className = '',
  rowClassName,
}: TableProps<T>) {
  const pad = size === 'small' ? 'px-2 py-1.5' : 'px-3 py-2'
  const getKey = (record: T, index: number): string => {
    if (typeof rowKey === 'function') return rowKey(record)
    const v = record[rowKey]
    return v !== undefined && v !== null ? String(v) : String(index)
  }
  return (
    <div className={`overflow-x-auto border border-line rounded-lg ${className}`}>
      <table className="w-full text-xs">
        <thead>
          <tr className="bg-page/60 border-b border-line">
            {columns.map((col) => (
              <th
                key={col.key}
                style={{ width: col.width }}
                className={`${pad} text-left font-medium text-slate-400 whitespace-nowrap`}
              >
                {col.title}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {dataSource.length === 0 ? (
            <tr>
              <td colSpan={columns.length} className={`${pad} text-center text-ink-dim`}>
                暂无数据
              </td>
            </tr>
          ) : (
            dataSource.map((record, index) => (
              <tr
                key={getKey(record, index)}
                className={`border-b border-line/60 last:border-0 hover:bg-page/40 ${
                  rowClassName ? rowClassName(record, index) : ''
                }`}
              >
                {columns.map((col) => {
                  const val = col.dataIndex ? record[col.dataIndex] : undefined
                  return (
                    <td key={col.key} className={`${pad} text-slate-300 align-top`}>
                      {col.render ? col.render(val, record, index) : (val as ReactNode)}
                    </td>
                  )
                })}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  )
}

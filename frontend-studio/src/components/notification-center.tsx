/**
 * NotificationCenter — 侧栏 logo 行铃铛 + 未读徽标 + 通知面板。
 *
 * 形态对齐设计定稿（docs/design-mockups/misc-pages.html「通知中心 Popover」+
 * global-sidebar-redesign.html 改版稿）：
 *   - 面板在主目录（侧栏）右侧展开，不遮侧栏导航。ui/Popover 的 PanelPlacement
 *     仅支持 top/bottom 展开，这里自管 fixed 定位：portal 到主题根（与
 *     ui/usePanelPosition 同理——脱离祖先 overflow:hidden 且留在主题作用域内），
 *     侧栏右缘 +8、顶与铃铛对齐；窄视口放不下时回退贴视口右缘并隐藏箭头。
 *   - 下划线 tabs（全部/任务/待审批/系统）+ 彩色软底图标芯片条目；
 *     未读 = 标题后 6px 品牌点（非整行淡底）；相对时间（mono）。
 *   - 图标芯片用信号色 soft 淡底 + lucide 线性图标（规范红线：无 emoji 图标）。
 */
import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Bell, Check, Clock, Info, Pause, X } from 'lucide-react'
import { Badge, Button } from './ui'
import { useNotificationStore } from '../stores/notification-store'
import type { NotificationItem } from '../services/notifications-api'

/** 面板宽度（紧凑版改稿；同步维护 place() 内的视口回退计算） */
const PANEL_W = 288

// kind → 图标芯片配色（信号色 soft 淡底，DESIGN_SYSTEM v4 token）
const KIND_META: Record<string, { icon: typeof Bell; bg: string; fg: string }> = {
  task_failed: { icon: X, bg: 'rgba(217,58,63,.08)', fg: '#D93A3F' },
  task_waiting_human: { icon: Pause, bg: 'rgba(176,125,26,.1)', fg: '#B07D1A' },
  task_completed: { icon: Check, bg: 'rgba(31,157,85,.1)', fg: '#1F9D55' },
  task_slow: { icon: Clock, bg: 'rgba(43,74,158,.08)', fg: '#2B4A9E' },
}
const KIND_DEFAULT = { icon: Info, bg: '#EDF0F5', fg: '#666E7D' }

type Tab = 'all' | 'task' | 'waiting' | 'system'
const TABS: { id: Tab; label: string }[] = [
  { id: 'all', label: '全部' },
  { id: 'task', label: '任务' },
  { id: 'waiting', label: '待审批' },
  { id: 'system', label: '系统' },
]

function matchTab(item: NotificationItem, tab: Tab): boolean {
  if (tab === 'all') return true
  if (tab === 'task') return item.kind.startsWith('task')
  if (tab === 'waiting') return item.kind === 'task_waiting_human'
  return !item.kind.startsWith('task')
}

/** 相对时间（定稿形态）：刚刚 / N 分钟前 / N 小时前 / 昨天 HH:mm / MM-DD */
function relTime(iso: string): string {
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return ''
  const diff = Date.now() - t
  if (diff < 60_000) return '刚刚'
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} 分钟前`
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} 小时前`
  const d = new Date(t)
  const hm = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  if (diff < 172_800_000) return `昨天 ${hm}`
  return `${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

interface NotificationCenterProps {
  /** Called when a notification with a related task is clicked. App injects
   * setActiveTab('board') + the highlight mechanism. */
  onNavigateTask?: (taskId: string) => void
}

function NotificationRow({
  item,
  onNavigateTask,
}: {
  item: NotificationItem
  onNavigateTask?: (taskId: string) => void
}) {
  const markAsRead = useNotificationStore((s) => s.markAsRead)
  const meta = KIND_META[item.kind] ?? KIND_DEFAULT
  const Ic = meta.icon

  const handleClick = () => {
    if (!item.read) {
      markAsRead(item.id)
    }
    if (item.related_task_id) {
      onNavigateTask?.(item.related_task_id)
    }
  }

  return (
    <div
      className="flex gap-2 px-3.5 py-2 border-b border-line last:border-b-0 cursor-pointer hover:bg-raise transition-colors"
      onClick={handleClick}
    >
      <span
        className="mt-px w-6 h-6 rounded-md flex items-center justify-center shrink-0"
        style={{ backgroundColor: meta.bg, color: meta.fg }}
      >
        <Ic className="w-3 h-3" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-xs font-semibold text-ink truncate leading-tight">
          {item.title}
          {!item.read && (
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-brand ml-1.5 align-[2px]" />
          )}
        </div>
        <div className="text-[10.5px] text-ink-dim truncate mt-0.5 leading-normal">{item.body}</div>
        <div className="font-mono text-[9px] text-ink-faint mt-0.5">{relTime(item.created_at)}</div>
      </div>
    </div>
  )
}

export function NotificationCenter({ onNavigateTask }: NotificationCenterProps) {
  const [open, setOpen] = useState(false)
  const [tab, setTab] = useState<Tab>('all')
  const { notifications, unreadCount, loadFromApi, markAllAsRead } = useNotificationStore()

  const btnRef = useRef<HTMLDivElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const [host, setHost] = useState<HTMLElement | null>(null)
  const [coords, setCoords] = useState<{ top: number; left: number; arrow: boolean } | null>(null)

  // host 在「打开时」查询而非 mount 时：主题类由 App useEffect 挂到 <html>，
  // 子组件 effect 先于父组件执行，mount 时查询必然为 null（生产无 StrictMode
  // 双跑兜底，服务器上表现为面板永远不渲染）。token 变量在 :root，body 兜底安全。
  useEffect(() => {
    if (!open) return
    setHost(document.querySelector<HTMLElement>('.theme-light, .theme-dark') ?? document.body)
  }, [open])

  useEffect(() => {
    if (open) {
      loadFromApi()
    }
  }, [open, loadFromApi])

  // 落位：主目录（#af-sidebar，见 ChatSidebar 根节点）右侧展开；顶与铃铛对齐。
  // 面板宽度固定，无需实测尺寸即可计算。
  const place = useCallback(() => {
    const btn = btnRef.current
    if (!btn) return
    const r = btn.getBoundingClientRect()
    const sb = document.getElementById('af-sidebar')?.getBoundingClientRect()
    const maxLeft = window.innerWidth - PANEL_W - 8
    const rightEdge = (sb ? sb.right : r.right) + 8
    const atRight = rightEdge <= maxLeft
    const top = Math.min(Math.max(8, r.top - 6), window.innerHeight - 60)
    setCoords({ top, left: atRight ? rightEdge : Math.max(8, maxLeft), arrow: atRight })
  }, [])

  useLayoutEffect(() => {
    if (open) place()
  }, [open, place])

  // 打开期间跟随窗口缩放/滚动（与 ui/Popover 的 follow 行为一致）
  useEffect(() => {
    if (!open) return
    place()
    window.addEventListener('resize', place)
    window.addEventListener('scroll', place, true)
    return () => {
      window.removeEventListener('resize', place)
      window.removeEventListener('scroll', place, true)
    }
  }, [open, place])

  // 点击外部关闭（portal 面板纳入判断）
  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      const t = e.target as Node
      if (btnRef.current?.contains(t) || panelRef.current?.contains(t)) return
      setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  // 跳转前先收面板：不关的话面板悬浮在新页面上方，拦截下层点击
  const handleNavigate = useCallback(
    (taskId: string) => {
      setOpen(false)
      onNavigateTask?.(taskId)
    },
    [onNavigateTask],
  )

  const filtered = notifications.filter((n) => matchTab(n, tab))
  const waitingCount = notifications.filter(
    (n) => n.kind === 'task_waiting_human' && !n.read,
  ).length

  return (
    <div ref={btnRef} className="relative inline-flex">
      <Badge count={unreadCount} size="small" style={{ backgroundColor: '#D93A3F' }}>
        <button
          type="button"
          title="通知"
          onClick={() => setOpen((v) => !v)}
          className="w-[30px] h-[30px] rounded-[9px] flex items-center justify-center text-ink-dim hover:bg-panel hover:text-ink hover:shadow-[var(--shadow-card)] cursor-pointer transition-colors"
        >
          <Bell className="w-4 h-4" />
        </button>
      </Badge>

      {open &&
        host &&
        createPortal(
          <div
            ref={panelRef}
            style={
              coords
                ? { position: 'fixed', top: coords.top, left: coords.left, zIndex: 210 }
                : { position: 'fixed', left: -9999, top: -9999, visibility: 'hidden', zIndex: 210 }
            }
            className="w-[288px] max-h-[calc(100vh-120px)] flex flex-col bg-panel border border-line rounded-[14px] shadow-[var(--shadow-pop)] overflow-hidden"
          >
            {/* 左缘箭头指向铃铛；窄视口回退盖住侧栏时隐藏 */}
            {coords?.arrow && (
              <span
                aria-hidden
                className="absolute w-[11px] h-[11px] bg-panel border-l border-t border-line rotate-45"
                style={{ top: 19, left: -5.5 }}
              />
            )}
            {/* 头部：通知 + 全部已读 */}
            <div className="flex items-center gap-2 px-3.5 pt-3 pb-2 border-b border-line shrink-0">
              <span className="text-[12.5px] font-bold text-ink">通知</span>
              {unreadCount > 0 && (
                <Button
                  type="link"
                  size="small"
                  className="ml-auto"
                  icon={<Check className="w-3 h-3" />}
                  onClick={() => markAllAsRead()}
                >
                  全部已读
                </Button>
              )}
            </div>
            {/* 下划线 tabs */}
            <div className="flex gap-3.5 px-3.5 border-b border-line shrink-0">
              {TABS.map(({ id, label }) => {
                const on = id === tab
                return (
                  <button
                    key={id}
                    type="button"
                    onClick={() => setTab(id)}
                    className={`pt-1.5 pb-1 -mb-px text-[11px] border-b-2 cursor-pointer transition-colors ${
                      on ? 'text-brand font-bold border-brand' : 'text-ink-dim border-transparent hover:text-ink'
                    }`}
                  >
                    {label}
                    {id === 'waiting' && waitingCount > 0 && (
                      <span className="ml-0.5 font-bold text-sig-wait">{waitingCount}</span>
                    )}
                  </button>
                )
              })}
            </div>
            {/* 列表：限高 240px（约 4 条）内部滚动，面板高度不随条目数膨胀 */}
            <div className="flex-1 min-h-0 overflow-y-auto max-h-[240px]">
              {filtered.length === 0 ? (
                <div className="py-6 text-center text-xs text-ink-faint">暂无通知</div>
              ) : (
                filtered.map((item) => (
                  <NotificationRow key={item.id} item={item} onNavigateTask={handleNavigate} />
                ))
              )}
            </div>
          </div>,
          host,
        )}
    </div>
  )
}

export default NotificationCenter

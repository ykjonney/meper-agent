/**
 * ChatSidebar — 融合侧栏（全局常驻，所有页面共用）。
 *
 * 设计（sidebar-more.html + 会话主页定稿）：
 * - logo：产品图标 + 衬线字标，点击回会话主页
 * - 功能 4 项（App 权限导航派生，选中 = 白底卡 + 靛蓝左条）
 * - 图钉固定项（📌 固定的导航追加在主功能之后，hover ✕ 取消，localStorage 持久化）
 * - 会话历史：时间分组（今天/近7天/更早），节标题标注 Agent 归属，首组带 ＋
 * - 空态按场景区分：聊天页引导下方输入 / 其它页给「＋ 开始新会话」
 * - 底部：通知铃铛（未读徽章）+ 用户条（头像菜单：个人设置/登出）+ 更改（功能分组+图钉）
 */
import { useEffect, useRef, useState, type ReactNode } from 'react'
import {
  Bell, CheckCircle, ChevronDown, ChevronRight, FileText, Trash2,
  LayoutDashboard, Mic, Plus, Shield, Link2, ArrowLeftRight, Key,
} from 'lucide-react'
import type { Agent } from '../../types'
import type { Session } from '../../services/session-api'
import AvatarRender from '../AvatarRender'
import NotificationCenter from '../notification-center'

/** 侧栏主要功能 4 项（其余导航项收纳进「更改」菜单）。 */
const PRIMARY_NAV: { id: string; label: string; Icon: (p: { size?: number; className?: string }) => ReactNode }[] = [
  { id: 'agents', label: '智能体', Icon: (p) => BotIcon(p) },
  { id: 'board', label: '任务', Icon: (p) => TaskIcon(p) },
  { id: 'workflows', label: '工作流', Icon: (p) => FlowIcon(p) },
  { id: 'resource', label: '资源库', Icon: (p) => ResIcon(p) },
]
function BotIcon({ size, className }: { size?: number; className?: string }) {
  return (
    <svg width={size ?? 15} height={size ?? 15} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.4" className={className}>
      <path d="M10 2 L16.5 4.5 V10 C16.5 14.5 13.8 17 10 18.3 C6.2 17 3.5 14.5 3.5 10 V4.5 Z" />
      <circle cx="10" cy="10" r="2.2" fill="currentColor" stroke="none" />
    </svg>
  )
}
function TaskIcon({ size, className }: { size?: number; className?: string }) {
  return (
    <svg width={size ?? 15} height={size ?? 15} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.4">
      <rect x="3" y="3" width="14" height="14" rx="2.5" />
      <path d="M6.5 7.5 H13.5 M6.5 12.5 H10" strokeLinecap="round" />
    </svg>
  )
}
function FlowIcon({ size, className }: { size?: number; className?: string }) {
  return (
    <svg width={size ?? 15} height={size ?? 15} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.4">
      <path d="M3 6 C5 4 7 4 9 6 C11 8 13 8 15 6 M3 12 C5 10 7 10 9 12 C11 14 13 14 15 12" strokeLinecap="round" />
    </svg>
  )
}
function ResIcon({ size, className }: { size?: number; className?: string }) {
  return (
    <svg width={size ?? 15} height={size ?? 15} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.4">
      <path d="M10 2 L16.5 5.8 V14.2 L10 18 L3.5 14.2 V5.8 Z" />
      <circle cx="10" cy="10" r="2.6" />
    </svg>
  )
}

/** 「更改」菜单条目图标（与 App NAV_ITEMS 同款 lucide）。 */
const MORE_ICONS: Record<string, (p: { size?: number; className?: string }) => ReactNode> = {
  voice: (p) => MicSvg(p),
  dashboard: (p) => DashSvg(p),
  users: (p) => UsersSvg(p),
  'external-auth': (p) => LinkSvg(p),
  transfer: (p) => TransferSvg(p),
  settings: (p) => KeySvg(p),
}
function MicSvg({ size, className }: { size?: number; className?: string }) {
  return (
    <svg width={size ?? 16} height={size ?? 16} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.4" className={className}>
      <path d="M9 3 C6.5 3 5 4.8 5 7 C5 10 3.5 11.5 3.5 11.5 H14.5 C14.5 11.5 13 10 13 7 C13 4.8 11.5 3 9 3 Z" />
      <path d="M7.8 13.5 A1.3 1.3 0 0 0 10.2 13.5" />
    </svg>
  )
}
function DashSvg({ size, className }: { size?: number; className?: string }) {
  return (
    <svg width={size ?? 16} height={size ?? 16} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.4" className={className}>
      <rect x="3" y="3" width="6" height="6" rx="1.5" />
      <rect x="11" y="3" width="6" height="6" rx="1.5" />
      <rect x="3" y="11" width="6" height="6" rx="1.5" />
      <rect x="11" y="11" width="6" height="6" rx="1.5" />
    </svg>
  )
}
function UsersSvg({ size, className }: { size?: number; className?: string }) {
  return (
    <svg width={size ?? 16} height={size ?? 16} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.4" className={className}>
      <circle cx="7" cy="7" r="3" />
      <path d="M2.5 16 C3 13 5 11.5 7 11.5 C9 11.5 11 13 11.5 16 M13.5 7 L16.5 10 M16.5 7 L13.5 10" />
    </svg>
  )
}
function LinkSvg({ size, className }: { size?: number; className?: string }) {
  return (
    <svg width={size ?? 16} height={size ?? 16} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.4" className={className}>
      <path d="M8 12 L12 8 M9.5 6.5 L11 5 A2.5 2.5 0 0 1 14.5 8.5 L13 10 M10.5 13.5 L9 15 A2.5 2.5 0 0 1 5.5 11.5 L7 10" />
    </svg>
  )
}
function TransferSvg({ size, className }: { size?: number; className?: string }) {
  return (
    <svg width={size ?? 16} height={size ?? 16} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.4" className={className}>
      <path d="M4 6 L10 3 L16 6 V14 L10 17 L4 14 Z M10 10 V17 M4 6 L10 10 L16 6" />
    </svg>
  )
}
function KeySvg({ size, className }: { size?: number; className?: string }) {
  return (
    <svg width={size ?? 16} height={size ?? 16} viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.4" className={className}>
      <circle cx="10" cy="10" r="3" />
      <path d="M10 2.5 V5 M10 15 V17.5 M2.5 10 H5 M15 10 H17.5 M4.7 4.7 L6.5 6.5 M13.5 13.5 L15.3 15.3 M15.3 4.7 L13.5 6.5 M6.5 13.5 L4.7 15.3" />
    </svg>
  )
}

export interface ChatSidebarProps {
  /** 会话列表（时间分组渲染）。 */
  sessions: Session[]
  sessionsLoading: boolean
  agents: Agent[]
  activeAgent?: Agent
  activeSessionId: string | null
  /** App 权限导航项（实时计数派生）。 */
  navItems?: { id: string; label: string; badge?: string }[]
  /** 当前激活 App tab。 */
  activeId?: string
  /** 非聊天路由的右侧内容；null = 聊天面板（决定空态形态）。 */
  activePage: ReactNode | null
  /** 图钉固定项（localStorage 持久化由父级管理）。 */
  pinnedNav: string[]
  onTogglePin: (id: string) => void
  onNavigate: (tab: string) => void
  onSelectSession: (id: string) => void
  onDeleteSession: (e: React.MouseEvent, id: string) => void
  onStartNewWithAgent: (agent: Agent) => void
  userInitial?: string
  username?: string
  onLogout: () => void
  onNavigateTask: (taskId: string) => void
  unreadCount: number
}

export function ChatSidebar({
  sessions, sessionsLoading, agents, activeAgent, activeSessionId,
  navItems, activeId, activePage, pinnedNav, onTogglePin,
  onNavigate, onSelectSession, onDeleteSession, onStartNewWithAgent,
  userInitial, username, onLogout, onNavigateTask, unreadCount,
}: ChatSidebarProps) {
  const [moreMenuOpen, setMoreMenuOpen] = useState(false)
  const [userMenuOpen, setUserMenuOpen] = useState(false)
  const userMenuRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!userMenuOpen) return
    const handler = (e: MouseEvent) => {
      if (userMenuRef.current && !userMenuRef.current.contains(e.target as Node)) {
        setUserMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [userMenuOpen])

  // 时间分组：今天 / 近 7 天 / 更早
  const buckets: { label: string; items: Session[] }[] = [
    { label: '今天', items: [] },
    { label: '近 7 天', items: [] },
    { label: '更早', items: [] },
  ]
  const now = Date.now()
  for (const sess of sessions) {
    const days = (now - new Date(sess.updated_at).getTime()) / 86400000
    ;(days < 1 ? buckets[0] : days < 7 ? buckets[1] : buckets[2]).items.push(sess)
  }
  const agentName = activeAgent?.name
  const fmtSessionTime = (iso: string) => {
    try {
      const d = new Date(iso)
      const diff = now - d.getTime()
      if (diff < 60_000) return '刚刚'
      if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}分钟前`
      if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}小时前`
      return d.toLocaleDateString()
    } catch {
      return ''
    }
  }

  return (
    <div className="flex flex-col h-full min-h-0 relative">
      {/* logo：产品图标 + 衬线字标，点击回到聊天主页 */}
      <div onClick={() => onNavigate?.('chat')} title="回到会话"
        className="px-4 pt-4 pb-3 cursor-pointer select-none w-fit flex items-center gap-2">
        <img src="/AFLogo.png" alt="MEPER Agent"
          className="w-[26px] h-[26px] rounded-[7px] object-contain select-none" draggable={false} />
        <span style={{ fontFamily: 'var(--font-serif)', fontStyle: 'italic', fontSize: 14, fontWeight: 700 }}>
          agent<span className="text-brand" style={{ fontStyle: 'normal' }}>·</span>flow
        </span>
      </div>
      {/* ── 功能入口（主 4 项）── */}
      <div className="px-4 pb-1" style={{ fontSize: 9, letterSpacing: '.16em', color: 'var(--color-ink-faint)' }}>功能</div>
      <div className="px-2 pb-1">
        {PRIMARY_NAV.filter(({ id }) => navItems?.some((n) => n.id === id)).map(({ id, label, Icon }) => {
          const badge = navItems?.find((n) => n.id === id)?.badge
          const isActive = activePage != null && id === activeId
          return (
            <button key={id} onClick={() => onNavigate?.(id)}
              className={`w-full flex items-center gap-[10px] px-3 py-[9px] text-[13px] cursor-pointer transition-colors ${isActive ? 'bg-panel shadow-[var(--shadow-card),inset_2px_0_0_var(--color-brand)]' : 'text-ink hover:bg-panel'}`}>
              <Icon size={15} className="opacity-70" />{label}
              {badge != null && <span className="ml-auto font-mono text-[9.5px] text-ink-faint">{badge}</span>}
            </button>
          )
        })}
        {/* 图钉固定项（设计稿 sidebar-more）：📌 固定的导航追加在主功能之后，hover ✕ 取消 */}
        {pinnedNav.map((id) => {
          const n = navItems?.find((x) => x.id === id)
          if (!n) return null
          const isActive = activePage != null && id === activeId
          return (
            <div key={`pin-${id}`}
              className="w-full flex items-center gap-[10px] px-3 py-[9px] text-[13px] cursor-pointer hover:bg-panel rounded-lg group/pin"
              onClick={() => onNavigate?.(id)}>
              <span className={`truncate ${isActive ? 'text-brand font-semibold' : 'text-ink'}`}>{n.label}</span>
              <span className="ml-auto font-mono text-[9.5px] text-ink-faint shrink-0">{n.badge ?? ''}</span>
              <button
                onClick={(e) => { e.stopPropagation(); onTogglePin(id) }}
                title="取消固定"
                className="ml-1 w-4 h-4 rounded flex items-center justify-center text-ink-faint opacity-0 group-hover/pin:opacity-100 hover:text-sig-fail cursor-pointer text-[10px] shrink-0"
              >✕</button>
            </div>
          )
        })}
      </div>
      <div className="flex-1 min-h-0 overflow-y-auto scrollbar-custom p-2 space-y-1">
        {sessionsLoading && (
          <div className="p-3 text-[11px] text-ink-dim font-mono">加载会话中…</div>
        )}
        {!sessionsLoading && sessions.length === 0 && (
          activePage == null ? (
            /* 聊天页空态：composer 就在下方，引导输入 */
            <div className="p-3 text-[11px] text-ink-dim font-sans">
              暂无会话 · 在下方输入，开始对话
            </div>
          ) : (
            /* 其它功能页空态：开始新会话入口（虚线添加形态） */
            <div className="px-2 pt-1">
              <div className="px-1 pb-2 text-[11px] text-ink-faint">暂无会话</div>
              <button
                onClick={() => { if (activeAgent) onStartNewWithAgent(activeAgent); onNavigate?.('chat') }}
                className="w-full flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg border border-dashed border-line-strong text-ink-dim text-xs cursor-pointer hover:text-brand hover:border-brand transition-colors"
              >
                ＋ 开始新会话
              </button>
            </div>
          )
        )}
        {buckets.filter((b) => b.items.length > 0).map((bucket, bi) => (
          <div key={bucket.label}>
            <div className="flex justify-between items-center px-2.5 pt-3 pb-1" style={{ fontSize: 9, letterSpacing: '.13em', color: 'var(--color-ink-faint)' }}>
              <span>{bucket.label}{agentName ? <> · <span className="text-brand">{agentName}</span></> : null}</span>
              {bi === 0 && (
                <span className="cursor-pointer text-[12px] hover:text-brand"
                  onClick={() => activeAgent && onStartNewWithAgent(activeAgent)}
                  title={`以 ${agentName ?? '当前 Agent'} 开新会话`}>＋</span>
              )}
            </div>
            {bucket.items.map((sess) => {
              const infoAgent = agents.find((a) => a.id === sess.agent_id)
              const isActive = activeSessionId === sess._id
              return (
                <div
                  key={sess._id}
                  onClick={() => onSelectSession(sess._id)}
                  className={`px-2.5 py-[7px] rounded-[7px] transition-all relative group cursor-pointer select-none ${
                    isActive
                      ? 'bg-panel shadow-[var(--shadow-card),inset_2px_0_0_var(--color-brand)]'
                      : 'hover:bg-raise'
                  }`}
                >
                  <span className={`block text-[12.5px] font-medium truncate font-sans leading-snug ${isActive ? 'text-brand' : 'text-ink'}`}>
                    {sess.title || infoAgent?.name || '未命名会话'}
                  </span>
                  <p className="text-[11px] text-ink-faint truncate font-sans leading-relaxed font-mono">
                    {fmtSessionTime(sess.updated_at)} · {sess.message_count ?? 0} 条消息
                  </p>
                  <button
                    onClick={(e) => onDeleteSession(e, sess._id)}
                    className="absolute right-2 bottom-3 opacity-0 group-hover:opacity-100 p-1 text-ink-dim hover:text-sig-fail hover:bg-panel rounded-md transition"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              )
            })}
          </div>
        ))}
      </div>

      {/* ── 底部：通知铃铛 + 用户条 + 更改 ── */}
      <div className="px-3 py-2.5 border-t border-line flex items-center gap-1.5">
        {/* ① 通知（未读徽章 + 通知中心浮层） */}
        <NotificationCenter onNavigateTask={onNavigateTask} />
        {/* ② 用户（brand 圆头像 → 账户菜单；遮罩点击关闭） */}
        <div className="relative">
          <button
            onClick={() => { setUserMenuOpen(v => !v); setMoreMenuOpen(false) }}
            title="账户菜单"
            className="w-8 h-8 rounded-full bg-brand text-white flex items-center justify-center text-[11px] font-bold cursor-pointer hover:opacity-85 transition shrink-0"
          >
            {userInitial ?? 'U'}
          </button>
          {userMenuOpen && (
            <>
              <div className="fixed inset-0 z-30" onClick={() => setUserMenuOpen(false)} />
              <div className="absolute bottom-full left-0 mb-2 w-40 bg-panel border border-line rounded-xl shadow-[var(--shadow-pop)] p-1 z-50 text-xs">
                <button onClick={() => { setUserMenuOpen(false); onNavigate?.('profile') }}
                  className="w-full text-left px-3 py-2 rounded-lg hover:bg-raise text-ink-dim hover:text-ink cursor-pointer">个人设置</button>
                <button onClick={() => { setUserMenuOpen(false); onLogout?.() }}
                  className="w-full text-left px-3 py-2 rounded-lg hover:bg-raise text-sig-fail cursor-pointer">登出</button>
              </div>
            </>
          )}
        </div>
        {/* ③ 更改（··· 更多 → 功能分组 + 图钉固定；条目带图标） */}
        <div className="relative flex-1 min-w-0">
          <button
            onClick={() => { setMoreMenuOpen(v => !v); setUserMenuOpen(false) }}
            className={`w-full flex items-center justify-center gap-2 px-2.5 py-2 rounded-[9px] cursor-pointer transition-all ${
              moreMenuOpen
                ? 'bg-panel text-brand font-bold shadow-[var(--shadow-card)]'
                : 'text-ink-dim hover:bg-panel hover:text-ink'
            }`}
          >
            更改
          </button>
          {moreMenuOpen && (
            <>
              <div className="fixed inset-0 z-30" onClick={() => setMoreMenuOpen(false)} />
              {/* more-pop（设计稿 sidebar-more）：上弹 + 箭头尾巴 + 分组图标 + 图钉固定 */}
              <div className="absolute bottom-full right-0 mb-3 w-[236px] bg-panel border border-line rounded-[14px] shadow-[var(--shadow-pop)] z-40">
                <div className="absolute -bottom-1.5 right-8 w-2.5 h-2.5 bg-panel border-l border-b border-line rotate-45" />
                <div className="px-3.5 pt-3 pb-1 text-[9.5px] font-bold tracking-[.2em] text-ink-faint">工作台</div>
                {(['voice', 'dashboard'] as const).map((id) => {
                  const n = navItems?.find((x) => x.id === id)
                  if (!n) return null
                  const pinned = pinnedNav.includes(id)
                  const Ic = MORE_ICONS[id]
                  return (
                    <div key={id} className="flex items-center gap-2.5 mx-1.5 px-2 py-1.5 rounded-lg text-[12.5px] text-ink-dim hover:bg-raise hover:text-ink cursor-pointer group/mp">
                      <span className="w-[17px] flex items-center justify-center shrink-0 text-ink-dim">{Ic && <Ic size={16} />}</span>
                      <button type="button" className="flex items-center gap-2.5 min-w-0 flex-1 text-left"
                        onClick={() => { setMoreMenuOpen(false); onNavigate?.(id) }}>
                        {n.label}
                        {pinned && <span className="ml-auto text-[9px] text-brand font-bold tracking-[.05em] shrink-0">已固定</span>}
                      </button>
                      <button
                        type="button"
                        title={pinned ? '取消固定' : '固定到侧栏'}
                        onClick={(e) => { e.stopPropagation(); onTogglePin(id) }}
                        className={`shrink-0 w-[18px] h-[18px] rounded-[5px] flex items-center justify-center text-[10px] cursor-pointer transition-opacity ${pinned ? 'text-brand opacity-100' : 'text-ink-faint opacity-0 group-hover/mp:opacity-100 hover:text-brand hover:bg-brand-soft'}`}
                      >
                        📌
                      </button>
                    </div>
                  )
                })}
                <div className="h-px bg-line mx-3.5 my-1.5" />
                <div className="px-3.5 pb-1 text-[9.5px] font-bold tracking-[.2em] text-ink-faint">管理</div>
                {(['users', 'external-auth', 'transfer', 'settings'] as const).map((id) => {
                  const n = navItems?.find((x) => x.id === id)
                  if (!n) return null
                  const pinned = pinnedNav.includes(id)
                  const Ic = MORE_ICONS[id]
                  return (
                    <div key={id} className="flex items-center gap-2.5 mx-1.5 px-2 py-1.5 rounded-lg text-[12.5px] text-ink-dim hover:bg-raise hover:text-ink cursor-pointer group/mp">
                      <span className="w-[17px] flex items-center justify-center shrink-0 text-ink-dim">{Ic && <Ic size={16} />}</span>
                      <button type="button" className="flex items-center gap-2.5 min-w-0 flex-1 text-left"
                        onClick={() => { setMoreMenuOpen(false); onNavigate?.(id) }}>
                        {n.label}
                        {pinned && <span className="ml-auto text-[9px] text-brand font-bold tracking-[.05em] shrink-0">已固定</span>}
                      </button>
                      <button
                        type="button"
                        title={pinned ? '取消固定' : '固定到侧栏'}
                        onClick={(e) => { e.stopPropagation(); onTogglePin(id) }}
                        className={`shrink-0 w-[18px] h-[18px] rounded-[5px] flex items-center justify-center text-[10px] cursor-pointer transition-opacity ${pinned ? 'text-brand opacity-100' : 'text-ink-faint opacity-0 group-hover/mp:opacity-100 hover:text-brand hover:bg-brand-soft'}`}
                      >
                        📌
                      </button>
                    </div>
                  )
                })}
                <div className="h-px bg-line mx-3.5 my-1.5" />
                <div className="flex items-center gap-2.5 mx-1.5 px-2 py-1.5 rounded-lg text-[12.5px] text-ink-dim hover:bg-raise hover:text-ink cursor-pointer"
                  onClick={() => { setMoreMenuOpen(false); onNavigate?.('profile') }}>
                  个人设置
                </div>
                <div className="px-3.5 py-2 text-[9.5px] text-ink-faint border-t border-line mt-1">
                  悬停条目图钉 📌 可固定到侧栏
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

import type { Dispatch, MouseEvent as ReactMouseEvent, ReactNode, RefObject, SetStateAction } from 'react';
import { MoreHorizontal, Pin, Settings, Trash2, X } from 'lucide-react';
import type { Agent } from '../../types';
import type { Session } from '../../services/session-api';
import { NotificationCenter } from '../notification-center';
import { MORE_ICONS, PRIMARY_NAV, clamp, formatSessionTime } from './message-utils';

interface ChatSidebarProps {
  rootRef: RefObject<HTMLDivElement | null>;
  startColDrag: (e: ReactMouseEvent, onMove: (clientX: number) => void) => void;
  setSessW: (w: number) => void;
  navItems?: { id: string; label: string; badge?: string }[];
  activeId?: string;
  activePage?: ReactNode;
  pinnedNav: string[];
  togglePin: (id: string) => void;
  sessions: Session[];
  sessionsLoading: boolean;
  activeSessionId: string | null;
  onSelectSession: (id: string) => void;
  onDeleteSession: (e: ReactMouseEvent, id: string) => void;
  activeAgent: Agent | null;
  agents: Agent[];
  onStartNewWithAgent: (ag: Agent) => void;
  userInitial?: string;
  /** 用户名（底部用户条展示，点头像/用户名上弹账户菜单）。 */
  username?: string;
  userMenuOpen: boolean;
  setUserMenuOpen: Dispatch<SetStateAction<boolean>>;
  moreMenuOpen: boolean;
  setMoreMenuOpen: Dispatch<SetStateAction<boolean>>;
  onNavigate?: (id: string) => void;
  onLogout?: () => void;
  onNavigateTask?: (taskId: string) => void;
}

/** 1. GLOBAL SIDEBAR：功能导航 + 会话历史 —— 全局常驻（App 各页面共用，
 *  非聊天页面由 activePage 渲染在右侧区域，侧栏本身不变）。 */
export function ChatSidebar({
  rootRef, startColDrag, setSessW,
  navItems, activeId, activePage, pinnedNav, togglePin,
  sessions, sessionsLoading, activeSessionId, onSelectSession, onDeleteSession,
  activeAgent, agents, onStartNewWithAgent,
  userInitial, username, userMenuOpen, setUserMenuOpen, moreMenuOpen, setMoreMenuOpen,
  onNavigate, onLogout, onNavigateTask,
}: ChatSidebarProps) {
  // 「更多」菜单可见项（系统设置已移出——由底部齿轮承担）；无可见项则不渲染入口
  const moreIds = ['dashboard', 'users', 'external-auth', 'external-access', 'transfer']
    .filter((id) => navItems?.some((n) => n.id === id));
  return (
    /* id 供 notification-center 定位「主目录右侧展开」的面板锚点，勿删 */
    <div id="af-sidebar" style={{ width: 'var(--sess-w)' }} className="min-h-0 border-r border-line bg-well flex flex-col justify-between h-full shrink-0">
      {/* 右缘拖拽手标：左右拉伸会话列表 */}
      <div
        onMouseDown={(e) => {
          const rect = rootRef.current?.getBoundingClientRect();
          if (!rect) return;
          startColDrag(e, (x) => {
            const w = clamp(x - rect.left, 200, 420);
            setSessW(w);
            localStorage.setItem('agentflow_chat_sess_w', String(w));
          });
        }}
        className="block absolute top-0 bottom-0 w-1 cursor-col-resize hover:bg-brand/40 transition-colors z-10"
        style={{ left: 'calc(var(--sess-w) - 2px)' }}
        title="拖拽调整宽度"
      />
      <div className="flex flex-col h-full min-h-0 relative">
        {/* logo 行：左产品图标 + 衬线字标，右通知铃铛（改版：通知自底部上移，面板在主目录右侧展开） */}
        <div className="px-4 pt-4 pb-3 flex items-center justify-between">
          <div onClick={() => onNavigate?.('chat')} title="回到会话"
            className="cursor-pointer select-none w-fit flex items-center gap-2">
            <img src="/AFLogo.png" alt="MEPER Agent"
              className="w-[26px] h-[26px] rounded-[7px] object-contain select-none" draggable={false} />
            <span style={{ fontFamily: 'var(--font-serif)', fontSize: 14, fontWeight: 700 }}>
              MEPER Agent
            </span>
          </div>
          <NotificationCenter onNavigateTask={onNavigateTask} />
        </div>
        {/* ── 功能入口（主 4 项；按 App 权限过滤，无权限的不显示）── */}
        <div className="px-4 pb-1" style={{ fontSize: 9, letterSpacing: '.16em', color: 'var(--color-ink-faint)' }}>功能</div>
        <div className="px-2 pb-6 flex flex-col gap-0.5">
          {PRIMARY_NAV.filter(({ id }) => navItems?.some((n) => n.id === id)).map(({ id, label, Icon }) => {
            const badge = navItems?.find((n) => n.id === id)?.badge;
            const isActive = activePage != null && id === activeId;
            return (
              <button key={id} onClick={() => onNavigate?.(id)}
                className={`w-full flex items-center gap-[10px] px-3 py-[9px] text-[13px] cursor-pointer transition-colors rounded-lg ${isActive ? 'bg-panel shadow-[var(--shadow-card),inset_2px_0_0_var(--color-brand)]' : 'text-ink hover:bg-panel'}`}>
                <Icon size={15} className="opacity-70" />{label}
                {badge != null && <span className="ml-auto font-mono text-[9.5px] text-ink-faint">{badge}</span>}
              </button>
            );
          })}
          {/* 图钉固定项（设计稿 sidebar-more）：固定的导航追加在主功能之后（与主导航同款
              图标样式），hover ✕ 取消；系统设置由底部齿轮承担，不再可固定。
              mt-1.5 与主功能列表留缝——相邻选中/悬停底色不连成一片 */}
          {pinnedNav.filter((id) => id !== 'settings').length > 0 && (
            <div className="mt-1.5 flex flex-col gap-0.5">
              {pinnedNav.filter((id) => id !== 'settings').map((id) => {
                const n = navItems?.find((x) => x.id === id)
                if (!n) return null
                const isActive = activePage != null && id === activeId
                const Ic = MORE_ICONS[id]
                return (
                  <div key={`pin-${id}`}
                    className={`w-full flex items-center gap-[10px] px-3 py-[9px] text-[13px] cursor-pointer transition-colors rounded-lg group/pin ${isActive ? 'bg-panel shadow-[var(--shadow-card),inset_2px_0_0_var(--color-brand)]' : 'text-ink hover:bg-panel'}`}
                    onClick={() => onNavigate?.(id)}>
                    <span className="opacity-70 shrink-0">{Ic && <Ic size={15} />}</span>
                    <span className="truncate">{n.label}</span>
                    <span className="ml-auto font-mono text-[9.5px] text-ink-faint shrink-0">{n.badge ?? ''}</span>
                    <button
                      onClick={(e) => { e.stopPropagation(); togglePin(id) }}
                      title="取消固定"
                      className="ml-1 w-4 h-4 rounded flex items-center justify-center text-ink-faint opacity-0 group-hover/pin:opacity-100 hover:text-sig-fail cursor-pointer shrink-0"
                    ><X size={10} /></button>
                  </div>
                )
              })}
            </div>
          )}
          {/* 「更多」（改版：自底部上移至功能列表末位，向下弹分组菜单） */}
          {moreIds.length > 0 && (
            <div className="relative">
              <button
                onClick={() => { setMoreMenuOpen(v => !v); setUserMenuOpen(false) }}
                className={`w-full flex items-center gap-[10px] px-3 py-[9px] text-[13px] cursor-pointer transition-colors rounded-lg ${
                  moreMenuOpen
                    ? 'bg-panel text-brand font-bold shadow-[var(--shadow-card)]'
                    : 'text-ink-dim hover:bg-panel hover:text-ink'
                }`}
              >
                <MoreHorizontal size={15} className="opacity-70" />更多
              </button>
              {moreMenuOpen && (
                <>
                  <div className="fixed inset-0 z-30" onClick={() => setMoreMenuOpen(false)} />
                  {/* more-pop（设计稿 sidebar-more / global-sidebar-redesign）：下弹 + 箭头尾巴 + 分组图标 + 图钉固定 */}
                  <div className="absolute top-full left-0 mt-2 w-[236px] bg-panel border border-line rounded-[14px] shadow-[var(--shadow-pop)] z-40">
                    <div className="absolute -top-1.5 left-[22px] w-2.5 h-2.5 bg-panel border-l border-t border-line rotate-45" />
                    <div className="px-3.5 pt-3 pb-1 text-[9.5px] font-bold tracking-[.2em] text-ink-faint">工作台</div>
                    {(['dashboard'] as const).map((id) => {
                      const n = (navItems ?? []).find((x) => x.id === id)
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
                            onClick={(e) => { e.stopPropagation(); togglePin(id) }}
                            className={`shrink-0 w-[18px] h-[18px] rounded-[5px] flex items-center justify-center cursor-pointer transition-opacity ${pinned ? 'text-brand opacity-100' : 'text-ink-faint opacity-0 group-hover/mp:opacity-100 hover:text-brand hover:bg-brand-soft'}`}
                          >
                            <Pin size={11} strokeWidth={2} />
                          </button>
                        </div>
                      )
                    })}
                    <div className="h-px bg-line mx-3.5 my-1.5" />
                    <div className="px-3.5 pb-1 text-[9.5px] font-bold tracking-[.2em] text-ink-faint">管理</div>
                    {(['users', 'external-auth', 'external-access', 'transfer'] as const).map((id) => {
                      const n = (navItems ?? []).find((x) => x.id === id)
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
                            onClick={(e) => { e.stopPropagation(); togglePin(id) }}
                            className={`shrink-0 w-[18px] h-[18px] rounded-[5px] flex items-center justify-center cursor-pointer transition-opacity ${pinned ? 'text-brand opacity-100' : 'text-ink-faint opacity-0 group-hover/mp:opacity-100 hover:text-brand hover:bg-brand-soft'}`}
                          >
                            <Pin size={11} strokeWidth={2} />
                          </button>
                        </div>
                      )
                    })}
                    <div className="h-px bg-line mx-3.5 my-1.5" />
                    <div className="px-3.5 py-2 text-[9.5px] text-ink-faint border-t border-line mt-1">
                      悬停条目出现图钉，可固定到侧栏
                    </div>
                  </div>
                </>
              )}
            </div>
          )}
        </div>

        {/* 会话列表头：与主目录同级的独立固定区（不在滚动容器内——
            sticky 会被滚动条目穿过，结构性分离才彻底） */}
        <div className="flex justify-between items-center px-4 py-1.5 shrink-0">
          <span style={{ fontSize: 9, letterSpacing: '.13em', color: 'var(--color-ink-faint)' }}>会话</span>
          <span
            className="cursor-pointer text-[13px] leading-none text-ink-dim hover:text-brand transition-colors"
            onClick={() => activeAgent && onStartNewWithAgent(activeAgent)}
            title={`以 ${activeAgent?.name ?? '当前 Agent'} 开新会话`}
          >＋</span>
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
              /* 其它功能页空态：开始新会话入口（虚线添加形态，与侧栏设计语言一致） */
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
          {(() => {
            // 时间分组：今天 / 近 7 天 / 更早（节标题标注当前 agent 归属）
            const filtered = sessions;
            const now = Date.now();
            const buckets: { label: string; items: typeof filtered }[] = [
              { label: '今天', items: [] },
              { label: '近 7 天', items: [] },
              { label: '更早', items: [] },
            ];
            for (const sess of filtered) {
              const days = (now - new Date(sess.updated_at).getTime()) / 86400000;
              (days < 1 ? buckets[0] : days < 7 ? buckets[1] : buckets[2]).items.push(sess);
            }
            const agentName = activeAgent?.name;
            return buckets.filter((b) => b.items.length > 0).map((bucket) => (
              <div key={bucket.label}>
                <div className="flex justify-between items-center px-2.5 pt-3 pb-1" style={{ fontSize: 9, letterSpacing: '.13em', color: 'var(--color-ink-faint)' }}>
                  <span>{bucket.label}{agentName ? <> · <span className="text-brand">{agentName}</span></> : null}</span>
                </div>
                {bucket.items.map((sess) => {
                  const infoAgent = agents.find((a) => a.id === sess.agent_id);
                  const isActive = activeSessionId === sess._id;
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
                        {formatSessionTime(sess.updated_at)} · {sess.message_count ?? 0} 条消息
                      </p>
                      <button
                        onClick={(e) => onDeleteSession(e, sess._id)}
                        className="absolute right-2 bottom-3 opacity-0 group-hover:opacity-100 p-1 text-ink-dim hover:text-sig-fail hover:bg-panel rounded-md transition"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  );
                })}
              </div>
            ));
          })()}
        </div>

        {/* 底部用户行（改版 global-sidebar-redesign）：去 border-t 分割线；
            大头像（36px）最左 + 用户名，点击上弹账户菜单；右端系统设置独立齿轮（按权限显隐） */}
        <div className="px-3 pt-2.5 pb-3 flex items-center gap-2">
          <div className="relative flex items-center min-w-0">
            <button
              onClick={() => { setUserMenuOpen(v => !v); setMoreMenuOpen(false) }}
              title="账户菜单"
              className="flex items-center gap-2.5 pl-0.5 pr-2.5 py-0.5 rounded-[12px] cursor-pointer hover:bg-panel hover:shadow-[var(--shadow-card)] transition-all min-w-0"
            >
              <span className="w-9 h-9 rounded-full bg-brand text-white flex items-center justify-center text-[13px] font-bold shrink-0">
                {userInitial ?? 'U'}
              </span>
              {username && <span className="text-[13px] font-medium text-ink truncate">{username}</span>}
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
          {/* 系统设置独立入口（改版：自「更多」菜单移出；无权限不渲染） */}
          {navItems?.some((n) => n.id === 'settings') && (
            <button
              onClick={() => onNavigate?.('settings')}
              title="系统设置"
              className="ml-auto w-8 h-8 rounded-[9px] flex items-center justify-center text-ink-dim hover:bg-panel hover:text-ink hover:shadow-[var(--shadow-card)] cursor-pointer transition-all shrink-0"
            >
              <Settings size={16} />
            </button>
          )}
        </div>
      </div>
    </div>
  );
}

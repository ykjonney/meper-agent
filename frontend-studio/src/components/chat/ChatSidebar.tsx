import type { Dispatch, MouseEvent as ReactMouseEvent, ReactNode, RefObject, SetStateAction } from 'react';
import { Trash2 } from 'lucide-react';
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
  userInitial, userMenuOpen, setUserMenuOpen, moreMenuOpen, setMoreMenuOpen,
  onNavigate, onLogout, onNavigateTask,
}: ChatSidebarProps) {
  return (
    <div style={{ width: 'var(--sess-w)' }} className="min-h-0 border-r border-line bg-well flex flex-col justify-between h-full shrink-0">
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
        {/* logo：产品图标 + 衬线字标，点击回到聊天主页 */}
        <div onClick={() => onNavigate?.('chat')} title="回到会话"
          className="px-4 pt-4 pb-3 cursor-pointer select-none w-fit flex items-center gap-2">
          <img src="/AFLogo.png" alt="MEPER Agent"
            className="w-[26px] h-[26px] rounded-[7px] object-contain select-none" draggable={false} />
          <span style={{ fontFamily: 'var(--font-serif)', fontStyle: 'italic', fontSize: 14, fontWeight: 700 }}>
            agent<span className="text-brand" style={{ fontStyle: 'normal' }}>·</span>flow
          </span>
        </div>
        {/* ── 功能入口（主 4 项；按 App 权限过滤，无权限的不显示）── */}
        <div className="px-4 pb-1" style={{ fontSize: 9, letterSpacing: '.16em', color: 'var(--color-ink-faint)' }}>功能</div>
        <div className="px-2 pb-6">
          {PRIMARY_NAV.filter(({ id }) => navItems?.some((n) => n.id === id)).map(({ id, label, Icon }) => {
            const badge = navItems?.find((n) => n.id === id)?.badge;
            const isActive = activePage != null && id === activeId;
            return (
              <button key={id} onClick={() => onNavigate?.(id)}
                className={`w-full flex items-center gap-[10px] px-3 py-[9px] text-[13px] cursor-pointer transition-colors ${isActive ? 'bg-panel shadow-[var(--shadow-card),inset_2px_0_0_var(--color-brand)]' : 'text-ink hover:bg-panel'}`}>
                <Icon size={15} className="opacity-70" />{label}
                {badge != null && <span className="ml-auto font-mono text-[9.5px] text-ink-faint">{badge}</span>}
              </button>
            );
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
                  onClick={(e) => { e.stopPropagation(); togglePin(id) }}
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
            return buckets.filter((b) => b.items.length > 0).map((bucket, bi) => (
              <div key={bucket.label}>
                <div className="flex justify-between items-center px-2.5 pt-3 pb-1" style={{ fontSize: 9, letterSpacing: '.13em', color: 'var(--color-ink-faint)' }}>
                  <span>{bucket.label}{agentName ? <> · <span className="text-brand">{agentName}</span></> : null}</span>
                  {/* 添加会话入口全局唯一：仅首个分组节标题显示 */}
                  {bi === 0 && (
                    <span className="cursor-pointer text-[12px] hover:text-brand"
                      onClick={() => activeAgent && onStartNewWithAgent(activeAgent)}
                      title={`以 ${agentName ?? '当前 Agent'} 开新会话`}>＋</span>
                  )}
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

        <div className="relative px-3 py-2.5 border-t border-line flex items-center gap-1.5">
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
                          className={`shrink-0 w-[18px] h-[18px] rounded-[5px] flex items-center justify-center text-[10px] cursor-pointer transition-opacity ${pinned ? 'text-brand opacity-100' : 'text-ink-faint opacity-0 group-hover/mp:opacity-100 hover:text-brand hover:bg-brand-soft'}`}
                        >
                          📌
                        </button>
                      </div>
                    )
                  })}
                  <div className="h-px bg-line mx-3.5 my-1.5" />
                  <div className="px-3.5 py-2 text-[9.5px] text-ink-faint border-t border-line mt-1">
                    悬停条目图钉 📌 可固定到侧栏
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

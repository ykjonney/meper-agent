import { DeleteOutlined, DisconnectOutlined, LogoutOutlined } from '@ant-design/icons'
import { Dropdown, Empty, Skeleton } from 'antd'

import { useAuthStore } from '../store/auth'
import type { AgentSummary, ChatSession } from '../types'

interface ConversationSidebarProps {
  agents: AgentSummary[]
  selectedAgentId: string | null
  onSelectAgent: (agentId: string) => void
  sessions: ChatSession[]
  activeSessionId: string | null
  onSelectSession: (sessionId: string) => void
  onCreateSession: () => void
  onDeleteSession: (session: ChatSession) => void
  creating: boolean
  loading: boolean
  /** 退出登录（jwt 模式：清 token 回登录页）。不传则不渲染。 */
  onLogout?: () => void
  /** 撤销授权（apikey 模式：解绑当前应用，回首绑门页可绑定其他账户）。
   * 不传则不渲染。 */
  onRevokeAuth?: () => void
}

function sessionLabel(session: ChatSession): string {
  if (session.title?.trim()) return session.title
  if (session.created_at) {
    return new Intl.DateTimeFormat('zh-CN', {
      month: 'numeric',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    }).format(new Date(session.created_at))
  }
  return `会话 ${session.id.slice(0, 6)}`
}

/** 会话 meta：相对时间（今天/昨天/N 天前 + 时刻）——v5 纸卡 mono 行 */
function relativeTime(iso?: string | null): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const now = new Date()
  const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime()
  const diffDays = Math.floor(
    (startOfToday - new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime()) / 86400000,
  )
  const hhmm = new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit' }).format(d)
  if (diffDays <= 0) return `今天 ${hhmm}`
  if (diffDays === 1) return `昨天 ${hhmm}`
  if (diffDays < 7) return `${diffDays} 天前`
  return new Intl.DateTimeFormat('zh-CN', { month: 'numeric', day: 'numeric' }).format(d)
}

export function ConversationSidebar(props: ConversationSidebarProps) {
  const user = useAuthStore((state) => state.user)
  const extUserName = useAuthStore((state) => state.extUserName)
  const displayName = extUserName || user?.username || '用户'
  const selected = props.agents.find((agent) => agent.id === props.selectedAgentId)
  // 助手选择器分段（v5 定稿）：切换是低频操作、会话列表才是抽屉主角——
  // 1 个不渲染；2-4 个纵向展开一眼全见；≥5 个收纳「当前助手」行 + 弹出纸卡
  const agentCount = props.agents.length
  const showExpanded = agentCount > 1 && agentCount <= 4
  const showCollapsed = agentCount > 4

  return (
    <aside className="conversation-sidebar">
      {/* 品牌头：靛蓝方章 + 衬线字标（单色 logo，替代渐变图） */}
      <div className="sidebar-brand">
        <span className="brand-seal">M</span>
        <span className="wordmark">
          <span className="wordmark-m">M</span>EPER Agent
        </span>
      </div>

      {showExpanded ? (
        <div className="agent-switcher">
          <div className="sidebar-label">选择助手</div>
          <div className="agent-list">
            {props.agents.map((agent) => {
              const active = agent.id === props.selectedAgentId
              return (
                <button
                  key={agent.id}
                  type="button"
                  className={`agent-item${active ? ' active' : ''}`}
                  onClick={() => props.onSelectAgent(agent.id)}
                >
                  <span className="agent-item-av">{agent.name.slice(0, 1)}</span>
                  <span className="agent-item-copy">
                    <span className="agent-item-name">{agent.name}</span>
                    {agent.description ? (
                      <span className="agent-item-sub">{agent.description}</span>
                    ) : null}
                  </span>
                  {active ? <span className="agent-item-dot" /> : null}
                </button>
              )
            })}
          </div>
        </div>
      ) : null}

      {showCollapsed && selected ? (
        <div className="agent-switcher">
          <div className="sidebar-label">当前助手</div>
          <Dropdown
            trigger={['click']}
            overlayClassName="agent-switcher-menu"
            menu={{
              selectedKeys: props.selectedAgentId ? [props.selectedAgentId] : [],
              items: props.agents.map((agent) => ({
                key: agent.id,
                label: (
                  <div className="agent-menu-item">
                    <span className="agent-item-av">{agent.name.slice(0, 1)}</span>
                    <span>{agent.name}</span>
                  </div>
                ),
              })),
              onClick: ({ key }) => props.onSelectAgent(key),
            }}
          >
            <button type="button" className="agent-current">
              <span className="agent-item-av">{selected.name.slice(0, 1)}</span>
              <span className="agent-item-name">{selected.name}</span>
              <svg
                className="agent-current-chev"
                width="11"
                height="11"
                viewBox="0 0 12 12"
                fill="none"
                aria-hidden
              >
                <path
                  d="M2.5 4.5L6 8l3.5-3.5"
                  stroke="currentColor"
                  strokeWidth="1.4"
                  strokeLinecap="round"
                  strokeLinejoin="round"
                />
              </svg>
            </button>
          </Dropdown>
        </div>
      ) : null}

      <button
        type="button"
        className="new-chat-card"
        disabled={!props.selectedAgentId || props.creating}
        onClick={props.onCreateSession}
      >
        <span className="new-chat-plus" aria-hidden>
          <svg width="10" height="10" viewBox="0 0 10 10" fill="none">
            <path
              d="M5 1.5v7M1.5 5h7"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeLinecap="round"
            />
          </svg>
        </span>
        开启新对话
      </button>

      <div className="conversation-list">
        <div className="sidebar-label">对话列表</div>
        {props.loading ? (
          <Skeleton active paragraph={{ rows: 5 }} title={false} />
        ) : props.sessions.length === 0 ? (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="还没有对话" />
        ) : (
          <div className="session-list">
            {props.sessions.map((session) => {
              const active = session.id === props.activeSessionId
              return (
                <div
                  key={session.id}
                  className={`sess${active ? ' active' : ''}`}
                  onClick={() => props.onSelectSession(session.id)}
                >
                  <div className="sess-t">{sessionLabel(session)}</div>
                  <div className="sess-m">{relativeTime(session.created_at)}</div>
                  <button
                    type="button"
                    className="sess-del"
                    aria-label="删除对话"
                    title="删除对话"
                    onClick={(event) => {
                      event.stopPropagation()
                      props.onDeleteSession(session)
                    }}
                  >
                    <DeleteOutlined />
                  </button>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* 底部用户区：姓氏圆点 + 名字 + 授权动作（主题切换已按 v5 裁剪清单删除） */}
      <div className="sidebar-account">
        <span className="u-av">{displayName.slice(0, 1)}</span>
        <span className="u-name">{displayName}</span>
        {props.onLogout ? (
          <button type="button" className="account-action" onClick={props.onLogout}>
            <LogoutOutlined />
          </button>
        ) : null}
        {props.onRevokeAuth ? (
          <button type="button" className="revoke-pill" onClick={props.onRevokeAuth}>
            <DisconnectOutlined />
            撤销授权
          </button>
        ) : null}
      </div>
    </aside>
  )
}

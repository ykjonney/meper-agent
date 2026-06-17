/**
 * Execution Logs page — today's session execution log viewer.
 *
 * Shows today's agent execution sessions from the backend,
 * with status filtering and expandable message preview.
 */
import { useState, useMemo } from 'react'
import { Tag, Select, Empty, Spin } from 'antd'
import {
  SearchOutlined,
  CheckCircleOutlined,
  CloseCircleOutlined,
  MessageOutlined,
  RobotOutlined,
  ClockCircleOutlined,
} from '@ant-design/icons'
import { useQuery } from '@tanstack/react-query'
import { useTheme } from '../contexts/ThemeContext'
import { sessionApi, sessionKeys, type Session } from '../services/session-api'
import { agentApi, agentKeys } from '../services/agent-api'

/* ─── Helpers ─── */

function isToday(dateStr: string): boolean {
  if (!dateStr) return false
  const d = new Date(dateStr)
  const now = new Date()
  return (
    d.getFullYear() === now.getFullYear() &&
    d.getMonth() === now.getMonth() &&
    d.getDate() === now.getDate()
  )
}

function formatTime(dateStr: string): string {
  if (!dateStr) return ''
  return new Date(dateStr).toLocaleTimeString('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

/* ─── Component ─── */

export default function ExecutionLogsPage() {
  const { t } = useTheme()
  const [statusFilter, setStatusFilter] = useState('all')
  const [searchText, setSearchText] = useState('')
  const [expandedId, setExpandedId] = useState<string | null>(null)

  /* ─── Fetch today's sessions (all agents) ─── */
  const { data: sessionsData, isLoading } = useQuery({
    queryKey: ['execution-logs', 'today'],
    queryFn: () => sessionApi.list({ page_size: 100 }),
    refetchOnWindowFocus: false,
  })

  /* ─── Fetch agent list for name lookup ─── */
  const { data: agentsData } = useQuery({
    queryKey: agentKeys.lists(),
    queryFn: () => agentApi.list(),
    refetchOnWindowFocus: false,
  })

  /* ─── Build agent name map ─── */
  const agentNames = useMemo(() => {
    const map: Record<string, string> = {}
    if (agentsData?.items) {
      for (const a of agentsData.items) {
        map[a.id] = a.name
      }
    }
    return map
  }, [agentsData])

  /* ─── Filter: today only → status → search ─── */
  const filtered = useMemo(() => {
    let list = (sessionsData?.items ?? []).filter((s) => isToday(s.created_at))
    if (statusFilter !== 'all') {
      list = list.filter((s) => s.status === statusFilter)
    }
    if (searchText.trim()) {
      const q = searchText.toLowerCase()
      list = list.filter(
        (s) =>
          s.title?.toLowerCase().includes(q) ||
          agentNames[s.agent_id]?.toLowerCase().includes(q),
      )
    }
    return list
  }, [sessionsData, statusFilter, searchText, agentNames])

  /* ─── Stats ─── */
  const stats = useMemo(() => {
    const todayAll = (sessionsData?.items ?? []).filter((s) => isToday(s.created_at))
    return {
      total: todayAll.length,
      messages: todayAll.reduce((sum, s) => sum + s.message_count, 0),
    }
  }, [sessionsData])

  const toggleExpand = (id: string) =>
    setExpandedId((prev) => (prev === id ? null : id))

  return (
    <div className="animate-[fadeIn_0.3s_ease-out]">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-lg font-semibold text-[#0F172A]">执行日志</h2>
          <p className="text-xs text-[#94A3B8] mt-0.5">
            今日共 {stats.total} 次会话，{stats.messages} 条消息
          </p>
        </div>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 mb-4">
        <div className="relative">
          <SearchOutlined className="absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8] text-sm" />
          <input
            type="text"
            placeholder="搜索会话..."
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            className="pl-9 pr-4 py-2 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 w-56"
            style={{ '--tw-ring-color': t.bg } as React.CSSProperties}
          />
        </div>
        <Select
          value={statusFilter}
          onChange={setStatusFilter}
          className="w-28"
          options={[
            { value: 'all', label: '全部状态' },
            { value: 'active', label: '进行中' },
            { value: 'archived', label: '已归档' },
          ]}
        />
      </div>

      {/* Log list */}
      <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
        {/* Table header */}
        <div className="grid grid-cols-[1fr_100px_60px_80px_60px] gap-4 px-4 py-2.5 bg-[#F8FAFC] border-b border-gray-100 text-xs font-medium text-[#64748B]">
          <span>会话</span>
          <span>Agent</span>
          <span>消息数</span>
          <span>时间</span>
          <span>状态</span>
        </div>

        {/* Loading */}
        {isLoading && (
          <div className="flex items-center justify-center py-12">
            <Spin />
          </div>
        )}

        {/* Empty */}
        {!isLoading && filtered.length === 0 && (
          <Empty description="今日暂无执行记录" className="my-12" />
        )}

        {/* Rows */}
        {filtered.map((s, i) => {
          const agentName = agentNames[s.agent_id] || s.agent_id
          const isExpanded = expandedId === s._id

          return (
            <div key={s._id}>
              <div
                className={`grid grid-cols-[1fr_100px_60px_80px_60px] gap-4 px-4 py-3 items-center hover:bg-[#F8FAFC] transition-colors duration-150 cursor-pointer text-sm ${
                  i > 0 ? 'border-t border-gray-50' : ''
                }`}
                onClick={() => toggleExpand(s._id)}
              >
                <div className="flex items-center gap-2 min-w-0">
                  <MessageOutlined className="text-[#94A3B8] text-xs shrink-0" />
                  <span className="text-[#0F172A] truncate text-sm">
                    {s.title || '新会话'}
                  </span>
                </div>
                <div className="flex items-center gap-1 min-w-0">
                  <RobotOutlined className="text-[10px] text-[#94A3B8] shrink-0" />
                  <span className="text-[#64748B] text-xs truncate">
                    {agentName}
                  </span>
                </div>
                <span className="text-[#64748B] text-xs font-mono">
                  {s.message_count}
                </span>
                <span className="text-[#64748B] text-xs font-mono flex items-center gap-1">
                  <ClockCircleOutlined className="text-[9px]" />
                  {formatTime(s.created_at)}
                </span>
                <div>
                  <SessionStatusTag status={s.status} />
                </div>
              </div>

              {/* Expanded: message preview */}
              {isExpanded && (
                <ExpandedDetail sessionId={s._id} />
              )}
            </div>
          )
        })}
      </div>
    </div>
  )
}

/* ─── Status tag ─── */

function SessionStatusTag({ status }: { status: string }) {
  const config: Record<string, { label: string; color: string; bg: string; icon: React.ReactNode }> = {
    active: { label: '进行中', color: '#2563EB', bg: '#EFF6FF', icon: null },
    archived: { label: '已归档', color: '#10B981', bg: '#D1FAE5', icon: <CheckCircleOutlined /> },
  }
  const c = config[status]
  if (!c) return null
  return (
    <Tag
      className="!m-0 !inline-flex !items-center !gap-1 !px-2 !py-0.5 !text-[11px] !rounded"
      style={{ color: c.color, background: c.bg, borderColor: 'transparent' }}
    >
      {c.icon}{c.label}
    </Tag>
  )
}

/* ─── Expanded detail: fetch session messages ─── */

function ExpandedDetail({ sessionId }: { sessionId: string }) {
  const { data, isLoading } = useQuery({
    queryKey: sessionKeys.detail(sessionId),
    queryFn: () => sessionApi.getDetail(sessionId),
    enabled: !!sessionId,
    refetchOnWindowFocus: false,
  })

  if (isLoading) {
    return (
      <div className="px-4 py-3 bg-[#FAFBFC] border-t border-gray-50 flex items-center justify-center">
        <Spin size="small" />
      </div>
    )
  }

  const messages = data?.messages ?? []

  if (messages.length === 0) {
    return (
      <div className="px-4 py-3 bg-[#FAFBFC] border-t border-gray-50 text-xs text-[#94A3B8]">
        暂无消息记录
      </div>
    )
  }

  return (
    <div className="px-4 py-3 bg-[#FAFBFC] border-t border-gray-50 space-y-1.5 max-h-64 overflow-y-auto">
      {messages.map((msg) => (
        <div key={msg._id} className="flex items-start gap-2">
          <span
            className={`text-[10px] font-medium shrink-0 mt-0.5 px-1.5 py-0.5 rounded ${
              msg.role === 'user'
                ? 'bg-blue-50 text-blue-600'
                : 'bg-emerald-50 text-emerald-600'
            }`}
          >
            {msg.role === 'user' ? '用户' : 'Agent'}
          </span>
          <span className="text-xs text-[#334155] leading-relaxed line-clamp-3 whitespace-pre-wrap">
            {msg.content}
          </span>
        </div>
      ))}
    </div>
  )
}

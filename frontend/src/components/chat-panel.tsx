/**
 * ChatPanel — reusable chat conversation component with SSE streaming.
 *
 * Renders a timeline of execution events: thinking blocks, tool calls,
 * tool results, and final answers. Supports enable_thinking toggle
 * for LLM native reasoning.
 *
 * Session management:
 * - Tracks a `sessionId` to maintain conversation continuity
 * - Passes `session_id` to backend on every invoke/stream call
 * - Backend auto-creates a session if none provided
 * - Loads history from backend when `sessionId` prop is provided
 */
import { useState, useRef, useCallback, useEffect } from 'react'
import { Input, Avatar, Tooltip, Empty, Switch, Tag, Spin, Popconfirm } from 'antd'
import {
  SendOutlined,
  UserOutlined,
  RobotOutlined,
  StopOutlined,
  PlusOutlined,
  DeleteOutlined,
  MessageOutlined,
  ExclamationCircleOutlined,
  BulbOutlined,
  ToolOutlined,
  CheckCircleOutlined,
  ReloadOutlined,
} from '@ant-design/icons'
import { useTheme } from '../contexts/ThemeContext'
import {
  agentApi,
  type StreamEvent,
  type ThinkingEvent,
  type ToolCallEvent,
  type ToolResultEvent,
  type FinalAnswerEvent,
} from '../services/agent-api'
import {
  sessionApi,
  type MessageRecord,
  type TimelineEntryData,
  type Session,
} from '../services/session-api'

/* ─── Types ─── */

export type TimelineEntryType = 'thinking' | 'tool_call' | 'tool_result' | 'final_answer' | 'error'

export interface TimelineEntry {
  id: string
  type: TimelineEntryType
  content: string
  /** For tool_call: the tool name */
  toolName?: string
  /** For tool_call: the args */
  args?: Record<string, unknown>
  /** Whether this entry is expanded (for collapsible items) */
  expanded?: boolean
}

export interface Message {
  id: string
  role: 'user' | 'agent' | 'error'
  content: string
  time: string
  requestId?: string
  isError?: boolean
  /** Timeline entries for agent messages */
  timeline?: TimelineEntry[]
}

export interface ChatPanelProps {
  agentId: string
  agentName?: string
  agentModel?: string
  /** Whether this model supports native thinking */
  modelSupportsThinking?: boolean
  /** Optional: load an existing session by ID */
  sessionId?: string
  /** Callback when a new session is created (child notifies parent) */
  onSessionChange?: (sessionId: string) => void
  showSidebar?: boolean
  className?: string
}

/* ─── Helpers ─── */

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`
}

function nowTime(): string {
  return new Date().toLocaleTimeString('zh-CN', { hour12: false })
}

function parseSseLines(buffer: string): { lines: string[]; remainder: string } {
  const parts = buffer.split('\n')
  const remainder = parts.pop() ?? ''
  const lines = parts.filter((l) => l.startsWith('data:'))
  return { lines, remainder }
}

/** Convert persisted timeline_entries back to TimelineEntry[] for UI rendering */
function historyEntryToTimeline(entries: TimelineEntryData[]): TimelineEntry[] {
  return entries.map((e, i) => {
    switch (e.type) {
      case 'thinking':
        return { id: `h-think-${i}`, type: 'thinking', content: e.content ?? '' }
      case 'tool_call':
        return { id: `h-tc-${i}`, type: 'tool_call', content: '', toolName: e.tool_name, args: e.args }
      case 'tool_result':
        return { id: `h-tr-${i}`, type: 'tool_result', content: e.content ?? '', toolName: e.tool_name }
      case 'final_answer':
        return { id: `h-fa-${i}`, type: 'final_answer', content: e.content ?? '' }
      default:
        return { id: `h-unk-${i}`, type: 'error', content: JSON.stringify(e) }
    }
  })
}

/** Convert backend MessageRecord[] to frontend Message[] */
function historyToMessages(records: MessageRecord[]): Message[] {
  return records.map((rec) => ({
    id: rec._id,
    role: rec.role,
    content: rec.content,
    time: rec.created_at ? new Date(rec.created_at).toLocaleTimeString('zh-CN', { hour12: false }) : '',
    timeline: rec.role === 'agent' && rec.timeline_entries?.length
      ? historyEntryToTimeline(rec.timeline_entries)
      : undefined,
  }))
}

/* ─── Component ─── */

export default function ChatPanel({
  agentId,
  agentName,
  agentModel,
  modelSupportsThinking = false,
  sessionId: sessionIdProp,
  onSessionChange,
  showSidebar = true,
  className = '',
}: ChatPanelProps) {
  const { t } = useTheme()

  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [isStreaming, setIsStreaming] = useState(false)
  const [isLoadingHistory, setIsLoadingHistory] = useState(false)
  const [enableThinking, setEnableThinking] = useState(false)
  const [currentSessionId, setCurrentSessionId] = useState<string | undefined>(sessionIdProp)
  const [sessionList, setSessionList] = useState<Session[]>([])
  const [isLoadingSessions, setIsLoadingSessions] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const sseBufferRef = useRef('')

  const scrollToBottom = useCallback(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [])

  /* ─── Session list management ─── */

  const refreshSessionList = useCallback(async () => {
    setIsLoadingSessions(true)
    try {
      const res = await sessionApi.list({ agent_id: agentId, page_size: 50 })
      setSessionList(res.items)
    } catch {
      // Silently ignore — session list is supplementary
    } finally {
      setIsLoadingSessions(false)
    }
  }, [agentId])

  // Load session list on mount
  useEffect(() => {
    refreshSessionList()
  }, [refreshSessionList])

  /* ─── Load history when sessionId prop changes ─── */

  useEffect(() => {
    setCurrentSessionId(sessionIdProp)
  }, [sessionIdProp])

  useEffect(() => {
    if (!currentSessionId) {
      setMessages([])
      return
    }

    let cancelled = false
    setIsLoadingHistory(true)

    sessionApi.getDetail(currentSessionId)
      .then((detail) => {
        if (cancelled) return
        setMessages(historyToMessages(detail.messages))
        // Scroll after history loads
        queueMicrotask(scrollToBottom)
      })
      .catch(() => {
        if (cancelled) return
        // Session not found or error — start fresh
        setMessages([])
      })
      .finally(() => {
        if (!cancelled) setIsLoadingHistory(false)
      })

    return () => { cancelled = true }
  }, [currentSessionId, scrollToBottom])

  /* ─── SSE stream handler ─── */

  const handleSend = useCallback(async () => {
    if (!input.trim() || isStreaming) return

    const userMsg: Message = {
      id: generateId(),
      role: 'user',
      content: input.trim(),
      time: nowTime(),
    }
    const agentMsgId = generateId()
    const agentMsg: Message = {
      id: agentMsgId,
      role: 'agent',
      content: '',
      time: nowTime(),
      timeline: [],
    }

    setMessages((prev) => [...prev, userMsg, agentMsg])
    setInput('')
    setIsStreaming(true)
    scrollToBottom()

    abortRef.current = new AbortController()
    sseBufferRef.current = ''

    try {
      const response = await agentApi.stream(agentId, {
        input: userMsg.content,
        session_id: currentSessionId || undefined,
        enable_thinking: enableThinking || undefined,
      })

      if (!response.ok) {
        throw new Error(`请求失败: ${response.status} ${response.statusText}`)
      }

      if (!response.body) {
        throw new Error('响应流为空')
      }

      // Extract session_id from response header if available
      const headerSessionId = response.headers.get('X-Session-Id')
      if (headerSessionId && !currentSessionId) {
        setCurrentSessionId(headerSessionId)
        onSessionChange?.(headerSessionId)
        // Refresh session list to include the newly created session
        refreshSessionList()
      }

      const reader = response.body.getReader()
      const decoder = new TextDecoder()

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        sseBufferRef.current += decoder.decode(value, { stream: true })
        const { lines, remainder } = parseSseLines(sseBufferRef.current)
        sseBufferRef.current = remainder

        for (const line of lines) {
          const jsonStr = line.slice(5).trim()
          if (!jsonStr) continue

          try {
            const event = JSON.parse(jsonStr) as StreamEvent

            if ('done' in event && event.done) {
              // Extract session_id from done event
              if (event.session_id && !currentSessionId) {
                setCurrentSessionId(event.session_id)
                onSessionChange?.(event.session_id)
                refreshSessionList()
              }
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === agentMsgId ? { ...m, requestId: event.request_id } : m,
                ),
              )
            } else if ('type' in event) {
              const eventType = (event as { type: string }).type

              // Token-level streaming: append delta text to content directly
              if (eventType === 'final_answer_delta') {
                const delta = (event as { content: string }).content
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === agentMsgId
                      ? { ...m, content: m.content + delta }
                      : m,
                  ),
                )
              } else if (eventType === 'error') {
                const errorContent = (event as { content: string }).content
                setMessages((prev) =>
                  prev.map((m) =>
                    m.id === agentMsgId
                      ? {
                          ...m,
                          role: 'error' as const,
                          content: errorContent,
                          isError: true,
                          timeline: [{ id: generateId(), type: 'error', content: errorContent }],
                        }
                      : m,
                  ),
                )
              } else {
                // Consolidated events: thinking, tool_call, tool_result, final_answer
                const entry = _sseEventToTimeline(event)
                if (entry) {
                  setMessages((prev) =>
                    prev.map((m) =>
                      m.id === agentMsgId
                        ? {
                            ...m,
                            timeline: [...(m.timeline ?? []), entry],
                            content: entry.type === 'final_answer' ? entry.content : m.content,
                          }
                        : m,
                    ),
                  )
                }
              }
            }
          } catch {
            // Skip unparseable lines
          }
        }

        scrollToBottom()
      }
    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === 'AbortError') {
        setMessages((prev) =>
          prev.map((m) =>
            m.id === agentMsgId && !(m.timeline?.length)
              ? { ...m, timeline: [{ id: generateId(), type: 'error', content: '(已停止)' }] }
              : m,
          ),
        )
      } else {
        const errorMessage = err instanceof Error ? err.message : '未知错误'
        setMessages((prev) =>
          prev.map((m) =>
            m.id === agentMsgId
              ? {
                  ...m,
                  role: 'error' as const,
                  content: errorMessage,
                  isError: true,
                  timeline: [{ id: generateId(), type: 'error', content: errorMessage }],
                }
              : m,
          ),
        )
      }
    } finally {
      setIsStreaming(false)
      abortRef.current = null
    }
  }, [input, isStreaming, agentId, enableThinking, currentSessionId, onSessionChange, scrollToBottom, refreshSessionList])

  const handleStop = useCallback(() => {
    abortRef.current?.abort()
  }, [])

  const handleNewChat = useCallback(() => {
    setMessages([])
    setCurrentSessionId(undefined)
    onSessionChange?.('')
  }, [onSessionChange])

  const handleSelectSession = useCallback((sid: string) => {
    if (sid === currentSessionId || isStreaming) return
    setCurrentSessionId(sid)
    onSessionChange?.(sid)
  }, [currentSessionId, isStreaming, onSessionChange])

  const handleDeleteSession = useCallback(async (sid: string) => {
    try {
      await sessionApi.remove(sid)
      // If deleting current session, start fresh
      if (sid === currentSessionId) {
        setMessages([])
        setCurrentSessionId(undefined)
        onSessionChange?.('')
      }
      // Refresh list
      refreshSessionList()
    } catch {
      // ignore
    }
  }, [currentSessionId, onSessionChange, refreshSessionList])

  const handleRetry = useCallback(
    (failedMsgId: string) => {
      const failIdx = messages.findIndex((m) => m.id === failedMsgId)
      if (failIdx < 1) return

      const userMsg = messages[failIdx - 1]
      if (userMsg?.role !== 'user') return

      setMessages((prev) => prev.filter((m) => m.id === failedMsgId))
      queueMicrotask(() => {
        setInput(userMsg.content)
      })
    },
    [messages],
  )

  const toggleTimelineEntry = useCallback((msgId: string, entryId: string) => {
    setMessages((prev) =>
      prev.map((m) =>
        m.id === msgId
          ? {
              ...m,
              timeline: (m.timeline ?? []).map((e) =>
                e.id === entryId ? { ...e, expanded: !e.expanded } : e,
              ),
            }
          : m,
      ),
    )
  }, [])

  /* ─── Render ─── */

  return (
    <div className={`flex h-full gap-6 ${className}`}>
      {/* ════════ Left panel: messages + input ════════ */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top bar: actions */}
        <div className="flex items-center justify-between mb-4 shrink-0">
          <div className="flex items-center gap-3">
            {agentName && (
              <span className="text-sm font-medium text-[#0F172A]">{agentName}</span>
            )}
            {agentModel && (
              <span className="text-[11px] text-[#94A3B8] font-mono">{agentModel}</span>
            )}
          </div>
          <div className="flex items-center gap-3">
            {/* Thinking toggle */}
            <div className="flex items-center gap-2">
              <Switch
                size="small"
                checked={enableThinking}
                onChange={setEnableThinking}
                disabled={isStreaming}
              />
              <span className="text-xs text-[#64748B] flex items-center gap-1">
                <BulbOutlined />
                深度思考
              </span>
              {!modelSupportsThinking && enableThinking && (
                <Tag className="!m-0 !text-[10px] !px-1.5" color="warning">
                  当前模型不支持推理
                </Tag>
              )}
            </div>
          </div>
        </div>

        {/* Messages area */}
        <div className="flex-1 rounded-xl border border-gray-200 bg-white p-4 overflow-y-auto mb-4">
          {/* Loading history indicator */}
          {isLoadingHistory && (
            <div className="flex items-center justify-center mt-16">
              <Spin />
            </div>
          )}

          <div className="flex flex-col gap-4">
            {!isLoadingHistory && messages.length === 0 && (
              <Empty
                description="发送一条消息开始测试"
                className="mt-16"
              />
            )}

            {messages.map((msg) => (
              <div key={msg.id}>
                {/* User message */}
                {msg.role === 'user' && (
                  <div className="flex items-start gap-3 flex-row-reverse">
                    <Avatar
                      size={32}
                      icon={<UserOutlined />}
                      style={{ background: '#94A3B8', flexShrink: 0 }}
                    />
                    <div
                      className="max-w-[75%] rounded-xl rounded-tr-sm px-4 py-2.5 text-sm leading-relaxed"
                      style={{ background: t.bg, color: t.primary }}
                    >
                      {msg.content}
                      <div className="text-[10px] text-[#94A3B8] mt-1.5 text-right">{msg.time}</div>
                    </div>
                  </div>
                )}

                {/* Error message */}
                {msg.role === 'error' && msg.isError && !msg.timeline?.length && (
                  <div className="flex items-start gap-3">
                    <Avatar
                      size={32}
                      icon={<ExclamationCircleOutlined />}
                      style={{ background: '#EF4444', flexShrink: 0 }}
                    />
                    <div className="max-w-[75%] rounded-xl rounded-tl-sm px-4 py-2.5 bg-[#FEF2F2] border border-red-100">
                      <div className="text-sm text-[#DC2626]">{msg.content}</div>
                      <div className="flex items-center justify-between mt-1.5">
                        <span className="text-[10px] text-[#94A3B8]">{msg.time}</span>
                        <button
                          onClick={() => handleRetry(msg.id)}
                          className="flex items-center gap-1 text-xs text-[#DC2626] hover:text-[#B91C1C] border-0 bg-transparent cursor-pointer"
                        >
                          <ReloadOutlined /> 重试
                        </button>
                      </div>
                    </div>
                  </div>
                )}

                {/* Agent message — streaming text or timeline entries */}
                {msg.role === 'agent' && (msg.content || (msg.timeline && msg.timeline.length > 0)) && (
                  <div className="flex items-start gap-3">
                    <Avatar
                      size={32}
                      icon={<RobotOutlined />}
                      style={{ background: t.primary, flexShrink: 0 }}
                    />
                    <div className="flex-1 min-w-0">
                      <div className="flex flex-col gap-2">
                        {/* Show streaming text content when available */}
                        {msg.content && (!msg.timeline || msg.timeline.length === 0) && (
                          <div className="rounded-xl rounded-tl-sm px-4 py-2.5 bg-[#F8FAFC] border border-gray-100">
                            <div className="text-sm leading-relaxed text-[#0F172A] whitespace-pre-wrap">
                              {msg.content}
                              {/* Blinking cursor during streaming */}
                              {isStreaming && (
                                <span className="inline-block w-0.5 h-4 ml-0.5 align-text-bottom animate-pulse" style={{ background: t.primary }} />
                              )}
                            </div>
                          </div>
                        )}
                        {/* Show timeline entries (tool calls, consolidated events) */}
                        {msg.timeline && msg.timeline.length > 0 && msg.timeline.map((entry) => (
                          <TimelineEntryCard
                            key={entry.id}
                            entry={entry}
                            msgId={msg.id}
                            onToggle={toggleTimelineEntry}
                          />
                        ))}
                      </div>
                      <div className="text-[10px] text-[#94A3B8] mt-2">{msg.time}</div>
                    </div>
                  </div>
                )}
              </div>
            ))}

            {/* Streaming indicator — show when last agent message has no content yet */}
            {isStreaming &&
              messages.length > 0 &&
              messages[messages.length - 1].role === 'agent' &&
              !messages[messages.length - 1].content &&
              !messages[messages.length - 1].timeline?.length && (
                <div className="flex items-start gap-3">
                  <Avatar
                    size={32}
                    icon={<RobotOutlined />}
                    style={{ background: t.primary, flexShrink: 0 }}
                  />
                  <div className="rounded-xl rounded-tl-sm px-4 py-2.5 bg-[#F8FAFC] border border-gray-100">
                    <div className="flex items-center gap-1.5">
                      <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: t.primary }} />
                      <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: t.primary, animationDelay: '0.2s' }} />
                      <span className="w-1.5 h-1.5 rounded-full animate-pulse" style={{ background: t.primary, animationDelay: '0.4s' }} />
                      <span className="text-xs text-[#94A3B8] ml-1">Agent 正在思考...</span>
                    </div>
                  </div>
                </div>
              )}
            <div ref={messagesEndRef} />
          </div>
        </div>

        {/* Input area */}
        <div className="flex items-center gap-3 shrink-0">
          <Input.TextArea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="输入测试消息..."
            rows={2}
            className="rounded-xl !border-gray-200 !resize-none"
            onPressEnter={(e) => {
              if (!e.shiftKey) {
                e.preventDefault()
                handleSend()
              }
            }}
          />
          <div className="flex flex-col gap-2">
            <Tooltip title={isStreaming ? '停止' : '发送'}>
              <button
                onClick={isStreaming ? handleStop : handleSend}
                disabled={!input.trim() && !isStreaming}
                className="w-10 h-10 flex items-center justify-center rounded-xl border-0 text-white transition-all duration-150 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
                style={{ background: t.primary }}
              >
                {isStreaming ? <StopOutlined /> : <SendOutlined />}
              </button>
            </Tooltip>
          </div>
        </div>
      </div>

      {/* ════════ Right panel: session list ════════ */}
      {showSidebar && (
        <div className="w-72 shrink-0 flex flex-col min-h-0">
          {/* Header */}
          <div className="flex items-center justify-between mb-3 shrink-0">
            <div className="flex items-center gap-2">
              <MessageOutlined style={{ color: t.primary, fontSize: 14 }} />
              <span className="text-sm font-medium text-[#0F172A]">历史会话</span>
              <span className="text-[10px] text-[#94A3B8]">({sessionList.length})</span>
            </div>
            <Tooltip title="新对话">
              <button
                onClick={handleNewChat}
                disabled={isStreaming}
                className="border-0 bg-transparent w-7 h-7 flex items-center justify-center rounded-md text-[#64748B] hover:text-[#0F172A] hover:bg-gray-50 transition-colors duration-150 disabled:opacity-40"
              >
                <PlusOutlined className="text-xs" />
              </button>
            </Tooltip>
          </div>

          {/* Session list (scrollable) */}
          <div className="flex-1 rounded-xl border border-gray-200 bg-white p-2 overflow-y-auto min-h-0">
            {isLoadingSessions && (
              <div className="flex items-center justify-center py-8">
                <Spin size="small" />
              </div>
            )}

            {!isLoadingSessions && sessionList.length === 0 && (
              <Empty
                description="暂无历史会话"
                className="mt-12"
                imageStyle={{ height: 48 }}
              />
            )}

            <div className="flex flex-col gap-1">
              {sessionList.map((s) => {
                const isActive = s._id === currentSessionId
                const title = s.title || '新会话'
                const time = s.updated_at
                  ? new Date(s.updated_at).toLocaleString('zh-CN', {
                      month: '2-digit',
                      day: '2-digit',
                      hour: '2-digit',
                      minute: '2-digit',
                      hour12: false,
                    })
                  : ''

                return (
                  <div
                    key={s._id}
                    onClick={() => handleSelectSession(s._id)}
                    className={`group cursor-pointer rounded-lg px-3 py-2 transition-colors duration-150 ${
                      isActive
                        ? 'bg-blue-50 border border-blue-200'
                        : 'hover:bg-gray-50 border border-transparent'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <div
                        className={`text-xs font-medium truncate flex-1 ${
                          isActive ? 'text-blue-700' : 'text-[#0F172A]'
                        }`}
                        title={title}
                      >
                        {title}
                      </div>
                      <Popconfirm
                        title="确定删除这个会话？"
                        okText="删除"
                        cancelText="取消"
                        okButtonProps={{ danger: true, size: 'small' }}
                        cancelButtonProps={{ size: 'small' }}
                        onConfirm={() => handleDeleteSession(s._id)}
                      >
                        <button
                          onClick={(e) => e.stopPropagation()}
                          className="opacity-0 group-hover:opacity-100 transition-opacity border-0 bg-transparent p-0.5 text-[#94A3B8] hover:text-[#EF4444] cursor-pointer"
                        >
                          <DeleteOutlined className="text-xs" />
                        </button>
                      </Popconfirm>
                    </div>
                    <div className="flex items-center justify-between mt-1">
                      <span className="text-[10px] text-[#94A3B8]">{time}</span>
                      <span className="text-[10px] text-[#94A3B8]">{s.message_count} 条</span>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>

          {/* Bottom: session info */}
          <div className="mt-3 shrink-0 rounded-xl border border-gray-200 bg-white p-3">
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs text-[#64748B]">状态</span>
                <span className={`text-xs font-medium ${isStreaming ? 'text-amber-500' : 'text-emerald-500'}`}>
                  {isStreaming ? '执行中' : '就绪'}
                </span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-xs text-[#64748B]">思考模式</span>
                <span className={`text-xs font-medium ${enableThinking ? 'text-blue-500' : 'text-[#94A3B8]'}`}>
                  {enableThinking ? '已开启' : '关闭'}
                </span>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

/* ─── Timeline entry card ─── */

function TimelineEntryCard({
  entry,
  msgId,
  onToggle,
}: {
  entry: TimelineEntry
  msgId: string
  onToggle: (msgId: string, entryId: string) => void
}) {
  switch (entry.type) {
    case 'thinking':
      return (
        <div className="rounded-lg border border-blue-100 bg-blue-50/50 overflow-hidden">
          <button
            onClick={() => onToggle(msgId, entry.id)}
            className="w-full flex items-center gap-2 px-3 py-2 border-0 bg-transparent cursor-pointer text-left hover:bg-blue-50 transition-colors"
          >
            <BulbOutlined className="text-blue-400 text-xs" />
            <span className="text-xs font-medium text-blue-600">思考过程</span>
            <span className="text-[10px] text-blue-300 ml-auto">
              {entry.expanded ? '收起' : '展开'}
            </span>
          </button>
          {entry.expanded && (
            <div className="px-3 pb-2 text-xs text-blue-700 whitespace-pre-wrap leading-relaxed border-t border-blue-100 pt-2">
              {entry.content}
            </div>
          )}
        </div>
      )

    case 'tool_call':
      return (
        <div className="flex items-center gap-2 px-3 py-1.5 rounded-lg bg-amber-50 border border-amber-100">
          <ToolOutlined className="text-amber-500 text-xs" />
          <span className="text-xs font-medium text-amber-700">
            {entry.toolName || 'unknown_tool'}
          </span>
          {entry.args && Object.keys(entry.args).length > 0 && (
            <span className="text-[10px] text-amber-400 truncate max-w-[200px]">
              {JSON.stringify(entry.args)}
            </span>
          )}
        </div>
      )

    case 'tool_result':
      return (
        <div className="rounded-lg border border-gray-100 bg-gray-50 overflow-hidden">
          <button
            onClick={() => onToggle(msgId, entry.id)}
            className="w-full flex items-center gap-2 px-3 py-1.5 border-0 bg-transparent cursor-pointer text-left hover:bg-gray-100 transition-colors"
          >
            <CheckCircleOutlined className="text-gray-400 text-xs" />
            <span className="text-xs text-gray-500">
              {entry.toolName ? `${entry.toolName} → ` : ''}工具结果
            </span>
            <span className="text-[10px] text-gray-300 ml-auto">
              {entry.expanded ? '收起' : '展开'}
            </span>
          </button>
          {entry.expanded && (
            <div className="px-3 pb-2 text-xs text-gray-600 whitespace-pre-wrap leading-relaxed border-t border-gray-100 pt-2 max-h-48 overflow-y-auto">
              {entry.content}
            </div>
          )}
        </div>
      )

    case 'final_answer':
      return (
        <div className="rounded-xl rounded-tl-sm px-4 py-2.5 bg-[#F8FAFC] border border-gray-100">
          <div className="text-sm leading-relaxed text-[#0F172A] whitespace-pre-wrap">
            {entry.content}
          </div>
        </div>
      )

    case 'error':
      return (
        <div className="rounded-xl rounded-tl-sm px-4 py-2.5 bg-[#FEF2F2] border border-red-100">
          <div className="text-sm text-[#DC2626]">{entry.content}</div>
        </div>
      )

    default:
      return null
  }
}

/* ─── SSE event to timeline entry converter ─── */

function _sseEventToTimeline(event: StreamEvent): TimelineEntry | null {
  // Defensive: ensure content is always a string (backend may send objects)
  const safeStr = (v: unknown): string => {
    if (typeof v === 'string') return v
    if (v == null) return ''
    if (typeof v === 'object') {
      try { return JSON.stringify(v) } catch { return String(v) }
    }
    return String(v)
  }

  if ('type' in event && event.type === 'thinking') {
    const e = event as ThinkingEvent
    return { id: generateId(), type: 'thinking', content: safeStr(e.content) }
  }
  if ('type' in event && event.type === 'tool_call') {
    const e = event as ToolCallEvent
    return { id: generateId(), type: 'tool_call', content: '', toolName: e.tool_name, args: e.args }
  }
  if ('type' in event && event.type === 'tool_result') {
    const e = event as ToolResultEvent
    return { id: generateId(), type: 'tool_result', content: e.content, toolName: e.tool_name }
  }
  if ('type' in event && event.type === 'final_answer') {
    const e = event as FinalAnswerEvent
    return { id: generateId(), type: 'final_answer', content: e.content }
  }
  return null
}

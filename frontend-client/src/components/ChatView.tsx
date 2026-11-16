import {
  AudioOutlined,
  CloseOutlined,
  DeploymentUnitOutlined,
  FileOutlined,
  MenuOutlined,
  PaperClipOutlined,
  QuestionCircleOutlined,
  PlusOutlined,
  LikeOutlined,
  LikeFilled,
  SafetyCertificateOutlined,
} from '@ant-design/icons'
import { Sender } from '@ant-design/x'
import {
  Alert,
  App,
  Badge,
  Button,
  Empty,
  Image,
  Input,
  Modal,
  Result,
  Skeleton,
  Spin,
  Tooltip,
  Typography,
} from 'antd'
import type { UploadFile } from 'antd'
import { LoadingOutlined, OrderedListOutlined } from '@ant-design/icons'
import { Popover, Tag, Tooltip as AntTooltip } from 'antd'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { useChat } from '../hooks/use-chat'
import { useAuthStore } from '../store/auth'
import { fetchAuthBootstrap, fetchMyAuthorizations } from '../api/authorizations'
import { fetchVoiceStatus } from '../api/voice'
import type { AgentSummary, ChatMessage } from '../types'
import { GeneratedFiles } from './GeneratedFiles'
import { MessageContent } from './MessageContent'
import { collectSessionTasks, WorkflowBoard } from './WorkflowBoard'
import { QuickActionsBar } from './QuickActionsBar'
import { sessionFeedback, voteMessage, type SessionFeedbackItem , listBackgroundTasks } from '../api/chat'
import { ClarificationFormCard } from './clarification-form-card'
import { VoiceComposer } from './voice/VoiceComposer'

/** 最新 todo 快照（todo_write 工具最后一次调用的清单）——header 胶囊展示。 */
interface TodoSnapshot {
  items: { content: string; status: string }[]
  done: number
}
function extractLatestTodos(messages: ChatMessage[]): TodoSnapshot | null {
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i]
    if (m.role !== 'assistant') continue
    for (let j = m.content.length - 1; j >= 0; j--) {
      const b = m.content[j]
      if (b.type !== 'tool' || b.tool.name !== 'todo_write' || !b.tool.args) continue
      try {
        const parsed = JSON.parse(b.tool.args)
        const todos = Array.isArray(parsed.todos) ? parsed.todos : []
        if (!todos.length) return { items: [], done: 0 }
        return {
          items: todos.map((t: { content?: string; status?: string }) => ({
            content: t.content ?? '',
            status: t.status ?? 'pending',
          })),
          done: todos.filter((t: { status?: string }) => t.status === 'completed').length,
        }
      } catch {
        return null
      }
    }
  }
  return null
}

/** 嵌入模式（chat-widget.js iframe 内）检测：仅此模式显示 header 关闭按钮，
 * 点击经 postMessage 通知 widget 收起面板（widget 侧悬浮关闭/全屏按钮已移除，
 * 悬浮样式会遮挡 header 内容；桌面端仍可点面板外部或 ESC 关闭）。 */
const IS_EMBEDDED = window.parent !== window

function closeEmbeddedPanel() {
  window.parent.postMessage({ type: 'agentflow:close' }, '*')
}

/** 已查看工作流任务 id 的 localStorage key（跨刷新持久，避免角标反复亮起）。 */
const SEEN_TASKS_KEY = 'meper_client_seen_tasks'

interface ChatViewProps {
  agent: AgentSummary | null
  agentLoading?: boolean
  sessionsLoading?: boolean
  sessionId: string | null
  /** 非空 = 本地接入会话（隐藏上传，文件由用户直接放入绑定目录） */
  localDir?: string
  onOpenNavigation: () => void
  onCreateSession: () => void
  /** 会话内容变化(如发完消息后端生成标题)时回调,用于刷新侧边栏会话列表 */
  onSessionChanged?: () => void
  /** 语音对话后端新建会话时回传新 session_id,用于切换当前会话 */
  onSessionSwitched?: (sessionId: string) => void
}

export function ChatView({
  agent,
  agentLoading,
  sessionsLoading,
  sessionId,
  localDir,
  onOpenNavigation,
  onCreateSession,
  onSessionChanged,
  onSessionSwitched,
}: ChatViewProps) {
  // 后台任务角标：轮询 registry（纯 FS 语义，与模型侧注入一致）
  const [bgBadge, setBgBadge] = useState<{ running: number; finishedUnread: number } | null>(null)
  useEffect(() => {
    if (!sessionId) {
      setBgBadge(null)
      return
    }
    let cancelled = false
    const poll = async () => {
      try {
        const items = await listBackgroundTasks(sessionId)
        if (cancelled) return
        const running = items.filter((task) => task.running).length
        const finishedUnread = items.filter((task) => !task.running && task.unread).length
        setBgBadge(running + finishedUnread > 0 ? { running, finishedUnread } : null)
      } catch {
        // 轮询失败不打扰（角标是次要体验）
      }
    }
    void poll()
    const timer = window.setInterval(poll, 15000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [sessionId])
  const { message } = App.useApp()
  const [input, setInput] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [filesOpen, setFilesOpen] = useState(false)
  const [filesRefreshKey, setFilesRefreshKey] = useState(0)
  // 工作流任务看板：header 按钮 / 消息内一行状态卡进入；focusTaskId 用于定位展开
  const [boardOpen, setBoardOpen] = useState(false)
  const [boardFocusTaskId, setBoardFocusTaskId] = useState<string | null>(null)
  // 已查看过的任务 id——角标只提示「未查看」的新任务，打开看板即全部已读。
  // 持久化到 localStorage：刷新页面后已读状态不丢（否则角标会反复亮起）
  const [seenTaskIds, setSeenTaskIds] = useState<Set<string>>(() => {
    try {
      const raw = localStorage.getItem(SEEN_TASKS_KEY)
      const arr = raw ? (JSON.parse(raw) as unknown) : []
      return new Set(Array.isArray(arr) ? (arr as string[]) : [])
    } catch {
      return new Set()
    }
  })
  const [clarificationAnswer, setClarificationAnswer] = useState('')
  // 运行时按需授权卡：账号/密码 + 提交错误信息（凭证只走授权 API，不进对话）
  const [authUsername, setAuthUsername] = useState('')
  const [authPassword, setAuthPassword] = useState('')
  const [authSubmitting, setAuthSubmitting] = useState(false)
  const [authError, setAuthError] = useState('')
  const [pendingPreview, setPendingPreview] = useState<{
    name: string
    url: string
  } | null>(null)
  const fileInputRef = useRef<HTMLInputElement | null>(null)
  const {
    messages,
    loading,
    running,
    hitl,
    loadError,
    send,
    cancel,
    answerClarification,
    answerAppAuthorization,
    declineAppAuthorization,
    dismissClarification,
    voiceAppendUserMessage,
    voiceBeginAssistantTurn,
    voiceAppendDelta,
    voiceFinishTurn,
    voiceAbort,
  } = useChat(
    agent?.id ?? null,
    sessionId,
    () => setFilesRefreshKey((value) => value + 1),
    onSessionChanged,
  )

  // 授权卡出现时带出账号默认值（可改）：优先该应用已绑定的用户名
  // （INVALID 重新授权只需重输密码）；无绑定（跨应用首次授权）退回
  // 身份用户名（bootstrap.ext_username）作猜测起点，带不出则留空
  useEffect(() => {
    if (hitl?.kind !== 'app_authorization' || !hitl.appId) return
    let cancelled = false
    void fetchMyAuthorizations()
      .then(async (result) => {
        if (cancelled) return
        const bound = result.bindings.find((b) => b.app_id === hitl.appId)
        if (bound) {
          setAuthUsername(bound.username)
          return
        }
        try {
          const boot = await fetchAuthBootstrap()
          if (!cancelled && boot.ext_username) setAuthUsername(boot.ext_username)
        } catch {
          /* 带不出默认值就留空，不影响流程 */
        }
      })
      .catch(() => {
        /* 同上 */
      })
    return () => {
      cancelled = true
    }
  }, [hitl?.kind, hitl?.appId])

  // 本会话的工作流任务（从消息流解析 task_created）——只在出现过任务后才显示
  // header「工作流」按钮；切会话随 messages 重置，天然清空
  const sessionTasks = useMemo(() => collectSessionTasks(messages), [messages])
  // 未查看数 = 当前任务 − 已读；antd Badge count=0 时自动隐藏红点
  const unseenTaskCount = sessionTasks.filter((t) => !seenTaskIds.has(t.task_id)).length
  // 最新 todo 快照（todo_write 清单）——header 胶囊
  const latestTodos = extractLatestTodos(messages)
  // 重新生成：取最后一条用户输入重发（仅非流式时可用）
  const handleRegenerate = useCallback(() => {
    if (running) return
    const lastUser = [...messages].reverse().find((m) => m.role === 'user')
    if (!lastUser) return
    const text = lastUser.content
      .filter((b) => b.type === 'text')
      .map((b) => b.text)
      .join('')
    if (text) void send(text, [])
  }, [messages, running, send])
  const lastAssistantId = messages.length ? messages[messages.length - 1].id : null
  // 批注贴头像：终端用户名首字符（zhangsan→Z，中文名取首字）
  const extUserName = useAuthStore((state) => state.extUserName)
  const authUser = useAuthStore((state) => state.user)
  const userInitial = (extUserName || authUser?.username || '客')[0].toUpperCase()

  // 看板打开期间把当前任务标记为已读（含打开期间新到的任务），并持久化
  useEffect(() => {
    if (!boardOpen) return
    setSeenTaskIds((prev) => {
      const next = new Set(prev)
      let changed = false
      for (const task of sessionTasks) {
        if (!next.has(task.task_id)) {
          next.add(task.task_id)
          changed = true
        }
      }
      if (changed) {
        try {
          // 上限 500 条防无限增长，超出丢弃最早的 id
          localStorage.setItem(
            SEEN_TASKS_KEY,
            JSON.stringify([...next].slice(-500)),
          )
        } catch {
          /* 存储失败静默——角标退化为本次会话内有效 */
        }
      }
      return changed ? next : prev
    })
  }, [boardOpen, sessionTasks])

  // 切换会话：关闭任务看板，避免残留旧会话的任务列表
  // （已读标记按 task_id 全局持久，不随会话清空）
  useEffect(() => {
    setBoardOpen(false)
    setBoardFocusTaskId(null)
  }, [sessionId])

  // ── 语音输入模式 ─────────────────────────────────────────────────
  const [inputMode, setInputMode] = useState<'text' | 'voice'>('text')
  const [voiceConfigured, setVoiceConfigured] = useState(false)
  const voiceAvailable = voiceConfigured && agent?.voiceEnabled === true

  useEffect(() => {
    let cancelled = false
    fetchVoiceStatus()
      .then((status) => {
        if (!cancelled) setVoiceConfigured(status.configured === true)
      })
      .catch(() => {
        // 探测失败按未配置处理（不弹错，麦克风按钮不出现即可）
      })
    return () => {
      cancelled = true
    }
  }, [])

  // 语音可用性变化后退出语音模式（如切换到未开启语音的 Agent）
  useEffect(() => {
    if (inputMode === 'voice' && !voiceAvailable) {
      voiceAbort()
      setInputMode('text')
    }
  }, [inputMode, voiceAvailable, voiceAbort])

  // ── 自动滚动跟随 ────────────────────────────────────────────────
  // 历史背景:.message-viewport(外层 overflow:auto)与 Bubble.List 内部
  // 的 scroll-box 形成双层滚动,Bubble.List 的 autoScroll 拿不到正确的贴底
  // 判定。这里关闭 Bubble.List 的 autoScroll,改由外层 viewport 自实现:
  // 用户贴底时跟随流式输出,上滚超过阈值就不打扰,切会话时滚到最新一条。
  const viewportRef = useRef<HTMLElement | null>(null)
  const isPinnedRef = useRef(true) // 用户是否处于「贴底」状态
  const PIN_THRESHOLD = 120 // 距底部多少 px 内视为贴底

  const scrollToBottom = (behavior: ScrollBehavior = 'auto') => {
    const el = viewportRef.current
    if (!el) return
    el.scrollTo({ top: el.scrollHeight, behavior })
  }

  const handleViewportScroll = () => {
    const el = viewportRef.current
    if (!el) return
    const distanceToBottom = el.scrollHeight - el.scrollTop - el.clientHeight
    isPinnedRef.current = distanceToBottom < PIN_THRESHOLD
  }

  // 用户展开/收起过程卡 = 主动浏览意图 → 脱离贴底，停掉 MutationObserver
  // 的自动跟随（否则展开挂载 activity-body 会被误当流式增量强滚到底部）。
  // 之后滚回底部（scroll 事件）会自动恢复 pinned。
  const handleViewportClick = (event: React.MouseEvent) => {
    if ((event.target as HTMLElement).closest('.activity-card-head')) {
      isPinnedRef.current = false
    }
  }

  // 内容尺寸变化时(流式增量、图片加载完成等),贴底则跟随
  useEffect(() => {
    const el = viewportRef.current
    if (!el) return
    // 观察直接子节点(.ant-bubble-list / skeleton / empty)的高度变化
    const observer = new ResizeObserver(() => {
      if (isPinnedRef.current) scrollToBottom('auto')
    })
    observer.observe(el)
    // 子树挂载/卸载也要重新观察
    const mo = new MutationObserver(() => {
      if (isPinnedRef.current) scrollToBottom('auto')
    })
    mo.observe(el, { childList: true, subtree: true })
    return () => {
      observer.disconnect()
      mo.disconnect()
    }
  }, [sessionId])

  // 切换会话:重置贴底并滚到最新一条
  useEffect(() => {
    isPinnedRef.current = true
    // 等首屏渲染完成后再滚
    requestAnimationFrame(() => scrollToBottom('auto'))
  }, [sessionId])

  // 消息变化(新增消息、流式增量、状态变更):贴底则跟随
  /* ── 消息级反馈（§8.2 v2）：会话各轮投票态，流结束/切会话刷新 ── */
  const [feedbackTick, setFeedbackTick] = useState(0)
  const [feedbackMap, setFeedbackMap] = useState<Record<string, SessionFeedbackItem>>({})
  useEffect(() => {
    if (!sessionId) return
    let cancelled = false
    sessionFeedback(sessionId)
      .then((items) => {
        if (cancelled) return
        const map: Record<string, SessionFeedbackItem> = {}
        for (const it of items) map[it.request_id] = it
        setFeedbackMap(map)
      })
      .catch(() => { /* 端点不可用/无权限（apikey 模式）——静默降级 */ })
    return () => { cancelled = true }
  }, [sessionId, feedbackTick, loading])

  const handleVoteMessage = async (requestId: string, value: 1 | -1) => {
    if (!sessionId) return
    const current = feedbackMap[requestId]?.value ?? 0
    if (current === value) return
    try {
      await voteMessage(sessionId, requestId, value)
      setFeedbackMap((prev) => ({
        ...prev,
        [requestId]: { ...(prev[requestId] ?? { request_id: requestId, value: 0, skills: [] }), value },
      }))
    } catch {
      // 投票失败静默——不打断对话
    }
  }

  const lastMessage = messages[messages.length - 1]
  const lastMessageKey = lastMessage
    ? `${lastMessage.id}:${lastMessage.status}:${lastMessage.content.length}`
    : ''
  useEffect(() => {
    if (isPinnedRef.current) scrollToBottom('auto')
  }, [lastMessageKey, messages.length, loading])
  // ── 自动滚动跟随 END ────────────────────────────────────────────

  // 图片缩略图 URL：files 变化时为图片建 objectURL，卸载/变更时回收
  const [thumbUrls, setThumbUrls] = useState<Map<number, string>>(new Map())
  useEffect(() => {
    const created = new Map<number, string>()
    files.forEach((file, index) => {
      if (file.type.startsWith('image/')) {
        created.set(index, URL.createObjectURL(file))
      }
    })
    setThumbUrls(created)
    return () => created.forEach((url) => URL.revokeObjectURL(url))
  }, [files])

  const addFiles = (next: File[]) => {
    setFiles((current) => {
      const merged = [...current]
      for (const file of next) {
        if (
          !merged.some(
            (item) =>
              item.name === file.name &&
              item.size === file.size &&
              item.lastModified === file.lastModified,
          )
        ) {
          merged.push(file)
        }
      }
      if (merged.length > 8) void message.warning('单次最多上传 8 个文件')
      return merged.slice(0, 8)
    })
  }

  const submit = (value: string, displayText?: string) => {
    void send(value, files, displayText)
    setInput('')
    setFiles([])
  }

  const submitClarification = (answer: string) => {
    const value = answer.trim()
    if (!value) return
    void answerClarification(value)
    setClarificationAnswer('')
  }

  if (!agent) {
    return (
      <main className="chat-view">
        <header className="chat-header">
        <Button
          className="mobile-nav-button"
          type="text"
          icon={<MenuOutlined />}
          onClick={onOpenNavigation}
        />
        {bgBadge ? (
          <Tooltip
            title={
              bgBadge.running > 0
                ? `${bgBadge.running} 个后台任务运行中（模型可用 bash_output 查看进度）`
                : `${bgBadge.finishedUnread} 个后台任务已完成，结果待查看`
            }
          >
            <Tag
              icon={<LoadingOutlined />}
              color={bgBadge.running > 0 ? 'processing' : 'default'}
              style={{ marginInlineStart: 8 }}
            >
              {bgBadge.running > 0
                ? `${bgBadge.running} 个后台任务`
                : `${bgBadge.finishedUnread} 个已完成`}
            </Tag>
          </Tooltip>
        ) : null}
        {IS_EMBEDDED ? (
          <Button
            type="text"
            icon={<CloseOutlined />}
            aria-label="关闭面板"
            onClick={closeEmbeddedPanel}
          />
        ) : null}
      </header>
        {agentLoading ? (
          <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', flex: 1 }}>
            <Spin size="large" />
          </div>
        ) : (
          <Result
            status="info"
            title="暂无可用 Agent"
            subTitle="请联系管理员为当前公司分配可调用的 Agent。"
          />
        )}
      </main>
    )
  }

  return (
    <main className="chat-view">
      <header className="chat-header">
        <Button
          className="mobile-nav-button"
          type="text"
          icon={<MenuOutlined />}
          onClick={onOpenNavigation}
          aria-label="打开对话列表"
        />
        {/* 品牌字标 + 当前助手胶囊（v5：品牌露出是功能） */}
        <div className="chat-brand">
          <span className="wordmark">
            <span className="wordmark-m">M</span>EPER Agent
          </span>
          <span className="agent-pill">{agent.name}</span>
        </div>
        {/* todo 清单胶囊：agent 用 todo_write 建清单后显示进度（点击展开明细） */}
        {latestTodos && latestTodos.items.length > 0 ? (
          <Popover
            title="任务清单"
            content={
              <div style={{ minWidth: 220, maxWidth: 300 }}>
                {latestTodos.items.map((t, i) => (
                  <div key={i} style={{ display: 'flex', gap: 7, alignItems: 'flex-start', padding: '3px 0', fontSize: 12 }}>
                    <span style={{ color: t.status === 'completed' ? '#1f9d55' : t.status === 'in_progress' ? '#2b4a9e' : '#98a2b0', flexShrink: 0 }}>
                      {t.status === 'completed' ? '✓' : t.status === 'in_progress' ? '●' : '○'}
                    </span>
                    <span style={{ color: t.status === 'completed' ? '#98a2b0' : '#1f2933' }}>{t.content}</span>
                  </div>
                ))}
              </div>
            }
          >
            <Badge count={`${latestTodos.done}/${latestTodos.items.length}`} style={{ background: '#2b4a9e' }} title="任务清单进度">
              <Button type="text" icon={<OrderedListOutlined />}>
                <span className="desktop-only-label">清单</span>
              </Button>
            </Badge>
          </Popover>
        ) : null}
        {/* 会话文件：仅 jwt 模式（内部测试）保留——内嵌终端用户无工作区概念（v5 裁剪清单） */}
        {!IS_EMBEDDED ? (
          <Button
            type="text"
            icon={<FileOutlined />}
            disabled={!sessionId}
            onClick={() => setFilesOpen(true)}
          >
            <span className="desktop-only-label">会话文件</span>
          </Button>
        ) : null}
        {/* 工作流任务看板入口：仅本会话出现过工作流任务时显示；角标=未查看的新任务数 */}
        {sessionTasks.length > 0 ? (
          <Badge count={unseenTaskCount} size="small" title="未查看的工作流任务">
            <Button
              type="text"
              icon={<DeploymentUnitOutlined />}
              onClick={() => {
                setBoardFocusTaskId(null) // header 进入不定位，平铺看板
                setBoardOpen(true)
              }}
            >
              <span className="desktop-only-label">工作流</span>
            </Button>
          </Badge>
        ) : null}
        {IS_EMBEDDED ? (
          <Button
            type="text"
            icon={<CloseOutlined />}
            aria-label="关闭面板"
            onClick={closeEmbeddedPanel}
          />
        ) : null}
      </header>

      {!sessionId ? (
        agentLoading || sessionsLoading ? (
          <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', flex: 1 }}>
            <Spin size="large" />
          </div>
        ) : (
        <div className="chat-empty">
          <Empty
            image={Empty.PRESENTED_IMAGE_SIMPLE}
            description="还没有对话，开始创建一个吧"
          >
            <Button type="primary" icon={<PlusOutlined />} onClick={onCreateSession}>
              快速创建对话
            </Button>
          </Empty>
        </div>
        )
      ) : (
        <>
          <section
            className="message-viewport"
            aria-live="polite"
            ref={viewportRef}
            onScroll={handleViewportScroll}
            onClick={handleViewportClick}
          >
            {loading ? (
              <div className="message-loading">
                <Skeleton active avatar paragraph={{ rows: 3 }} />
                <Skeleton active paragraph={{ rows: 2 }} />
              </div>
            ) : loadError ? (
              <Alert type="error" showIcon message="历史消息加载失败" description={loadError} />
            ) : messages.length === 0 ? (
              <div className="welcome-state">
                <div className="welcome-mark">{agent.name.slice(0, 1)}</div>
                {agent.welcomeMessage ? (
                  <div className="welcome-message">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {agent.welcomeMessage}
                    </ReactMarkdown>
                  </div>
                ) : (
                  <>
                    <Typography.Title level={2}>和 {agent.name} 开始对话</Typography.Title>
                    <Typography.Paragraph type="secondary">
                      可以直接提问，也可以上传图片、文档或数据文件。
                    </Typography.Paragraph>
                  </>
                )}
              </div>
            ) : (
              <div className="message-flow">
                {/* v5 形制：书写流 + 批注贴（脱离 ant-bubble 范式）。
                    agent = 通栏书写流墨字；user = 右贴边靛蓝批注贴 + 姓氏圆点。 */}
                {messages.map((chatMessage) =>
                  chatMessage.role === 'user' ? (
                    <div className="msg-row msg-row-user" key={chatMessage.id}>
                      <div className="note-user">
                        <MessageContent message={chatMessage} sessionId={sessionId} />
                      </div>
                      <div className="msg-avatar msg-avatar-user">{userInitial}</div>
                    </div>
                  ) : (
                    <div className="msg-row msg-row-ai" key={chatMessage.id}>
                      <div className="msg-avatar msg-avatar-agent">{agent.name.slice(0, 1)}</div>
                      <div className="msg-body">
                        <MessageContent
                          message={chatMessage}
                          sessionId={sessionId}
                          onOpenTaskBoard={(taskId) => {
                            setBoardFocusTaskId(taskId)
                            setBoardOpen(true)
                          }}
                          onRegenerate={
                            running
                              ? undefined
                              : chatMessage.id === lastAssistantId
                                ? handleRegenerate
                                : undefined
                          }
                        />
                        {chatMessage.status !== 'loading' && chatMessage.requestId && (
                          <div className="msg-feedback">
                            <Button
                              aria-label="msg-vote-up"
                              type="text"
                              size="small"
                              title={feedbackMap[chatMessage.requestId]?.value === 1 ? '已点过赞' : '这轮回复有帮助'}
                              onClick={() => void handleVoteMessage(chatMessage.requestId!, 1)}
                              className={
                                feedbackMap[chatMessage.requestId]?.value === 1
                                  ? '!text-blue-500'
                                  : '!text-gray-400 hover:!text-blue-500'
                              }
                              icon={
                                feedbackMap[chatMessage.requestId]?.value === 1 ? (
                                  <LikeFilled />
                                ) : (
                                  <LikeOutlined />
                                )
                              }
                            />
                            <Button
                              aria-label="msg-vote-down"
                              type="text"
                              size="small"
                              title={feedbackMap[chatMessage.requestId]?.value === -1 ? '已点过踩' : '这轮回复没帮助'}
                              onClick={() => void handleVoteMessage(chatMessage.requestId!, -1)}
                              className={
                                feedbackMap[chatMessage.requestId]?.value === -1
                                  ? '!text-red-500'
                                  : '!text-gray-400 hover:!text-red-500'
                              }
                              icon={<LikeOutlined style={{ transform: 'rotate(180deg)' }} />}
                            />
                          </div>
                        )}
                      </div>
                    </div>
                  ),
                )}
              </div>
            )}
          </section>

          <footer className="composer-dock">
            {hitl ? (
              hitl.kind === 'app_authorization' ? (
                <Alert
                  className="hitl-card"
                  type="warning"
                  showIcon
                  icon={<SafetyCertificateOutlined />}
                  message="需要应用授权"
                  description={
                    <div className="clarification-content">
                      <Typography.Text>
                        {hitl.errorKind === 'INVALID'
                          ? `「${hitl.appName || hitl.appId}」的授权凭证已失效（可能修改过密码或用户名），请输入最新凭证后继续。`
                          : `任务需要访问「${hitl.appName || hitl.appId}」，请完成授权后继续。`}
                        {hitl.reason ? `（${hitl.reason}）` : ''}
                      </Typography.Text>
                      <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                        凭证仅用于本次授权，不会出现在对话中。
                      </Typography.Text>
                      {authError ? (
                        <Typography.Text type="danger" style={{ fontSize: 12 }}>
                          {authError}
                        </Typography.Text>
                      ) : null}
                      <div className="clarification-options">
                        <Input
                          value={authUsername}
                          onChange={(event) => setAuthUsername(event.target.value)}
                          placeholder={`「${hitl.appName || hitl.appId || '该应用'}」账号`}
                          autoComplete="off"
                          disabled={authSubmitting || running}
                        />
                        <Input.Password
                          value={authPassword}
                          onChange={(event) => setAuthPassword(event.target.value)}
                          placeholder={`「${hitl.appName || hitl.appId || '该应用'}」密码`}
                          autoComplete="new-password"
                          disabled={authSubmitting || running}
                          onPressEnter={() => {
                            if (!authUsername.trim() || !authPassword) return
                            setAuthSubmitting(true)
                            void answerAppAuthorization(authUsername.trim(), authPassword)
                              .then((error) => {
                                setAuthError(error ?? '')
                                if (!error) {
                                  setAuthUsername('')
                                  setAuthPassword('')
                                }
                              })
                              .finally(() => setAuthSubmitting(false))
                          }}
                        />
                        <Button
                          type="primary"
                          loading={authSubmitting}
                          disabled={!authUsername.trim() || !authPassword || running}
                          onClick={() => {
                            setAuthSubmitting(true)
                            void answerAppAuthorization(authUsername.trim(), authPassword)
                              .then((error) => {
                                setAuthError(error ?? '')
                                if (!error) {
                                  setAuthUsername('')
                                  setAuthPassword('')
                                }
                              })
                              .finally(() => setAuthSubmitting(false))
                          }}
                        >
                          完成授权
                        </Button>
                        <Button
                          type="text"
                          disabled={authSubmitting || running}
                          onClick={() => void declineAppAuthorization()}
                        >
                          暂不授权
                        </Button>
                      </div>
                    </div>
                  }
                />
              ) : hitl.kind === 'workflow_confirmation' ? (
                <Alert
                  className="hitl-card"
                  type="warning"
                  showIcon
                  icon={<QuestionCircleOutlined />}
                  message="工作流确认"
                  description={
                    <div className="clarification-content">
                      <div className="workflow-confirmation-row">
                        <Typography.Text type="secondary">工作流：</Typography.Text>
                        <Typography.Text strong>
                          {hitl.workflowName || '（未命名）'}
                        </Typography.Text>
                      </div>
                      {hitl.workflowDescription ? (
                        <Typography.Text type="secondary">
                          {hitl.workflowDescription}
                        </Typography.Text>
                      ) : null}
                      {hitl.inputPreview &&
                      Object.keys(hitl.inputPreview).length > 0 ? (
                        <div className="workflow-confirmation-params">
                          <Typography.Text type="secondary">输入参数：</Typography.Text>
                          <div className="workflow-confirmation-params-list">
                            {Object.entries(hitl.inputPreview).map(([key, value]) => (
                              <div key={key} className="workflow-confirmation-param">
                                <span className="workflow-confirmation-param-key">
                                  {key}
                                </span>
                                <span className="workflow-confirmation-param-value">
                                  {typeof value === 'string'
                                    ? value
                                    : JSON.stringify(value)}
                                </span>
                              </div>
                            ))}
                          </div>
                        </div>
                      ) : null}
                      <div className="clarification-options">
                        <Button
                          danger
                          type="primary"
                          loading={running}
                          onClick={() => submitClarification('拒绝')}
                        >
                          拒绝
                        </Button>
                        <Button
                          type="primary"
                          loading={running}
                          onClick={() =>
                            submitClarification(
                              `确认执行 ${hitl.workflowName ?? ''}`.trim(),
                            )
                          }
                        >
                          确认执行
                        </Button>
                        <Button type="text" disabled={running} onClick={() => void dismissClarification()}>
                          忽略
                        </Button>
                      </div>
                    </div>
                  }
                />
              ) : (
                <Alert
                  className="hitl-card"
                  type="warning"
                  showIcon
                  icon={<QuestionCircleOutlined />}
                  message={
                    hitl.clarificationType === 'risk_confirmation'
                      ? '操作确认'
                      : 'Agent 需要补充信息'
                  }
                  description={
                    <div className="clarification-content">
                      <Typography.Text>{hitl.question}</Typography.Text>
                      {hitl.context ? (
                        <Typography.Text type="secondary">{hitl.context}</Typography.Text>
                      ) : null}
                      {hitl.fields && hitl.fields.length > 0 ? (
                        <>
                          <ClarificationFormCard
                            question=""
                            context={hitl.context}
                            fields={hitl.fields}
                            answered={false}
                            result={undefined}
                            onSubmit={(jsonStr) => submitClarification(jsonStr)}
                          />
                          <div className="clarification-options">
                            <Button
                              type="text"
                              disabled={running}
                              onClick={() => void dismissClarification()}
                            >
                              忽略此问题，直接重新输入
                            </Button>
                          </div>
                        </>
                      ) : (
                      <>
                      {hitl.options.length > 0 ? (
                        <div className="clarification-options">
                          {hitl.options.map((option) => (
                            <Button
                              key={option}
                              onClick={() => submitClarification(option)}
                            >
                              {option}
                            </Button>
                          ))}
                        </div>
                      ) : null}
                      {hitl.clarificationType === 'risk_confirmation' ? (
                        <div className="clarification-options">
                          <Button onClick={() => submitClarification('取消')}>取消</Button>
                          <Button
                            danger
                            type="primary"
                            onClick={() => submitClarification('确认')}
                          >
                            确认执行
                          </Button>
                        </div>
                      ) : null}
                      <div className="clarification-input">
                        <Input
                          value={clarificationAnswer}
                          onChange={(event) => setClarificationAnswer(event.target.value)}
                          onPressEnter={() => submitClarification(clarificationAnswer)}
                          placeholder="输入你的回答"
                          disabled={running}
                        />
                        <Button
                          type="primary"
                          disabled={!clarificationAnswer.trim() || running}
                          onClick={() => submitClarification(clarificationAnswer)}
                        >
                          发送
                        </Button>
                      </div>
                      {/* 跳过入口：可选问题允许不回答直接继续（下一条消息走普通
                          stream）。文案与 studio 端 ClarificationCard 保持一致。 */}
                      <div className="clarification-options">
                        <Button
                          type="text"
                          disabled={running}
                          onClick={() => void dismissClarification()}
                        >
                          跳过此问题，直接继续 →
                        </Button>
                      </div>
                      </>
                      )}
                    </div>
                  }
                />
              )
            ) : null}
            {files.length > 0 ? (
              <div className="composer-attachments">
                {files.map((file, index) =>
                  file.type.startsWith('image/') ? (
                    <div
                      key={`${index}:${file.name}`}
                      className="att-image-card"
                      role="button"
                      tabIndex={0}
                      title={file.name}
                      onClick={() => {
                        const url = thumbUrls.get(index)
                        if (url) setPendingPreview({ name: file.name, url })
                      }}
                    >
                      {thumbUrls.get(index) ? (
                        <img src={thumbUrls.get(index)} alt={file.name} />
                      ) : (
                        <span className="att-image-loading">…</span>
                      )}
                      <button
                        type="button"
                        className="att-remove"
                        aria-label="移除"
                        onClick={(e) => {
                          e.stopPropagation()
                          setFiles((current) => current.filter((_, i) => i !== index))
                        }}
                      >
                        ✕
                      </button>
                    </div>
                  ) : (
                    <div key={`${index}:${file.name}`} className="att-file-chip">
                      <span className="att-file-icon">📄</span>
                      <span className="att-file-name" title={file.name}>{file.name}</span>
                      <button
                        type="button"
                        className="att-remove"
                        aria-label="移除"
                        onClick={() => setFiles((current) => current.filter((_, i) => i !== index))}
                      >
                        ✕
                      </button>
                    </div>
                  ),
                )}
              </div>
            ) : null}
            {(agent.recommendedItems?.length ?? 0) > 0 || (agent.recommendedGroups?.length ?? 0) > 0 ? (
              <QuickActionsBar
                items={agent.recommendedItems ?? []}
                groups={agent.recommendedGroups}
                disabled={running || Boolean(hitl)}
                onSelect={(item) =>
                  submit(
                    item.prompt || item.label,
                    // prompt 为空时发送的就是 label 本身，无需额外展示文案
                    item.prompt ? item.label : undefined,
                  )
                }
              />
            ) : null}
            {inputMode === 'voice' && voiceAvailable ? (
              <VoiceComposer
                agentId={agent?.id}
                sessionId={sessionId ?? undefined}
                onExit={() => {
                  voiceAbort()
                  setInputMode('text')
                }}
                onTranscriptFinal={voiceAppendUserMessage}
                onTurnStarted={(info) => {
                  voiceBeginAssistantTurn()
                  // voice.start 未带 session_id 时后端新建会话并在此回传
                  if (info.session_id && info.session_id !== sessionId) {
                    onSessionSwitched?.(info.session_id)
                  }
                }}
                onAgentDelta={voiceAppendDelta}
                onTurnEnd={voiceFinishTurn}
                onInterruptRequest={voiceAppendDelta}
              />
            ) : (
            <Sender
              value={input}
              onChange={setInput}
              onSubmit={(value) => submit(value)}
              onCancel={cancel}
              onPasteFile={(pasted) => addFiles(Array.from(pasted))}
              loading={running}
              disabled={Boolean(hitl)}
              placeholder={hitl ? '请先处理待确认操作' : '输入消息，Enter 发送'}
              autoSize={{ minRows: 1, maxRows: 6 }}
              // 默认发送按钮在文本为空时禁用（onSendDisabled: !value），会挡住
              // "仅附件"轮次——有文件排队时改用显式启用的 SendButton 覆盖
              // （其 effect 会同步 submitDisabled=false，Enter 发送同样放行）。
              suffix={(originNode, { components }) =>
                files.length > 0 && !running ? (
                  <components.SendButton disabled={false} />
                ) : (
                  originNode
                )
              }
              prefix={
                <>
                  {voiceAvailable && (
                    <Tooltip title="切换到语音输入">
                      <Button
                        type="text"
                        icon={<AudioOutlined />}
                        onClick={() => setInputMode('voice')}
                        aria-label="切换到语音输入"
                        disabled={running || Boolean(hitl)}
                      />
                    </Tooltip>
                  )}
                  <Tooltip title={localDir ? '本地目录会话：文件请直接放入绑定的本地目录' : undefined}>
                    <Button
                      type="text"
                      icon={<PaperClipOutlined />}
                      onClick={() => fileInputRef.current?.click()}
                      aria-label="上传附件"
                      disabled={running || Boolean(hitl) || Boolean(localDir)}
                    />
                  </Tooltip>
                </>
              }
            />
            )}
            <input
              ref={fileInputRef}
              className="hidden-file-input"
              type="file"
              multiple
              onChange={(event) => {
                addFiles(Array.from(event.target.files ?? []))
                event.currentTarget.value = ''
              }}
            />
            <Typography.Text className="composer-note" type="secondary">
              Agent 输出可能有误，请核对关键结果。写操作执行前会再次确认。
            </Typography.Text>
          </footer>
        </>
      )}

      <GeneratedFiles
        sessionId={sessionId}
        open={filesOpen}
        onClose={() => setFilesOpen(false)}
        refreshKey={filesRefreshKey}
      />
      <WorkflowBoard
        tasks={sessionTasks}
        open={boardOpen}
        onClose={() => setBoardOpen(false)}
        focusTaskId={boardFocusTaskId}
      />
      <Modal
        title={pendingPreview?.name}
        open={Boolean(pendingPreview)}
        footer={null}
        onCancel={() => {
          if (pendingPreview?.url) URL.revokeObjectURL(pendingPreview.url)
          setPendingPreview(null)
        }}
        destroyOnHidden
      >
        {pendingPreview ? (
          <Image
            className="file-preview-image"
            src={pendingPreview.url}
            alt={pendingPreview.name}
            preview={false}
          />
        ) : null}
      </Modal>
    </main>
  )
}

import { useState, useRef, useEffect, useLayoutEffect, useMemo, Fragment, FormEvent, useCallback, type MouseEvent, type ChangeEvent, type ReactNode } from 'react';
import { Agent, Message, type ChatAttachment, type TimelineEntry } from '../types';
import {
  Send, Plus, FileCode, CheckCircle, Check,
  Bot, Terminal, Loader2, Paperclip, Brain, X, ClipboardList, ShieldAlert,
  Wrench, AlertTriangle, ChevronRight, ChevronDown, User, Download, FileText, Image as ImageIcon, Mic, Copy, RotateCcw,
  PenLine, SquarePen, FolderSearch, Search, Globe, Link2, BarChart3, FileSearch, BookOpen,
  ThumbsUp, ThumbsDown, PanelRight, Workflow,
  FolderOpen, LayoutDashboard, Shield, ArrowLeftRight, Key,
} from 'lucide-react';
import { toast } from './ui/toast';
import { IconAgent, IconTask, IconFlow, IconResource } from './IndigoIcons';
import { NotificationCenter } from './notification-center';
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query';
import { Popover } from './ui';
import { userSkillsApi, type SessionFeedbackItem } from '../services/user-skills-api';
import {
  sessionApi, sessionKeys, type Session, type MessageRecord, type FileRef, getFileId,
} from '../services/session-api';
import { agentApi, agentKeys, type DoneTimelineEntry, type ThinkingLevel } from '../services/agent-api';
import { toStudioAgent } from '../services/adapters';
import { getFileBlob, downloadFile as downloadFileById } from '../services/file-api';
import { parseSSEStream } from '../lib/sse-parser';
import { formatFileSize } from '../lib/file-preview';
import { formatTimeFull } from '../lib/formatTime';
import { countZi, truncateByZi } from '../lib/text-stats';
import { SessionFilesPanel, type SessionFilesPanelHandle } from './SessionFilesPanel';
import AvatarRender from './AvatarRender';
import { Markdown } from './Markdown';
import { detectPreviewKind } from './FilePreview';
import { FilePreviewModal } from './FilePreviewModal';
import { WorkflowTaskCard, parseTaskCreated } from './WorkflowTaskCard';
import WorkflowProposalCard from './workflow-proposal-card';
import {
  ClarificationFormCard,
  DISMISSED_CLARIFICATION_TEXT,
  type ClarificationField,
} from './clarification-form-card';
import { voiceConfigApi, voiceConfigKeys } from '../services/voice-config-api';

// 思考档位元数据：label=档位文字，color=强度色（信号色 token，明暗主题自适应；
// off=灰 / low=绿 / medium=黄 / high=橙红）。
import { ActivityGroup, StreamingDots } from './chat/ActivityGroup';
import { ChatAttachmentCard } from './chat/ChatAttachmentCard';
import { Composer } from './chat/Composer';
import { ChatSidebar } from './chat/ChatSidebar';
import { MessageList } from './chat/MessageList';
import { useModelLabels } from './chat/useModelLabels';
import { ArtifactsPanel } from './chat/ArtifactsPanel';
import { EmptySession } from './chat/EmptySession';
import { SessionHeader } from './chat/SessionHeader';
import { userMessageToDisplay, agentMessageToDisplay, doneTimelineToEntries, formatSessionTime, isInterruptTool, parseOutputAttachments } from './chat/message-utils';

interface ChatHomepageProps {
  /** Studio agents already adapted to the view model; if absent we fetch. */
  agents?: Agent[];
  theme?: 'light' | 'dark';
  /** 固定 agent 模式：会话列表按该 agent 过滤，点 + 直通新建会话（不弹选择框）。 */
  fixedAgentId?: string;
  /** 侧栏功能项点击后跳转 App tab。 */
  onNavigate?: (tab: string) => void;
  /** App 下发的权限过滤导航项（含实时计数）：功能 4 项与「··· 更多」菜单由此派生。 */
  navItems?: { id: string; label: string; badge?: string }[];
  /** 当前激活的 App tab（非聊天页面态用于功能项选中高亮）。 */
  activeId?: string;
  /** 非聊天路由的右侧内容（license 条 + 页面 stage）；null = 渲染聊天面板。
   *  本组件是全局壳层：侧栏在任何页面都常驻不变，只有右侧区域切换。 */
  activePage?: ReactNode;
  /** 侧栏头像下拉：登出（App 层吊销 token 并跳登录页）。 */
  onLogout?: () => void;
  /** 用户名首字（侧栏底部头像）。 */
  userInitial?: string;
  /** 用户名（底部用户条展示）。 */
  username?: string;
  /** 通知点击跳转任务详情（App 层切换看板+打开详情）。 */
  onNavigateTask?: (taskId: string) => void;
}

/** 「更改」菜单条目图标（与 App NAV_ITEMS 同款 lucide） */

/** 「更改」菜单条目图标（与 App NAV_ITEMS 同款 lucide） */

export function ChatHomepage({ agents: agentsProp, theme = 'dark', fixedAgentId,
                               onNavigate, navItems, activeId, activePage, onLogout, userInitial, username, onNavigateTask }: ChatHomepageProps) {
  const qc = useQueryClient();

  // ── Agents (fallback fetch if not passed in) ──
  const { data: agentsData } = useQuery({
    queryKey: agentKeys.list({ page: 1, page_size: 50, status: 'all' }),
    queryFn: () => agentApi.list({ page: 1, page_size: 50, status: 'all' }),
    enabled: !agentsProp || agentsProp.length === 0,
    staleTime: 60_000,
  });
  const agents: Agent[] =
    agentsProp && agentsProp.length > 0
      ? agentsProp
      : (agentsData?.items ?? []).map(toStudioAgent);
  // `agents` is recomputed (new array ref) on every render via .map(), so it
  // must NOT be a dependency of the history-loading effect — otherwise that
  // effect re-fires mid-stream and wipes the optimistic first message. Keep a
  // ref so the effect can read the latest agent name/avatar without re-running.
  const agentsRef = useRef<Agent[]>(agents);
  agentsRef.current = agents;

  const { modelLabel } = useModelLabels();

  const { data: voiceStatus } = useQuery({
    queryKey: voiceConfigKeys.status,
    queryFn: voiceConfigApi.status,
    staleTime: 60_000,
    retry: false,
  });
  const voiceConfigured = voiceStatus?.configured === true;

  // ── Sessions list ──
  // 当前对话对象的意图态：尚未有会话（空白新对话）时指向目标 agent。
  // 切换 agent 只设置此值，首次发送消息时才真正创建会话。
  const [draftAgentId, setDraftAgentId] = useState<string | null>(null);
  // agents 首次加载后默认与第一个 agent 对话（固定 agent 模式则固定为该 agent），
  // 会话列表从一开始就按 agent 过滤，不混入其他 agent 的对话。
  useEffect(() => {
    if (draftAgentId === null && agents.length > 0) {
      setDraftAgentId(fixedAgentId ?? agents[0].id);
    }
  }, [agents, draftAgentId, fixedAgentId]);

  // 会话列表始终按当前对话对象过滤（固定 agent 模式优先），不混入其他 agent 的对话。
  const filterAgentId = fixedAgentId ?? draftAgentId;
  const { data: sessionsData, isLoading: sessionsLoading } = useQuery({
    queryKey: filterAgentId ? sessionKeys.list({ agent_id: filterAgentId }) : sessionKeys.lists(),
    queryFn: () =>
      sessionApi.list({
        page: 1,
        page_size: 50,
        ...(filterAgentId ? { agent_id: filterAgentId } : {}),
      }),
    staleTime: 15_000,
  });
  const sessions: Session[] = sessionsData?.items ?? [];

  const [activeSessionId, setActiveSessionId] = useState<string | null>(null);
  // 空白态发送时新创建的会话 id：流式期间不绑定 activeSessionId（避免消息加载
  // effect 清空流式占位），done/流终止时再绑定并加载权威数据。
  const createdSessionIdRef = useRef<string | null>(null);
  // 已创建但尚未绑定（流结束才 setActiveSessionId）的新会话 id：仅供侧栏
  // 高亮兜底——发送时侧栏条目立即出现且选中，输出结束不发生"灰→亮"跳变
  const [pendingSessionId, setPendingSessionId] = useState<string | null>(null);
  // 前端记录的工具耗时（toolCallId → 时间）：落库 timeline 无时间戳，而消息加载
  // effect 会先清空 liveMessages 再拉取，state 途径取不到——用 ref 跨阶段兜底。
  const toolTimesRef = useRef(new Map<string, { startedAt?: number; endedAt?: number }>());

  // ── 消息级反馈（§8.2 v2）：会话各轮投票态，流结束/切会话时刷新 ──
  const [feedbackTick, setFeedbackTick] = useState(0);
  const [feedbackMap, setFeedbackMap] = useState<Record<string, SessionFeedbackItem>>({});
  useEffect(() => {
    if (!activeSessionId) return;
    let cancelled = false;
    userSkillsApi.sessionFeedback(activeSessionId)
      .then((items) => {
        if (cancelled) return;
        const map: Record<string, SessionFeedbackItem> = {};
        for (const it of items) map[it.request_id] = it;
        setFeedbackMap(map);
      })
      .catch(() => { /* 端点不可用（旧后端）——静默 */ });
    return () => { cancelled = true; };
  }, [activeSessionId, feedbackTick]);

  const handleVoteMessage = useCallback(async (requestId: string, value: 1 | -1) => {
    if (!activeSessionId) return;
    const current = feedbackMap[requestId]?.value ?? 0;
    if (current === value) return;  // 同向已投——no-op
    try {
      await userSkillsApi.voteMessage(activeSessionId, requestId, value);
      setFeedbackMap((prev) => ({
        ...prev,
        [requestId]: { ...(prev[requestId] ?? { request_id: requestId, value: 0, skills: [] }), value },
      }));
    } catch {
      // 投票失败静默——不打断对话
    }
  }, [activeSessionId, feedbackMap]);

  // 侧栏「··· 更多」下拉（收纳非核心功能入口，权限过滤自 navItems）
  const [moreMenuOpen, setMoreMenuOpen] = useState(false);
  // ── 图钉固定导航（设计稿 sidebar-more.html）：固定项追加在主功能之后，localStorage 持久化 ──
  const [pinnedNav, setPinnedNav] = useState<string[]>(() => {
    try { return JSON.parse(localStorage.getItem('agentflow_pinned_nav') ?? '[]') } catch { return [] }
  })
  useEffect(() => {
    localStorage.setItem('agentflow_pinned_nav', JSON.stringify(pinnedNav))
  }, [pinnedNav])
  const togglePin = (id: string) =>
    setPinnedNav((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))
  // 侧栏底部头像下拉（个人设置 / 登出）：点击外部关闭
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const userMenuRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!userMenuOpen) return;
    // 注意：本文件已从 react 导入 MouseEvent 类型，这里不能显式注解（会遮蔽 DOM 事件类型）
    const handler = (e: globalThis.MouseEvent) => {
      if (userMenuRef.current && !userMenuRef.current.contains(e.target as Node)) {
        setUserMenuOpen(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [userMenuOpen]);
  /* ─── v3.2 可拉伸布局：会话列表宽 / 右侧功能区宽与开关 ─── */
  const rootRef = useRef<HTMLDivElement>(null);
  const [sessW, setSessW] = useState(() => Number(localStorage.getItem('agentflow_chat_sess_w')) || 240);
  const [panelOpen, setPanelOpen] = useState(() => localStorage.getItem('agentflow_chat_panel') === '1');
  const [panelW, setPanelW] = useState(() => Number(localStorage.getItem('agentflow_chat_panel_w')) || 340);
  const [agentMenuOpen, setAgentMenuOpen] = useState(false);
  /** 通用列宽拖拽：mousedown 起手，mousemove 连续回调，mouseup 收尾。 */
  const startColDrag = (e: React.MouseEvent, onMove: (clientX: number) => void) => {
    e.preventDefault();
    e.stopPropagation();
    const move = (ev: globalThis.MouseEvent) => onMove(ev.clientX);
    const up = () => {
      document.removeEventListener('mousemove', move);
      document.removeEventListener('mouseup', up);
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
    };
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';
    document.addEventListener('mousemove', move);
    document.addEventListener('mouseup', up);
  };
  const [inputText, setInputText] = useState('');
  const [inputMode, setInputMode] = useState<'text' | 'voice'>('text');
  const [isStreaming, setIsStreaming] = useState(false);
  // 当前流式中的 agent 消息 id（文本/语音两路占位消息）——消息级"生成中"动效
  // 的判据。不能用 msg.status 判：thinking final / tool_call_start 会把它清成
  // undefined（避免工具期误显"思考中"），导致思考完成→正文生成、工具完成→
  // 下一轮等空窗期失去执行中指示（用户分不清回答结束还是仍在等）。
  const [streamingMsgId, setStreamingMsgId] = useState<string | null>(null);
  // Live messages for the active session (history + in-flight stream deltas).
  const [liveMessages, setLiveMessages] = useState<Message[]>([]);
  const artifactCount = useMemo(
    () => liveMessages.reduce((n, m) => n + (m.attachments?.length ?? 0), 0),
    [liveMessages],
  );

  const [streamError, setStreamError] = useState<string | null>(null);
  // Thinking mode toggle (enable_thinking execution param) + pending file attachments.
  // NOTE: pendingFiles holds raw File objects queued locally — the actual upload
  // happens inside handleSendMessage (before the stream fires), mirroring
  // frontend/src/components/chat-panel.tsx. This avoids the race where the text
  // prompt is sent before the file upload resolves.
  // 思考强度档位（thinking_level）：off=直答；low/medium/high 按厂商映射
  // （o-series effort 直传 / Anthropic budget / Qwen·GLM 开关）。
  const [thinkingLevel, setThinkingLevel] = useState<ThinkingLevel>('medium');
  const [modelMenuOpen, setModelMenuOpen] = useState(false);
  // 聊天中切换模型 = 回写该 Agent 的 default_model（每请求现读 agent doc，
  // 计划模式（plan_mode）：只调研不执行，agent 产出计划书卡片（propose_plan，
  // 文档样式）待审批。批准后自动关闭；反馈/重新规划时保持开启。
  // 刻意不持久化：计划模式是任务级开关而非会话偏好——刷新/切会话重置为
  // 关（安全方向默认），可见性由常驻横幅承担（有横幅=开，无=关，零歧义）；
  // 刷新后的反馈 resume 由服务端 checkpoint 推断兜底，不依赖本开关。
  const [planMode, setPlanMode] = useState(false);
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  // Right-pane tab: 'chat' (messages) | 'files' (generated-file manager).
  const [rightTab, setRightTab] = useState<'chat' | 'files'>('chat');

  const messageEndRef = useRef<HTMLDivElement>(null);
  // 对话滚动容器：贴底判定用（只有输出贴底时才自动跟随，见 isPinnedToBottom）。
  const chatScrollRef = useRef<HTMLDivElement>(null);
  // 每次消息更新【前】捕获的贴底状态：DOM 提交后据此决定是否跟随滚动。
  // 不能在 effect 里现测——新内容撑高后距底必超阈值，守卫会永久脱锁，
  // 表现为流式输出不再自动跟随（需手动滚动）。
  const pinnedRef = useRef(true);
  const abortRef = useRef<AbortController | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  // 输入框高度自适应：随内容增高（rows=2 起），超上限转内部滚动。
  const inputTextareaRef = useRef<HTMLTextAreaElement>(null);
  const filesPanelRef = useRef<SessionFilesPanelHandle>(null);
  const voiceAgentMsgIdRef = useRef<string | null>(null);
  // ask_clarification / confirm_workflow 中断态：SSE 收到 interrupt 或历史回填时
  // 记录对应的消息 id，使下一次发送走 /resume 而非 /stream（避免 agent 重复提问）。
  const pendingInterruptRef = useRef<{ toolMsgId: string } | null>(null);
  // 流式回答中被切换走的会话：后端后台任务仍会跑完并把完整回答一次性落库。
  // 记录这些 sessionId，切回时轮询 getDetail 直到 agent 回复落库后整体显示。
  const pendingBackgroundSessionsRef = useRef<Set<string>>(new Set());

  // ── Timeline 流式渲染 refs（对齐 frontend chat-panel 的 RAF 批处理）──
  // 每个 text_delta 只进 buffer，一帧最多 setState 一次，保证平滑且多轮
  // text→tool→text 顺序正确（tool_call_start 重置 textEntryIdRef 让新轮 text
  // 开新 entry）。
  const deltaBufferRef = useRef<{ agentMsgId: string; delta: string } | null>(null);
  const rafIdRef = useRef<number | null>(null);
  const textEntryIdRef = useRef<string | null>(null);
  const textStartedRef = useRef(false);


  /** 输出是否贴底（距底部 120px 内）。自动跟随滚动只在贴底时发生——
   *  用户上翻阅读历史、或点开工具/思考详情时，即使 liveMessages 变化
   *  （流式输出/展开收起）也不会把视口拽到底部。
   *  注意：只允许在消息更新【前】调用（DOM 反映用户真实阅读位置），
   *  更新后检测会把"单帧新增内容超 120px"误判为用户上翻。 */
  const isPinnedToBottom = useCallback((): boolean => {
    const el = chatScrollRef.current;
    if (!el) return true;
    return el.scrollHeight - el.scrollTop - el.clientHeight < 120;
  }, []);
  // 用户是否上翻离开底部（显示「回到底部」浮标）
  const [showJumpToBottom, setShowJumpToBottom] = useState(false);

  /** 统一的流式消息更新入口：更新前捕获贴底状态，滚动 effect 据此跟随。 */
  const updateLiveMessages = useCallback(
    (updater: Message[] | ((prev: Message[]) => Message[])) => {
      pinnedRef.current = isPinnedToBottom();
      setLiveMessages(updater);
    },
    [isPinnedToBottom],
  );

  /** 把累积的 delta flush 进 agent 消息的 timeline（追加到当前 text entry 或新建）。 */
  const flushDelta = useCallback(() => {
    rafIdRef.current = null;
    const buf = deltaBufferRef.current;
    if (!buf) return;
    deltaBufferRef.current = null;
    const { agentMsgId, delta } = buf;
    updateLiveMessages((prev) =>
      prev.map((m) => {
        if (m.id !== agentMsgId) return m;
        const tl = [...(m.timeline ?? [])];
        const existingId = textEntryIdRef.current;
        if (
          existingId &&
          tl.length > 0 &&
          tl[tl.length - 1].id === existingId &&
          tl[tl.length - 1].type === 'text'
        ) {
          // 快路径：ref 命中末尾 text entry，直接追加。
          tl[tl.length - 1] = { ...tl[tl.length - 1], content: tl[tl.length - 1].content + delta };
        } else if (textStartedRef.current && tl.length > 0 && tl[tl.length - 1].type === 'text') {
          // 同一 LLM 输出阶段（无 tool_call 介入），合并进末尾 text entry。
          const lastIdx = tl.length - 1;
          tl[lastIdx] = { ...tl[lastIdx], content: tl[lastIdx].content + delta };
          textEntryIdRef.current = tl[lastIdx].id;
        } else {
          // 新文本块（首个 delta，或 tool_call 之后）：push 新 entry。
          const newId = `${agentMsgId}-text-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
          tl.push({ id: newId, type: 'text', content: delta });
          textEntryIdRef.current = newId;
          textStartedRef.current = true;
        }
        return { ...m, timeline: tl };
      }),
    );
    // 滚动统一交给 liveMessages 的 layout effect（依据更新前 pinnedRef）。
  }, [updateLiveMessages]);

  /** 累积 text_delta 进 buffer，调度 RAF flush（一帧一次）。 */
  const appendDelta = useCallback(
    (agentMsgId: string, delta: string) => {
      const prev = deltaBufferRef.current;
      if (prev && prev.agentMsgId === agentMsgId) prev.delta += delta;
      else deltaBufferRef.current = { agentMsgId, delta };
      if (!rafIdRef.current) rafIdRef.current = requestAnimationFrame(flushDelta);
    },
    [flushDelta],
  );

  const activeSession = sessions.find((s) => s._id === activeSessionId) ?? null;
  // 固定 agent 模式无会话时恒为该 agent；普通模式按 activeSession → draft → 首个。
  const activeAgent =
    agents.find((a) => a.id === activeSession?.agent_id) ??
    (fixedAgentId ? agents.find((a) => a.id === fixedAgentId) : null) ??
    agents.find((a) => a.id === draftAgentId) ??
    agents[0] ??
    null;
  const voiceAvailable = voiceConfigured && activeAgent?.voiceEnabled === true;
  // 语音按钮常显，tooltip 按不可用原因给出引导（未选 Agent / 服务未配置 / Agent 未开语音）
  const voiceHint = !activeAgent
    ? '选择 Agent 后可语音对话'
    : !voiceConfigured
      ? '语音服务未配置（设置 → 语音）'
      : activeAgent.voiceEnabled
        ? '切换到语音对话'
        : '该 Agent 未开启语音能力（智能体编辑页可开启）';

  useEffect(() => {
    if (inputMode === 'voice' && !voiceAvailable) setInputMode('text');
  }, [inputMode, voiceAvailable]);
  // ── 输入框 auto-grow ──
  // 大量文本时输入框随内容增高（消息区 flex-1 min-h-0 自动让位），超过上限
  // （160px ≈ 8 行）切换为内部滚动方便回看编辑；发送清空后缩回初始高度（空会话 rows=4 / 会话 rows=2）。
  useEffect(() => {
    const el = inputTextareaRef.current;
    if (!el) return;
    const maxHeight = 160;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, maxHeight)}px`;
    el.style.overflowY = el.scrollHeight > maxHeight ? 'auto' : 'hidden';
  }, [inputText, activeSession]);


  // Auto-select latest session once, on initial load only. 之后进入空白态
  // （切 agent / 点 + 新对话）不再自动抓回旧会话——新对话就该是空 composer，
  // 首次发送时才创建会话；想续旧会话从列表显式点入。
  // 竞态守卫：等 filterAgentId 就绪才选中——draftAgentId 默认化前 query 可能
  // 先送来全量列表，选中其他 agent 的会话会让 activeSession 游离在列表外。
  const autoSelectedRef = useRef(false);
  useEffect(() => {
    if (!autoSelectedRef.current && !activeSessionId && filterAgentId && sessions.length > 0) {
      const target = sessions.find((s) => s.agent_id === filterAgentId);
      if (target) {
        autoSelectedRef.current = true;
        setActiveSessionId(target._id);
      }
    }
  }, [sessions, activeSessionId, filterAgentId]);

  // Load messages when the active session changes.
  // NOTE: depends on `activeSessionId` only. `agents` is recomputed (new array
  // ref) on every render, so listing it as a dependency would re-fire this
  // effect mid-stream and wipe the optimistic first message. Read it via
  // agentsRef instead. Likewise guard against re-entry while a stream is live.
  // Load messages when the active session changes. NOTE: depends on `activeSessionId`
  // only — `agents` is a fresh array every render, listing it would re-fire mid-stream
  // and wipe the optimistic first message; read it via agentsRef instead. There is NO
  // streaming guard here: switching sessions mid-stream is the legitimate trigger, and
  // handleSelectSession aborts the in-flight stream first so this load takes over.
  useEffect(() => {
    let cancelled = false;
    let pollTimer: ReturnType<typeof setTimeout> | null = null;
    const sid = activeSessionId;
    if (!sid) {
      setLiveMessages([]);
      pinnedRef.current = true;
      return;
    }
    // 不预清空：保留旧内容直到落库数据就绪一次性替换（stale-while-revalidate
    // 的 UI 等价物）——"清空→白屏等待→回填"的高度两次跳变才是闪/抖的来源。
    // 切换会话的旧请求不写回由上方 cancelled 守卫保证；新会话绑定场景 prev
    // 即刚流完的消息，替换时同位置同角色沿用原 id（见 load 内配对），原地更新。
    // 会话切换/清空后回到贴底初始态：加载完成即定位到最新消息。
    pinnedRef.current = true;
    setStreamError(null);

    // Session switched away mid-stream: the backend asyncio task keeps running and
    // persists the full reply once finished. Poll getDetail until the agent reply
    // lands (messages end with role==='agent' — normal/interrupt/error turns all
    // produce one) or the timeout elapses, then render in one shot.
    const pollStartedAt = Date.now();
    const POLL_INTERVAL = 1500;
    const POLL_TIMEOUT = 90000;

    const load = () => {
      sessionApi
        .getDetail(sid)
        .then((detail) => {
          if (cancelled) return;
          const mapped: Message[] = [];
          for (const rec of detail.messages) {
            if (rec.role === 'user') mapped.push(userMessageToDisplay(rec));
            else {
              const agent = agentsRef.current.find((a) => a.id === detail.session.agent_id);
              mapped.push(
                agentMessageToDisplay(rec, agent?.name ?? 'Agent', agent?.avatar ?? ''),
              );
            }
          }
          // 会话加载完成回到贴底：最新消息就在底部。
          pinnedRef.current = true;
          // 落库 timeline 无工具耗时：从 ref 里把前端记录的 startedAt/endedAt
          // 按 toolCallId 回填（否则 done 后绑定会话触发本加载，收起态组头的
          // 执行耗时会闪一下就消失——effect 先行清空了 liveMessages，state
          // 途径取不到流式数据）。
          setLiveMessages(() => {
            const times = toolTimesRef.current;
            if (!times.size) return mapped;
            return mapped.map((m) =>
              m.timeline?.some((e) => e.type === 'tool' && e.toolCallId && times.has(e.toolCallId))
                ? {
                    ...m,
                    timeline: m.timeline.map((e) =>
                      e.type === 'tool' && e.toolCallId && times.has(e.toolCallId)
                        ? { ...e, ...times.get(e.toolCallId) }
                        : e,
                    ),
                  }
                : m,
            );
          });
          // 检测未答的 interrupt（ask_clarification/confirm_workflow）：页面跳转后
          // SSE 中断导致 pendingInterruptRef 丢失，从历史恢复，使下次发送走 /resume。
          const pending = [...mapped].reverse().find((m) => m.isInterrupted);
          if (pending) pendingInterruptRef.current = { toolMsgId: pending.id };

          if (pendingBackgroundSessionsRef.current.has(sid)) {
            const lastIsAgent =
              detail.messages.length > 0 &&
              detail.messages[detail.messages.length - 1].role === 'agent';
            if (lastIsAgent) {
              // 后端已落库完整回答，停止轮询。
              pendingBackgroundSessionsRef.current.delete(sid);
            } else if (Date.now() - pollStartedAt < POLL_TIMEOUT) {
              pollTimer = setTimeout(load, POLL_INTERVAL);
            } else {
              // 超时仍未落库（后端异常），放弃轮询。
              pendingBackgroundSessionsRef.current.delete(sid);
            }
          }
        })
        .catch((e) => {
          if (cancelled) return;
          // 会话已被删除（404 / “不存在”）：静默回到空状态，不弹报错横幅。
          const status = (e as { response?: { status?: number } })?.response?.status;
          const msg = (e as Error).message ?? '';
          if (status === 404 || /不存在|not found/i.test(msg)) {
            setActiveSessionId(null);
            setLiveMessages([]);
            pinnedRef.current = true;
            pendingBackgroundSessionsRef.current.delete(sid);
            return;
          }
          setStreamError(`加载会话失败：${msg}`);
        });
    };
    load();

    return () => {
      cancelled = true;
      if (pollTimer) clearTimeout(pollTimer);
    };
  }, [activeSessionId]);

  // 贴底时跟随滚动（流式输出/展开收起）。依据 pinnedRef（更新前捕获）而非现测
  // 几何距离——新内容渲染后距底必超阈值，现测会把内容增长误判为用户上翻，
  // 守卫永久脱锁导致流式输出不再跟随。瞬时跳底（paint 前）避免 smooth 动画
  // 在高频 delta 下被打断、滞后累积。
  useLayoutEffect(() => {
    if (!pinnedRef.current) return;
    const el = chatScrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
    else messageEndRef.current?.scrollIntoView();
    // 跳底 = 回到最新：浮标必隐。兜底程序跳底后内容收缩时浏览器 clamp
    // scrollTop 触发的 scroll 事件被上翻判定误读（收起动画期间高发）。
    setShowJumpToBottom(false);
  }, [liveMessages]);

  const refreshSessions = useCallback(() => {
    qc.invalidateQueries({ queryKey: sessionKeys.lists() });
  }, [qc]);

  const handleSelectSession = (id: string) => {
    setInputMode('text');
    if (isStreaming && id !== activeSessionId) {
      // 流式中切到别的会话：打断前端 SSE 渲染（后端后台任务不受影响，会继续跑完
      // 落库）。标记原会话为"后台进行中"，以便切回时轮询 getDetail 拉取落库结果。
      pendingBackgroundSessionsRef.current.add(activeSessionId);
      abortRef.current?.abort();
      setIsStreaming(false);
    }
    setActiveSessionId(id);
    // 全局侧栏：从其它功能页点会话 → 回到聊天界面
    onNavigate?.('chat');
  };

  const handleDeleteSession = async (e: MouseEvent, id: string) => {
    e.stopPropagation();
    try {
      await sessionApi.remove(id);
      // 删除当前会话时，主动选中相邻的下一个仍存在的会话；一个都不剩则
      // 置空进入空状态引导。不依赖自动选中 effect——它可能从尚未刷新的
      // 列表缓存里挑回刚删的那个会话，触发 getDetail 404 报错。
      if (activeSessionId === id) {
        setInputMode('text');
        const idx = sessions.findIndex((s) => s._id === id);
        const remaining = sessions.filter((s) => s._id !== id);
        const next = remaining[idx] ?? remaining[idx - 1] ?? null;
        setActiveSessionId(next?._id ?? null);
      }
      refreshSessions();
    } catch (err) {
      setStreamError(`删除会话失败：${(err as Error).message}`);
    }
  };

  // 切换对话对象：只进入空白新对话态，不立即创建会话——首次发送时才真正
  // 创建（见 handleSendMessage），避免用户未输入就在后端留下空会话。
  const handleStartNewWithAgent = (agent: Agent) => {
    setDraftAgentId(agent.id);
    setActiveSessionId(null);
    setPendingSessionId(null);
    setInputMode('text');
    setAgentMenuOpen(false);
    // 全局侧栏：从其它功能页点「＋」→ 回到聊天界面空白新对话
    onNavigate?.('chat');
  };

  /** Pick a file into the local queue (no network upload yet — that happens
   *  at send time in handleSendMessage, so text + files dispatch together). */
  const handleUploadFile = (e: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    e.target.value = ''; // reset so the same file can be re-picked
    if (files.length) {
      setPendingFiles((prev) => [...prev, ...files]);
    }
  };

  /** Send a message and consume the SSE stream into liveMessages. */
  // 忽略待答的澄清/确认卡片：持久化忽略标记（后端合成 tool_result，刷新后
  // 不复活），本地关闭卡片交互态并清 pending 路由——之后用户正常发送的
  // 消息/附件走 /stream 新一轮（挂起的 interrupt 由后端新输入自然丢弃）。
  const handleDismissInterrupt = async (msgId: string) => {
    const sessionId = activeSessionId;
    const agent = activeAgent;
    if (!sessionId || !agent || isStreaming) return;
    try {
      await agentApi.dismissInterrupt(agent.id, sessionId);
    } catch (err) {
      setStreamError(`忽略失败：${(err as Error).message}`);
      return;
    }
    updateLiveMessages((prev) =>
      prev.map((m) => {
        if (m.id !== msgId) return m;
        // 把 timeline 里第一个未答的 interrupt tool entry 填上忽略标记。
        let dismissed = false;
        const tl = (m.timeline ?? []).map((e) => {
          if (
            !dismissed &&
            e.type === 'tool' &&
            isInterruptTool(e.toolName) &&
            !e.result
          ) {
            dismissed = true;
            return { ...e, result: DISMISSED_CLARIFICATION_TEXT };
          }
          return e;
        });
        return { ...m, isInterrupted: false, timeline: tl };
      }),
    );
    if (pendingInterruptRef.current?.toolMsgId === msgId) {
      pendingInterruptRef.current = null;
    }
  };

  // 批准计划（零 LLM 成本）：写 PLAN.md + 合成 tool_result 终止挂起，
  // 随后自动发送 kickoff 消息触发执行（新 run、全量工具、读 PLAN.md、
  // 逐项对照验收标准）。编辑后的版本以传入 plan 为准落盘。
  const handleApprovePlan = async (msgId: string, plan: string) => {
    const sessionId = activeSessionId;
    const agent = activeAgent;
    if (!sessionId || !agent || isStreaming) return;
    if (!plan.trim()) {
      setStreamError('计划内容为空，无法批准');
      return;
    }
    try {
      await agentApi.approvePlan(agent.id, sessionId, plan);
    } catch (err) {
      setStreamError(`批准失败：${(err as Error).message}`);
      return;
    }
    setPlanMode(false); // 执行轮 = 普通 chat 语义（全量工具）
    if (pendingInterruptRef.current?.toolMsgId === msgId) {
      pendingInterruptRef.current = null;
    }
    updateLiveMessages((prev) =>
      prev.map((m) => {
        if (m.id !== msgId) return m;
        let answered = false;
        const tl = (m.timeline ?? []).map((e) => {
          if (!answered && e.type === 'tool' && e.toolName === 'propose_plan' && !e.result) {
            answered = true;
            return {
              ...e,
              result: '用户已批准该计划（全文已写入 workspace/PLAN.md）。',
              toolStatus: 'success' as const,
            };
          }
          return e;
        });
        return { ...m, isInterrupted: false, timeline: tl };
      }),
    );
    // 批准即执行：kickoff 新一轮——指示读取 PLAN.md（抗压缩事实源）、
    // 每步勾选、完成前逐项对照验收标准。
    await handleSendMessage(
      undefined,
      '计划已获批准，全文见 workspace 的 PLAN.md。请先读取 PLAN.md，然后逐条按步骤执行；'
        + '每完成一步将对应 checkbox 勾选为 [x]；全部完成后逐项对照「验收标准」核验，'
        + '未通过的项目继续修复，全部通过再作总结。',
    );
  };

  const handleSendMessage = async (e?: FormEvent, overrideText?: string) => {
    e?.preventDefault();
    const agent = activeAgent;
    // Allow send with text only OR files only (matches legacy chat-panel.tsx).
    // overrideText 来自 ask_clarification 卡片的选项/内联回答（走 /resume）。
    const prompt = (overrideText ?? inputText).trim();
    if ((!prompt && pendingFiles.length === 0) || !agent || isStreaming) return;
    // 未配置默认模型的 Agent 不允许发起会话（后端无从选择 LLM）
    if (!agent.model) {
      toast.error(`「${agent.name}」未配置默认模型，请先在智能体编辑页选择模型`);
      return;
    }

    // 空白新对话：首次发送时才真正创建会话（切 agent / 点 + 只进入空白态，
    // 见 handleStartNewWithAgent）。resume 回答必在已有会话中，不受影响。
    // 注意：创建后**不**立即 setActiveSessionId——那会触发消息加载 effect 清空
    // liveMessages，占位气泡消失后所有 SSE 事件（prev.map 按 agentMsgId 匹配）
    // 将静默丢失。改为流结束（done/finally）时绑定，见 createdSessionIdRef。
    let sessionId = activeSessionId;
    if (!sessionId) {
      try {
        // 传入用户输入作标题（截断规则与后端 add_message 的一致：30 字 + …）。
        // 后端仅在标题为空时才从首条消息生成——直接带上真标题，侧栏创建
        // 即显示最终标题，消除流结束后"标题回填"的两段式变化。
        const sess = await sessionApi.create(agent.id, prompt.slice(0, 30) + (prompt.length > 30 ? '…' : ''));
        sessionId = sess._id;
        createdSessionIdRef.current = sess._id;
        setPendingSessionId(sess._id);
        // 发送即确定会话：侧栏立即出现新会话（不等流结束），契合"用户回车
        // 即会话成立"的心智；activeSessionId 仍流结束绑定（绑定即触发加载）
        refreshSessions();
      } catch (err) {
        setStreamError(`创建会话失败：${(err as Error).message}`);
        return;
      }
    }

    setInputText('');
    setStreamError(null);

    // ── Upload queued files BEFORE dispatching the text prompt, so text + files
    // travel together and the agent sees the file content in the same turn.
    // (frontend-studio previously uploaded at pick-time, which raced the text
    // send and left the file unattached.) Mirrors chat-panel.tsx:443-489. ──
    const uploadedFileIds: string[] = [];
    const uploadedPaths: string[] = [];
    // 捕获完整 FileRef（含 mime_type/size/name），用于立即在用户气泡内联渲染附件，
    // 不必等历史重载。source='upload' → ChatAttachmentCard 走 getFileBlob(id) 取数。
    const uploadedAttachments: ChatAttachment[] = [];
    if (pendingFiles.length > 0) {
      setUploading(true);
      try {
        for (const f of pendingFiles) {
          const res = await sessionApi.uploadFile(sessionId, f);
          if (res.workspace_path) uploadedPaths.push(res.workspace_path);
          const id = getFileId(res.file);
          if (id) {
            uploadedFileIds.push(id);
            uploadedAttachments.push({
              source: 'upload',
              ref: id,
              name: res.file.name || f.name,
              mime_type: res.file.mime_type || f.type || undefined,
              size: res.file.size || f.size || undefined,
            });
          }
        }
      } catch (err) {
        setStreamError(`文件上传失败：${(err as Error).message}`);
        setUploading(false);
        return;
      } finally {
        setUploading(false);
      }
      setPendingFiles([]);
    }

    // 仅附件无文本也继续执行（后端 ExecutionRequest 允许 input 为空但需
    // 携带 file_ids）：图片多模态场景"只贴图不打字"是核心用法。
    // userMsg.content 为空串时气泡只内联渲染附件。

    const userMsg: Message = {
      id: 'msg_user_' + Date.now(),
      senderName: '我',
      avatar: '👩‍💼',
      role: 'user',
      content: prompt,
      timestamp: '刚刚',
      // 立即内联渲染上传附件（图片直显 + 点击弹窗），不等历史重载
      attachments: uploadedAttachments.length > 0 ? uploadedAttachments : undefined,
    };

    // Placeholder agent bubble updated incrementally as deltas arrive.
    const agentMsgId = 'msg_stream_' + Date.now();
    const agentMsg: Message = {
      id: agentMsgId,
      senderName: agent.name,
      avatar: agent.avatar,
      role: 'agent',
      agentId: agent.id,
      content: '',
      timestamp: '刚刚',
      status: 'thinking',
      timeline: [],
    };
    // 重置 timeline 流式追踪 refs（让首轮 text 开新 entry）。
    textEntryIdRef.current = null;
    textStartedRef.current = false;
    deltaBufferRef.current = null;
    if (rafIdRef.current) {
      cancelAnimationFrame(rafIdRef.current);
      rafIdRef.current = null;
    }

    // ── 是否走 /resume：pendingInterruptRef 已设置（SSE interrupt）或存在等待中的
    // ask_clarification/confirm_workflow（页面跳转后从历史恢复）。回答注入对应卡片
    // 作为结果，不再单独渲染用户气泡；下次走 resume 让 agent 继续而非重复提问。
    const resumeMsgId =
      pendingInterruptRef.current?.toolMsgId ??
      [...liveMessages].reverse().find((m) => m.isInterrupted)?.id;
    const isResume = !!resumeMsgId;

    updateLiveMessages((prev) => {
      if (isResume && resumeMsgId) {
        // 回答作为旧中断卡片的 timeline tool entry 的 result，关闭中断态；
        // 不渲染独立用户气泡。
        return prev
          .map((m) => {
            if (m.id !== resumeMsgId) return m;
            // 把 timeline 里第一个未答的 tool entry 填上用户回答。
            let answered = false;
            const tl = (m.timeline ?? []).map((e) => {
              if (
                !answered &&
                e.type === 'tool' &&
                isInterruptTool(e.toolName) &&
                !e.result
              ) {
                answered = true;
                return { ...e, result: prompt, toolStatus: 'success' as const };
              }
              return e;
            });
            return { ...m, isInterrupted: false, timeline: tl };
          })
          .concat(agentMsg);
      }
      return [...prev, userMsg, agentMsg];
    });
    // 用户主动发消息 = 明确要看新回复：无条件恢复跟随（即使发送前在上翻），
    // 避免整个流式过程都不跟随。跳底交给 useLayoutEffect 的瞬时 scrollTop
    // 赋值——勿再用 smooth scrollIntoView：两者会抢 scrollTop，动画轨迹把
    // 视口停在半路，scroll 事件误判"用户上翻"导致「回到最新」浮标闪现。
    pinnedRef.current = true;
    pendingInterruptRef.current = null;
    setIsStreaming(true);
    setStreamingMsgId(agentMsgId);


    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const res = isResume
        ? await agentApi.resume(agent.id, {
            session_id: sessionId,
            // resume 的 answer 不允许为空(ResumeRequest min_length=1):
            // 澄清回答时只贴图不打字 → 占位让请求可过,agent 从上下文理解。
            answer: prompt || '(用户上传了附件)',
            thinking_level: thinkingLevel,
            // 反馈保持 plan 上下文的最终保证在服务端（探针读 checkpoint
            // 推断挂起类型强制 plan，刷新/多端下客户端状态失真也不受影响）；
            // 此处 plan_mode 仅为提示。
            plan_mode: planMode || undefined,
          }, controller.signal)
        : await agentApi.stream(agent.id, {
            input: prompt,
            session_id: sessionId,
            thinking_level: thinkingLevel,
            plan_mode: planMode || undefined,
            // file_ids: persists the reference on the user message (history).
            // file_paths: backend embeds file contents into the LLM user message
            // (agents.py:589-610) — without this the agent never sees the content.
            file_ids: uploadedFileIds.length > 0 ? uploadedFileIds : undefined,
            file_paths: uploadedPaths.length > 0 ? uploadedPaths : undefined,
          }, controller.signal);
      // Attachments already handed off to the execution request above
      // (pendingFiles cleared earlier in this function).
      if (!res.ok) {
        let detail = `HTTP ${res.status}`;
        try {
          const body = await res.json();
          detail = body?.error?.message ?? body?.message ?? detail;
        } catch {
          /* ignore */
        }
        throw new Error(detail);
      }

      // 累积流式过程中 agent 产出的 output 文件路径，挂到 agent 消息上内联预览。
      const streamedAttachments: ChatAttachment[] = [];
      // 当前 LLM 轮的 thinking 累积与 entry 定位。轮次边界是 thinking 完整事件
      // （on_chat_model_end）——注意 tool_call_start 在流式期间先于它到达，不能
      // 作为边界，否则 final 会在 tool entry 之后另起新卡片，把本轮思考重复一遍。
      // 同轮交错思考块（thinking→text→thinking）归并进同一个 entry，与后端
      // 持久化结构（final 合并全部块）一致。
      let thinkingText = '';
      let thinkingEntryId: string | null = null;

      for await (const evt of parseSSEStream(res)) {
        if (controller.signal.aborted) break;
        // StreamDoneEvent has no `type` field (it carries `done: true`); every
        // other event has one. Handle the done-event first so the switch below
        // narrows the discriminated union cleanly on `evt.type`.
        if (!('type' in evt)) {
          // Stream finished — refresh sessions so persisted messages/timeline load,
          // and reload generated files so any new outputs appear immediately.
          // 无预建会话直接开聊时，后端在首个请求时创建了会话——流结束才绑定
          // session_id（流式中绑定会触发消息加载 effect 清空流式占位气泡）。
          if (!activeSessionId && (createdSessionIdRef.current ?? evt.session_id)) {
            setActiveSessionId(createdSessionIdRef.current ?? evt.session_id);
            setPendingSessionId(null);
          }
          refreshSessions();
          filesPanelRef.current?.refresh();
          setFeedbackTick((t) => t + 1);  // 本轮可能 load 了技能——刷新反馈态
          // 权威终态：done 携带与落库同源的 timeline，整体替换流式累加
          // 结果（防止流内漂移造成重复显示）；旧后端不带 timeline 时走
          // 原有"收敛 pending/running"路径。
          const finalTimeline = evt.timeline
            ? doneTimelineToEntries(evt.timeline, agentMsgId)
            : null;
          updateLiveMessages((prev) =>
            prev.map((m) => {
              if (m.id !== agentMsgId) return m;
              let tl: TimelineEntry[];
              if (finalTimeline) {
                // 权威 timeline 无时间戳：把流式期间记录的工具耗时按 toolCallId
                // 合并回去（收起态组头要显示执行耗时；对不上的条目优雅降级）。
                const times = new Map<string, { startedAt?: number; endedAt?: number }>();
                for (const e of m.timeline ?? []) {
                  if (e.type === 'tool' && e.toolCallId && (e.startedAt != null || e.endedAt != null)) {
                    times.set(e.toolCallId, { startedAt: e.startedAt, endedAt: e.endedAt });
                    toolTimesRef.current.set(e.toolCallId, times.get(e.toolCallId)!);
                  }
                }
                tl = times.size
                  ? finalTimeline.map((e) =>
                      e.type === 'tool' && e.toolCallId && times.has(e.toolCallId)
                        ? { ...e, ...times.get(e.toolCallId) }
                        : e,
                    )
                  : finalTimeline;
              } else {
                tl = (m.timeline ?? []).map((e) =>
                  e.type === 'tool' &&
                  (e.toolStatus === 'pending' || e.toolStatus === 'running') &&
                  e.toolName !== 'ask_clarification' &&
                  e.toolName !== 'confirm_workflow' &&
                  e.toolName !== ''
                    ? { ...e, toolStatus: 'success' as const }
                    : e,
                );
              }
              return {
                ...m, status: undefined, timeline: tl,
                usage: evt.usage ?? m.usage,
                requestId: evt.request_id || m.requestId,  // §8.2 消息级反馈轮次键
              };
            }),
          );
          continue;
        }
        switch (evt.type) {
          case 'thinking':
          case 'thinking_delta': {
            // thinking = on_chat_model_end 的权威全文 → 覆盖；thinking_delta = 增量 → 追加。
            // 按 thinkingEntryId 定位本轮 entry（可能不在末尾——text 已插入），
            // final 到达即本轮结束：写入全文、收起、清空累积。
            const isFinal = evt.type === 'thinking';
            thinkingText = isFinal ? evt.content : thinkingText + evt.content;
            const text = thinkingText;
            // id 在 setState 外生成（updater 需保持纯函数，StrictMode 下可能双调）。
            const pushId = thinkingEntryId
              ?? `${agentMsgId}-think-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
            thinkingEntryId = pushId;
            if (isFinal) {
              thinkingText = '';
              thinkingEntryId = null;
            }
            updateLiveMessages((prev) =>
              prev.map((m) => {
                if (m.id !== agentMsgId) return m;
                const tl = [...(m.timeline ?? [])];
                const idx = tl.findIndex((e) => e.id === pushId);
                if (idx >= 0) {
                  tl[idx] = {
                    ...tl[idx],
                    content: text,
                    expanded: isFinal && !tl[idx].userToggled ? false : tl[idx].expanded,
                  };
                } else {
                  tl.push({ id: pushId, type: 'thinking', content: text, expanded: !isFinal });
                }
                // final = 本轮思考结束（on_chat_model_end）。注意事件顺序：final 常
                // 晚于 tool_call_start 到达（后者已把 status 清为 undefined），此处
                // 若无条件设回 'thinking'，工具执行期间（tool_call/tool_result 均不
                // 动 status）气泡会一直错误显示"思考中"，直到下一个 text_delta。
                return { ...m, status: isFinal ? undefined : 'thinking', timeline: tl };
              }),
            );
            break;
          }
          case 'tool_call_start': {
            // 先同步 flush 文本 buffer（让 text 出现在 tool 之前），再 push 一个
            // pending tool entry，并重置 text refs（让 tool 之后的新 text 开新 entry）。
            // 注意：此处不重置 thinking 累积——tool_call_start 在流式期间先于
            // on_chat_model_end 到达，thinking 的轮次边界是 final 事件本身。
            if (rafIdRef.current) cancelAnimationFrame(rafIdRef.current);
            // 必须走 flushDelta 的合并语义（尾巴并入当前轮已存在的 text entry）。
            // 不能手动把 buf push 成新 entry——那会把一轮正文劈成两个 entry，
            // 随后 text final 从后往前只覆盖最后一个（尾巴→变成全文），头部
            // entry 成孤儿，同一轮回复重复显示两张几乎相同的卡。
            flushDelta();
            textEntryIdRef.current = null;
            textStartedRef.current = false;
            // tool_call_start 携带首个 chunk 里已流出的工具名（多数模型此刻
            // 已有名字；个别模型 name 在后续 chunk 才到则为空，此时先显示
            // "调用工具…"占位），完整名字/args 由后续 tool_call 事件补全。
            const toolName = evt.tool_name || '';
            const toolEntryId = `${agentMsgId}-tool-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
            updateLiveMessages((prev) =>
              prev.map((m) => {
                if (m.id !== agentMsgId) return m;
                const tl = [...(m.timeline ?? [])];
                tl.push({ id: toolEntryId, type: 'tool', content: '', toolName, toolStatus: 'pending' });
                return { ...m, status: undefined, timeline: tl };
              }),
            );
            break;
          }
          case 'tool_call': {
            // 升级 pending tool entry 为 running（填入完整 args + toolCallId），
            // 没有就新建。toolCallId 用于把后续 tool_result 精确配对到本调用
            //（处理并行同名调用，如两次 kb_search）。
            // tool_call 完整事件由后端 on_chat_model_end 在 final thinking 之后
            // 发出，到达即本轮 LLM 已结束；若该轮 final thinking 缺失（reasoning
            // 提取为空时不发），在此兜底重置累积，避免下一轮思考拼进同一张卡片。
            thinkingText = '';
            thinkingEntryId = null;
            if (rafIdRef.current) cancelAnimationFrame(rafIdRef.current);
            // 同步 flush 而非直接清空：tool_call 无 start、或 start 与 call 之间
            // 又有 delta 到达时，尾巴并入当前轮 text entry 而不是丢给 final 覆盖。
            flushDelta();
            textEntryIdRef.current = null;
            textStartedRef.current = false;
            updateLiveMessages((prev) =>
              prev.map((m) => {
                if (m.id !== agentMsgId) return m;
                const tl = [...(m.timeline ?? [])];
                const targetIdx = tl.findIndex(
                  (e) => e.type === 'tool' && e.toolStatus === 'pending',
                );
                if (targetIdx >= 0) {
                  tl[targetIdx] = {
                    ...tl[targetIdx],
                    toolName: evt.tool_name,
                    toolCallId: evt.id,
                    args: evt.args,
                    toolStatus: 'running',
                    startedAt: Date.now(),
                  };
                } else {
                  tl.push({
                    id: `${agentMsgId}-tool-${Date.now()}`,
                    type: 'tool',
                    content: '',
                    toolName: evt.tool_name,
                    toolCallId: evt.id,
                    args: evt.args,
                    toolStatus: 'running',
                    startedAt: Date.now(),
                  });
                }
                return { ...m, timeline: tl };
              }),
            );
            break;
          }
          case 'tool_result': {
            const resultContent = evt.content;
            const isError = evt.status === 'error';
            const tcid = evt.tool_call_id;
            // 优先按 tool_call_id 精确匹配（处理并行同名调用）；无 id 的旧数据
            // 回退到 toolName + running 匹配。
            const matchesEntry = (e: TimelineEntry): boolean =>
              e.type === 'tool' &&
              e.toolStatus === 'running' &&
              (tcid ? e.toolCallId === tcid : e.toolName === evt.tool_name);
            // 解析工具结果里产出的 output 文件，累积到 agent 消息（去重）。
            const newAtts = parseOutputAttachments(resultContent);
            if (newAtts.length > 0) {
              for (const a of newAtts) {
                if (!streamedAttachments.some((b) => b.ref === a.ref)) {
                  streamedAttachments.push(a);
                }
              }
            }
            updateLiveMessages((prev) =>
              prev.map((m) => {
                if (m.id !== agentMsgId) return m;
                const tl = [...(m.timeline ?? [])];
                // 从后往前找匹配的 running tool entry，填入 result + 状态。
                for (let i = tl.length - 1; i >= 0; i--) {
                  if (matchesEntry(tl[i])) {
                    tl[i] = {
                      ...tl[i],
                      result: resultContent,
                      toolStatus: isError ? 'error' : 'success',
                      endedAt: Date.now(),
                    };
                    break;
                  }
                }
                return {
                  ...m,
                  timeline: tl,
                  attachments: streamedAttachments.length > 0 ? [...streamedAttachments] : m.attachments,
                };
              }),
            );
            break;
          }
          case 'text_delta':
            // 走 RAF 批处理（appendDelta/flushDelta），平滑且多轮顺序正确。
            appendDelta(agentMsgId, evt.content);
            updateLiveMessages((prev) =>
              prev.map((m) => (m.id === agentMsgId ? { ...m, status: undefined } : m)),
            );
            break;
          case 'text': {
            // 权威全文：覆盖最后一个 text entry，没有就 push。
            const content = evt.content;
            if (content) {
              if (rafIdRef.current) cancelAnimationFrame(rafIdRef.current);
              deltaBufferRef.current = null;
              rafIdRef.current = null;
              updateLiveMessages((prev) =>
                prev.map((m) => {
                  if (m.id !== agentMsgId) return m;
                  const tl = [...(m.timeline ?? [])];
                  let found = false;
                  for (let i = tl.length - 1; i >= 0; i--) {
                    if (tl[i].type === 'text') {
                      tl[i] = { ...tl[i], content };
                      found = true;
                      break;
                    }
                  }
                  if (!found) tl.push({ id: `${agentMsgId}-text-${Date.now()}`, type: 'text', content });
                  return { ...m, status: undefined, timeline: tl };
                }),
              );
            }
            break;
          }
          case 'error': {
            // 不 throw 中断流：把错误记录到 agent 消息 timeline 的 error entry。
            // 错误可能来自中途（如某个工具的加载失败），后续仍可能有事件。
            const errContent = evt.content || '执行出错';
            setStreamError(errContent);
            updateLiveMessages((prev) =>
              prev.map((m) => {
                if (m.id !== agentMsgId) return m;
                const tl = [...(m.timeline ?? [])];
                tl.push({ id: `${agentMsgId}-err-${Date.now()}`, type: 'error', content: `❌ ${errContent}` });
                return { ...m, status: 'error', timeline: tl };
              }),
            );
            break;
          }
          case 'interrupt': {
            // Agent 经 ask_clarification/confirm_workflow 暂停等待用户回答：
            // 标记该消息为中断态（卡片可交互），记录消息 id 使下次发送走 /resume。
            // 后端在 interrupt 事件里把 question/options/fields/context 作为顶级
            // 字段下发（权威来源），这里回填到对应 ask_clarification tool entry 的
            // args——即使 tool_call 的 args 缺失/延迟，卡片也能正常渲染。
            updateLiveMessages((prev) =>
              prev.map((m) => {
                if (m.id !== agentMsgId) return m;
                const tl = [...(m.timeline ?? [])];
                for (let i = tl.length - 1; i >= 0; i--) {
                  if (
                    tl[i].type === 'tool' &&
                    !tl[i].result &&
                    isInterruptTool(tl[i].toolName)
                  ) {
                    if (tl[i].toolName === 'ask_clarification') {
                      // 把后端权威字段合并进 args（不覆盖已有值）。
                      const args = { ...tl[i].args };
                      if (!args.question && evt.question) args.question = evt.question;
                      if (!args.clarification_type && evt.clarification_type)
                        args.clarification_type = evt.clarification_type;
                      if (args.context == null && evt.context != null) args.context = evt.context;
                      if (args.options == null && evt.options != null) args.options = evt.options;
                      if (args.fields == null && evt.fields != null) args.fields = evt.fields;
                      tl[i] = { ...tl[i], args, toolStatus: 'success' };
                    } else if (tl[i].toolName === 'propose_plan') {
                      // 计划审批：回填后端权威的 plan 全文（kind=plan）。
                      const args = { ...tl[i].args };
                      if (!args.plan && evt.plan) args.plan = evt.plan;
                      tl[i] = { ...tl[i], args, toolStatus: 'success' };
                    } else {
                      tl[i] = { ...tl[i], toolStatus: 'success' };
                    }
                    break;
                  }
                }
                return { ...m, isInterrupted: true, timeline: tl };
              }),
            );
            pendingInterruptRef.current = { toolMsgId: agentMsgId };
            break;
          }
          default:
            break;
        }
      }
      // 兜底 flush 残留 delta。
      if (rafIdRef.current) {
        cancelAnimationFrame(rafIdRef.current);
        rafIdRef.current = null;
      }
      if (deltaBufferRef.current) flushDelta();
    } catch (err) {
      // 用户主动中止（切换会话 / 点停止生成）时 controller 已 abort：静默退出，
      // 不弹"流式请求失败"横幅、不写 error entry。仅对真实异常报错。
      if (!controller.signal.aborted) {
        const msg = (err as Error).message || '流式请求失败';
        setStreamError(msg);
        updateLiveMessages((prev) =>
          prev.map((m) => {
            if (m.id !== agentMsgId) return m;
            const tl = [...(m.timeline ?? [])];
            tl.push({ id: `${agentMsgId}-err-${Date.now()}`, type: 'error', content: `❌ ${msg}` });
            return { ...m, status: 'error', timeline: tl };
          }),
        );
      }
    } finally {
      setIsStreaming(false);
      setStreamingMsgId(null);
      // 中止（stop/切会话）没有 done 事件收尾：占位残留的 thinking 态会让
      // "思考中"标签与占位动效永远挂着，这里防御性清掉（正常 done 路径已是
      // undefined，no-op）。
      updateLiveMessages((prev) =>
        prev.map((m) => (m.id === agentMsgId && m.status === 'thinking' ? { ...m, status: undefined } : m)),
      );
      abortRef.current = null;
      refreshSessions();
      // 空白态新建的会话：流结束（无论 done/stop/异常）统一绑定——
      // 消息加载 effect 随之拉取权威数据，占位气泡被持久化内容替换。
      if (createdSessionIdRef.current) {
        setActiveSessionId(createdSessionIdRef.current);
        setPendingSessionId(null);
        createdSessionIdRef.current = null;
      }
    }
  };

  const handleStop = () => {
    // 先通知服务端停止生成（mid-stream abort：立即打断 LLM token 流/工具执行，
    // 半截回复不落库，可直接开始新对话），再断本地 SSE 连接（fetch signal）。
    // 服务端调用 fire-and-forget——409（已结束）等失败不影响本地停止。
    // 注意：会话切换的 abort（handleSelectSession）不通知服务端，后台跑完
    // 落库、切回可见是刻意语义。
    if (activeAgent) void agentApi.stop(activeAgent.id);
    abortRef.current?.abort();
    setIsStreaming(false);
  };

  const handleVoiceTranscriptFinal = (text: string) => {
    const transcript = text.trim();
    if (!transcript) return;
    // 语音输入 = 发送语义：无条件恢复跟随（与文本发送一致）。
    pinnedRef.current = true;
    updateLiveMessages((prev) => [
      ...prev,
      {
        id: `msg_voice_user_${Date.now()}`,
        senderName: '我',
        avatar: '',
        role: 'user',
        content: transcript,
        timestamp: '刚刚',
      },
    ]);
  };

  const handleVoiceTurnStarted = (message: { request_id?: string }) => {
    const agent = activeAgent;
    if (!agent) return;
    const agentMsgId = `msg_voice_agent_${message.request_id || Date.now()}`;
    voiceAgentMsgIdRef.current = agentMsgId;
    textEntryIdRef.current = null;
    textStartedRef.current = false;
    deltaBufferRef.current = null;
    if (rafIdRef.current) {
      cancelAnimationFrame(rafIdRef.current);
      rafIdRef.current = null;
    }
    // 新一轮语音回复开始生成：恢复跟随。
    pinnedRef.current = true;
    setStreamingMsgId(agentMsgId);
    updateLiveMessages((prev) => [
      ...prev,
      {
        id: agentMsgId,
        senderName: agent.name,
        avatar: agent.avatar,
        role: 'agent',
        agentId: agent.id,
        content: '',
        timestamp: '刚刚',
        status: 'thinking',
        timeline: [],
      },
    ]);
  };

  const handleVoiceAgentDelta = (delta: string) => {
    const agentMsgId = voiceAgentMsgIdRef.current;
    if (agentMsgId && delta) appendDelta(agentMsgId, delta);
  };

  const handleVoiceTurnEnd = (message: { session_id?: string }) => {
    if (rafIdRef.current) {
      cancelAnimationFrame(rafIdRef.current);
      rafIdRef.current = null;
    }
    if (deltaBufferRef.current) flushDelta();

    const agentMsgId = voiceAgentMsgIdRef.current;
    if (agentMsgId) {
      updateLiveMessages((prev) =>
        prev.map((item) =>
          item.id === agentMsgId ? { ...item, status: undefined } : item,
        ),
      );
    }
    voiceAgentMsgIdRef.current = null;
    setStreamingMsgId(null);
    refreshSessions();
    filesPanelRef.current?.refresh();

    // Voice persistence is complete before turn.end. Reload the same session so
    // Markdown, tools, attachments and clarification cards use the established
    // chat renderer instead of a separate voice-only transcript view.
    const sessionId = message.session_id || activeSessionId;
    if (!sessionId || sessionId !== activeSessionId) return;
    void sessionApi.getDetail(sessionId).then((detail) => {
      const mapped: Message[] = [];
      for (const record of detail.messages) {
        if (record.role === 'user') mapped.push(userMessageToDisplay(record));
        else {
          const agent = agentsRef.current.find((item) => item.id === detail.session.agent_id);
          mapped.push(
            agentMessageToDisplay(record, agent?.name ?? 'Agent', agent?.avatar ?? ''),
          );
        }
      }
      // 重载完成回到贴底：最新消息就在底部。
      pinnedRef.current = true;
      // 就地定稿：流结束的无缝绑定场景下（prev 即刚流完的消息），同位置
      // 同角色沿用原 id —— React key 稳定 → 列表 DOM 原地更新，消除整列
      // 重挂载造成的"页面刷新感"（头像重载 / Markdown 重渲染 / 动画重放）。
      // 数据字段仍全部来自后端权威记录；手动切换会话时 prev 配不上对，
      // 自然退回后端 id 重建（内容全换，重建符合预期）。
      setLiveMessages((prev) =>
        mapped.map((m, i) => {
          const old = prev[i];
          return old && old.role === m.role ? { ...m, id: old.id } : m;
        }),
      );
      const pending = [...mapped].reverse().find((item) => item.isInterrupted);
      pendingInterruptRef.current = pending ? { toolMsgId: pending.id } : null;
    }).catch((error: Error) => {
      setStreamError(`刷新语音对话失败：${error.message}`);
    });
  };

  const handleVoiceInterruptRequest = (question: string) => {
    // The voice protocol carries clarification separately from text deltas;
    // append it optimistically, then turn.end history refresh restores the card.
    handleVoiceAgentDelta(question);
  };

  // ── Composer（voice / 文本两态）：空会话态居中渲染，会话态落底渲染 ──
  const composerEl = (
    <Composer
      theme={theme}
      activeAgent={activeAgent}
      activeSession={activeSession}
      activeSessionId={activeSessionId ?? pendingSessionId}
      inputMode={inputMode} setInputMode={setInputMode}
      inputText={inputText} setInputText={setInputText}
      inputTextareaRef={inputTextareaRef} fileInputRef={fileInputRef}
      pendingFiles={pendingFiles} setPendingFiles={setPendingFiles}
      uploading={uploading} onUploadFile={handleUploadFile}
      isStreaming={isStreaming} liveMessages={liveMessages}
      onSendMessage={handleSendMessage} onStop={handleStop}
      planMode={planMode} setPlanMode={setPlanMode}
      thinkingLevel={thinkingLevel} setThinkingLevel={setThinkingLevel}
      modelMenuOpen={modelMenuOpen} setModelMenuOpen={setModelMenuOpen}
      voiceAvailable={voiceAvailable}
      voiceHint={voiceHint}
      onTranscriptFinal={handleVoiceTranscriptFinal}
      onTurnStarted={handleVoiceTurnStarted}
      onAgentDelta={handleVoiceAgentDelta}
      onTurnEnd={handleVoiceTurnEnd}
      onInterruptRequest={handleVoiceInterruptRequest}
      setStreamError={setStreamError}
    />
  );

  return (
    <div
    ref={rootRef}
    style={{ ['--sess-w' as string]: `${sessW}px`, ['--panel-w' as string]: `${panelW}px` }}
    className="af-scope theme-indigo flex gap-0 bg-page border-0 overflow-hidden relative w-full h-full min-h-0 flex-1 flex-row"
  >
      {/* 1. GLOBAL SIDEBAR：功能导航 + 会话历史 —— 全局常驻（App 各页面共用，
          非聊天页面由 activePage 渲染在右侧区域，侧栏本身不变） */}
      <ChatSidebar
        rootRef={rootRef} startColDrag={startColDrag} setSessW={setSessW}
        navItems={navItems} activeId={activeId} activePage={activePage}
        pinnedNav={pinnedNav} togglePin={togglePin}
        sessions={sessions} sessionsLoading={sessionsLoading}
        activeSessionId={activeSessionId ?? pendingSessionId}
        onSelectSession={handleSelectSession} onDeleteSession={handleDeleteSession}
        activeAgent={activeAgent} agents={agents}
        onStartNewWithAgent={handleStartNewWithAgent}
        userInitial={userInitial} username={username}
        userMenuOpen={userMenuOpen} setUserMenuOpen={setUserMenuOpen}
        moreMenuOpen={moreMenuOpen} setMoreMenuOpen={setMoreMenuOpen}
        onNavigate={onNavigate} onLogout={onLogout} onNavigateTask={onNavigateTask}
      />

      {activePage ? (
      <div className="flex-1 min-w-0 min-h-0 flex flex-col">{activePage}</div>
      ) : (
      <>
      {/* 2. CHAT STREAM PANEL：顶栏 = 衬线会话标题 + agent 身份 + 功能区开关 */}
      <div className="min-h-0 min-w-0 flex flex-col h-full bg-page relative flex-1">
        {streamError && (
          <div className="px-6 py-2 bg-sig-fail-soft border-b border-line text-sig-fail text-[11px] font-sans">
            ⚠ {streamError}
          </div>
        )}

        {/* 新会话首条消息的流式期间 activeSession 仍为 null（流结束才绑定，
            见 handleSendMessage 的 createdSessionIdRef 注释）——此时按
            liveMessages 判定，直接进入会话视图展示占位气泡与流式输出 */}
        {(!activeSession && liveMessages.length === 0) ? (
        <EmptySession
          composerEl={composerEl}
          agents={agents}
          activeAgent={activeAgent}
          agentMenuOpen={agentMenuOpen}
          setAgentMenuOpen={setAgentMenuOpen}
          onSelectAgent={handleStartNewWithAgent}
          onPickSuggestion={setInputText}
          modelLabel={modelLabel}
        />
        ) : (
        <>
        <SessionHeader
          activeSession={activeSession}
          agents={agents}
          activeAgent={activeAgent}
          agentMenuOpen={agentMenuOpen}
          setAgentMenuOpen={setAgentMenuOpen}
          onSelectAgent={handleStartNewWithAgent}
          panelOpen={panelOpen}
          onTogglePanel={() => setPanelOpen((v) => !v)}
          modelLabel={modelLabel}
        />

        <MessageList
          messages={liveMessages}
          activeSession={activeSession}
          sessionsLoading={sessionsLoading}
          activeAgent={activeAgent}
          activeSessionId={activeSessionId ?? pendingSessionId}
          isStreaming={isStreaming}
          pinnedRef={pinnedRef}
          streamingMsgId={streamingMsgId}
          feedbackMap={feedbackMap}
          chatScrollRef={chatScrollRef}
          messageEndRef={messageEndRef}
          setShowJumpToBottom={setShowJumpToBottom}
          showJumpToBottom={showJumpToBottom}
          theme={theme}
          onAnswer={(a) => handleSendMessage(undefined, a)}
          onEditMessage={setInputText}
          inputTextareaRef={inputTextareaRef}
          onDismissInterrupt={handleDismissInterrupt}
          onApprovePlan={handleApprovePlan}
          onVote={handleVoteMessage}
          onRegenerate={(before) => {
            const lastUser = [...liveMessages.slice(0, liveMessages.indexOf(before))].reverse().find((m) => m.role === 'user');
            if (lastUser?.content) {
              void handleSendMessage(undefined, lastUser.content);
            } else {
              toast.error('找不到原始输入，无法重新生成');
            }
          }}
        />

        {/* composer 同理：流式期间（activeSession 未绑定）也要保持输入框可见 */}
        {(activeSession || liveMessages.length > 0) && (
          <div
            ref={(el) => {
              if (!el) return;
              const ro = new ResizeObserver(() => {
                document.documentElement.style.setProperty('--composer-h', `${el.offsetHeight}px`);
              });
              ro.observe(el);
            }}
            className="px-4 pb-4 pt-2"
          >
            {composerEl}
          </div>
        )}

      </>
      )}
      </div>

      {/* 4. RIGHT PANEL：产物 + 后续扩展功能（左右可拉伸，默认关闭，≥lg 显示）。
          根级子级（聊天面板 div 之外）——否则会被纵向排到 composer 下方 */}
      {panelOpen && (
        <ArtifactsPanel
          rootRef={rootRef}
          startColDrag={startColDrag}
          setPanelW={setPanelW}
          artifactCount={artifactCount}
          onClose={() => setPanelOpen(false)}
          filesPanelRef={filesPanelRef}
          activeSessionId={activeSessionId ?? pendingSessionId}
        />
      )}
      </>
      )}
    </div>
  );
}

export interface Agent {
  id: string;
  name: string;
  avatar: string;
  description: string;
  /** 终端用户首屏欢迎词（Markdown）— 后端 welcome_message */
  welcomeMessage?: string;
  /** 终端用户首屏推荐问题/操作 — 后端 recommended_items */
  recommendedItems?: { label: string; prompt: string }[];
  /** 终端用户首屏推荐项分类分组（与独立项共存）— 后端 recommended_groups */
  recommendedGroups?: { title: string; items: { label: string; prompt: string }[] }[];
  model: string;
  /** Agent-level capability switch; global voice credentials are checked separately. */
  voiceEnabled: boolean;
  /** 允许该 agent 创建新 agent（能力门控，默认关；创建物为草稿态且不再拥有此能力） */
  canSpawnAgents: boolean;
  temperature: number;
  /** 系统提示词（整段自由文本 — 后端 system_prompt 直通） */
  systemPrompt: string;
  status: 'idle' | 'thinking' | 'online' | 'offline';
  statusText?: string;
  iconColor: string;
  skills: string[];
  /** 自定义工具绑定（组织库已开启工具；凭证为工具级统一配置） */
  customTools?: { tool_id: string; user_args: Record<string, unknown> }[];
  lastActive: string;
  /** Max retry count for execution (backend: 0-10, default 3). */
  maxRetry?: number;
  /** Session token budget (backend max_tokens; 0 = use global default). */
  maxTokens?: number;
  /** 线上配置版本号（草稿制：published 编辑写草稿层，publish 合并时 +1） */
  version?: number;
  /** 存在未发布草稿（published agent；AgentPicker 据此派生「· 草稿」影子条目） */
  hasDraft?: boolean;
  /** 本条目是草稿预览入口（影子条目）——聊天以此条目发起时以草稿层执行 */
  draftPreview?: boolean;
}

export interface Skill {
  id: string;
  name: string;
  description: string;
  tags: string[];
  avatar: string;
  author: string;
  rating: number;
  usersCount: number;
  isAdded: boolean;
  isPaid?: boolean;
  includedSkills?: string[];
  datasets?: string[];
}

export interface WorkflowNode {
  id: string;
  type: 'start' | 'agent' | 'router' | 'checker' | 'end' | 'custom';
  label: string;
  x: number;
  y: number;
  systemPrompt?: string;
  model?: string;
  tools: string[];
  status: 'idle' | 'running' | 'completed' | 'failed';
}

export interface WorkflowEdge {
  id: string;
  source: string;
  target: string;
  label?: string;
  status: 'idle' | 'active' | 'passed';
}

export interface Workflow {
  id: string;
  name: string;
  description: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  status: 'stable' | 'draft';
  lastRun?: string;
}

export interface User {
  id: string;
  name: string;
  avatar: string;
  email: string;
  /** 后端角色 name（key，如 admin / content_editor）。直存以兼容自定义角色，
   *  显示名由 UserManagement 从动态 roles 列表解析。 */
  role: string;
  /** 超级管理员（初始管理员）。普通管理员不可对管理员执行管理写操作。 */
  isSuperAdmin: boolean;
  permissions: {
    'agent:write': boolean;
    'workflow:write': boolean;
    'skill:write': boolean;
    'apikey:manage': boolean;
    'user:manage': boolean;
  };
  status: 'active' | 'suspended';
}

export interface ExecutionLog {
  id: string;
  workflowId: string;
  workflowName: string;
  timestamp: string;
  status: 'success' | 'failed' | 'running';
  latency: number;
  tokensUsed: number;
  steps: {
    nodeId: string;
    nodeLabel: string;
    timestamp: string;
    output: string;
  }[];
}

/** Token usage for an agent message (mirrors backend token_usage / SSE done usage). */
export interface TokenUsage {
  total_tokens?: number;
  input_tokens?: number;
  output_tokens?: number;
  llm_calls?: number;
  tool_calls?: number;
  /** 累计执行时长（秒）：LLM 与工具阶段（后端 usage 落库字段，历史消息可用） */
  llm_duration?: number;
  tool_duration?: number;
}

/** Timeline entry types for agent messages (mirrors frontend chat-panel). */
export type TimelineEntryType = 'thinking' | 'tool' | 'text' | 'error';
export type ToolStatus = 'pending' | 'running' | 'success' | 'error';

/** A single entry in an agent message's timeline. Agent messages render as an
 *  ordered list of these entries (text / tool / thinking / error), so multi-
 *  turn REACT (text→tool→text→tool) keeps correct chronological order. */
export interface TimelineEntry {
  id: string;
  type: TimelineEntryType;
  /** text/error/thinking 的正文 */
  content: string;
  /** tool 类型专用 */
  toolName?: string;
  args?: Record<string, unknown>;
  /** LLM-assigned call id linking tool_call ↔ tool_result. Used to pair
   *  parallel same-name calls precisely (instead of by tool_name). */
  toolCallId?: string;
  result?: string;
  toolStatus?: ToolStatus;
  /** 前端计时：工具开始执行 / 结束（流式路径记录，历史数据无此字段） */
  startedAt?: number;
  endedAt?: number;
  /** 折叠态（thinking / tool 详情） */
  expanded?: boolean;
  /** 用户手动切换过折叠——thinking 流式结束后的自动收起据此让位于用户选择 */
  userToggled?: boolean;
  /** 后端权威标记（text 专用）：on_chat_model_end 判定无 tool_calls → 该文本
   *  即最终回答。挂起→恢复轮 finished 无跃迁，权威收起以此为锚点。 */
  final?: boolean;
}

export interface Message {
  id: string;
  senderName: string;
  avatar: string;
  role: 'user' | 'agent';
  agentId?: string;
  content: string;
  timestamp: string;
  status?: string;
  /** 本轮执行请求 id——消息级反馈（§8.2）的轮次键 */
  requestId?: string;
  attachment?: {
    name: string;
    type: 'markdown' | 'video' | 'image' | 'code';
    content: string;
  };
  /** 可预览附件列表（用户上传 + agent 产出统一抽象）。
   *  source 决定取数路径：upload 走 getFileBlob(ref)（FileRef.id），
   *  output 走 sessionApi.previewFile(sid, ref)（output/ 相对路径）。 */
  attachments?: ChatAttachment[];
  /** Agent 消息的 timeline（text/tool/thinking/error 按顺序）。
   *  agent 消息靠此字段渲染；扁平 tool* 字段仅过渡期保留。 */
  timeline?: TimelineEntry[];
  /** Agent 经 interrupt 暂停，等待用户回答（ask_clarification /
   *  confirm_workflow）。为 true 时，timeline 里未答的 tool entry 卡片
   *  可交互，下一次发送走 /resume。 */
  isInterrupted?: boolean;
  /** Structured tool-call fields. When `status === 'tool'`, the message is
   *  rendered as a ToolCallCard instead of a plain text bubble. (过渡期保留) */
  toolName?: string;
  toolArgs?: Record<string, unknown>;
  toolResult?: string;
  toolStatus?: ToolStatus;
  /** ask_clarification 等待用户回答时为 true（卡片可交互，回答走 /resume）。
   *  (过渡期保留，新代码用 isInterrupted + timeline entry) */
  clarificationActive?: boolean;
  /** Token usage for this agent message (history: rec.token_usage; stream: done event usage). */
  usage?: TokenUsage;
}

/** 对话内可预览附件（用户上传 / agent 产出统一模型）。
 *  - source='upload'：ref = FileRef.id，经 getFileBlob(ref) 取 blob
 *  - source='output'：ref = 相对 output/ 的路径，经 sessionApi.previewFile(sid, ref) 取 blob */
export interface ChatAttachment {
  source: 'upload' | 'output';
  ref: string;
  name: string;
  mime_type?: string;
  size?: number;
}

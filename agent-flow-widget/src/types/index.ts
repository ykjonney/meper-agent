// agent-flow-widget/src/types/index.ts

/** Widget 初始化配置 */
export interface WidgetConfig {
  /** 必填：API Key */
  apiKey: string;
  /** 必填：Agent ID */
  agentId: string;
  /** 必填：后端 API 地址 */
  apiBaseUrl: string;
  /** 可选：聊天窗口标题 */
  title?: string;
  /** 可选：浮窗位置 */
  position?: 'bottom-right' | 'bottom-left';
}

/** 时间线条目类型 */
export type TimelineEntryType = 'thinking' | 'text' | 'tool_call' | 'error' | 'interrupt';

/** 工具调用状态 */
export type ToolStatus = 'pending' | 'running' | 'success' | 'error';

/** 时间线条目 */
export interface TimelineEntry {
  id: string;
  type: TimelineEntryType;
  content: string;
  timestamp: number;
  /** tool_call 专用：工具名称 */
  toolName?: string;
  /** tool_call 专用：工具参数 */
  toolArgs?: Record<string, unknown>;
  /** tool_call 专用：调用状态 */
  toolStatus?: ToolStatus;
  /** thinking 专用：是否折叠 */
  collapsed?: boolean;
}

/** Interrupt 数据 */
export interface InterruptData {
  question: string;
  clarification_type?: string;
  context?: string;
  options?: string[];
  interrupt_id?: string;
}

/** 聊天消息 */
export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
  /** 是否正在流式输出中 */
  streaming?: boolean;
  /** assistant 消息的完成时间线 */
  timeline?: TimelineEntry[];
}

/** 会话 */
export interface Session {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
}

/** SSE 流式事件 - 扩展支持所有事件类型 */
export type StreamEvent =
  | { type: 'text_delta'; content: string }
  | { type: 'text'; content: string }
  | { type: 'thinking_delta'; content: string }
  | { type: 'thinking'; content: string }
  | { type: 'tool_call_start' }
  | { type: 'tool_call'; tool_name: string; args: Record<string, unknown>; id: string }
  | { type: 'tool_result'; tool_name: string; content: string }
  | { type: 'interrupt'; question: string; clarification_type?: string; context?: string; options?: string[]; interrupt_id?: string }
  | { type: 'error'; message: string; source?: string }
  | { type: 'done'; session_id: string };

/** Agent 调用请求 */
export interface InvokeRequest {
  message: string;
  session_id?: string;
  visitor_id: string;
}

/** Agent 调用响应头 */
export interface InvokeResponseHeaders {
  sessionId: string;
  requestId: string;
}

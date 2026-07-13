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

/** 聊天消息 */
export interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: number;
  /** 是否正在流式输出中 */
  streaming?: boolean;
}

/** 会话 */
export interface Session {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
}

/** SSE 流式事件 */
export type StreamEvent =
  | { type: 'text'; content: string }
  | { type: 'done'; session_id: string }
  | { type: 'error'; message: string };

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

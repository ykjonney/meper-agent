/**
 * Execution logs service — wraps backend /admin/execution-logs endpoints.
 *
 * 每条记录是一次 agent 调用（invoke/stream/resume，跨 internal/api_key/im
 * 三渠道）。列表不含 events（单条可达 16KB）——详情弹窗经 get(logId) 取
 * 完整过程事件（ExecutionRecorder 产出）。
 *
 * Uses the shared apiClient instance (auto auth header + 401 refresh).
 * Response fields are snake_case per backend contract.
 */
import { apiClient } from '../lib/api-client'

/* ─── Types (snake_case, matches backend contract) ─── */

export type ExecutionSource = 'internal' | 'api_key' | 'im'
export type ExecutionStatus = 'success' | 'error' | 'cancelled'

/**
 * 过程事件（ExecutionRecorder 产物，紧凑键名以控制落库体积）。
 * t=相对 run 开始的毫秒偏移；e=事件类型；其余键按事件类型出现。
 */
export interface ExecutionEvent {
  t: number
  e: string
  /** request 序号（request_begin/end） */
  i?: number
  /** request_end: completed | retryable | fatal（预留） */
  status?: string
  /** 耗时毫秒（request_end / tool_result） */
  dur?: number
  in_tok?: number
  out_tok?: number
  /** 工具调用的 tool_call_id */
  id?: string
  /** 工具名 */
  n?: string
  /** 参数预览（≤200 字符） */
  args?: string
  /** 工具结果是否成功（best-effort 嗅探） */
  ok?: boolean
  /** 工具结果字符数 */
  size?: number
  /** interrupt: clarification | app_authorization | cancelled */
  kind?: string
  /** compaction: tool_output | llm_summary */
  level?: string
  /** compaction: 压缩前原文字符数 */
  before?: number
  /** error: llm | graph | tool */
  source?: string
  code?: string
  msg?: string
  /** events_truncated: 被丢弃的中段工具事件数 */
  dropped?: number
  /** tools_resolved */
  ctx?: string
  model?: string
  tools?: string[]
  load_errors?: { tool: string; error: string }[]
}

export interface ExecutionLogItem {
  _id: string
  source: ExecutionSource
  user_id: string
  /** 富化的人类可读调用者名（用户名/API Key 名/渠道名） */
  caller_name?: string
  agent_id: string
  session_id: string
  request_id: string
  endpoint?: string
  channel_id?: string
  status: ExecutionStatus
  status_code: number
  latency_ms: number
  llm_duration_ms: number
  tool_duration_ms: number
  other_duration_ms: number
  ttft_ms: number
  total_tokens: number
  input_tokens: number
  output_tokens: number
  llm_calls: number
  timestamp: string
}

export interface ExecutionLogDetail extends ExecutionLogItem {
  events: ExecutionEvent[]
}

export interface ExecutionLogListParams {
  source?: string
  status?: string
  agent_id?: string
  session_id?: string
  page?: number
  page_size?: number
}

export interface ExecutionLogListResponse {
  items: ExecutionLogItem[]
  total: number
  page: number
  page_size: number
}

/* ─── Stats / daily trend（仪表盘） ─── */

export interface ExecutionStatsChannel {
  calls: number
  tokens: number
  input_tokens: number
  output_tokens: number
  success: number
  failed: number
  avg_latency_ms?: number
}

export interface ExecutionStatsTotals extends ExecutionStatsChannel {
  success_rate: number
}

export interface ExecutionStatsResponse {
  channels: Record<string, ExecutionStatsChannel>
  totals: ExecutionStatsTotals
}

/** 按日聚合行（缺日补零）：calls/tokens/failed。 */
export interface DailyTrendItem {
  date: string
  calls: number
  tokens: number
  failed: number
}

export interface ExecutionStatsParams {
  /** ISO date（YYYY-MM-DD）单日视图；与 start/end 互斥时优先 */
  date?: string
  start?: string
  end?: string
}

/* ─── API ─── */

export const executionLogApi = {
  async list(params: ExecutionLogListParams = {}): Promise<ExecutionLogListResponse> {
    const res = await apiClient.get<ExecutionLogListResponse>('/api/v1/execution-logs', {
      params: {
        source: params.source || undefined,
        status: params.status || undefined,
        agent_id: params.agent_id || undefined,
        session_id: params.session_id || undefined,
        page: params.page ?? 1,
        page_size: params.page_size ?? 20,
      },
    })
    return res.data
  },

  /** 详情（含 events 过程事件；admin 端点） */
  async get(logId: string): Promise<ExecutionLogDetail> {
    const res = await apiClient.get<ExecutionLogDetail>(`/api/v1/execution-logs/${logId}`)
    return res.data
  },

  /** 渠道聚合统计（admin 端点；date=单日视图） */
  async getStats(params: ExecutionStatsParams = {}): Promise<ExecutionStatsResponse> {
    const res = await apiClient.get<ExecutionStatsResponse>('/api/v1/execution-stats', {
      params: {
        date: params.date || undefined,
        start: params.start || undefined,
        end: params.end || undefined,
      },
    })
    return res.data
  },

  /** 按日聚合趋势（admin 端点；缺日补零） */
  async getDailyTrend(days = 7): Promise<DailyTrendItem[]> {
    const res = await apiClient.get<DailyTrendItem[]>('/api/v1/execution-logs/daily', {
      params: { days },
    })
    return res.data
  },
}

/* ─── Query key factory ─── */

export const executionLogKeys = {
  all: ['execution-logs'] as const,
  lists: () => [...executionLogKeys.all, 'list'] as const,
  list: (params: ExecutionLogListParams) => [...executionLogKeys.lists(), params] as const,
  details: () => [...executionLogKeys.all, 'detail'] as const,
  detail: (id: string) => [...executionLogKeys.details(), id] as const,
  stats: (params: ExecutionStatsParams) => [...executionLogKeys.all, 'stats', params] as const,
  trend: (days: number) => [...executionLogKeys.all, 'trend', days] as const,
}

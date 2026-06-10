/**
 * Agent API service — wraps backend /agents endpoints.
 *
 * Uses the shared apiClient instance (auto auth header + 401 refresh).
 * Response fields are snake_case per backend contract.
 */
import { apiClient, type NormalizedApiError } from './api-client'
import { ENV } from '../config/env'
import { useAuthStore } from '../stores/auth-store'

/* ─── Types (snake_case, matches backend schemas) ─── */

export type AgentStatus = 'draft' | 'published' | 'archived'

export interface LlmConfig {
  default_model: string
  temperature: number
  max_retry: number
}

export interface SavedPrompt {
  id: string
  name: string
  content: string
  is_active: boolean
}

export interface Agent {
  id: string
  name: string
  description: string
  system_prompt: string
  saved_system_prompts: SavedPrompt[]
  /** Legacy field — kept for backward compatibility with old agents */
  tool_ids: string[]
  /** Skill tool IDs (source=markdown) */
  skill_ids: string[]
  /** MCP connection IDs (tools loaded from remote MCP servers) */
  mcp_connection_ids: string[]
  /** Built-in tool whitelist (bash/read/write) */
  builtin_config: string[]
  workflow_ids: string[]
  knowledge_base_ids: string[]
  llm_config: LlmConfig
  status: AgentStatus
  version: number
  created_at: string
  updated_at: string
}

export interface AgentCreateInput {
  name: string
  description?: string
  system_prompt?: string
  saved_system_prompts?: SavedPrompt[]
  /** @deprecated Use skill_ids instead */
  tool_ids?: string[]
  /** Skill tool IDs (source=markdown) */
  skill_ids?: string[]
  /** MCP connection IDs */
  mcp_connection_ids?: string[]
  /** Built-in tool whitelist (bash/read/write) */
  builtin_config?: string[]
  workflow_ids?: string[]
  knowledge_base_ids?: string[]
  llm_config?: Partial<LlmConfig>
}

export interface AgentUpdateInput {
  name: string
  description?: string
  system_prompt?: string
  saved_system_prompts?: SavedPrompt[]
  /** @deprecated Use skill_ids instead */
  tool_ids?: string[]
  /** Skill tool IDs (source=markdown) */
  skill_ids?: string[]
  /** MCP connection IDs */
  mcp_connection_ids?: string[]
  /** Built-in tool whitelist (bash/read/write) */
  builtin_config?: string[]
  workflow_ids?: string[]
  knowledge_base_ids?: string[]
  llm_config?: Partial<LlmConfig>
  status?: AgentStatus
}

/** Model config update payload for PATCH /agents/{id}/model-config */
export interface ModelConfigUpdateInput {
  default_model: string
  temperature: number
  max_retry: number
}

export interface AgentListParams {
  page?: number
  page_size?: number
  name?: string
  status?: AgentStatus
}

export interface AgentListResponse {
  items: Agent[]
  total: number
  page: number
  page_size: number
}

/* ─── Execution types (invoke / stream) ─── */

export interface ExecutionRequest {
  input: string
  session_id?: string
  enable_thinking?: boolean
}

export interface ExecutionResponse {
  output: string
  execution_path: string
  request_id: string
  agent_id: string
  session_id: string
  step_count: number
}

/* ─── SSE structured event types ─── */

/** LLM native reasoning (e.g. Claude extended thinking) — consolidated */
export interface ThinkingEvent {
  type: 'thinking'
  content: string
}

/** Streaming delta of LLM reasoning (incremental) */
export interface ThinkingDeltaEvent {
  type: 'thinking_delta'
  content: string
}

/** AI decided to call a tool */
export interface ToolCallEvent {
  type: 'tool_call'
  tool_name: string
  args: Record<string, unknown>
}

/** Tool returned a result */
export interface ToolResultEvent {
  type: 'tool_result'
  tool_name: string
  content: string
}

/** Incremental text delta of the final answer */
export interface FinalAnswerDeltaEvent {
  type: 'final_answer_delta'
  content: string
}

/** Final answer text from the AI — consolidated, marks completion */
export interface FinalAnswerEvent {
  type: 'final_answer'
  content: string
}

/** Error during execution */
export interface ErrorEvent {
  type: 'error'
  content: string
}

/** Execution finished */
export interface StreamDoneEvent {
  done: true
  request_id: string
  session_id: string
}

/** Union of all SSE event types */
export type StreamEvent =
  | ThinkingEvent
  | ThinkingDeltaEvent
  | ToolCallEvent
  | ToolResultEvent
  | FinalAnswerDeltaEvent
  | FinalAnswerEvent
  | ErrorEvent
  | StreamDoneEvent

/* ─── API methods ─── */

export const agentApi = {
  /**
   * List agents with optional pagination, name search, status filter.
   * GET /api/v1/agents
   */
  async list(params: AgentListParams = {}): Promise<AgentListResponse> {
    const res = await apiClient.get<AgentListResponse>('/api/v1/agents', {
      params: {
        page: params.page ?? 1,
        page_size: params.page_size ?? 20,
        ...(params.name ? { name: params.name } : {}),
        ...(params.status ? { status: params.status } : {}),
      },
    })
    return res.data
  },

  /**
   * Get a single agent by ID.
   * GET /api/v1/agents/{id}
   */
  async get(agentId: string): Promise<Agent> {
    const res = await apiClient.get<Agent>(`/api/v1/agents/${encodeURIComponent(agentId)}`)
    return res.data
  },

  /**
   * Create a new agent.
   * POST /api/v1/agents — returns 201 on success.
   */
  async create(input: AgentCreateInput): Promise<Agent> {
    const res = await apiClient.post<Agent>('/api/v1/agents', input)
    return res.data
  },

  /**
   * Update an agent (full PUT, version auto-increments).
   * PUT /api/v1/agents/{id}
   */
  async update(agentId: string, input: AgentUpdateInput): Promise<Agent> {
    const res = await apiClient.put<Agent>(`/api/v1/agents/${encodeURIComponent(agentId)}`, input)
    return res.data
  },

  /**
   * Delete an agent. Returns 204 No Content on success.
   * DELETE /api/v1/agents/{id}
   */
  async remove(agentId: string): Promise<void> {
    await apiClient.delete(`/api/v1/agents/${encodeURIComponent(agentId)}`)
  },

  /**
   * Update only the model configuration (PATCH).
   * PATCH /api/v1/agents/{id}/model-config
   */
  async updateModelConfig(agentId: string, input: ModelConfigUpdateInput): Promise<Agent> {
    const res = await apiClient.patch<Agent>(
      `/api/v1/agents/${encodeURIComponent(agentId)}/model-config`,
      input,
    )
    return res.data
  },

  /**
   * Publish an agent (draft/archived → published).
   * POST /api/v1/agents/{id}/publish
   */
  async publish(agentId: string): Promise<Agent> {
    const res = await apiClient.post<Agent>(
      `/api/v1/agents/${encodeURIComponent(agentId)}/publish`,
    )
    return res.data
  },

  /**
   * Archive an agent (published → archived).
   * POST /api/v1/agents/{id}/archive
   */
  async archive(agentId: string): Promise<Agent> {
    const res = await apiClient.post<Agent>(
      `/api/v1/agents/${encodeURIComponent(agentId)}/archive`,
    )
    return res.data
  },

  /**
   * Duplicate an agent. Creates a new draft agent with copied config.
   * POST /api/v1/agents/{id}/duplicate — returns 201.
   */
  async duplicate(agentId: string): Promise<Agent> {
    const res = await apiClient.post<Agent>(
      `/api/v1/agents/${encodeURIComponent(agentId)}/duplicate`,
    )
    return res.data
  },

  /**
   * Invoke an agent synchronously (non-streaming).
   * POST /api/v1/agents/{id}/invoke
   */
  async invoke(agentId: string, body: ExecutionRequest): Promise<ExecutionResponse> {
    const res = await apiClient.post<ExecutionResponse>(
      `/api/v1/agents/${encodeURIComponent(agentId)}/invoke`,
      body,
    )
    return res.data
  },

  /**
   * Stream an agent execution via SSE (POST + ReadableStream).
   *
   * Uses raw fetch instead of axios because axios does not support
   * streaming response bodies. Returns the raw Response so the caller
   * can read the body as a ReadableStream and parse SSE events.
   */
  async stream(agentId: string, body: ExecutionRequest): Promise<Response> {
    const accessToken = useAuthStore.getState().accessToken
    const url = `${ENV.API_BASE_URL}/api/v1/agents/${encodeURIComponent(agentId)}/stream`

    return fetch(url, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
      },
      body: JSON.stringify(body),
    })
  },
}

/* ─── Query key factory ─── */

export const agentKeys = {
  all: ['agents'] as const,
  lists: () => [...agentKeys.all, 'list'] as const,
  list: (params: AgentListParams) => [...agentKeys.lists(), params] as const,
  details: () => [...agentKeys.all, 'detail'] as const,
  detail: (id: string) => [...agentKeys.details(), id] as const,
}

/* ─── Error helpers ─── */

export function isAgentError(
  err: unknown,
): err is NormalizedApiError {
  return (
    typeof err === 'object' &&
    err !== null &&
    'message' in err &&
    typeof (err as { message: unknown }).message === 'string'
  )
}

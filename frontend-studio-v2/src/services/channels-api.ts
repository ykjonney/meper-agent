/**
 * Channels API service - wraps backend /channels endpoints (IM integration).
 *
 * 平台类型固定为飞书/钉钉（studio 消息渠道页），每个平台下可创建多个
 * 渠道实例（各绑一个 agent、独立凭据）。管理端点 admin-only；入站回调由
 * 平台长连接/webhook 直连后端，前端不参与。
 *
 * Uses the shared apiClient (auto auth header + 401 refresh).
 * Response fields are snake_case per backend contract.
 */
import { apiClient } from '../lib/api-client'

/* ─── Types (snake_case, matches backend schemas/channel.py) ─── */

export type ChannelProvider = 'lark' | 'dingtalk' | 'wecom' | 'mock'
export type ChannelStatus = 'active' | 'degraded' | 'disabled'
export type ReceiveMode = 'webhook' | 'long_connection'
export type ConnectionStatus =
  | 'long_connection_connected'
  | 'long_connection_disconnected'
  | 'not_long_connection'

export interface CredentialFieldSchema {
  key: string
  label: string
  type: 'text' | 'secret'
  required: boolean
}

export interface ProviderSchema {
  label: string
  credential_fields: CredentialFieldSchema[]
  /** 运行时实际可用的接收模式（长连接依赖后端工厂 + 全局开关） */
  receive_modes: ReceiveMode[]
}

export interface Channel {
  id: string
  name: string
  provider: ChannelProvider
  agent_id: string
  owner_user_id: string
  enabled: boolean
  status: ChannelStatus
  receive_mode: ReceiveMode
  /** 读取时服务端恒为掩码值（如 "ab****yz"） */
  credentials: Record<string, string>
  inbound_url: string
  connection_status: ConnectionStatus
  created_at: string
  updated_at: string
}

export interface ChannelListParams {
  page?: number
  page_size?: number
  provider?: ChannelProvider
}

export interface ChannelCreateInput {
  name: string
  provider: ChannelProvider
  agent_id: string
  credentials: Record<string, string>
  receive_mode?: ReceiveMode
}

export interface ChannelUpdateInput {
  name?: string
  agent_id?: string
  /** 只传非空值——后端 merge，不覆盖未提供的字段 */
  credentials?: Record<string, string>
  enabled?: boolean
  receive_mode?: ReceiveMode
}

export interface ChannelListResponse {
  items: Channel[]
  total: number
  page: number
  page_size: number
}

export interface ProviderSchemaResponse {
  providers: Record<string, ProviderSchema>
}

/* ─── API methods ─── */

export const channelsApi = {
  /**
   * List channels (global, admin-only route). Optional provider filter.
   * GET /api/v1/channels
   */
  async list(params: ChannelListParams = {}): Promise<ChannelListResponse> {
    const res = await apiClient.get<ChannelListResponse>('/api/v1/channels', {
      params: {
        page: params.page ?? 1,
        page_size: params.page_size ?? 100,
        ...(params.provider ? { provider: params.provider } : {}),
      },
    })
    return res.data
  },

  /**
   * Create a channel instance (multiple instances per provider are allowed —
   * e.g. several Lark apps, each bound to its own agent).
   * POST /api/v1/channels
   */
  async create(input: ChannelCreateInput): Promise<Channel> {
    const res = await apiClient.post<Channel>('/api/v1/channels', input)
    return res.data
  },

  /**
   * Partial update (partial credentials merge server-side).
   * PATCH /api/v1/channels/{id}
   */
  async update(channelId: string, input: ChannelUpdateInput): Promise<Channel> {
    const res = await apiClient.patch<Channel>(
      `/api/v1/channels/${encodeURIComponent(channelId)}`,
      input,
    )
    return res.data
  },

  /**
   * Soft delete (server tombstones + stops the long connection; the doc is
   * kept for inbound event-log audit and disappears from the list).
   * DELETE /api/v1/channels/{id}
   */
  async remove(channelId: string): Promise<void> {
    await apiClient.delete(`/api/v1/channels/${encodeURIComponent(channelId)}`)
  },

  /** POST /api/v1/channels/{id}/enable */
  async enable(channelId: string): Promise<void> {
    await apiClient.post(`/api/v1/channels/${encodeURIComponent(channelId)}/enable`)
  },

  /** POST /api/v1/channels/{id}/disable */
  async disable(channelId: string): Promise<void> {
    await apiClient.post(`/api/v1/channels/${encodeURIComponent(channelId)}/disable`)
  },

  /** POST /api/v1/channels/{id}/reset — 清除 DEGRADED 并重置失败计数 */
  async reset(channelId: string): Promise<void> {
    await apiClient.post(`/api/v1/channels/${encodeURIComponent(channelId)}/reset`)
  },

  /**
   * Provider credential field definitions + runtime-available receive modes.
   * GET /api/v1/channels/providers/schema
   */
  async getProviderSchema(): Promise<ProviderSchemaResponse> {
    const res = await apiClient.get<ProviderSchemaResponse>(
      '/api/v1/channels/providers/schema',
    )
    return res.data
  },
}

/* ─── Query key factory ─── */

export const channelKeys = {
  all: ['channels'] as const,
  lists: () => [...channelKeys.all, 'list'] as const,
  list: (params: ChannelListParams) => [...channelKeys.lists(), params] as const,
  schema: () => [...channelKeys.all, 'provider-schema'] as const,
}

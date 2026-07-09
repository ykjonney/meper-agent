/**
 * Webhook management service — wraps backend /webhooks endpoints.
 */
import { apiClient } from './api-client'

/* ─── Types ─── */

export type WebhookStatus = 'active' | 'disabled'

export const WEBHOOK_EVENTS = [
  'agent.completed',
  'agent.failed',
  'task.completed',
  'task.failed',
  'task.waiting_human',
] as const

export const WEBHOOK_EVENT_LABELS: Record<string, string> = {
  'agent.completed': 'Agent 完成',
  'agent.failed': 'Agent 失败',
  'task.completed': 'Task 完成',
  'task.failed': 'Task 失败',
  'task.waiting_human': 'Task 等待审批',
}

export interface Webhook {
  id: string
  name: string
  url: string
  events: string[]
  api_key_id: string | null
  status: WebhookStatus
  created_at: string
  updated_at: string
}

export interface WebhookCreateInput {
  name: string
  url: string
  events: string[]
  api_key_id?: string | null
}

export interface WebhookUpdateInput {
  name?: string
  url?: string
  events?: string[]
  status?: WebhookStatus
}

export interface WebhookListResponse {
  items: Webhook[]
  total: number
  page: number
  page_size: number
}

export interface WebhookTestResult {
  success: boolean
  status_code: number | null
  error: string | null
}

export interface WebhookDeliveryLog {
  id: string
  webhook_id: string
  event: string
  url: string
  status_code: number | null
  success: boolean
  attempts: number
  error: string | null
  timestamp: string
}

/* ─── API ─── */

export const webhookApi = {
  async list(page = 1, page_size = 20): Promise<WebhookListResponse> {
    const res = await apiClient.get<WebhookListResponse>('/api/v1/webhooks', {
      params: { page, page_size },
    })
    return res.data
  },

  async get(id: string): Promise<Webhook> {
    const res = await apiClient.get<Webhook>(`/api/v1/webhooks/${id}`)
    return res.data
  },

  async create(input: WebhookCreateInput): Promise<Webhook> {
    const res = await apiClient.post<Webhook>('/api/v1/webhooks', input)
    return res.data
  },

  async update(id: string, input: WebhookUpdateInput): Promise<Webhook> {
    const res = await apiClient.put<Webhook>(`/api/v1/webhooks/${id}`, input)
    return res.data
  },

  async delete(id: string): Promise<void> {
    await apiClient.delete(`/api/v1/webhooks/${id}`)
  },

  async test(id: string): Promise<WebhookTestResult> {
    const res = await apiClient.post<WebhookTestResult>(`/api/v1/webhooks/${id}/test`)
    return res.data
  },

  async logs(id: string, limit = 50): Promise<WebhookDeliveryLog[]> {
    const res = await apiClient.get<WebhookDeliveryLog[]>(`/api/v1/webhooks/${id}/logs`, {
      params: { limit },
    })
    return res.data
  },
}

export const webhookKeys = {
  all: ['webhooks'] as const,
  lists: () => [...webhookKeys.all, 'list'] as const,
  list: (page: number) => [...webhookKeys.lists(), page] as const,
  details: () => [...webhookKeys.all, 'detail'] as const,
  detail: (id: string) => [...webhookKeys.details(), id] as const,
  logs: (id: string) => [...webhookKeys.all, 'logs', id] as const,
}

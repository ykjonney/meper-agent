/**
 * Triggers API service - wraps backend /triggers endpoints.
 *
 * Triggers are independent documents (collection: triggers). Each trigger
 * binds a workflow to a cron/once schedule. The polling scheduler on the
 * backend reads `next_trigger_at` to decide when to fire — API endpoints only
 * do DB bookkeeping, no Celery dispatch from the client side.
 *
 * Uses the shared apiClient instance (auto auth header + 401 refresh).
 * Response fields are snake_case per backend contract.
 */
import { apiClient } from '../lib/api-client'

/* ─── Types (snake_case, matches backend Trigger model) ─── */

export type TriggerType = 'cron' | 'once'

export interface TriggerConfig {
  _id?: string
  id?: string
  workflow_id: string
  user_id?: string
  type: TriggerType
  enabled: boolean
  cron_expression?: string
  execute_at?: string
  default_input: Record<string, unknown>
  schedule_version?: number
  last_triggered_at?: string
  next_trigger_at?: string
  created_at: string
  updated_at: string
}

/** Helper to extract the trigger ID from a response (supports both _id and id). */
export function getTriggerId(trigger: TriggerConfig): string {
  return trigger._id || trigger.id || ''
}

/** Schedule frequency presets for the visual cron picker. */
export type ScheduleFrequency = 'hourly' | 'daily' | 'weekly' | 'monthly' | 'custom'

export const WEEKDAY_LABELS = ['一', '二', '三', '四', '五', '六', '日']

/* ─── API methods ─── */

export const triggersApi = {
  /**
   * List triggers for the current user.
   * GET /api/v1/triggers
   */
  async list(): Promise<{ total: number; items: TriggerConfig[] }> {
    const res = await apiClient.get<{ total: number; items: TriggerConfig[] }>(
      '/api/v1/triggers',
    )
    return res.data
  },

  /**
   * Get a trigger by ID.
   * GET /api/v1/triggers/{id}
   */
  async getById(triggerId: string): Promise<TriggerConfig> {
    const res = await apiClient.get<TriggerConfig>(
      `/api/v1/triggers/${encodeURIComponent(triggerId)}`,
    )
    return res.data
  },

  /**
   * Create a new trigger for a workflow.
   * POST /api/v1/triggers
   */
  async create(workflowId: string, config: Partial<TriggerConfig>): Promise<TriggerConfig> {
    const res = await apiClient.post<TriggerConfig>('/api/v1/triggers', {
      workflow_id: workflowId,
      type: config.type || 'cron',
      enabled: config.enabled ?? false,
      cron_expression: config.cron_expression,
      execute_at: config.execute_at,
      default_input: config.default_input,
    })
    return res.data
  },

  /**
   * Update a trigger by ID (partial).
   * PUT /api/v1/triggers/{id}
   */
  async updateById(
    triggerId: string,
    config: Partial<TriggerConfig>,
  ): Promise<TriggerConfig> {
    const payload: Record<string, unknown> = {}
    if (config.type !== undefined) payload.type = config.type
    if (config.enabled !== undefined) payload.enabled = config.enabled
    if (config.cron_expression !== undefined) payload.cron_expression = config.cron_expression
    if (config.execute_at !== undefined) payload.execute_at = config.execute_at
    if (config.default_input !== undefined) payload.default_input = config.default_input
    const res = await apiClient.put<TriggerConfig>(
      `/api/v1/triggers/${encodeURIComponent(triggerId)}`,
      payload,
    )
    return res.data
  },

  /**
   * Toggle the enabled state of a trigger.
   * PATCH /api/v1/triggers/{id}/toggle
   */
  async toggle(triggerId: string, enabled: boolean): Promise<TriggerConfig> {
    const res = await apiClient.patch<TriggerConfig>(
      `/api/v1/triggers/${encodeURIComponent(triggerId)}/toggle`,
      { enabled },
    )
    return res.data
  },

  /**
   * Delete a trigger (stops the scheduled task permanently).
   * DELETE /api/v1/triggers/{id}
   */
  async remove(triggerId: string): Promise<void> {
    await apiClient.delete(`/api/v1/triggers/${encodeURIComponent(triggerId)}`)
  },
}

/* ─── Query key factory ─── */

export const triggerKeys = {
  all: ['triggers'] as const,
  lists: () => [...triggerKeys.all, 'list'] as const,
  list: () => [...triggerKeys.lists()] as const,
  details: () => [...triggerKeys.all, 'detail'] as const,
  detail: (id: string) => [...triggerKeys.details(), id] as const,
}

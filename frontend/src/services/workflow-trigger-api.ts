/**
 * Workflow Trigger API service — wraps backend /triggers endpoints.
 *
 * Uses the shared apiClient instance (auto auth header + 401 refresh).
 * Triggers are independent documents. Multiple triggers can exist per workflow.
 */
import { apiClient } from './api-client'

import type { TriggerConfig } from '@/types/workflow-trigger'

/** Helper to extract the trigger ID from a response (supports both _id and id). */
function getTriggerId(trigger: TriggerConfig): string {
  return trigger._id || trigger.id || ''
}

export const WorkflowTriggerAPI = {
  /**
   * Find triggers for a given workflow.
   * Returns the first trigger or null if none exists.
   */
  async findTriggerForWorkflow(workflowId: string): Promise<TriggerConfig | null> {
    const res = await apiClient.get<{ total: number; items: TriggerConfig[] }>(
      '/api/v1/triggers',
      { params: { workflow_id: workflowId } },
    )
    const items = res.data.items || []
    return items.length > 0 ? items[0] : null
  },

  /**
   * Create a new trigger for a workflow (always POST).
   * Same user can have multiple triggers for the same workflow.
   */
  async createTrigger(workflowId: string, config: Partial<TriggerConfig>): Promise<TriggerConfig> {
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
   * Create or update a trigger for a workflow.
   * If a trigger already exists, updates it (PUT).
   * Otherwise creates a new one (POST).
   */
  async updateTrigger(workflowId: string, config: Partial<TriggerConfig>): Promise<TriggerConfig> {
    const existing = await this.findTriggerForWorkflow(workflowId)
    if (existing) {
      const triggerId = getTriggerId(existing)
      const res = await apiClient.put<TriggerConfig>(
        `/api/v1/triggers/${encodeURIComponent(triggerId)}`,
        {
          type: config.type,
          cron_expression: config.cron_expression,
          execute_at: config.execute_at,
          default_input: config.default_input,
        },
      )
      return res.data
    } else {
      const res = await apiClient.post<TriggerConfig>('/api/v1/triggers', {
        workflow_id: workflowId,
        type: config.type || 'cron',
        enabled: config.enabled ?? false,
        cron_expression: config.cron_expression,
        execute_at: config.execute_at,
        default_input: config.default_input,
      })
      return res.data
    }
  },

  /**
   * Get the current user's trigger for a workflow.
   * Throws 404-equivalent if not found (returns null via rejection).
   */
  async getTrigger(workflowId: string): Promise<TriggerConfig> {
    const trigger = await this.findTriggerForWorkflow(workflowId)
    if (!trigger) {
      const err = new Error('Trigger not found') as Error & { response?: { status: number } }
      err.response = { status: 404 }
      throw err
    }
    return trigger
  },

  /**
   * Toggle the enabled state of a trigger.
   */
  async toggleTrigger(workflowId: string, enabled: boolean): Promise<TriggerConfig> {
    const existing = await this.findTriggerForWorkflow(workflowId)
    if (!existing) {
      throw new Error('Trigger not found')
    }
    const triggerId = getTriggerId(existing)
    const res = await apiClient.patch<TriggerConfig>(
      `/api/v1/triggers/${encodeURIComponent(triggerId)}/toggle`,
      { enabled },
    )
    return res.data
  },

  /**
   * Get a trigger by its ID directly.
   */
  async getTriggerById(triggerId: string): Promise<TriggerConfig> {
    const res = await apiClient.get<TriggerConfig>(
      `/api/v1/triggers/${encodeURIComponent(triggerId)}`,
    )
    return res.data
  },

  /**
   * Update a trigger by its ID directly (used when editing a pending scheduled task).
   */
  async updateTriggerById(triggerId: string, config: Partial<TriggerConfig>): Promise<TriggerConfig> {
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
   * List all triggers for the current user (no workflow_id filter).
   */
  async listTriggers(): Promise<{ total: number; items: TriggerConfig[] }> {
    const res = await apiClient.get<{ total: number; items: TriggerConfig[] }>(
      '/api/v1/triggers',
    )
    return res.data
  },

  /**
   * Delete a trigger by its ID (stops the scheduled task permanently).
   */
  async deleteTriggerById(triggerId: string): Promise<void> {
    await apiClient.delete(`/api/v1/triggers/${encodeURIComponent(triggerId)}`)
  },
}

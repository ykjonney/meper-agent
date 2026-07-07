/**
 * Workflow Trigger API service — wraps backend /workflows/:id/trigger endpoints.
 *
 * Uses the shared apiClient instance (auto auth header + 401 refresh).
 */
import { apiClient } from './api-client'

import type { TriggerConfig } from '@/types/workflow-trigger'

export const WorkflowTriggerAPI = {
  async updateTrigger(workflowId: string, config: Partial<TriggerConfig>) {
    const res = await apiClient.post<TriggerConfig>(
      `/api/v1/workflows/${encodeURIComponent(workflowId)}/trigger`,
      config,
    )
    return res.data
  },

  async getTrigger(workflowId: string) {
    const res = await apiClient.get<TriggerConfig>(
      `/api/v1/workflows/${encodeURIComponent(workflowId)}/trigger`,
    )
    return res.data
  },

  async deleteTrigger(workflowId: string) {
    const res = await apiClient.delete<{ status: string }>(
      `/api/v1/workflows/${encodeURIComponent(workflowId)}/trigger`,
    )
    return res.data
  },

  async toggleTrigger(workflowId: string, enabled: boolean) {
    const res = await apiClient.patch<TriggerConfig>(
      `/api/v1/workflows/${encodeURIComponent(workflowId)}/trigger/toggle`,
      { enabled },
    )
    return res.data
  },
}

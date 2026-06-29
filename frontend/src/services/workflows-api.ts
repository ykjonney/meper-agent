/**
 * Workflows API service — wraps backend /workflows endpoints.
 *
 * Uses the shared apiClient instance (auto auth header + 401 refresh).
 * Response fields are snake_case per backend contract.
 */
import { apiClient } from './api-client'

/* ─── Types ─── */

export type WorkflowStatusValue = 'draft' | 'published' | 'archived'

export interface WorkflowNode {
  node_id: string
  type: string
  label: string
  config: Record<string, unknown>
  position: { x: number; y: number }
}

export interface WorkflowEdge {
  edge_id: string
  source: string
  target: string
  label: string
  condition?: string | null
}

/** next_nodes 条目 — 放在普通节点 config 中，替代独立 edge */
export interface NextNodeRef {
  target: string
  label: string
  condition?: string | null
}

export interface WorkflowSummary {
  id: string
  name: string
  description: string
  status: WorkflowStatusValue
  version: number
  node_count: number
  tags: string[]
  created_by: string
  created_at: string
  updated_at: string
}

export interface WorkflowDetail extends WorkflowSummary {
  nodes: WorkflowNode[]
  edges: WorkflowEdge[]
}

export interface WorkflowListParams {
  page?: number
  page_size?: number
  status?: string
  name?: string
}

export interface WorkflowListResponse {
  items: WorkflowSummary[]
  total: number
  page: number
  page_size: number
}

export interface WorkflowCreatePayload {
  name: string
  description?: string
  tags?: string[]
}

export interface WorkflowUpdatePayload {
  name?: string
  description?: string
  nodes?: WorkflowNode[]
  edges?: WorkflowEdge[]
  tags?: string[]
}

/* ─── API methods ─── */

export const workflowsApi = {
  /**
   * List workflow templates with optional filtering.
   * GET /api/v1/workflows
   */
  async list(params: WorkflowListParams = {}): Promise<WorkflowListResponse> {
    const res = await apiClient.get<WorkflowListResponse>('/api/v1/workflows', { params })
    return res.data
  },

  /**
   * Get a single workflow template by ID.
   * GET /api/v1/workflows/{id}
   */
  async get(workflowId: string): Promise<WorkflowDetail> {
    const res = await apiClient.get<WorkflowDetail>(`/api/v1/workflows/${encodeURIComponent(workflowId)}`)
    return res.data
  },

  /**
   * Create a new workflow template.
   * POST /api/v1/workflows
   */
  async create(data: WorkflowCreatePayload): Promise<WorkflowDetail> {
    const res = await apiClient.post<WorkflowDetail>('/api/v1/workflows', data)
    return res.data
  },

  /**
   * Update a workflow template.
   * PUT /api/v1/workflows/{id}
   */
  async update(workflowId: string, data: WorkflowUpdatePayload): Promise<WorkflowDetail> {
    const res = await apiClient.put<WorkflowDetail>(
      `/api/v1/workflows/${encodeURIComponent(workflowId)}`,
      data,
    )
    return res.data
  },

  /**
   * Delete a workflow template.
   * DELETE /api/v1/workflows/{id}
   */
  async remove(workflowId: string): Promise<void> {
    await apiClient.delete(`/api/v1/workflows/${encodeURIComponent(workflowId)}`)
  },

  /**
   * Publish a workflow template (draft → published).
   * POST /api/v1/workflows/{id}/publish
   */
  async publish(workflowId: string): Promise<WorkflowDetail> {
    const res = await apiClient.post<WorkflowDetail>(
      `/api/v1/workflows/${encodeURIComponent(workflowId)}/publish`,
    )
    return res.data
  },

  /**
   * Archive a workflow template (published → archived).
   * POST /api/v1/workflows/{id}/archive
   */
  async archive(workflowId: string): Promise<WorkflowDetail> {
    const res = await apiClient.post<WorkflowDetail>(
      `/api/v1/workflows/${encodeURIComponent(workflowId)}/archive`,
    )
    return res.data
  },
}

/* ─── Query key factory ─── */

export const workflowKeys = {
  all: ['workflows'] as const,
  lists: () => [...workflowKeys.all, 'list'] as const,
  list: (params: WorkflowListParams) => [...workflowKeys.lists(), params] as const,
  details: () => [...workflowKeys.all, 'detail'] as const,
  detail: (id: string) => [...workflowKeys.details(), id] as const,
}

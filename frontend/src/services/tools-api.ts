/**
 * Tools API service — wraps backend /tools endpoints.
 *
 * Uses the shared apiClient instance (auto auth header + 401 refresh).
 * Response fields are snake_case per backend contract.
 */
import { apiClient } from './api-client'

/* ─── Types (snake_case, matches backend schemas) ─── */

export type ToolStatus = 'draft' | 'active' | 'inactive'

export interface SkillFile {
  path: string
  content: string
  size: number
}

export interface Tool {
  id: string
  name: string
  description: string
  input_schema: Record<string, unknown>
  output_schema: Record<string, unknown>
  instructions: string
  source: string
  source_file: string
  mcp_connection_id: string
  status: ToolStatus
  version: number
  tags: string[]
  files: SkillFile[]
  created_at: string
  updated_at: string
}

export interface ToolListParams {
  page?: number
  page_size?: number
  name?: string
  status?: ToolStatus
  /** Filter by source: markdown / mcp / builtin */
  source?: string
}

export interface ToolListResponse {
  items: Tool[]
  total: number
  page: number
  page_size: number
}

export interface ToolUploadResult {
  created: Tool[]
  errors: ToolUploadError[]
}

export interface ToolUploadError {
  filename: string
  error: string
}

export interface SkillFileTreeNode {
  key: string
  title: string
  is_leaf: boolean
  children?: SkillFileTreeNode[]
  size: number
}

export interface SkillFileTreeResponse {
  tool_id: string
  files: SkillFileTreeNode[]
}

export interface SkillFileUpdatePayload {
  content: string
}

/* ─── API methods ─── */

export const toolsApi = {
  /**
   * List tools with optional pagination, name search, status filter.
   * GET /api/v1/tools
   */
  async list(params: ToolListParams = {}): Promise<ToolListResponse> {
    const res = await apiClient.get<ToolListResponse>('/api/v1/tools', {
      params: {
        page: params.page ?? 1,
        page_size: params.page_size ?? 20,
        ...(params.name ? { name: params.name } : {}),
        ...(params.status ? { status: params.status } : {}),
        ...(params.source ? { source: params.source } : {}),
      },
    })
    return res.data
  },

  /**
   * Get a single tool by ID.
   * GET /api/v1/tools/{id}
   */
  async get(toolId: string): Promise<Tool> {
    const res = await apiClient.get<Tool>(`/api/v1/tools/${encodeURIComponent(toolId)}`)
    return res.data
  },

  /**
   * Upload Skill files (single or directory).
   * POST /api/v1/tools/upload
   */
  async upload(files: File[]): Promise<ToolUploadResult> {
    const formData = new FormData()
    files.forEach((f) => formData.append('files', f))
    const res = await apiClient.post<ToolUploadResult>('/api/v1/tools/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
    })
    return res.data
  },

  /**
   * Update a tool's status or tags.
   * PUT /api/v1/tools/{id}
   */
  async update(toolId: string, data: { status?: ToolStatus; tags?: string[] }): Promise<Tool> {
    const res = await apiClient.put<Tool>(`/api/v1/tools/${encodeURIComponent(toolId)}`, data)
    return res.data
  },

  /**
   * Delete a tool.
   * DELETE /api/v1/tools/{id}
   */
  async remove(toolId: string): Promise<void> {
    await apiClient.delete(`/api/v1/tools/${encodeURIComponent(toolId)}`)
  },

  /**
   * Get file tree for a directory-based tool.
   * GET /api/v1/tools/{id}/files
   */
  async getFileTree(toolId: string): Promise<SkillFileTreeResponse> {
    const res = await apiClient.get<SkillFileTreeResponse>(
      `/api/v1/tools/${encodeURIComponent(toolId)}/files`,
    )
    return res.data
  },

  /**
   * Get a single file's content.
   * GET /api/v1/tools/{id}/files/{path}
   */
  async getFileContent(toolId: string, filePath: string): Promise<SkillFile> {
    const res = await apiClient.get<SkillFile>(
      `/api/v1/tools/${encodeURIComponent(toolId)}/files/${encodeURIComponent(filePath)}`,
    )
    return res.data
  },

  /**
   * Update a single file's content.
   * PUT /api/v1/tools/{id}/files/{path}
   */
  async updateFileContent(toolId: string, filePath: string, content: string): Promise<SkillFile> {
    const res = await apiClient.put<SkillFile>(
      `/api/v1/tools/${encodeURIComponent(toolId)}/files/${encodeURIComponent(filePath)}`,
      { content },
    )
    return res.data
  },
}

/* ─── Query key factory ─── */

export const toolKeys = {
  all: ['tools'] as const,
  lists: () => [...toolKeys.all, 'list'] as const,
  list: (params: ToolListParams) => [...toolKeys.lists(), params] as const,
  details: () => [...toolKeys.all, 'detail'] as const,
  detail: (id: string) => [...toolKeys.details(), id] as const,
  files: (id: string) => [...toolKeys.detail(id), 'files'] as const,
  fileContent: (id: string, path: string) => [...toolKeys.detail(id), 'file', path] as const,
}

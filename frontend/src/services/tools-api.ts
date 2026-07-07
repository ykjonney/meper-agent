/**
 * Tools API service — wraps backend /tools endpoints.
 *
 * Uses the shared apiClient instance (auto auth header + 401 refresh).
 * Response fields are snake_case per backend contract.
 */
import { apiClient } from './api-client'

/* ─── Types (snake_case, matches backend schemas) ─── */

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
  credential_type: string
  credential_fields: string[]
  endpoint: Record<string, unknown>
  code: string
  prebuilt_name: string
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
  /** Filter by source: markdown / mcp / builtin */
  source?: string
  /** Filter by MCP connection ID */
  mcp_connection_id?: string
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

export interface BuiltinTool {
  name: string
  description: string
  parameters: Record<string, unknown>
}

/* ─── API methods ─── */

export const toolsApi = {
  /**
   * List tools with optional pagination, name search, source filter.
   * GET /api/v1/tools
   */
  async list(params: ToolListParams = {}): Promise<ToolListResponse> {
    const res = await apiClient.get<ToolListResponse>('/api/v1/tools', {
      params: {
        page: params.page ?? 1,
        page_size: params.page_size ?? 20,
        ...(params.name ? { name: params.name } : {}),
        ...(params.source ? { source: params.source } : {}),
        ...(params.mcp_connection_id ? { mcp_connection_id: params.mcp_connection_id } : {}),
      },
    })
    return res.data
  },

  /**
   * List built-in tools (bash / read / write).
   * GET /api/v1/tools/builtin
   */
  async listBuiltins(): Promise<BuiltinTool[]> {
    const res = await apiClient.get<BuiltinTool[]>('/api/v1/tools/builtin')
    return res.data
  },

  /**
   * List prebuilt tools (platform-registered).
   * GET /api/v1/tools/prebuilt
   */
  async listPrebuilt(): Promise<Record<string, unknown>[]> {
    const res = await apiClient.get<Record<string, unknown>[]>('/api/v1/tools/prebuilt')
    return res.data
  },

  /**
   * Create a custom tool (OpenAPI / Code / Prebuilt).
   * POST /api/v1/tools
   */
  async createCustom(body: {
    name: string
    description?: string
    source: string
    input_schema?: Record<string, unknown>
    credential_type?: string
    credential_fields?: string[]
    endpoint?: Record<string, unknown>
    code?: string
    prebuilt_name?: string
  }): Promise<Tool> {
    const res = await apiClient.post<Tool>('/api/v1/tools', body)
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
   * Update a tool's tags.
   * PUT /api/v1/tools/{id}
   */
  async update(toolId: string, data: { tags?: string[] }): Promise<Tool> {
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

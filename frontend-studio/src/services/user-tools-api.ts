/**
 * User tools API — 组织工具库（ToB 治理模型）。
 *
 * 后端：app/api/v1/user_tools.py
 * 流程：tool:write 创建 → submit → admin 审查 → admin 配置凭证 → admin 开启
 * → 「已开启」的工具才能被 Agent 绑定 / 工作流节点直调（凭证工具级统一）。
 */
import { apiClient } from '../lib/api-client'

/* ─── Types ─── */

export interface UserToolItem {
  id: string
  name: string
  description: string
  /** 工具类型：openapi（HTTP 封装）| code（Python 沙箱） */
  source: string
  /** 市场审查状态机 */
  status: 'private' | 'submitted' | 'published' | 'hidden'
  /** admin 开启开关——True 才能被 Agent/工作流使用 */
  enabled: boolean
  owner_user_id?: string
  derived_from?: string | null
  derived_from_name?: string | null
  stats: { load_count?: number; up?: number; down?: number }
  version: number
  tags: string[]
  created_at: string
  updated_at: string
}

export interface UserToolDetail extends UserToolItem {
  user_args_schema?: Record<string, unknown>
  llm_args_schema?: Record<string, unknown>
  endpoint?: Record<string, unknown>
  code?: string
  /** 工具级凭证（sensitive 字段 enc: 密文，非敏感明文），凭证弹窗回显用 */
  org_user_args?: Record<string, unknown>
  /** 返回字段声明——下游工作流精确引用 {{node.result.字段}} */
  output_schema?: { type?: string; fields?: Array<{ name: string; type: string; description?: string; is_list?: boolean }> }
}

export interface ToolMarketItem {
  id: string
  name: string
  description: string
  source: string
  kind: 'official' | 'user'
  author_name: string
  /** 治理可用性：官方看 status(active)，用户工具看 enabled */
  enabled: boolean
  is_own: boolean
  my_vote: number
  score: number
  status?: string
  stats: { load_count?: number; up?: number; down?: number }
  tags?: string[]
}

export interface ToolDefinitionPayload {
  name: string
  description: string
  source: string
  user_args_schema?: Record<string, unknown>
  llm_args_schema?: Record<string, unknown>
  endpoint?: Record<string, unknown>
  code?: string
  tags?: string[]
}

/** 可用工具全集条目（官方 active + 组织库 enabled）——绑定/节点候选 */
export interface EnabledToolItem {
  id: string
  name: string
  description: string
  source: string
  org: 'official' | 'user'
  /** 运行参数定义（工作流节点按此渲染结构化参数表单） */
  llm_args_schema?: Record<string, unknown>
  /** 返回字段声明（选择工具时快照进节点 config，变量选择器按此平铺 result.xxx） */
  output_schema?: Record<string, unknown>
}

/* ─── API methods ─── */

export const userToolsApi = {
  /** 可用工具全集（Agent 绑定 / 工作流节点候选） */
  listEnabled() {
    return apiClient.get<EnabledToolItem[]>('/api/v1/user-tools/enabled').then((r) => r.data)
  },

  get(toolId: string) {
    return apiClient.get<UserToolDetail>(`/api/v1/user-tools/${toolId}`).then((r) => r.data)
  },

  create(body: ToolDefinitionPayload) {
    return apiClient.post<UserToolDetail>('/api/v1/user-tools', body).then((r) => r.data)
  },

  update(toolId: string, body: Partial<ToolDefinitionPayload>) {
    return apiClient.put<UserToolDetail>(`/api/v1/user-tools/${toolId}`, body).then((r) => r.data)
  },

  remove(toolId: string) {
    return apiClient.delete(`/api/v1/user-tools/${toolId}`).then((r) => r.data)
  },

  /* ── 组织工具库目录 ── */

  marketplace(q = '') {
    return apiClient
      .get<ToolMarketItem[]>('/api/v1/user-tools/marketplace', { params: q ? { q } : {} })
      .then((r) => r.data)
  },

  submit(toolId: string) {
    return apiClient.post(`/api/v1/user-tools/${toolId}/submit`).then((r) => r.data)
  },

  fork(toolId: string) {
    return apiClient.post(`/api/v1/user-tools/${toolId}/fork`).then((r) => r.data)
  },

  vote(toolId: string, value: 1 | -1) {
    return apiClient.post(`/api/v1/user-tools/${toolId}/vote`, { value }).then((r) => r.data)
  },

  /* ── admin 治理 ── */

  /** 配置工具级统一凭证（sensitive 后端加密；全使用点共用） */
  saveOrgArgs(toolId: string, userArgs: Record<string, unknown>) {
    return apiClient
      .put(`/api/v1/user-tools/${toolId}/args`, { user_args: userArgs })
      .then((r) => r.data)
  },

  /** 开启/停用（开启三重校验：published + 定义完整 + 凭证完整） */
  enable(toolId: string, enabled: boolean) {
    return apiClient
      .post<UserToolItem>(`/api/v1/user-tools/${toolId}/enable`, { enabled })
      .then((r) => r.data)
  },

  reviewList(status = 'submitted') {
    return apiClient
      .get<UserToolDetail[]>(`/api/v1/user-tools/admin/review`, { params: { status } })
      .then((r) => r.data)
  },

  review(toolId: string, action: 'approve' | 'reject', reason = '') {
    return apiClient
      .post(`/api/v1/user-tools/admin/review/${toolId}`, { action, reason })
      .then((r) => r.data)
  },
}

/* ─── Query key factory ─── */

export const userToolKeys = {
  all: ['userTools'] as const,
  enabled: () => [...userToolKeys.all, 'enabled'] as const,
  detail: (id: string) => [...userToolKeys.all, 'detail', id] as const,
  marketplace: (q: string) => [...userToolKeys.all, 'marketplace', q] as const,
  review: (status: string) => [...userToolKeys.all, 'review', status] as const,
}

/**
 * Backend type definitions (snake_case, matches backend Pydantic schemas).
 *
 * Shared/cross-cutting types live here. Service-specific types stay in their
 * own *-api.ts files. WorkflowNode/Edge/NextNodeRef mirror
 * frontend/src/services/workflows-api.ts (lines 13-34).
 */

/* ─── Auth ─── */

export interface AuthUser {
  id: string
  username: string
  role: string
  permissions: string[]
  /** 权限键 → 中文名（/auth/me 由后端 permission_labels 组装下发） */
  permission_labels?: Record<string, string>
  /** 超级管理员标记（初始管理员）——映射到 store 侧 AuthUser.isSuperAdmin。 */
  is_super_admin?: boolean
}

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
  expires_in: number
  user?: AuthUser
}

/* ─── Workflow graph types ─── */

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

/* ─── RBAC ─── */

export type RoleType = 'system' | 'custom'

export interface Role {
  id: string
  name: string
  display_name: string
  description: string
  role_type: RoleType
  permissions: string[]
  created_at: string
  updated_at: string
}

/**
 * All available permission keys, grouped by module (for the checkbox UI).
 * Keys must match backend ALL_PERMISSION_KEYS.
 */
export const PERMISSION_GROUPS: Record<string, string[]> = {
  '用户管理': ['user:read', 'user:write'],
  'Agent 管理': ['agent:read', 'agent:write', 'agent:invoke'],
  '工作流': ['workflow:read', 'workflow:write'],
  '定时任务': ['trigger:read', 'trigger:write', 'trigger:manage'],
  '工具': ['tool:read', 'tool:write'],
  '应用': ['application:read', 'application:write'],
  'MCP': ['mcp:read', 'mcp:write'],
  '消息渠道': ['channel:read', 'channel:write'],
  'Skill': ['skill:read', 'skill:write'],
  '任务': ['task:read', 'task:write', 'task:invoke'],
  '知识库': ['knowledge:read', 'knowledge:write'],
  '执行日志': ['execution:read:all', 'execution:read:own'],
  '系统': ['apikey:manage', 'settings:manage', 'model:read', 'model:write'],
}

/** Flat list of all permission keys */
export const ALL_PERMISSIONS: string[] = Object.values(PERMISSION_GROUPS).flat()

/* ── 权限点中文标签 ──────────────────────────────────────────────
   展示层翻译（角色卡 chips / 权限树叶子）；存储/提交仍用原始 key。
   由 PERMISSION_GROUPS 自动生成，后端新增权限点时资源/动作词典
   覆盖不了的自动回退显示原文。 */

const RESOURCE_LABELS: Record<string, string> = {
  user: '用户', agent: 'Agent', workflow: '工作流', trigger: '定时任务',
  tool: '工具', application: '应用', mcp: 'MCP', channel: '消息渠道',
  skill: 'Skill', task: '任务', knowledge: '知识库', execution: '执行日志',
  apikey: 'API Key', settings: '系统设置', model: '模型',
}

const ACTION_LABELS: Record<string, string> = {
  read: '查看', write: '管理', invoke: '调用', manage: '管理',
}

const SCOPE_SUFFIX: Record<string, string> = {
  all: '全部', own: '仅本人',
}

export const PERMISSION_LABELS: Record<string, string> = Object.fromEntries(
  ALL_PERMISSIONS.map((k) => {
    const [res, action, scope] = k.split(':')
    const r = RESOURCE_LABELS[res] ?? res
    const a = ACTION_LABELS[action] ?? action
    const label = scope ? `${r} ${a}${SCOPE_SUFFIX[scope] ?? scope}` : `${r} ${a}`
    return [k, label]
  }),
)

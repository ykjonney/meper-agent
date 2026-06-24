/**
 * 变量类型系统 — 类型定义、配置元数据、约束默认值。
 *
 * 支持的类型：text / number / boolean / json / file / select
 * 每种类型有对应的约束字段，在 VariableTypeSelector 中动态展示。
 */

/* ─── 类型名称 ─── */

export type VariableTypeName = 'text' | 'number' | 'boolean' | 'json' | 'file' | 'select'

/* ─── 变量定义 ─── */

export interface VariableDefinition {
  /** 变量名，如 user_query */
  name: string
  /** 显示标签 */
  label: string
  /** 变量类型 */
  type: VariableTypeName
  /** 类型相关约束 */
  constraints: Record<string, unknown>
  /** 简短说明 */
  description?: string
  /** 是否必填 */
  required?: boolean
  /** 系统默认变量：只读，用户不可编辑/删除 */
  readonly?: boolean
}

/* ─── 约束字段描述 ─── */

export interface ConstraintFieldDef {
  name: string
  label: string
  /** 字段值类型：用于表单渲染 */
  valueType: 'number' | 'string' | 'boolean' | 'json' | 'tags'
  defaultValue: unknown
  placeholder?: string
  min?: number
  max?: number
}

/* ─── 类型配置元数据 ─── */

export interface VariableTypeConfig {
  label: string
  color: string
  icon: string
  description: string
  constraintFields: ConstraintFieldDef[]
}

export const VARIABLE_TYPE_CONFIGS: Record<VariableTypeName, VariableTypeConfig> = {
  text: {
    label: '文本',
    color: '#3B82F6',
    icon: 'T',
    description: '文本字符串',
    constraintFields: [
      { name: 'max_length', label: '最大长度', valueType: 'number', defaultValue: null, placeholder: '不限' },
      { name: 'min_length', label: '最小长度', valueType: 'number', defaultValue: null, placeholder: '不限' },
      { name: 'default_value', label: '默认值', valueType: 'string', defaultValue: '', placeholder: '可选' },
      { name: 'required', label: '必填', valueType: 'boolean', defaultValue: false },
    ],
  },
  number: {
    label: '数字',
    color: '#F59E0B',
    icon: '#',
    description: '数值',
    constraintFields: [
      { name: 'min', label: '最小值', valueType: 'number', defaultValue: null, placeholder: '不限' },
      { name: 'max', label: '最大值', valueType: 'number', defaultValue: null, placeholder: '不限' },
      { name: 'default_value', label: '默认值', valueType: 'number', defaultValue: null, placeholder: '可选' },
      { name: 'required', label: '必填', valueType: 'boolean', defaultValue: false },
      { name: 'precision', label: '精度（小数位）', valueType: 'number', defaultValue: null, placeholder: '不限', min: 0, max: 10 },
    ],
  },
  boolean: {
    label: '布尔',
    color: '#8B5CF6',
    icon: '✔',
    description: '是/否值',
    constraintFields: [
      { name: 'default_value', label: '默认值', valueType: 'boolean', defaultValue: null },
    ],
  },
  json: {
    label: 'JSON',
    color: '#06B6D4',
    icon: '{}',
    description: '结构化 JSON 数据',
    constraintFields: [
      { name: 'schema', label: 'JSON Schema', valueType: 'json', defaultValue: null, placeholder: '{"type": "object", ...}' },
      { name: 'default_value', label: '默认值', valueType: 'json', defaultValue: null, placeholder: '{"key": "value"}' },
      { name: 'required', label: '必填', valueType: 'boolean', defaultValue: false },
    ],
  },
  file: {
    label: '文件',
    color: '#F97316',
    icon: '📄',
    description: '文件上传',
    constraintFields: [
      { name: 'allowed_extensions', label: '允许的扩展名', valueType: 'tags', defaultValue: [], placeholder: '如 .pdf, .txt' },
      { name: 'max_size_mb', label: '最大大小 (MB)', valueType: 'number', defaultValue: null, placeholder: '不限', min: 1, max: 1024 },
      { name: 'multiple', label: '允许多文件', valueType: 'boolean', defaultValue: false },
    ],
  },
  select: {
    label: '选择',
    color: '#EC4899',
    icon: '☰',
    description: '预定义选项',
    constraintFields: [
      { name: 'options', label: '选项列表', valueType: 'json', defaultValue: [], placeholder: '["option1", "option2"]' },
      { name: 'default_value', label: '默认值', valueType: 'string', defaultValue: '', placeholder: '可选' },
      { name: 'multiple', label: '多选', valueType: 'boolean', defaultValue: false },
    ],
  },
}

/* ─── 辅助函数 ─── */

/**
 * 根据类型名称生成默认约束值
 */
export function getDefaultConstraints(type: VariableTypeName): Record<string, unknown> {
  const config = VARIABLE_TYPE_CONFIGS[type]
  const constraints: Record<string, unknown> = {}
  for (const field of config.constraintFields) {
    if (field.defaultValue !== null && field.defaultValue !== undefined) {
      constraints[field.name] = field.defaultValue
    }
  }
  return constraints
}

/**
 * 创建新的变量定义，包含默认约束
 */
export function createVariableDefinition(
  name: string,
  type: VariableTypeName,
  label?: string,
): VariableDefinition {
  return {
    name,
    label: label || name,
    type,
    constraints: getDefaultConstraints(type),
  }
}

/* ─── 图标和颜色映射（用于 VariableSelector 展示） ─── */

export const TYPE_ICON_MAP: Record<string, string> = {
  text: 'T',
  number: '#',
  boolean: '✔',
  json: '{}',
  file: '📄',
  select: '☰',
}

export const TYPE_COLOR_MAP: Record<string, string> = {
  text: '#3B82F6',
  number: '#F59E0B',
  boolean: '#8B5CF6',
  json: '#06B6D4',
  file: '#F97316',
  select: '#EC4899',
}

/**
 * 获取类型的显示图标（带颜色的文字标记）
 */
export function getTypeIcon(type: string): string {
  return TYPE_ICON_MAP[type] ?? '?'
}

/**
 * 获取类型的显示颜色
 */
export function getTypeColor(type: string): string {
  return TYPE_COLOR_MAP[type] ?? '#64748B'
}

/**
 * 获取类型的显示标签
 */
export function getTypeLabel(type: string): string {
  return VARIABLE_TYPE_CONFIGS[type as VariableTypeName]?.label ?? type
}

/**
 * 格式化类型约束为可读字符串（用于 Tooltip）
 */
export function formatConstraints(constraints: Record<string, unknown>): string {
  const parts: string[] = []
  for (const [key, value] of Object.entries(constraints)) {
    if (value === null || value === undefined || value === '') continue
    if (typeof value === 'boolean') {
      if (value) parts.push(key)
      continue
    }
    if (Array.isArray(value) && value.length === 0) continue
    parts.push(`${key}=${Array.isArray(value) ? value.join(',') : String(value)}`)
  }
  return parts.join(' | ') || '无约束'
}

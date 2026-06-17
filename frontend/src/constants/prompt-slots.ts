/**
 * Fixed prompt slot schema — shared across Agent form and AgentNode config.
 *
 * Mirrors backend SLOT_SCHEMA in models/prompt_template.py.
 * tool_declaration is always auto-appended by the renderer (not in this list).
 */

export interface SlotDef {
  name: string
  label: string
  required: boolean
  placeholder: string
}

export const FIXED_SLOTS: SlotDef[] = [
  { name: 'role', label: '角色定义', required: false, placeholder: '定义 Agent 的身份、人格和专业能力，例如："你是一位资深客服专家，擅长用温和的语气解答用户问题"' },
  { name: 'task', label: '任务描述', required: false, placeholder: '描述 Agent 的核心职责和工作目标，例如："根据用户的问题，提供准确、简洁的解答"' },
  { name: 'constraints', label: '约束规则', required: false, placeholder: '定义行为边界和禁止事项，例如："不要编造信息，不确定时明确告知用户"' },
  { name: 'context', label: '上下文信息', required: false, placeholder: '提供背景知识或环境信息，例如："当前产品版本为 v2.0，支持的语种为中文和英文"' },
  { name: 'output_format', label: '输出格式', required: false, placeholder: '指定期望的输出结构或格式，例如："使用 Markdown 格式，先给出结论再展开分析"' },
]

export const SLOT_NAMES: string[] = FIXED_SLOTS.map((s) => s.name)

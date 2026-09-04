/**
 * WorkflowBaseNode — 通用自定义节点底座。
 *
 * 两行结构：上行「类别」（图标 + 类型名，类型色），下行「信息区」
 * （所选 Agent/工具名、模型、输入变量清单、分支数等摘要，逐行展示）。
 * 不放 node label——节点身份由类别 + 配置摘要表达。
 *
 * 样式规范：
 * - 边框：细边框 + 左侧 2px 类型色 accent 条（不同类型一眼可辨）；
 *   选中态整框品牌蓝，配置不完整 amber 警示。
 * - 尺寸：宽度按类型固定给定（不随内容变化，不同类型宽度不同）；
 *   高度随信息行数自适应（内容超宽换行/截断）。
 * - 字体层次：类别行 8px/medium/类型色；信息行 7px/regular/灰，
 *   必填项以红色 * 标记。
 *
 * lucide-react 版本（替换原 @ant-design/icons）。
 */
import { memo, type ReactNode } from 'react'
import { Handle, Position, type NodeProps } from '@xyflow/react'
import {
  PlayCircle,
  StopCircle,
  Workflow,
  Wrench,
  GitBranch,
  Split,
  UserCheck,
} from 'lucide-react'
import type { WorkflowNodeData } from '../utils/canvas-converters'
import { useAgentInfo, useToolNames } from '../agent-info'

type Props = NodeProps & { data: WorkflowNodeData }

/** 节点类型 → 图标组件映射（直接在渲染时创建，避免序列化问题） */
const TYPE_ICONS: Record<string, ReactNode> = {
  start: <PlayCircle size={9} strokeWidth={2} />,
  end: <StopCircle size={9} strokeWidth={2} />,
  agent: <Workflow size={9} strokeWidth={2} />,
  tool: <Wrench size={9} strokeWidth={2} />,
  gateway: <GitBranch size={9} strokeWidth={2} />,
  parallel: <Split size={9} strokeWidth={2} />,
  human: <UserCheck size={9} strokeWidth={2} />,
}

/** 节点类型 → 类别名（上行固定展示） */
const TYPE_NAMES: Record<string, string> = {
  start: '开始',
  end: '结束',
  agent: 'Agent',
  tool: '工具',
  gateway: '网关',
  parallel: '并行',
  human: '人工审批',
}

/** 节点类型 → 固定宽度（按类型实际情况给定，不随内容变化；高度自适应） */
const TYPE_WIDTH: Record<string, number> = {
  start: 105,
  end: 85,
  agent: 120,
  tool: 115,
  gateway: 80,
  parallel: 80,
  human: 115,
}

/** 信息区单行（text 必填时可带红色 * 标记） */
interface InfoRow {
  text: string
  required?: boolean
}

/** start 节点输入变量最多展示行数，超出折叠为 +N（悬停看全文）。 */
const MAX_VAR_ROWS = 5

/**
 * 信息区行集：按类型提取配置摘要。
 * Agent/工具名称优先经 context 实时解析（列表），降级 config 选择时缓存；
 * 卡片不显示 ID 等不可读内容——名称不可得时用可读占位。
 */
function getInfoRows(
  type: string,
  config: Record<string, unknown>,
  agentInfoMap: Record<string, { name: string; model: string }>,
  toolNameMap: Record<string, string>,
): InfoRow[] {
  switch (type) {
    case 'start': {
      // 优先 config.output_variables（用户自定义输入变量，逐行展示 + 必填标记）
      const outputVars = config.output_variables as
        | Array<{ name?: string; required?: boolean }>
        | undefined
      if (outputVars && outputVars.length > 0) {
        const rows: InfoRow[] = outputVars
          .filter((v) => v.name)
          .slice(0, MAX_VAR_ROWS)
          .map((v) => ({ text: v.name as string, required: !!v.required }))
        const rest = outputVars.length - MAX_VAR_ROWS
        if (rest > 0) rows.push({ text: `… +${rest} 项` })
        return rows
      }
      // fallback input_schema（properties + required 数组）
      const schema = config.input_schema as
        | { properties?: Record<string, unknown>; required?: string[] }
        | undefined
      const keys = schema?.properties ? Object.keys(schema.properties) : []
      if (keys.length === 0) return [{ text: '未定义输入变量' }]
      const requiredSet = new Set(schema?.required ?? [])
      const rows: InfoRow[] = keys.slice(0, MAX_VAR_ROWS).map((k) => ({
        text: k,
        required: requiredSet.has(k),
      }))
      const rest = keys.length - MAX_VAR_ROWS
      if (rest > 0) rows.push({ text: `… +${rest} 项` })
      return rows
    }
    case 'end': {
      const mapping = config.output_mapping as Record<string, unknown> | undefined
      if (!mapping || Object.keys(mapping).length === 0) return [{ text: '未定义输出映射' }]
      return [{ text: Object.keys(mapping).join(', ') }]
    }
    case 'agent': {
      const agentId = config.agent_id as string | undefined
      if (!agentId) return [{ text: '未选择 Agent' }]
      const live = agentInfoMap[agentId]
      const name = live?.name || (config.agent_name as string | undefined)
      const model = live?.model || (config.agent_model as string | undefined)
      // 名称不可得（未发布/已删除/列表加载中）→ 可读占位，绝不显示 ID；
      // 模型引用若是 model_xxx ULID（config 缓存未解析）则不显示该行。
      const rows: InfoRow[] = [{ text: name || '未命名 Agent' }]
      if (model && !model.startsWith('model_')) rows.push({ text: model })
      return rows
    }
    case 'tool': {
      const toolId = config.tool_id as string | undefined
      if (!toolId) return [{ text: '未选择工具' }]
      const name = toolNameMap[toolId] || (config.tool_name as string | undefined)
      return [{ text: name || '未命名工具' }]
    }
    case 'gateway': {
      const conditions = config.conditions as unknown[] | undefined
      return conditions && conditions.length > 0
        ? [{ text: `${conditions.length} 个条件分支` }]
        : [{ text: '未配置条件' }]
    }
    case 'parallel': {
      const branches = config.branches as unknown[] | undefined
      return branches && branches.length > 0
        ? [{ text: `${branches.length} 个并行分支` }]
        : [{ text: '未配置分支' }]
    }
    case 'human': {
      const title = config.title as string | undefined
      return [{ text: title || '未设置审批标题' }]
    }
    default:
      return []
  }
}

/**
 * 必填配置完整性检查（与后端 validator 的 MISSING_* 规则对齐）。
 * 不完整的节点在画布上以琥珀色边框 + 角标警示，避免执行时才被
 * WORKFLOW_VALIDATION_FAILED 拦下、对着裸 node_id 找不到节点。
 */
function isIncomplete(type: string, config: Record<string, unknown>): boolean {
  switch (type) {
    case 'agent':
      return !config.agent_id
    case 'tool':
      return !config.tool_id
    case 'subflow':
      return !config.workflow_id
    default:
      return false
  }
}

function WorkflowBaseNode({ data, selected }: Props) {
  const { typeColor, workflowNode } = data
  const nodeType = workflowNode.type
  const isStart = nodeType === 'start'
  const isEnd = nodeType === 'end'
  const icon = TYPE_ICONS[nodeType]
  const typeName = TYPE_NAMES[nodeType] ?? nodeType
  const size = TYPE_WIDTH[nodeType] ?? 130
  const agentInfoMap = useAgentInfo()
  const toolNameMap = useToolNames()
  const rows = getInfoRows(
    nodeType, workflowNode.config as Record<string, unknown>, agentInfoMap, toolNameMap,
  )
  const incomplete = isIncomplete(nodeType, workflowNode.config as Record<string, unknown>)

  // 左侧 accent 色随状态让位：选中 > 配置不完整 > 类型色。
  const accentColor = selected ? '#1E5EFF' : incomplete ? '#f59e0b' : typeColor
  const fullText = rows.map((r) => `${r.text}${r.required ? ' *' : ''}`).join('\n')

  return (
    <div
      className={`
        relative rounded-md bg-[#18181b] shadow-sm border border-l-2 transition-shadow cursor-pointer
        ${selected ? 'border-[#1E5EFF] shadow-md' : incomplete ? 'border-amber-500/70 hover:shadow-md' : 'border-[#27272a] hover:shadow-md'}
      `}
      style={{ width: size, borderLeftColor: accentColor }}
    >
      {/* 配置不完整角标 */}
      {incomplete && (
        <span
          title="配置不完整：缺少必填项（如未选择 Agent），执行前校验会拦截"
          className="absolute -top-1 -right-1 w-1.5 h-1.5 rounded-full bg-amber-500"
        />
      )}
      {/* 主体：上行类别 / 下行信息区（逐行，高度自适应）。
          类别行用 leading-tight——leading-none 会裁掉 "Agent" 的 g 等
          字母下伸部（高度=字号时字形溢出行盒）。 */}
      <div className="px-1.5 py-1">
        <div className="flex items-center gap-1 leading-tight">
          <span className="flex-shrink-0" style={{ color: typeColor }}>{icon}</span>
          <span className="text-[8px] font-medium truncate" style={{ color: typeColor }}>
            {typeName}
          </span>
        </div>
        {rows.length > 0 && (
          <div className="mt-0.5 space-y-px" title={fullText}>
            {rows.map((row, i) => (
              <div key={i} className="flex items-baseline leading-snug">
                <span className="flex-1 min-w-0 text-[7px] font-normal text-[#a1a1aa] truncate">
                  {row.text}
                </span>
                {row.required && (
                  <span className="shrink-0 text-[7px] leading-none text-red-400">*</span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Source Handle — End 节点隐藏 */}
      {!isEnd && (
        <Handle
          type="source"
          position={Position.Right}
          className="!w-1.5 !h-1.5 !border-[1.5px] !border-[#09090b] !transition-colors"
          style={{ backgroundColor: typeColor }}
        />
      )}

      {/* Target Handle — Start 节点隐藏 */}
      {!isStart && (
        <Handle
          type="target"
          position={Position.Left}
          className="!w-1.5 !h-1.5 !border-[1.5px] !border-[#09090b] !transition-colors"
          style={{ backgroundColor: typeColor }}
        />
      )}
    </div>
  )
}

export default memo(WorkflowBaseNode)

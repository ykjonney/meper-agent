/**
 * WorkflowBaseNode — 通用自定义节点底座。
 *
 * 卡片（Dify/Coze 节奏）：头部 = 28px 类型色淡底圆角图标块（类型识别的
 * 第一要素）+ 节点标题（12.5px semibold；WorkflowNode.label 用户命名 ||
 * 类型名，二选一永不并排）；内容区 = 头部以淡分隔线断开的配置摘要
 * （Agent/工具名、模型、输入变量清单、分支数等）。
 *
 * 样式规范：
 * - 卡体：rounded-[10px] + panel 底 + 卡片阴影；选中态品牌色边框 +
 *   ring 光晕；配置不完整 sig-wait 虚线框 + 角标；循环成员紫边 + 🔁。
 * - 尺寸：宽度按类型固定（180-240px 呼吸感宽度），高度随信息行数自适应。
 * - 连接点：9px 圆点、panel 色描边、hover 放大（index.css react-flow 层）。
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
  Repeat,
  type LucideIcon,
} from 'lucide-react'
import { getTypeColor, type WorkflowNodeData } from '../utils/canvas-converters'
import type { WorkflowNode } from '../../../services/workflows-api'
import { useAgentInfo, useToolNames } from '../agent-info'

type Props = NodeProps & { data: WorkflowNodeData }

/** 节点类型 → 图标组件映射（badge 11px / 循环步骤行 8px 复用同源） */
const TYPE_ICON_COMPS: Record<string, LucideIcon> = {
  start: PlayCircle,
  end: StopCircle,
  agent: Workflow,
  tool: Wrench,
  gateway: GitBranch,
  parallel: Split,
  human: UserCheck,
  loop: Repeat,
}

const TYPE_ICONS: Record<string, ReactNode> = Object.fromEntries(
  Object.entries(TYPE_ICON_COMPS).map(([k, C]) => [k, <C key={k} size={11} strokeWidth={2} />]),
)

/** 节点类型 → 类别名（上行固定展示） */
const TYPE_NAMES: Record<string, string> = {
  start: '开始',
  end: '结束',
  agent: 'Agent',
  tool: '工具',
  gateway: '网关',
  parallel: '并行',
  human: '人工审批',
  loop: '循环',
}

/** 节点类型 → 固定宽度（Dify/Coze 节点卡节奏：~180-240px 呼吸感宽度，
 *  高度自适应。loop 最宽：卡片逐行展示体步骤。 */
const TYPE_WIDTH: Record<string, number> = {
  start: 150,
  end: 140,
  agent: 180,
  tool: 165,
  gateway: 150,
  parallel: 150,
  human: 170,
  loop: 200,
}

/** 信息区单行（text 必填时可带红色 * 标记；循环步骤行带节点类型小图标） */
interface InfoRow {
  text: string
  required?: boolean
  /** 循环步骤行的节点类型（渲染 8px 类型色小图标） */
  iconType?: string
}

/** start 节点输入变量最多展示行数，超出折叠为 +N（悬停看全文）。 */
const MAX_VAR_ROWS = 5

/**
 * 信息区行集：按类型提取配置摘要。
 * Agent/工具名称优先经 context 实时解析（列表），降级 config 选择时缓存；
 * 卡片不显示 ID 等不可读内容——名称不可得时用可读占位。
 */
/** 循环体步骤的显示名——与 LoopNodeConfig.nodeLabel 同规则：
 * 节点名称优先（两个步骤共用同一 agent 时靠节点名区分）；未改名
 * （label=类型默认名）时回退实时解析的 Agent/工具名 > config 缓存名 */
function stepDisplayName(
  n: WorkflowNode,
  agentInfoMap: Record<string, { name: string; model: string }>,
  toolNameMap: Record<string, string>,
): string {
  const cfg = (n.config ?? {}) as Record<string, unknown>
  const typeDefault = TYPE_NAMES[n.type] ?? n.type
  const customLabel = (n.label || '') && n.label !== typeDefault ? n.label : ''
  if (customLabel) return customLabel
  if (n.type === 'agent') {
    const id = cfg.agent_id as string | undefined
    const live = id ? agentInfoMap[id] : undefined
    return String(live?.name || cfg.agent_name || typeDefault)
  }
  if (n.type === 'tool') {
    const id = cfg.tool_id as string | undefined
    const live = id ? toolNameMap[id] : undefined
    return String(live || cfg.tool_name || typeDefault)
  }
  return typeDefault
}

function getInfoRows(
  type: string,
  config: Record<string, unknown>,
  agentInfoMap: Record<string, { name: string; model: string }>,
  toolNameMap: Record<string, string>,
  loopSteps?: WorkflowNode[],
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
    case 'loop': {
      // 卡片逐行展示体步骤（成员在画布上隐藏，这里是用户看见循环内容
      // 的唯一位置）——行序即执行序，行首带节点类型小图标；超出折叠 +N
      if (loopSteps && loopSteps.length > 0) {
        const rows: InfoRow[] = loopSteps.slice(0, MAX_VAR_ROWS).map((s) => ({
          text: stepDisplayName(s, agentInfoMap, toolNameMap),
          iconType: s.type,
        }))
        const rest = loopSteps.length - MAX_VAR_ROWS
        if (rest > 0) rows.push({ text: `… +${rest} 步` })
        return rows
      }
      const body = config.body as string[] | undefined
      return body && body.length > 0
        ? [{ text: `每轮 ${body.length} 步` }]
        : [{ text: '选中后在右侧添加步骤' }]
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
  // 节点名称（画布标识，可选）——trim 后为空则不渲染该行
  const nodeLabel = (workflowNode.label || '').trim()
  const rows = getInfoRows(
    nodeType, workflowNode.config as Record<string, unknown>, agentInfoMap, toolNameMap, data.loopSteps,
  )
  const incomplete = isIncomplete(nodeType, workflowNode.config as Record<string, unknown>)

  // 左侧 accent 色随状态让位：选中 > 配置不完整 > 循环成员紫 > 类型色。
  const inLoop = !!data.isInLoop
  const accentColor = selected
    ? 'var(--color-brand)'
    : incomplete
      ? 'var(--color-sig-wait)'
      : inLoop
        ? '#A855F7'
        : typeColor
  // hover 全文：主标题 + 各摘要行（必带回退类型名，与卡片所见一致）
  const hoverText = [nodeLabel || typeName, ...rows.map((r) => `${r.text}${r.required ? ' *' : ''}`)]
    .join('\n')

  return (
    <div
      className={`
        relative rounded-[10px] bg-panel shadow-[var(--shadow-card)] border transition-all duration-150 cursor-pointer
        ${selected
          ? 'border-brand ring-[3px] ring-brand/10 shadow-md'
          : incomplete
            ? 'border-sig-wait border-dashed hover:shadow-md'
            : inLoop
              ? 'border-[#A855F7]/50 hover:shadow-md'
              : 'border-line hover:shadow-md'}
      `}
      style={{ width: size }}
    >
      {/* 配置不完整角标 */}
      {incomplete && (
        <span
          title="配置不完整：缺少必填项（如未选择 Agent），执行前校验会拦截"
          className="absolute -top-1 -right-1 w-2.5 h-2.5 rounded-full bg-sig-wait border-2 border-panel"
        />
      )}
      {/* 循环体成员角标（🔁 左上，与 loop 节点同紫色） */}
      {inLoop && !incomplete && (
        <span
          title="循环节点成员（每轮执行）"
          className="absolute -top-2.5 -left-2 text-[11px] leading-none"
        >
          <Repeat size={11} className="text-sig-wait" />
        </span>
      )}
      {/* 头部：28px 类型色淡底图标块 + 标题（12.5px semibold，Dify/Coze 节奏）。
          主标题 = 节点名称 || 类型名（二选一，永不并排）；类型识别靠图标色。
          leading-tight 防 "g" 等字母下伸部被裁。 */}
      <div className="flex items-center gap-1.5 px-2 pt-1.5 pb-1">
        <div
          className="shrink-0 w-5 h-5 flex items-center justify-center [&>svg]:w-[17px] [&>svg]:h-[17px]"
          style={{ color: typeColor }}
        >
          {icon}
        </div>
        <div className="min-w-0 flex-1 text-[11.5px] font-semibold text-ink truncate leading-tight" title={hoverText}>
          {nodeLabel || typeName}
        </div>
        {accentColor !== typeColor && !selected && (
          <span
            className="shrink-0 w-1.5 h-1.5 rounded-full"
            style={{ backgroundColor: accentColor }}
            title={incomplete ? '配置不完整' : '循环节点成员'}
          />
        )}
      </div>

      {/* 内容摘要区：与头部以淡分隔线断开（Dify 内容区节奏） */}
      {rows.length > 0 && (
        <div className="border-t border-line/70 px-2 pb-1.5 pt-1 space-y-0.5">
          {rows.map((row, i) => {
            const StepIcon = row.iconType ? TYPE_ICON_COMPS[row.iconType] : null
            return (
              <div key={i} className="flex items-center gap-1 leading-snug">
                {StepIcon && (
                  <StepIcon
                    size={9}
                    strokeWidth={2}
                    color={getTypeColor(row.iconType!)}
                    className="shrink-0"
                  />
                )}
                <span className="flex-1 min-w-0 text-[10.5px] font-normal text-ink-dim truncate">
                  {row.text}
                </span>
                {row.required && (
                  <span className="shrink-0 text-[10px] leading-none text-sig-fail">*</span>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Source Handle — End 节点隐藏（9px 圆点，panel 白底 + 类型色描边，
          hover 放大见 index.css react-flow 主题层） */}
      {!isEnd && (
        <Handle
          type="source"
          position={Position.Right}
          style={{ backgroundColor: typeColor }}
        />
      )}

      {/* Target Handle — Start 节点隐藏 */}
      {!isStart && (
        <Handle
          type="target"
          position={Position.Left}
          style={{ backgroundColor: typeColor }}
        />
      )}
    </div>
  )
}

export default memo(WorkflowBaseNode)

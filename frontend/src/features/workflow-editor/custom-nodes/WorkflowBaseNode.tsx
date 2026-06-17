/**
 * WorkflowBaseNode — 通用自定义节点底座（紧凑版）。
 *
 * 显示：图标（代表节点类型）+ 主要信息摘要。
 */
import { memo } from 'react'
import { Handle, Position, type NodeProps } from '@xyflow/react'
import {
  PlayCircleOutlined,
  StopOutlined,
  BranchesOutlined,
  NodeCollapseOutlined,
  LinkOutlined,
  NodeIndexOutlined,
  ExclamationCircleOutlined,
} from '@ant-design/icons'
import type { WorkflowNodeData } from '../utils/canvas-converters'

type Props = NodeProps & { data: WorkflowNodeData }

/** 节点类型 → 图标组件映射（直接在渲染时创建，避免序列化问题） */
const TYPE_ICONS: Record<string, React.ReactNode> = {
  start: <PlayCircleOutlined />,
  end: <StopOutlined />,
  agent: <BranchesOutlined />,
  tool: <NodeCollapseOutlined />,
  gateway: <LinkOutlined />,
  parallel: <NodeIndexOutlined />,
  human: <ExclamationCircleOutlined />,
}

/**
 * 从节点 config 中提取一段简要描述，显示在节点卡片上。
 */
function getNodeSummary(type: string, config: Record<string, unknown>): string {
  switch (type) {
    case 'start': {
      // 优先读 config.output_variables（用户自定义输出变量）
      const outputVars = config.output_variables as Array<{ name?: string }> | undefined
      if (outputVars && outputVars.length > 0) {
        return `输出: ${outputVars.map((v) => v.name).join(', ')}`
      }
      // fallback 到 input_schema
      const schema = config.input_schema as { properties?: Record<string, unknown> } | undefined
      const keys = schema?.properties ? Object.keys(schema.properties) : []
      if (keys.length === 0) return '未定义输出变量'
      return `输出: ${keys.join(', ')}`
    }
    case 'end': {
      const mapping = config.output_mapping as Record<string, unknown> | undefined
      if (!mapping || Object.keys(mapping).length === 0) return '未定义输出映射'
      return `输出: ${Object.keys(mapping).join(', ')}`
    }
    case 'agent': {
      const agentId = config.agent_id as string | undefined
      const query = config.input_query as string | undefined
      if (agentId && query) {
        const shortQuery = query.length > 25 ? `${query.slice(0, 25)}...` : query
        return `Agent: ${agentId.slice(0, 8)}.. | ${shortQuery}`
      }
      if (agentId) return `Agent: ${agentId.slice(0, 8)}.. | 未填写查询`
      if (query) {
        const shortQuery = query.length > 25 ? `${query.slice(0, 25)}...` : query
        return `查询: ${shortQuery}`
      }
      return '请选择 Agent 并填写查询'
    }
    case 'tool': {
      const toolId = config.tool_id as string | undefined
      if (toolId) return `工具: ${toolId}`
      return '未选择工具'
    }
    case 'gateway': {
      const conditions = config.conditions as unknown[] | undefined
      if (conditions && conditions.length > 0) return `${conditions.length} 个条件分支`
      return '未配置条件'
    }
    case 'parallel': {
      const branches = config.branches as unknown[] | undefined
      if (branches && branches.length > 0) return `${branches.length} 个并行分支`
      return '未配置分支'
    }
    case 'human': {
      const title = config.title as string | undefined
      if (title) return title
      return '未设置审批标题'
    }
    default:
      return ''
  }
}

function WorkflowBaseNode({ data, selected }: Props) {
  const { typeColor, workflowNode } = data
  const nodeType = workflowNode.type
  const isStart = nodeType === 'start'
  const isEnd = nodeType === 'end'
  const icon = TYPE_ICONS[nodeType]
  const summary = getNodeSummary(nodeType, workflowNode.config as Record<string, unknown>)

  return (
    <div
      className={`
        relative rounded-md bg-white shadow-sm border transition-shadow cursor-pointer
        ${selected ? 'border-[#1E5EFF] shadow-md' : 'border-gray-200 hover:shadow-md'}
      `}
      style={{ minWidth: 110, maxWidth: 160 }}
    >
      {/* 主体 */}
      <div className="px-2 py-1.5">
        {/* 图标 + 名称 */}
        <div className="flex items-center gap-1">
          <span className="text-xs flex-shrink-0" style={{ color: typeColor }}>{icon}</span>
          <span className="text-[11px] font-medium text-[#0F172A] truncate">{data.label}</span>
        </div>

        {/* 摘要信息 */}
        {summary && (
          <div className="text-[9px] text-[#64748B] mt-0.5 truncate" title={summary}>
            {summary}
          </div>
        )}
      </div>

      {/* Source Handle — End 节点隐藏 */}
      {!isEnd && (
        <Handle
          type="source"
          position={Position.Right}
          className="!w-1.5 !h-1.5 !border-[1.5px] !border-white !transition-colors"
          style={{ backgroundColor: typeColor }}
        />
      )}

      {/* Target Handle — Start 节点隐藏 */}
      {!isStart && (
        <Handle
          type="target"
          position={Position.Left}
          className="!w-1.5 !h-1.5 !border-[1.5px] !border-white !transition-colors"
          style={{ backgroundColor: typeColor }}
        />
      )}
    </div>
  )
}

export default memo(WorkflowBaseNode)

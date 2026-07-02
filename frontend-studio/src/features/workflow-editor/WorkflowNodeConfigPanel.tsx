/**
 * WorkflowNodeConfigPanel — 右侧配置面板。
 *
 * 根据选中节点类型，分发到对应的 Config 子组件。
 * 移除了独立的 EdgeConfigPanel（边配置现在通过节点的 next_nodes 管理）。
 *
 * antd 组件 → 原生 Tailwind ui 封装；@ant-design/icons → lucide-react。
 */
import { Input, Tag, Button, Popconfirm } from '../../components/ui'
import { Trash2 } from 'lucide-react'
import { ListTree } from 'lucide-react'
import type { WorkflowNode } from '../../services/workflows-api'
import { NODE_TYPE_CONFIGS } from './utils/node-type-configs'
import StartNodeConfig from './node-config-panels/StartNodeConfig'
import EndNodeConfig from './node-config-panels/EndNodeConfig'
import AgentNodeConfig from './node-config-panels/AgentNodeConfig'
import ToolNodeConfig from './node-config-panels/ToolNodeConfig'
import GatewayNodeConfig from './node-config-panels/GatewayNodeConfig'
import ParallelNodeConfig from './node-config-panels/ParallelNodeConfig'
import HumanNodeConfig from './node-config-panels/HumanNodeConfig'

/* ─── Props ─── */

interface NodePanelProps {
  node: WorkflowNode
  allNodes: WorkflowNode[]
  onNodeChange: (updated: WorkflowNode) => void
}

/* ─── Node Config Panel ─── */

function NodeConfigPanel({ node, allNodes, onNodeChange }: NodePanelProps) {
  const handleConfigChange = (newConfig: Record<string, unknown>) => {
    onNodeChange({ ...node, config: newConfig })
  }

  const commonProps = {
    config: node.config,
    onChange: handleConfigChange,
    currentNodeId: node.node_id,
    allNodes,
  }

  switch (node.type) {
    case 'start':
      return <StartNodeConfig config={node.config} onChange={handleConfigChange} />
    case 'end':
      return <EndNodeConfig {...commonProps} />
    case 'agent':
      return <AgentNodeConfig {...commonProps} />
    case 'tool':
      return <ToolNodeConfig {...commonProps} />
    case 'gateway':
      return <GatewayNodeConfig {...commonProps} />
    case 'parallel':
      return <ParallelNodeConfig config={node.config} onChange={handleConfigChange} />
    case 'human':
      return <HumanNodeConfig {...commonProps} />
    default:
      return (
        <div>
          <label className="block text-xs text-slate-400 mb-1">Config (JSON)</label>
          <Input.TextArea
            value={JSON.stringify(node.config, null, 2)}
            onChange={(e) => {
              try { handleConfigChange(JSON.parse(e.target.value)) }
              catch { /* allow editing invalid JSON */ }
            }}
            rows={6}
            className="font-mono text-xs"
          />
        </div>
      )
  }
}

/* ─── 主面板 ─── */

interface WorkflowNodeConfigPanelProps {
  selectedNode: WorkflowNode | null
  allNodes: WorkflowNode[]
  onNodeChange: (updated: WorkflowNode) => void
  onNodeDelete?: (nodeId: string) => void
}

export default function WorkflowNodeConfigPanel({
  selectedNode,
  allNodes,
  onNodeChange,
  onNodeDelete,
}: WorkflowNodeConfigPanelProps) {
  if (selectedNode) {
    const nt = NODE_TYPE_CONFIGS[selectedNode.type]
    return (
      <div className="border border-[#27272a] rounded-xl bg-[#18181b] p-4">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full inline-block" style={{ backgroundColor: nt?.color }} />
            <span className="text-sm font-medium text-[#fafafa]">
              {nt?.label ?? selectedNode.type} 配置
            </span>
          </div>
          <Tag className="!m-0 !text-[10px]">{selectedNode.node_id}</Tag>
        </div>
        <Input
          value={selectedNode.label}
          onChange={(e) => onNodeChange({ ...selectedNode, label: e.target.value })}
          placeholder="节点名称"
          className="mb-3"
        />
        <NodeConfigPanel
          node={selectedNode}
          allNodes={allNodes}
          onNodeChange={onNodeChange}
        />
        {nt && (
          <p className="text-[10px] text-[#71717a] mt-3">{nt.description}</p>
        )}
        {onNodeDelete && selectedNode.node_id && (
          <div className="mt-4 pt-3 border-t border-[#27272a]">
            <Popconfirm
              title="确定删除这个节点？"
              description="关联的连接也会被删除。"
              onConfirm={() => onNodeDelete(selectedNode.node_id)}
              okText="删除"
              cancelText="取消"
              okButtonProps={{ danger: true }}
            >
              <Button
                danger
                icon={<Trash2 size={12} />}
                className="w-full"
              >
                删除节点
              </Button>
            </Popconfirm>
          </div>
        )}
      </div>
    )
  }

  // 未选中
  return (
    <div className="border border-[#27272a] rounded-xl bg-[#18181b] p-6 text-center text-xs text-[#71717a]">
      <ListTree size={24} className="mx-auto mb-2" />
      <p>选择一个节点进行配置</p>
    </div>
  )
}

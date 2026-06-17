/**
 * GatewayNodeConfig — 网关节点配置面板。
 *
 * 增强版：
 * - target node_id 改为 Select
 * - expression 接入 VariableSelector
 */
import { Button, Input, Select } from 'antd'
import { PlusOutlined } from '@ant-design/icons'
import VariableSelector from '../VariableSelector'
import { getNodeOptions } from '../utils/dag-utils'
import type { WorkflowNode } from '../../../services/workflows-api'

interface Props {
  config: Record<string, unknown>
  onChange: (c: Record<string, unknown>) => void
  currentNodeId: string
  allNodes: WorkflowNode[]
}

export default function GatewayNodeConfig({ config, onChange, currentNodeId, allNodes }: Props) {
  const conditions = (config.conditions as Array<Record<string, unknown>>) ?? []
  const nodeOptions = getNodeOptions(allNodes.filter((n) => n.node_id !== currentNodeId))

  const addCondition = () => {
    onChange({ ...config, conditions: [...conditions, { expression: '', expected: true, target: '' }] })
  }
  const updateCondition = (idx: number, field: string, value: unknown) => {
    const updated = [...conditions]
    updated[idx] = { ...updated[idx], [field]: value }
    onChange({ ...config, conditions: updated })
  }
  const removeCondition = (idx: number) => {
    onChange({ ...config, conditions: conditions.filter((_, i) => i !== idx) })
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs text-[#64748B]">条件列表</span>
        <Button size="small" icon={<PlusOutlined />} onClick={addCondition}>
          添加条件
        </Button>
      </div>
      {conditions.map((cond, idx) => (
        <div key={idx} className="border border-gray-200 rounded-lg p-3 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-[#94A3B8] font-mono">条件 #{idx + 1}</span>
            <button
              onClick={() => removeCondition(idx)}
              className="text-[#EF4444] text-[10px] hover:underline bg-transparent border-0 cursor-pointer"
            >
              删除
            </button>
          </div>
          <div>
            <label className="block text-[10px] text-[#64748B] mb-0.5">表达式</label>
            <VariableSelector
              value={(cond.expression as string) ?? ''}
              onChange={(val) => updateCondition(idx, 'expression', val)}
              currentNodeId={currentNodeId}
              allNodes={allNodes}
                  placeholder="{{ node_id.field }} == value"
              textarea={false}
              rows={1}
            />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <div>
              <label className="block text-[10px] text-[#64748B] mb-0.5">期望值</label>
              <Input
                size="small"
                value={String(cond.expected ?? 'true')}
                onChange={(e) => updateCondition(idx, 'expected', e.target.value)}
                placeholder="true / 'ok' / 42"
              />
            </div>
            <div>
              <label className="block text-[10px] text-[#64748B] mb-0.5">目标节点</label>
              <Select
                size="small"
                className="w-full"
                value={(cond.target as string) || undefined}
                onChange={(val) => updateCondition(idx, 'target', val)}
                options={nodeOptions}
                placeholder="选择节点..."
                allowClear
              />
            </div>
          </div>
        </div>
      ))}
      {conditions.length === 0 && (
        <div className="text-xs text-[#94A3B8] text-center py-4">暂无条件，点击「添加条件」创建</div>
      )}
      <div>
        <label className="block text-xs text-[#64748B] mb-1">默认分支 (无匹配时)</label>
        <Select
          className="w-full"
          value={(config.default_branch as string) || undefined}
          onChange={(val) => onChange({ ...config, default_branch: val })}
          options={nodeOptions}
          placeholder="选择节点..."
          allowClear
        />
      </div>
    </div>
  )
}

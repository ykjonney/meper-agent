/**
 * GatewayNodeConfig — 网关节点配置面板。
 *
 * 增强版：
 * - target node_id 改为 Select
 * - expression 接入 VariableSelector
 * - operator 改为下拉选择（==, !=, >, <, >=, <=, contains, not_contains），
 *   不再让用户在 expression 里手填符号
 *
 * antd 组件 → 原生 Tailwind ui 封装；@ant-design/icons → lucide-react。
 */
import { Button, Input, Select } from '../../../components/ui'
import { Plus } from 'lucide-react'
import VariableSelector from '../VariableSelector'
import { getNodeOptions } from '../utils/dag-utils'
import type { WorkflowNode } from '../../../services/workflows-api'

interface Props {
  config: Record<string, unknown>
  onChange: (c: Record<string, unknown>) => void
  currentNodeId: string
  allNodes: WorkflowNode[]
}

// 网关比较符枚举。==/!=/contains/not_contains 对字符串大小写不敏感（后端 _gateway_compare 实现）。
// label 不含括号，按用户要求保持简洁。
const OPERATOR_OPTIONS = [
  { value: '==', label: '== 等于' },
  { value: '!=', label: '!= 不等于' },
  { value: '>', label: '> 大于' },
  { value: '<', label: '< 小于' },
  { value: '>=', label: '>= 大于等于' },
  { value: '<=', label: '<= 小于等于' },
  { value: 'contains', label: '包含' },
  { value: 'not_contains', label: '不包含' },
]

export default function GatewayNodeConfig({ config, onChange, currentNodeId, allNodes }: Props) {
  const conditions = (config.conditions as Array<Record<string, unknown>>) ?? []
  const nodeOptions = getNodeOptions(allNodes.filter((n) => n.node_id !== currentNodeId))

  const addCondition = () => {
    onChange({ ...config, conditions: [...conditions, { expression: '', operator: '==', expected: true, target: '' }] })
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
        <span className="text-xs text-slate-400">条件列表</span>
        <Button size="small" icon={<Plus size={12} />} onClick={addCondition}>
          添加条件
        </Button>
      </div>
      {conditions.map((cond, idx) => (
        <div key={idx} className="border border-[#27272a] rounded-lg p-3 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[10px] text-[#71717a] font-mono">条件 #{idx + 1}</span>
            <button
              onClick={() => removeCondition(idx)}
              className="text-[#EF4444] text-[10px] hover:underline bg-transparent border-0 cursor-pointer"
            >
              删除
            </button>
          </div>
          <div>
            <label className="block text-[10px] text-slate-400 mb-0.5">表达式</label>
            <VariableSelector
              value={(cond.expression as string) ?? ''}
              onChange={(val) => updateCondition(idx, 'expression', val)}
              currentNodeId={currentNodeId}
              allNodes={allNodes}
              placeholder="{{ node_id.field }}"
              textarea={false}
              rows={1}
            />
          </div>
          <div className="grid grid-cols-3 gap-2">
            <div>
              <label className="block text-[10px] text-slate-400 mb-0.5">判断符</label>
              <Select
                size="small"
                className="w-full"
                value={(cond.operator as string) || '=='}
                onChange={(val) => updateCondition(idx, 'operator', val ?? '==')}
                options={OPERATOR_OPTIONS}
              />
            </div>
            <div>
              <label className="block text-[10px] text-slate-400 mb-0.5">期望值</label>
              <Input
                size="small"
                value={String(cond.expected ?? 'true')}
                onChange={(e) => updateCondition(idx, 'expected', e.target.value)}
                placeholder="true / 'ok' / 42"
              />
            </div>
            <div>
              <label className="block text-[10px] text-slate-400 mb-0.5">目标节点</label>
              <Select
                size="small"
                className="w-full"
                value={(cond.target as string) || null}
                onChange={(val) => updateCondition(idx, 'target', val ?? '')}
                options={nodeOptions}
                placeholder="选择节点..."
                allowClear
              />
            </div>
          </div>
        </div>
      ))}
      {conditions.length === 0 && (
        <div className="text-xs text-[#71717a] text-center py-4">暂无条件，点击「添加条件」创建</div>
      )}
      <div>
        <label className="block text-xs text-slate-400 mb-1">默认分支 (无匹配时)</label>
        <Select
          className="w-full"
          value={(config.default_branch as string) || null}
          onChange={(val) => onChange({ ...config, default_branch: val ?? '' })}
          options={nodeOptions}
          placeholder="选择节点..."
          allowClear
        />
      </div>
    </div>
  )
}

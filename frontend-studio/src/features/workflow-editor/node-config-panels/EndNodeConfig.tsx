/**
 * EndNodeConfig — 结束节点配置面板。
 *
 * 结束节点通过 output_mapping 定义工作流最终输出。
 * output_mapping 是一个 dict: { "输出字段名": "{{上游变量表达式}}" }
 */
import { Plus, Trash2 } from 'lucide-react'
import { Button, Input } from '../../../components/ui'
import VariableSelector from '../VariableSelector'
import HelpHint from '../HelpHint'
import type { WorkflowNode } from '../../../services/workflows-api'

interface Props {
  config: Record<string, unknown>
  onChange: (c: Record<string, unknown>) => void
  currentNodeId: string
  allNodes: WorkflowNode[]
}

export default function EndNodeConfig({ config, onChange, currentNodeId, allNodes }: Props) {
  const mapping = (config.output_mapping as Record<string, string>) ?? {}

  const entries = Object.entries(mapping)

  const updateEntry = (key: string, value: string) => {
    onChange({ ...config, output_mapping: { ...mapping, [key]: value } })
  }

  const updateKey = (oldKey: string, newKey: string) => {
    const next: Record<string, string> = {}
    for (const [k, v] of Object.entries(mapping)) {
      next[k === oldKey ? newKey : k] = v
    }
    onChange({ ...config, output_mapping: next })
  }

  const removeEntry = (key: string) => {
    const next = { ...mapping }
    delete next[key]
    onChange({ ...config, output_mapping: next })
  }

  const addEntry = () => {
    const newKey = `field_${Object.keys(mapping).length + 1}`
    onChange({ ...config, output_mapping: { ...mapping, [newKey]: '' } })
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between mb-2">
        <p className="text-[10px] text-slate-400 font-medium flex items-center gap-1">
          输出映射
          <HelpHint
            text={
              '每个字段的值可引用上游节点的输出（点输入框旁的「变量」按钮选择）。' +
              '未配置时默认返回执行完成状态。'
            }
          />
        </p>
        <Button size="small" type="dashed" icon={<Plus size={12} />} onClick={addEntry}>
          添加字段
        </Button>
      </div>

      {entries.length === 0 && (
        <p className="text-[10px] text-[#71717a]">
          未配置输出映射，默认返回 {"{ status: \"completed\" }"}
        </p>
      )}

      {entries.map(([key, value]) => (
        <div key={key} className="space-y-1 p-2 bg-[#121214]/60 rounded-lg">
          <div className="flex items-center gap-1.5">
            <Input
              size="small"
              value={key}
              onChange={(e) => updateKey(key, e.target.value)}
              className="!text-xs flex-1"
              placeholder="字段名"
            />
            <Button
              size="small"
              type="text"
              danger
              icon={<Trash2 size={12} />}
              onClick={() => removeEntry(key)}
            />
          </div>
          <VariableSelector
            value={value}
            onChange={(val) => updateEntry(key, val)}
            currentNodeId={currentNodeId}
            allNodes={allNodes}
            placeholder="引用上游变量表达式..."
            rows={2}
          />
        </div>
      ))}
    </div>
  )
}

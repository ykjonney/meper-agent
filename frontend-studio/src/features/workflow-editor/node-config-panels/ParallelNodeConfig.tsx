/**
 * ParallelNodeConfig — 并行节点配置面板。
 */
import { Input, Select } from '../../../components/ui'

interface Props {
  config: Record<string, unknown>
  onChange: (c: Record<string, unknown>) => void
}

export default function ParallelNodeConfig({ config, onChange }: Props) {
  return (
    <div className="space-y-3">
      <div>
        <label className="block text-xs text-slate-400 mb-1">合并策略</label>
        <Select
          className="w-full"
          value={(config.join_strategy as string) ?? 'all'}
          onChange={(val) => onChange({ ...config, join_strategy: val ?? 'all' })}
          options={[
            { value: 'all', label: '等待所有分支完成' },
            { value: 'any', label: '任一分支完成即可' },
            { value: 'race', label: '竞速模式（取最快结果）' },
          ]}
        />
      </div>
      <div>
        <label className="block text-xs text-slate-400 mb-1">变量作用域</label>
        <Select
          className="w-full"
          value={(config.scope as string) ?? 'shared'}
          onChange={(val) => onChange({ ...config, scope: val ?? 'shared' })}
          options={[
            { value: 'shared', label: '共享作用域' },
            { value: 'isolated', label: '隔离作用域' },
          ]}
        />
      </div>
      <div>
        <label className="block text-xs text-slate-400 mb-1">分支配置 (JSON)</label>
        <Input.TextArea
          value={JSON.stringify(config.branches ?? [], null, 2)}
          onChange={(e) => {
            try { onChange({ ...config, branches: JSON.parse(e.target.value) }) }
            catch { /* allow editing invalid JSON */ }
          }}
          rows={4}
          className="font-mono text-xs"
          placeholder='[{"name": "branch_1", "nodes": []}]'
        />
      </div>
    </div>
  )
}

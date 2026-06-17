/**
 * ToolNodeConfig — 工具节点配置面板。
 *
 * 增强版：
 * - Tool ID 改为 Select（从 API 查询可用工具）
 * - Params 接入 VariableSelector
 */
import { useQuery } from '@tanstack/react-query'
import { Select, Input, Spin } from 'antd'
import { toolsApi, toolKeys } from '../../../services/tools-api'
import VariableSelector from '../VariableSelector'
import type { WorkflowNode } from '../../../services/workflows-api'

interface Props {
  config: Record<string, unknown>
  onChange: (c: Record<string, unknown>) => void
  currentNodeId: string
  allNodes: WorkflowNode[]
}

export default function ToolNodeConfig({ config, onChange, currentNodeId, allNodes }: Props) {
  const { data: toolsData, isLoading } = useQuery({
    queryKey: toolKeys.list({ page: 1, page_size: 100 }),
    queryFn: () => toolsApi.list({ page: 1, page_size: 100 }),
  })

  const toolOptions = (toolsData?.items ?? []).map((t) => ({
    value: t.id,
    label: `${t.name} (${t.source})`,
  }))

  return (
    <div className="space-y-3">
      <div>
        <label className="block text-xs text-[#64748B] mb-1">工具</label>
        {isLoading ? (
          <Spin size="small" />
        ) : (
          <Select
            className="w-full"
            value={config.tool_id as string || undefined}
            onChange={(val) => onChange({ ...config, tool_id: val })}
            options={toolOptions}
            placeholder="选择工具..."
            showSearch
            filterOption={(input, option) =>
              (option?.label as string ?? '').toLowerCase().includes(input.toLowerCase())
            }
            allowClear
          />
        )}
      </div>
      <div>
        <VariableSelector
          label="Params (JSON，支持模板变量)"
          value={JSON.stringify(config.params ?? {}, null, 2)}
          onChange={(val) => {
            try { onChange({ ...config, params: JSON.parse(val) }) }
            catch { onChange({ ...config, params: val }) }
          }}
          currentNodeId={currentNodeId}
          allNodes={allNodes}
          placeholder='{"key": "{{ node.field }}"}'
          rows={4}
        />
      </div>
      <div>
        <label className="block text-xs text-[#64748B] mb-1">超时 (ms)</label>
        <Input
          type="number"
          value={(config.timeout_ms as number) ?? 30000}
          onChange={(e) => onChange({ ...config, timeout_ms: parseInt(e.target.value) || 30000 })}
          min={1000}
          step={1000}
        />
      </div>
    </div>
  )
}

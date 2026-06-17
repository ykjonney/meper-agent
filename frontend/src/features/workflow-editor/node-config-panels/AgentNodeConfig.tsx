/**
 * AgentNodeConfig — Agent 节点配置面板。
 *
 * - Agent ID 通过 Select 选择
 * - 查询（input_query）：必填，作为 user message，支持变量池
 * - 上下文（input_prompt）：可选，注入 Agent 的 context 卡槽，支持变量池
 * - 输出变量：VariableListEditor，默认 response(text)
 *
 * Agent 节点不覆盖其他卡槽（role/task/constraints/output_format），
 * 这些由 Agent 自身的配置决定。
 * 工作流中的行为约束（如"禁止反问"）应在 Agent 自身的 constraints 卡槽中配置。
 */
import { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Select, Input, Spin } from 'antd'
import { agentApi, agentKeys } from '../../../services/agent-api'
import VariableSelector from '../VariableSelector'
import VariableListEditor from '../VariableListEditor'
import type { WorkflowNode } from '../../../services/workflows-api'
import type { VariableDefinition, VariableTypeName } from '../utils/variable-types'

interface Props {
  config: Record<string, unknown>
  onChange: (c: Record<string, unknown>) => void
  currentNodeId: string
  allNodes: WorkflowNode[]
}

export default function AgentNodeConfig({ config, onChange, currentNodeId, allNodes }: Props) {
  const { data: agentsData, isLoading } = useQuery({
    queryKey: agentKeys.list({ page: 1, page_size: 100 }),
    queryFn: () => agentApi.list({ page: 1, page_size: 100 }),
  })

  const agents = agentsData?.items ?? []
  const agentOptions = agents.map((a) => ({
    value: a.id,
    label: `${a.name} (${a.id.substring(0, 8)}...)`,
  }))

  // 输出变量：初始化时提供默认值
  const outputVariables = (config.output_variables as VariableDefinition[]) ?? []
  const [initialized, setInitialized] = useState(false)

  useEffect(() => {
    if (!initialized && (!config.output_variables || !Array.isArray(config.output_variables) || (config.output_variables as VariableDefinition[]).length === 0)) {
      const defaults: VariableDefinition[] = [
        {
          name: 'response',
          label: 'Agent 响应',
          type: 'text' as VariableTypeName,
          constraints: {},
          description: 'Agent 的输出文本',
        },
      ]
      onChange({ ...config, output_variables: defaults })
      setInitialized(true)
    } else if (!initialized) {
      setInitialized(true)
    }
  }, [initialized, config, onChange])

  const handleOutputVariablesChange = (variables: VariableDefinition[]) => {
    onChange({ ...config, output_variables: variables })
  }

  // 查询内容变更（作为 user message）
  const handleInputQueryChange = (val: string) => {
    onChange({ ...config, input_query: val })
  }

  // 上下文变更（注入 Agent 的 context 卡槽）
  const handleContextChange = (val: string) => {
    onChange({ ...config, input_prompt: val })
  }

  return (
    <div className="space-y-3">
      {/* Agent 选择 */}
      <div>
        <label className="block text-xs text-[#64748B] mb-1">Agent</label>
        {isLoading ? (
          <Spin size="small" />
        ) : (
          <Select
            className="w-full"
            value={config.agent_id as string || undefined}
            onChange={(val) => onChange({ ...config, agent_id: val })}
            options={agentOptions}
            placeholder="选择 Agent..."
            showSearch
            filterOption={(input, option) =>
              (option?.label as string ?? '').toLowerCase().includes(input.toLowerCase())
            }
            allowClear
          />
        )}
      </div>

      {/* 查询（必填）→ user message */}
      <div>
        <VariableSelector
          label="查询"
          value={config.input_query as string ?? ''}
          onChange={handleInputQueryChange}
          currentNodeId={currentNodeId}
          allNodes={allNodes}
          placeholder="作为用户消息发送给 Agent，支持 {{变量}} ..."
          rows={2}
          required
        />
      </div>

      {/* 上下文（可选）→ 注入 context 卡槽 */}
      <div>
        <VariableSelector
          label="上下文"
          value={config.input_prompt as string ?? ''}
          onChange={handleContextChange}
          currentNodeId={currentNodeId}
          allNodes={allNodes}
          placeholder="注入到 Agent 的 context 卡槽，支持 {{变量}} ..."
          rows={3}
        />
        <div className="text-[10px] text-[#94A3B8] mt-0.5">
          此内容会覆盖 Agent 的 context 卡槽值，用于注入工作流上下文。角色、任务、约束等由 Agent 自身配置决定。
        </div>
      </div>

      {/* 输出变量区域 */}
      <VariableListEditor
        value={outputVariables}
        onChange={handleOutputVariablesChange}
        nodeType="agent"
      />

      {/* Temperature + 最大重试 */}
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs text-[#64748B] mb-1">Temperature</label>
          <Input
            type="number"
            value={(config.temperature as number) ?? 0.7}
            onChange={(e) => onChange({ ...config, temperature: parseFloat(e.target.value) || 0.7 })}
            step={0.1}
            min={0}
            max={2}
          />
        </div>
        <div>
          <label className="block text-xs text-[#64748B] mb-1">最大重试</label>
          <Input
            type="number"
            value={(config.max_retry as number) ?? 3}
            onChange={(e) => onChange({ ...config, max_retry: parseInt(e.target.value) || 3 })}
            min={0}
            max={10}
          />
        </div>
      </div>
    </div>
  )
}

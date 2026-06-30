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
import { useEffect, useMemo } from 'react'
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
  const agentsById = new Map(agents.map((a) => [a.id, a] as const))
  const agentOptions = agents.map((a) => ({
    value: a.id,
    label: a.name,
  }))

  // 输出变量：智能合并系统默认变量
  //
  // 策略：每次节点 ID 变化时，扫描 output_variables：
  //   1. 缺失的系统默认变量（如 files）→ 自动补齐
  //   2. 已存在的系统默认变量 → 升级 readonly = true（覆盖可能存在的旧值）
  //   3. 用户自定义变量（不在系统白名单内）→ 原样保留
  //
  // 这样存量数据（v2 之前生成的）打开面板时也能"自我升级"，
  // 不会破坏用户已有的自定义变量。
  const outputVariables = (config.output_variables as VariableDefinition[]) ?? []

  // 系统默认变量注册表（用 useMemo 稳定引用，避免 useEffect 重复触发）
  const SYSTEM_DEFAULT_VARIABLES = useMemo<VariableDefinition[]>(() => [
    {
      name: 'response',
      label: 'Agent 响应',
      type: 'text' as VariableTypeName,
      constraints: {},
      description: 'Agent 的输出文本',
      readonly: true,
    },
    {
      name: 'files',
      label: '生成文件',
      type: 'file' as VariableTypeName,
      constraints: { multiple: true, allowed_extensions: [], max_size_mb: null },
      description: 'Agent 工具生成的文件列表（如 Excel/PDF/CSV）',
      readonly: true,
    },
  ], [])

  useEffect(() => {
    const existing = (config.output_variables as VariableDefinition[] | undefined) ?? []

    // 计算需要补齐的系统默认变量（在 SYSTEM_DEFAULT_VARIABLES 但不在 existing）
    const missing = SYSTEM_DEFAULT_VARIABLES.filter(
      (sv) => !existing.some((ev) => ev.name === sv.name),
    )

    // 计算需要升级 readonly 的系统默认变量（已存在但 readonly !== true）
    const upgraded = existing.map((ev) => {
      const sysVar = SYSTEM_DEFAULT_VARIABLES.find((sv) => sv.name === ev.name)
      if (sysVar && ev.readonly !== true) {
        return { ...ev, readonly: true }
      }
      return ev
    })

    // 没有变化则不触发 onChange（避免无限循环）
    if (missing.length === 0 && JSON.stringify(upgraded) === JSON.stringify(existing)) {
      return
    }

    // 合并：先放已有的（升级后），再补缺失的
    const merged: VariableDefinition[] = [...upgraded, ...missing]

    // 使用 queueMicrotask 延迟执行，避免在渲染过程中触发状态更新
    queueMicrotask(() => {
      onChange({ ...config, output_variables: merged })
    })
  }, [currentNodeId]) // 只在节点 ID 变化时执行，移除 config 和 onChange 依赖

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
            onChange={(val) => {
              const agent = agentsById.get(val)
              onChange({
                ...config,
                agent_id: val,
                agent_name: agent?.name ?? '',
              })
            }}
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

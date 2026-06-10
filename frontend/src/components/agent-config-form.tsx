/**
 * AgentConfigForm — pure form for Agent configuration (no Drawer shell).
 *
 * Extracted from agent-config-drawer.tsx so it can be embedded in
 * both the Drawer (for quick create) and the detail page tab.
 *
 * Exposes a `submit()` method via `ref` and reports `dirty` state
 * so the parent can render its own save button.
 */
import { useState, useEffect, useImperativeHandle, forwardRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Input, InputNumber, Select, Slider, Button, Collapse, Tag, message, Modal,
} from 'antd'
import {
  CloudUploadOutlined,
  StopOutlined,
} from '@ant-design/icons'
import {
  agentApi,
  agentKeys,
  type Agent,
} from '../services/agent-api'
import {
  modelApi,
  modelKeys,
  type Model,
} from '../services/model-api'
import { AGENT_STATUS_STYLES } from '../constants/agent-status'
import ToolSelector, {
  DEFAULT_TOOL_VALUE,
  type ToolSelectorValue,
} from './tool-selector'
import SystemPromptManager from './system-prompt-manager'
import type { SavedPrompt } from '../services/agent-api'

/* ─── Status styles ─── */
const STATUS_STYLES = AGENT_STATUS_STYLES

/* ─── Public handle ─── */
export interface AgentConfigFormHandle {
  /** Trigger the underlying save mutation. */
  submit: () => void
  /** Whether there is an ongoing save. */
  isSaving: () => boolean
}

/* ─── Props ─── */
export interface AgentConfigFormProps {
  agent: Agent | null
  mode: 'create' | 'edit'
  /** Called after a successful save/create. */
  onSaved?: () => void
}

const AgentConfigForm = forwardRef<AgentConfigFormHandle, AgentConfigFormProps>(
  function AgentConfigForm({ agent, mode, onSaved }, ref) {
    const queryClient = useQueryClient()
    const isEdit = mode === 'edit' && agent !== null

    /* ─── Form state ─── */
    const [formName, setFormName] = useState('')
    const [formDesc, setFormDesc] = useState('')
    const [formPrompt, setFormPrompt] = useState('')
    const [formModelId, setFormModelId] = useState('')
    const [formTemperature, setFormTemperature] = useState(0.7)
    const [formMaxRetry, setFormMaxRetry] = useState(3)
    const [formPrompts, setFormPrompts] = useState<SavedPrompt[]>([])
    const [toolConfig, setToolConfig] = useState<ToolSelectorValue>(DEFAULT_TOOL_VALUE)

    /* ─── Populate form when agent changes ─── */
    useEffect(() => {
      if (agent && isEdit) {
        setFormName(agent.name)
        setFormDesc(agent.description)
        setFormPrompt(agent.system_prompt)
        setFormPrompts(agent.saved_system_prompts ?? [])
        setFormModelId(agent.llm_config?.default_model || '')
        setFormTemperature(agent.llm_config?.temperature ?? 0.7)
        setFormMaxRetry(agent.llm_config?.max_retry ?? 3)
        setToolConfig({
          builtin_config: agent.builtin_config ?? [],
          skill_ids: (agent.skill_ids && agent.skill_ids.length > 0)
            ? agent.skill_ids
            : (agent.tool_ids ?? []),
          mcp_connection_ids: agent.mcp_connection_ids ?? [],
        })
      } else {
        setFormName('')
        setFormDesc('')
        setFormPrompt('')
        setFormPrompts([])
        setFormModelId('')
        setFormTemperature(0.7)
        setFormMaxRetry(3)
        setToolConfig(DEFAULT_TOOL_VALUE)
      }
    }, [agent, isEdit])

    /* ─── Query: available models ─── */
    const { data: modelsData } = useQuery({
      queryKey: modelKeys.list({ page: 1, page_size: 100, status: 'active' }),
      queryFn: () => modelApi.list({ page: 1, page_size: 100, status: 'active' }),
    })
    const availableModels: Model[] = modelsData?.items ?? []

    /* ─── Mutation: save agent ─── */
    const saveMutation = useMutation({
      mutationFn: async () => {
        const llmConfig = {
          default_model: formModelId,
          temperature: formTemperature,
          max_retry: formMaxRetry,
        }

        if (isEdit && agent) {
          return agentApi.update(agent.id, {
            name: formName.trim(),
            description: formDesc.trim(),
            system_prompt: formPrompt.trim(),
            saved_system_prompts: formPrompts,
            skill_ids: toolConfig.skill_ids,
            mcp_connection_ids: toolConfig.mcp_connection_ids,
            builtin_config: toolConfig.builtin_config,
            workflow_ids: agent.workflow_ids,
            knowledge_base_ids: agent.knowledge_base_ids,
            llm_config: llmConfig,
          })
        } else {
          return agentApi.create({
            name: formName.trim(),
            description: formDesc.trim(),
            system_prompt: formPrompt.trim(),
            saved_system_prompts: formPrompts,
            skill_ids: toolConfig.skill_ids,
            mcp_connection_ids: toolConfig.mcp_connection_ids,
            builtin_config: toolConfig.builtin_config,
            llm_config: llmConfig,
          })
        }
      },
      onSuccess: () => {
        message.success(isEdit ? 'Agent 更新成功' : 'Agent 创建成功')
        queryClient.invalidateQueries({ queryKey: agentKeys.lists() })
        if (agent) {
          queryClient.invalidateQueries({ queryKey: agentKeys.detail(agent.id) })
        }
        onSaved?.()
      },
      onError: (err: unknown) => {
        const msg = err && typeof err === 'object' && 'message' in err
          ? (err as { message: string }).message
          : isEdit ? '更新失败' : '创建失败'
        message.error(msg)
      },
    })

    /* ─── Mutation: publish / archive ─── */
    const publishMutation = useMutation({
      mutationFn: agentApi.publish,
      onSuccess: () => {
        message.success('Agent 已发布')
        queryClient.invalidateQueries({ queryKey: agentKeys.lists() })
        if (agent) {
          queryClient.invalidateQueries({ queryKey: agentKeys.detail(agent.id) })
        }
      },
      onError: (err: unknown) => {
        const msg = err && typeof err === 'object' && 'message' in err
          ? (err as { message: string }).message : '发布失败'
        message.error(msg)
      },
    })

    const archiveMutation = useMutation({
      mutationFn: agentApi.archive,
      onSuccess: () => {
        message.success('Agent 已下架')
        queryClient.invalidateQueries({ queryKey: agentKeys.lists() })
        if (agent) {
          queryClient.invalidateQueries({ queryKey: agentKeys.detail(agent.id) })
        }
      },
      onError: (err: unknown) => {
        const msg = err && typeof err === 'object' && 'message' in err
          ? (err as { message: string }).message : '下架失败'
        message.error(msg)
      },
    })

    /* ─── Imperative handle ─── */
    useImperativeHandle(ref, () => ({
      submit: () => {
        if (!formName.trim()) {
          message.warning('请输入 Agent 名称')
          return
        }
        saveMutation.mutate()
      },
      isSaving: () => saveMutation.isPending,
    }), [formName, saveMutation])

    /* ─── Current status info ─── */
    const currentStatus = agent?.status ?? 'draft'
    const statusStyle = STATUS_STYLES[currentStatus] ?? STATUS_STYLES.draft
    const canPublish = currentStatus === 'draft' || currentStatus === 'archived'
    const canArchive = currentStatus === 'published'

    /* ─── Collapse items ─── */
    const collapseItems = [
      {
        key: 'basic',
        label: '基本信息',
        children: (
          <div className="flex flex-col gap-4">
            <div>
              <label className="block text-sm text-[#0F172A] mb-1.5">
                名称 <span className="text-[#EF4444]">*</span>
              </label>
              <Input
                placeholder="请输入 Agent 名称（1-100 字符）"
                value={formName}
                onChange={(e) => setFormName(e.target.value)}
                maxLength={100}
                showCount
              />
            </div>
            <div>
              <label className="block text-sm text-[#0F172A] mb-1.5">描述</label>
              <Input.TextArea
                placeholder="简要描述 Agent 的用途"
                value={formDesc}
                onChange={(e) => setFormDesc(e.target.value)}
                maxLength={500}
                showCount
                rows={2}
              />
            </div>
          </div>
        ),
      },
      {
        key: 'prompt',
        label: '系统提示词',
        extra: formPrompts.length > 0
          ? <span className="text-[11px] text-[#94A3B8]">{formPrompts.length} 个模板</span>
          : undefined,
        children: (
          <div>
            <SystemPromptManager
              value={formPrompt}
              prompts={formPrompts}
              onChange={(prompt, prompts) => {
                setFormPrompt(prompt)
                setFormPrompts(prompts)
              }}
            />
            <div className="text-[11px] text-[#94A3B8] mt-1">
              提示词决定了 Agent 的行为方式和能力边界
            </div>
          </div>
        ),
      },
      {
        key: 'model',
        label: '模型配置',
        children: (
          <div className="flex flex-col gap-4">
            <div>
              <label className="block text-sm text-[#0F172A] mb-1.5">默认模型</label>
              <Select
                placeholder="选择默认模型"
                value={formModelId || undefined}
                onChange={(val) => setFormModelId(val || '')}
                allowClear
                showSearch
                optionFilterProp="label"
                className="w-full"
                options={availableModels.map(m => ({
                  value: m.id,
                  label: `${m.name} (${m.model_id})`,
                }))}
              />
            </div>

            <div>
              <label className="block text-sm text-[#0F172A] mb-1.5">
                Temperature <span className="text-[11px] text-[#94A3B8] font-normal">({formTemperature})</span>
              </label>
              <Slider
                min={0}
                max={2}
                step={0.1}
                value={formTemperature}
                onChange={setFormTemperature}
                tooltip={{ formatter: (v) => v?.toFixed(1) }}
              />
              <div className="flex justify-between text-[11px] text-[#94A3B8] -mt-2">
                <span>精确 (0)</span>
                <span>创意 (2)</span>
              </div>
            </div>

            <div>
              <label className="block text-sm text-[#0F172A] mb-1.5">
                最大重试次数 <span className="text-[11px] text-[#94A3B8] font-normal">({formMaxRetry})</span>
              </label>
              <InputNumber
                min={0}
                max={10}
                value={formMaxRetry}
                onChange={(v) => setFormMaxRetry(v ?? 3)}
                className="w-full"
              />
              <div className="text-[11px] text-[#94A3B8] mt-1">
                当 LLM 调用失败时自动重试的次数，建议 1-5
              </div>
            </div>
          </div>
        ),
      },
      {
        key: 'tools',
        label: '工具配置',
        children: (
          <ToolSelector
            value={toolConfig}
            onChange={setToolConfig}
          />
        ),
      },
      ...(isEdit
        ? [{
            key: 'lifecycle',
            label: '生命周期',
            children: (
              <div className="flex flex-col gap-4">
                <div className="flex items-center justify-between">
                  <span className="text-sm text-[#0F172A]">当前状态</span>
                  <Tag style={{ color: statusStyle.color, background: statusStyle.bg, borderColor: 'transparent' }}>
                    {statusStyle.label}
                  </Tag>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-[#0F172A]">版本号</span>
                  <span className="text-sm font-mono text-[#64748B]">v{agent?.version ?? 1}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-[#0F172A]">创建时间</span>
                  <span className="text-xs text-[#94A3B8]">{agent?.created_at ? new Date(agent.created_at).toLocaleString('zh-CN') : '-'}</span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-sm text-[#0F172A]">更新时间</span>
                  <span className="text-xs text-[#94A3B8]">{agent?.updated_at ? new Date(agent.updated_at).toLocaleString('zh-CN') : '-'}</span>
                </div>
                <div className="pt-2 border-t border-gray-100 flex gap-2">
                  {canPublish && (
                    <Button
                      type="primary"
                      icon={<CloudUploadOutlined />}
                      onClick={() => {
                        if (!agent) return
                        Modal.confirm({
                          title: '确认发布',
                          content: `确定要发布 Agent「${agent.name}」吗？发布后将出现在对话测试面板中。`,
                          okText: '发布',
                          cancelText: '取消',
                          onOk: () => publishMutation.mutate(agent.id),
                        })
                      }}
                      loading={publishMutation.isPending}
                      style={{ background: '#10B981', borderColor: '#10B981' }}
                    >
                      发布
                    </Button>
                  )}
                  {canArchive && (
                    <Button
                      danger
                      icon={<StopOutlined />}
                      onClick={() => {
                        if (!agent) return
                        Modal.confirm({
                          title: '确认下架',
                          content: `确定要下架 Agent「${agent.name}」吗？下架后新对话将无法使用此 Agent。`,
                          okText: '下架',
                          cancelText: '取消',
                          onOk: () => archiveMutation.mutate(agent.id),
                        })
                      }}
                      loading={archiveMutation.isPending}
                    >
                      下架
                    </Button>
                  )}
                  {!canPublish && !canArchive && (
                    <div className="text-[11px] text-[#94A3B8]">
                      当前状态不支持发布/下架操作
                    </div>
                  )}
                </div>
              </div>
            ),
          }]
        : []),
    ]

    return (
      <Collapse
        defaultActiveKey={['basic', 'prompt', 'model', 'tools', ...(isEdit ? ['lifecycle'] : [])]}
        items={collapseItems}
        className="!bg-transparent"
        expandIconPosition="end"
      />
    )
  },
)

export default AgentConfigForm

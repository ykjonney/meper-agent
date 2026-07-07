/**
 * TriggerConfigModal — 定时触发配置 Modal。
 *
 * 包含：启用开关、触发类型选择、频率配置（TriggerSchedulePicker）、
 * 输入参数表单（从 start node 变量自动生成）、状态显示。
 */
import { useState, useEffect, useCallback, useMemo } from 'react'
import { Modal, Switch, Radio, Button, message, Divider, Tooltip } from 'antd'
import { DeleteOutlined } from '@ant-design/icons'
import type { WorkflowNode } from '@/services/workflows-api'
import type { TriggerConfig, TriggerType } from '@/types/workflow-trigger'
import type { VariableDefinition } from '@/features/workflow-editor/utils/variable-types'
import { WorkflowTriggerAPI } from '@/services/workflow-trigger-api'
import TriggerSchedulePicker from './TriggerSchedulePicker'
import VariableFormField from '@/features/workflow-editor/VariableFormField'

interface Props {
  workflowId: string
  workflowName: string
  nodes: WorkflowNode[]
  open: boolean
  onClose: () => void
}

export default function TriggerConfigModal({ workflowId, workflowName, nodes, open, onClose }: Props) {
  // 从 start 节点提取变量定义
  const startNode = nodes.find((n) => n.type === 'start')
  const variables = useMemo<VariableDefinition[]>(
    () => (startNode?.config?.output_variables as VariableDefinition[]) ?? [],
    [startNode],
  )

  /* ─── 表单状态 ─── */
  const [enabled, setEnabled] = useState(false)
  const [triggerType, setTriggerType] = useState<TriggerType>('cron')
  const [cronExpression, setCronExpression] = useState('0 9 * * *')
  const [executeAt, setExecuteAt] = useState('')
  const [defaultInput, setDefaultInput] = useState<Record<string, unknown>>({})
  const [loading, setLoading] = useState(false)
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)

  // 已保存的配置（用于显示状态）
  const [savedConfig, setSavedConfig] = useState<TriggerConfig | null>(null)

  /* ─── 加载现有配置 ─── */
  const loadConfig = useCallback(async () => {
    setLoading(true)
    try {
      const config = await WorkflowTriggerAPI.getTrigger(workflowId)
      setSavedConfig(config)
      setEnabled(config.enabled)
      setTriggerType(config.type)
      setCronExpression(config.cron_expression ?? '0 9 * * *')
      setExecuteAt(config.execute_at ?? '')
      setDefaultInput(config.default_input ?? {})
    } catch (err: unknown) {
      // 404 视为未配置
      const status = err && typeof err === 'object' && 'response' in err
        ? (err as { response?: { status?: number } }).response?.status
        : undefined
      if (status === 404) {
        setSavedConfig(null)
        setEnabled(false)
        setTriggerType('cron')
        setCronExpression('0 9 * * *')
        setExecuteAt('')
        setDefaultInput({})
      }
    } finally {
      setLoading(false)
      setDirty(false)
    }
  }, [workflowId])

  useEffect(() => {
    if (open) {
      void loadConfig()
    }
  }, [open, loadConfig])

  /* ─── 初始化 default_input 的默认值 ─── */
  useEffect(() => {
    if (open && variables.length > 0 && !dirty && !savedConfig) {
      const defaults: Record<string, unknown> = {}
      for (const v of variables) {
        if (v.constraints?.default_value !== undefined && v.constraints?.default_value !== null) {
          defaults[v.name] = v.constraints.default_value
        }
      }
      if (Object.keys(defaults).length > 0) {
        setDefaultInput(defaults)
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, variables])

  /* ─── 保存 ─── */
  const handleSave = async () => {
    // 启用时验证必填参数
    if (enabled && variables.length > 0) {
      const missing: string[] = []
      for (const v of variables) {
        if (v.constraints?.required) {
          const val = defaultInput[v.name]
          const isEmpty = val === undefined || val === null || val === '' || (Array.isArray(val) && val.length === 0)
          if (isEmpty) {
            missing.push(v.label || v.name)
          }
        }
      }
      if (missing.length > 0) {
        message.warning(`启用前请填写必填项: ${missing.join('、')}`)
        return
      }
    }

    // 一次性触发必须设置执行时间
    if (triggerType === 'once' && !executeAt) {
      message.warning('请选择执行时间')
      return
    }

    // Cron 表达式非空验证
    if (triggerType === 'cron' && !cronExpression.trim()) {
      message.warning('请填写 Cron 表达式')
      return
    }

    setSaving(true)
    try {
      const payload: Partial<TriggerConfig> = {
        type: triggerType,
        enabled,
        default_input: defaultInput as Record<string, any>,
      }
      if (triggerType === 'cron') {
        payload.cron_expression = cronExpression
      } else {
        payload.execute_at = executeAt
      }

      const config = await WorkflowTriggerAPI.updateTrigger(workflowId, payload)
      setSavedConfig(config)
      setDirty(false)
      message.success('定时触发配置已保存')
    } catch (err: unknown) {
      const msg = err && typeof err === 'object' && 'message' in err
        ? (err as { message: string }).message : '保存失败'
      message.error(msg)
    } finally {
      setSaving(false)
    }
  }

  /* ─── 删除 ─── */
  const handleDelete = async () => {
    try {
      await WorkflowTriggerAPI.deleteTrigger(workflowId)
      setSavedConfig(null)
      setEnabled(false)
      setTriggerType('cron')
      setCronExpression('0 9 * * *')
      setExecuteAt('')
      setDefaultInput({})
      setDirty(false)
      message.success('定时触发配置已删除')
      onClose()
    } catch (err: unknown) {
      const msg = err && typeof err === 'object' && 'message' in err
        ? (err as { message: string }).message : '删除失败'
      message.error(msg)
    }
  }

  /* ─── 表单变更标记 dirty ─── */
  const markDirty = useCallback(() => setDirty(true), [])

  const setValue = useCallback((name: string, val: unknown) => {
    setDefaultInput((prev) => ({ ...prev, [name]: val }))
    setDirty(true)
  }, [])

  return (
    <Modal
      title={`定时触发: ${workflowName}`}
      open={open}
      onCancel={onClose}
      width={560}
      footer={
        <div className="flex items-center justify-between">
          <div>
            {savedConfig && (
              <Button
                danger
                icon={<DeleteOutlined />}
                onClick={handleDelete}
                size="small"
              >
                删除
              </Button>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button onClick={onClose}>关闭</Button>
            <Button
              type="primary"
              onClick={handleSave}
              loading={saving}
              disabled={!dirty && !!savedConfig}
            >
              保存
            </Button>
          </div>
        </div>
      }
    >
      <div className="space-y-4 py-2">
        {/* 启用开关 */}
        <div className="flex items-center gap-3">
          <span className="text-sm text-[#0F172A]">启用</span>
          <Switch
            checked={enabled}
            onChange={(checked) => { setEnabled(checked); markDirty() }}
            size="small"
          />
          {enabled && (
            <span className="text-xs text-green-500">● 已启用</span>
          )}
        </div>

        {/* 触发类型 */}
        <div className="flex items-center gap-3">
          <span className="text-sm text-[#0F172A]">触发类型:</span>
          <Radio.Group
            value={triggerType}
            onChange={(e) => { setTriggerType(e.target.value); markDirty() }}
          >
            <Radio value="cron">重复执行</Radio>
            <Radio value="once">一次性</Radio>
          </Radio.Group>
        </div>

        <Divider className="!my-2" />

        {/* 频率配置 */}
        {triggerType === 'cron' && (
          <div>
            <div className="text-sm text-[#0F172A] font-medium mb-2">执行频率</div>
            <TriggerSchedulePicker
              value={cronExpression}
              onChange={(cron) => { setCronExpression(cron); markDirty() }}
              disabled={loading}
            />
          </div>
        )}

        {triggerType === 'once' && (
          <div>
            <div className="text-sm text-[#0F172A] font-medium mb-2">执行时间</div>
            <input
              type="datetime-local"
              value={executeAt}
              onChange={(e) => { setExecuteAt(e.target.value); markDirty() }}
              className="w-full border border-gray-200 rounded-lg px-3 py-1.5 text-sm"
            />
          </div>
        )}

        <Divider className="!my-2" />

        {/* 输入参数 */}
        <div>
          <div className="text-sm text-[#0F172A] font-medium mb-2">输入参数</div>
          {variables.length > 0 ? (
            <div className="space-y-3">
              {variables.map((v) => (
                <VariableFormField
                  key={v.name}
                  variable={v}
                  value={defaultInput[v.name]}
                  onChange={(val) => setValue(v.name, val)}
                  disabled={loading}
                />
              ))}
              <p className="text-[10px] text-[#94A3B8]">
                提示: 支持模板语法 <code>{'{{ now() }}'}</code> <code>{'{{ today() }}'}</code>
              </p>
            </div>
          ) : (
            <div className="text-xs text-[#94A3B8]">
              开始节点未定义变量，触发时将使用空输入。
            </div>
          )}
        </div>

        {/* 状态信息 */}
        {savedConfig && (savedConfig.last_triggered_at || savedConfig.next_trigger_at) && (
          <>
            <Divider className="!my-2" />
            <div>
              <div className="text-sm text-[#0F172A] font-medium mb-1">状态</div>
              <div className="text-xs text-[#64748B] space-y-0.5">
                {savedConfig.last_triggered_at && (
                  <div>上次触发: {new Date(savedConfig.last_triggered_at).toLocaleString('zh-CN')}</div>
                )}
                {savedConfig.next_trigger_at && (
                  <div>下次触发: {new Date(savedConfig.next_trigger_at).toLocaleString('zh-CN')}</div>
                )}
              </div>
            </div>
          </>
        )}
      </div>
    </Modal>
  )
}

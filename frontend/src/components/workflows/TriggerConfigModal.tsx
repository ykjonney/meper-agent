/**
 * TriggerConfigModal — 定时触发配置 Modal。
 *
 * 包含：启用开关、触发类型选择、频率配置（TriggerSchedulePicker）、
 * 输入参数表单（从 start node 变量自动生成）、状态显示。
 */
import { useState, useEffect, useCallback, useMemo } from 'react'
import { Modal, Switch, Radio, Button, message, Divider, Tooltip, DatePicker } from 'antd'
import { InfoCircleOutlined } from '@ant-design/icons'
import { useQueryClient } from '@tanstack/react-query'
import type { WorkflowNode } from '@/services/workflows-api'
import type { TriggerConfig, TriggerType } from '@/types/workflow-trigger'
import type { VariableDefinition } from '@/features/workflow-editor/utils/variable-types'
import { WorkflowTriggerAPI } from '@/services/workflow-trigger-api'
import { taskKeys } from '@/services/tasks-api'
import TriggerSchedulePicker from './TriggerSchedulePicker'
import VariableFormField from '@/features/workflow-editor/VariableFormField'
import dayjs from 'dayjs'

interface Props {
  workflowId: string
  workflowName: string
  nodes: WorkflowNode[]
  open: boolean
  onClose: () => void
}

export default function TriggerConfigModal({ workflowId, workflowName, nodes, open, onClose }: Props) {
  const queryClient = useQueryClient()

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
  const [saving, setSaving] = useState(false)
  const [dirty, setDirty] = useState(false)

  /* ─── 初始化表单（每次打开都是全新的创建） ─── */
  /* eslint-disable react-hooks/set-state-in-effect -- form reset on modal open */
  useEffect(() => {
    if (open) {
      setEnabled(false)
      setTriggerType('cron')
      setCronExpression('0 9 * * *')
      setExecuteAt('')
      setDefaultInput({})
      setDirty(false)
    }
  }, [open])
  /* eslint-enable react-hooks/set-state-in-effect */

  /* ─── 初始化 default_input 的默认值 ─── */
  /* eslint-disable react-hooks/set-state-in-effect -- initialize defaults when variables loaded */
  useEffect(() => {
    if (open && variables.length > 0) {
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
  }, [open, variables])
  /* eslint-enable react-hooks/set-state-in-effect */

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

    // 一次性触发不能选择过去的时间
    if (triggerType === 'once' && executeAt && dayjs(executeAt).isBefore(dayjs())) {
      message.warning('执行时间不能早于当前时间')
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
        default_input: defaultInput as Record<string, unknown>,
      }
      if (triggerType === 'cron') {
        payload.cron_expression = cronExpression
      } else {
        payload.execute_at = executeAt
      }

      await WorkflowTriggerAPI.createTrigger(workflowId, payload)
      setDirty(false)
      // Invalidate tasks list so the new pending placeholder task appears
      queryClient.invalidateQueries({ queryKey: taskKeys.lists() })
      message.success('定时任务已创建')
    } catch (err: unknown) {
      const msg = err && typeof err === 'object' && 'message' in err
        ? (err as { message: string }).message : '保存失败'
      message.error(msg)
    } finally {
      setSaving(false)
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
            <Tooltip title="要停止定时任务，请在任务管理中取消待执行的任务">
              <InfoCircleOutlined className="text-xs text-[#94A3B8]" />
              <span className="text-xs text-[#94A3B8] ml-1">取消待执行任务可停止定时</span>
            </Tooltip>
          </div>
          <div className="flex items-center gap-2">
            <Button onClick={onClose}>关闭</Button>
            <Button
              type="primary"
              onClick={handleSave}
              loading={saving}
              disabled={!dirty}
            >
              创建
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
              disabled={saving}
            />
          </div>
        )}

        {triggerType === 'once' && (
          <div>
            <div className="text-sm text-[#0F172A] font-medium mb-2">执行时间</div>
            <DatePicker
              showTime={{ format: 'HH:mm' }}
              format="YYYY-MM-DD HH:mm"
              value={executeAt ? dayjs(executeAt) : null}
              onChange={(date) => {
                // Send ISO string with timezone offset to avoid ambiguity
                setExecuteAt(date ? date.toISOString() : '')
                markDirty()
              }}
              disabledDate={(current) => current && current < dayjs().startOf('day')}
              className="!w-full"
              disabled={saving}
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
                  disabled={saving}
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
      </div>
    </Modal>
  )
}

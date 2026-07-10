/**
 * TriggerConfigModal - 定时任务创建/编辑 Modal。
 *
 * 字段：工作流选择（创建模式）/ 只读（编辑模式）、启用开关、触发类型
 * (cron 重复 / once 一次性)、调度配置（cron 用 TriggerSchedulePicker，
 * once 用原生 datetime-local）、默认输入参数（JSON）。
 *
 * workflow Select 的 value 用 registry entry _id (wfr_，唯一稳定)，提交时
 * 解析成模板 workflow_id (wf_) 传后端 - 引擎直接按 _id 查 workflows 集合。
 */
import { useState, useEffect } from 'react'
import { Modal, Input, Select, Switch } from '../ui'
import { toast } from '../ui/toast'
import {
  triggersApi,
  getTriggerId,
  type TriggerConfig,
  type TriggerType,
} from '../../services/triggers-api'
import type { WorkflowRegistryEntry } from '../../services/tasks-api'
import TriggerSchedulePicker from './TriggerSchedulePicker'

interface Props {
  open: boolean
  mode: 'create' | 'edit'
  /** 编辑模式时传入已有 trigger */
  trigger?: TriggerConfig | null
  /** 已发布 workflow 列表（创建模式选 workflow 用） */
  workflows: WorkflowRegistryEntry[]
  onClose: () => void
  onSaved: () => void
}

/** 把 registry entry _id (wfr_) 解析为模板 workflow_id (wf_)；已是 wf_ 则原样返回。 */
function resolveTemplateId(
  workflows: WorkflowRegistryEntry[],
  maybeRegistryId: string,
): string {
  const entry = workflows.find(
    (wf) => wf._id === maybeRegistryId || wf.workflow_id === maybeRegistryId,
  )
  return entry?.workflow_id ?? maybeRegistryId
}

/** ISO -> datetime-local 输入值 (YYYY-MM-DDTHH:MM，本地时区)。 */
function toDatetimeLocal(iso: string): string {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** datetime-local 输入值 -> ISO 字符串。 */
function fromDatetimeLocal(local: string): string {
  if (!local) return ''
  const d = new Date(local)
  if (Number.isNaN(d.getTime())) return ''
  return d.toISOString()
}

const datetimeInputCls =
  'h-8 w-full px-2.5 rounded-md border border-[#27272a] bg-[#121214] text-[#fafafa] text-xs ' +
  'focus:outline-none focus:border-[#1E5EFF] focus:ring-1 focus:ring-[#1E5EFF]/30 [color-scheme:dark]'

export default function TriggerConfigModal({
  open,
  mode,
  trigger,
  workflows,
  onClose,
  onSaved,
}: Props) {
  const isEdit = mode === 'edit'
  // 创建模式下 Select 的 value 用 registry entry _id (wfr_)
  const [entryId, setEntryId] = useState('')
  const [enabled, setEnabled] = useState(false)
  const [triggerType, setTriggerType] = useState<TriggerType>('cron')
  const [cronExpression, setCronExpression] = useState('0 9 * * *')
  const [executeAt, setExecuteAt] = useState('')
  const [defaultInputText, setDefaultInputText] = useState('{}')
  const [saving, setSaving] = useState(false)

  // 打开时初始化表单
  useEffect(() => {
    if (!open) return
    if (isEdit && trigger) {
      setEntryId(trigger.workflow_id)
      setEnabled(trigger.enabled)
      setTriggerType(trigger.type)
      setCronExpression(trigger.cron_expression || '0 9 * * *')
      setExecuteAt(trigger.execute_at || '')
      setDefaultInputText(JSON.stringify(trigger.default_input ?? {}, null, 2))
    } else {
      setEntryId('')
      setEnabled(false)
      setTriggerType('cron')
      setCronExpression('0 9 * * *')
      setExecuteAt('')
      setDefaultInputText('{}')
    }
  }, [open, isEdit, trigger])

  const handleSave = async () => {
    if (!isEdit && !entryId) {
      toast.error('请选择工作流')
      return
    }
    if (triggerType === 'cron' && !cronExpression.trim()) {
      toast.error('请填写 Cron 表达式')
      return
    }
    if (triggerType === 'once' && !executeAt) {
      toast.error('请选择执行时间')
      return
    }

    // 解析 default_input JSON
    let defaultInput: Record<string, unknown> = {}
    const text = defaultInputText.trim()
    if (text) {
      try {
        const parsed = JSON.parse(text)
        if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
          toast.error('输入参数必须是 JSON 对象')
          return
        }
        defaultInput = parsed as Record<string, unknown>
      } catch {
        toast.error('输入参数 JSON 格式错误')
        return
      }
    }

    const payload: Partial<TriggerConfig> = {
      type: triggerType,
      enabled,
      default_input: defaultInput,
    }
    if (triggerType === 'cron') {
      payload.cron_expression = cronExpression
    } else {
      payload.execute_at = executeAt
    }

    setSaving(true)
    try {
      if (isEdit && trigger) {
        await triggersApi.updateById(getTriggerId(trigger), payload)
        toast.success('定时任务已更新')
      } else {
        const workflowId = resolveTemplateId(workflows, entryId)
        await triggersApi.create(workflowId, payload)
        toast.success('定时任务已创建')
      }
      onSaved()
      onClose()
    } catch (err: unknown) {
      const msg =
        err && typeof err === 'object' && 'message' in err
          ? (err as { message: string }).message
          : '保存失败'
      toast.error(msg)
    } finally {
      setSaving(false)
    }
  }

  // 编辑模式下展示 workflow 名（用 entryId 即 workflow_id 解析）
  const editWorkflowName =
    workflows.find(
      (w) => w.workflow_id === entryId || w._id === entryId,
    )?.name || entryId

  return (
    <Modal
      open={open}
      title={isEdit ? '编辑定时任务' : '新建定时任务'}
      onCancel={onClose}
      onOk={handleSave}
      okText={isEdit ? '保存' : '创建'}
      cancelText="取消"
      width={560}
      okButtonProps={{ disabled: saving }}
    >
      <div className="space-y-4">
        {/* 工作流 */}
        <div className="space-y-1.5">
          <div className="text-xs font-medium text-[#fafafa]">
            工作流{isEdit && '（不可更改）'}
          </div>
          {isEdit ? (
            <div className="text-xs text-slate-400 px-2.5 h-8 flex items-center rounded-md border border-[#27272a] bg-[#121214]">
              {editWorkflowName}
            </div>
          ) : (
            <Select
              value={entryId || null}
              onChange={(v) => setEntryId(v ?? '')}
              placeholder="选择已发布的工作流"
              options={workflows.map((w) => ({
                value: w._id,
                label: `${w.name} (v${w.version})`,
              }))}
            />
          )}
        </div>

        {/* 启用开关 */}
        <div className="flex items-center gap-3">
          <span className="text-xs font-medium text-[#fafafa]">启用</span>
          <Switch checked={enabled} onChange={setEnabled} size="small" />
          {enabled && <span className="text-[11px] text-emerald-400">● 已启用</span>}
        </div>

        {/* 触发类型 */}
        <div className="flex items-center gap-3">
          <span className="text-xs font-medium text-[#fafafa]">触发类型</span>
          <div className="flex gap-1.5">
            {(['cron', 'once'] as TriggerType[]).map((t) => {
              const active = triggerType === t
              return (
                <button
                  key={t}
                  type="button"
                  onClick={() => setTriggerType(t)}
                  className={`h-7 px-3 rounded-md text-xs font-medium border cursor-pointer transition-colors
                    ${active
                      ? 'bg-[#1E5EFF] border-[#1E5EFF] text-white'
                      : 'bg-[#18181b] border-[#27272a] text-slate-300 hover:border-[#1E5EFF]'}`}
                >
                  {t === 'cron' ? '重复执行' : '一次性'}
                </button>
              )
            })}
          </div>
        </div>

        {/* 调度配置 */}
        {triggerType === 'cron' ? (
          <div className="space-y-1.5">
            <div className="text-xs font-medium text-[#fafafa]">执行频率</div>
            <TriggerSchedulePicker
              value={cronExpression}
              onChange={setCronExpression}
              disabled={saving}
            />
          </div>
        ) : (
          <div className="space-y-1.5">
            <div className="text-xs font-medium text-[#fafafa]">执行时间</div>
            <input
              type="datetime-local"
              value={toDatetimeLocal(executeAt)}
              onChange={(e) => setExecuteAt(fromDatetimeLocal(e.target.value))}
              className={datetimeInputCls}
            />
            <p className="text-[10px] text-[#71717a]">
              到达此时间后触发一次，过期时间不会触发。
            </p>
          </div>
        )}

        {/* 默认输入参数 */}
        <div className="space-y-1.5">
          <div className="text-xs font-medium text-[#fafafa]">输入参数（JSON）</div>
          <Input.TextArea
            rows={4}
            value={defaultInputText}
            onChange={(e) => setDefaultInputText(e.target.value)}
            placeholder='{"key": "value"}'
            className="font-mono"
          />
          <p className="text-[10px] text-[#71717a]">
            定时触发时传入工作流的默认输入。支持模板语法 {'{{ now() }}'} / {'{{ today() }}'}。无输入参数可留空。
          </p>
        </div>
      </div>
    </Modal>
  )
}

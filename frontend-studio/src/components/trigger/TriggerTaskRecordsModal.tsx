/**
 * TriggerTaskRecordsModal - 某个 trigger 的触发任务记录。
 *
 * 调 tasksApi.list({ trigger_id }) 拉该 trigger 触发产生的任务
 * (source=trigger_scheduled)。点行 -> onViewTask(taskId) 跳转到任务看板明细
 * (App 切 board tab + 打开根级 TaskDetailDrawer)。
 */
import { useQuery } from '@tanstack/react-query'
import { Modal, Tag, Spin } from '../ui'
import {
  tasksApi,
  type TaskSummary,
  type TaskStatusValue,
  type WorkflowRegistryEntry,
} from '../../services/tasks-api'
import { getTriggerId, type TriggerConfig } from '../../services/triggers-api'

interface Props {
  trigger: TriggerConfig | null
  workflows: WorkflowRegistryEntry[]
  onClose: () => void
  onViewTask: (taskId: string) => void
}

const STATUS_TAG: Record<TaskStatusValue, { color: string; label: string }> = {
  pending: { color: 'default', label: '待执行' },
  running: { color: 'blue', label: '运行中' },
  waiting_human: { color: 'purple', label: '等待人工' },
  completed: { color: 'success', label: '已完成' },
  failed: { color: 'red', label: '已失败' },
  cancelled: { color: 'default', label: '已取消' },
}

function formatDateTime(iso?: string): string {
  if (!iso) return '-'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return '-'
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
}

function inputSummary(input: Record<string, unknown>): string {
  const keys = Object.keys(input)
  if (keys.length === 0) return '（无输入）'
  return JSON.stringify(input)
}

export default function TriggerTaskRecordsModal({
  trigger,
  workflows,
  onClose,
  onViewTask,
}: Props) {
  const triggerId = trigger ? getTriggerId(trigger) : ''
  const open = trigger !== null

  const { data, isLoading } = useQuery({
    queryKey: ['trigger-records', triggerId],
    queryFn: () => tasksApi.list({ trigger_id: triggerId, page: 1, page_size: 50 }),
    enabled: open && !!triggerId,
  })

  const workflowName = trigger
    ? workflows.find(
        (w) => w.workflow_id === trigger.workflow_id || w._id === trigger.workflow_id,
      )?.name || trigger.workflow_id
    : ''

  const tasks = data?.items ?? []

  return (
    <Modal
      open={open}
      title={trigger ? `触发记录：${workflowName}` : '触发记录'}
      onCancel={onClose}
      onOk={onClose}
      okText="关闭"
      cancelText="取消"
      width={640}
    >
      <div className="space-y-3">
        {/* trigger 摘要 */}
        {trigger && (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[11px] text-[#a1a1aa] p-2.5 rounded-md bg-[#121214] border border-[#27272a]">
            <span>类型：{trigger.type === 'cron' ? '重复' : '一次性'}</span>
            {trigger.type === 'cron' ? (
              <span className="font-mono">{trigger.cron_expression || '-'}</span>
            ) : (
              <span>执行时间：{formatDateTime(trigger.execute_at)}</span>
            )}
            <span>上次触发：{formatDateTime(trigger.last_triggered_at)}</span>
          </div>
        )}

        {/* 记录列表 */}
        {isLoading ? (
          <div className="flex items-center justify-center py-10">
            <Spin />
          </div>
        ) : tasks.length === 0 ? (
          <div className="text-center py-10 text-xs text-[#71717a]">
            暂无触发记录。启用该定时任务后，到点触发会产生任务记录。
          </div>
        ) : (
          <div className="space-y-1.5 max-h-[50vh] overflow-y-auto">
            {tasks.map((task: TaskSummary) => {
              const st = STATUS_TAG[task.status] ?? STATUS_TAG.pending
              return (
                <div
                  key={task.id}
                  className="flex items-center gap-3 p-2.5 rounded-md border border-[#27272a] bg-[#121214] hover:border-[#1E5EFF] cursor-pointer transition-colors"
                  onClick={() => onViewTask(task.id)}
                >
                  <Tag color={st.color}>{st.label}</Tag>
                  <span className="text-[11px] text-slate-400 w-44 shrink-0">
                    {formatDateTime(task.created_at)}
                  </span>
                  <span className="text-[11px] text-slate-300 flex-1 truncate font-mono">
                    {inputSummary(task.input)}
                  </span>
                  <span className="text-[11px] text-[#1E5EFF] shrink-0">查看明细 →</span>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </Modal>
  )
}

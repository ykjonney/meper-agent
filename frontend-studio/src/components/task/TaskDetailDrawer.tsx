/**
 * TaskDetailDrawer — 任务详情抽屉（点击看板卡片打开）。
 *
 * 重构后的结构（自上而下）：
 * - Header：任务详情 + 工作流名 + 状态 pill + 关闭
 * - Sticky 操作栏：常驻可见（取消/继续/通过/驳回/重试/删除），不用滚到底
 * - 错误提示（failed 时置顶醒目红色 Alert）
 * - 审批信息（waiting_human 时展示 human_context + 上游输出，供决策）
 * - 执行流程：双视图切换（流程时间线 / 流程图）
 * - 产物（completed/running 均展示 Agent 节点产出文件，复用对话预览能力）
 * - 基本信息 + 输入参数
 *
 * 详情查询与卡片共用 taskKeys.detail(id) 缓存，running/pending/waiting_human 时 5s 轮询。
 * 干预（cancel/retry/approve/reject/resume）交由父级 mutation 统一处理。
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  X, Ban, RotateCcw, Trash2, Check, AlertTriangle, ListTree, Share2,
} from 'lucide-react'
import {
  tasksApi, taskKeys,
  type TaskSummary, type TaskDetail,
} from '../../services/tasks-api'
import { TASK_STATUS_STYLES } from '../../constants/task-status'
import { Button, Modal, Spin } from '../ui'
import { TaskOutputFiles } from './TaskOutputFiles'
import { TaskFlowTimeline } from './TaskFlowTimeline'
import { TaskFlowGraph } from './TaskFlowGraph'
import { APPROVAL_ACCENT } from './TaskBoardCard'

type FlowView = 'timeline' | 'graph'

export interface TaskDetailDrawerProps {
  taskId: string | null
  open: boolean
  onClose: () => void
  workflowNameMap: Record<string, string>
  /** 解析 created_by（user id）→ 可读 username 的函数，由父级注入 */
  creatorLabel?: (created_by: string, created_by_type?: string) => string
  /** 把 task.workflow_id（可能是 registry id wfr_...）解析为可拉 /workflows/{id} 的模板 id（wf_...） */
  resolveTemplateId?: (maybeRegistryId: string) => string
  theme?: 'light' | 'dark'
  onCancel?: (task: TaskSummary | TaskDetail) => void
  onRetry?: (task: TaskSummary | TaskDetail) => void
  /** resume：waiting_human 无人工 options 时推进继续执行（对齐 legacy-antd） */
  onResume?: (task: TaskSummary | TaskDetail) => void
  onDelete?: (task: TaskSummary | TaskDetail) => void
  onApprove?: (task: TaskSummary | TaskDetail, comment: string) => void
  onReject?: (task: TaskSummary | TaskDetail, comment: string) => void
  interveneLoading?: boolean
  deleteLoading?: boolean
}

export function TaskDetailDrawer({
  taskId,
  open,
  onClose,
  workflowNameMap,
  creatorLabel,
  resolveTemplateId,
  theme = 'dark',
  onCancel,
  onRetry,
  onResume,
  onDelete,
  onApprove,
  onReject,
  interveneLoading = false,
  deleteLoading = false,
}: TaskDetailDrawerProps) {
  const { data: taskDetail, isLoading } = useQuery({
    queryKey: taskKeys.detail(taskId ?? ''),
    queryFn: () => tasksApi.get(taskId!),
    enabled: !!taskId && open,
    refetchInterval: (query) => {
      const task = query.state.data
      if (task?.status === 'running' || task?.status === 'pending' || task?.status === 'waiting_human') {
        return 5_000
      }
      return false
    },
  })

  // 执行流程视图切换（默认时间线；切到图时才懒加载）
  const [flowView, setFlowView] = useState<FlowView>('timeline')

  // 审批弹窗
  const [approvalAction, setApprovalAction] = useState<'approve' | 'reject' | null>(null)
  const [approvalComment, setApprovalComment] = useState('')

  const openApproval = (action: 'approve' | 'reject') => {
    setApprovalAction(action)
    setApprovalComment('')
  }

  const closeApproval = () => {
    if (interveneLoading) return
    setApprovalAction(null)
    setApprovalComment('')
  }

  const submitApproval = () => {
    if (!approvalAction || !taskDetail || interveneLoading) return
    if (approvalAction === 'approve') {
      onApprove?.(taskDetail, approvalComment)
    } else {
      onReject?.(taskDetail, approvalComment)
    }
    setApprovalAction(null)
    setApprovalComment('')
  }

  if (!open || !taskId) return null

  const status = taskDetail?.status
  // waiting_human 且 checkpoint 无人工 options → 用 resume（继续）；有 options → approve/reject
  const humanOptions = (taskDetail?.status === 'waiting_human' && taskDetail.checkpoint?.human_context?.options)
    ? (taskDetail.checkpoint.human_context.options as string[]).filter(Boolean)
    : []
  const useResume = taskDetail?.status === 'waiting_human' && humanOptions.length === 0

  return (
    <div className="w-full max-w-xl border-l border-[#27272a] h-full flex flex-col bg-[#121214] shadow-2xl fixed right-0 top-0 z-40 animate-slide-left">
      {/* ── Header ── */}
      <div className="flex items-center justify-between border-b border-[#27272a] px-5 py-3.5 shrink-0">
        <div className="min-w-0">
          <div className="text-[10px] text-indigo-400 font-bold uppercase tracking-wider font-mono">
            任务详情
          </div>
          <h3 className="text-sm font-bold text-[#fafafa] truncate mt-0.5">
            {taskDetail ? (workflowNameMap[taskDetail.workflow_id] ?? taskDetail.workflow_id) : '加载中…'}
          </h3>
        </div>
        <div className="flex items-center gap-3 shrink-0">
          {taskDetail && status && (
            <span
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-medium border"
              style={{
                color: TASK_STATUS_STYLES[status].color,
                background: TASK_STATUS_STYLES[status].bg,
                borderColor: `${TASK_STATUS_STYLES[status].accent}33`,
              }}
            >
              {TASK_STATUS_STYLES[status].label}
            </span>
          )}
          <button
            onClick={onClose}
            className="p-1 rounded-lg text-[#a1a1aa] hover:text-[#fafafa] hover:bg-[#18181b] transition cursor-pointer"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* ── Sticky 操作栏（常驻可见） ── */}
      {taskDetail && status && (
        <div className="flex items-center gap-2 flex-wrap border-b border-[#27272a] px-5 py-2.5 shrink-0 bg-[#18181b]/40">
          {status === 'running' && onCancel && (
            <Button danger size="small" icon={<Ban className="w-3.5 h-3.5" />} onClick={() => onCancel(taskDetail)} loading={interveneLoading}>
              取消任务
            </Button>
          )}
          {status === 'waiting_human' && useResume && onResume && (
            <Button type="primary" size="small" icon={<RotateCcw className="w-3.5 h-3.5" />} onClick={() => onResume(taskDetail)} loading={interveneLoading}>
              继续
            </Button>
          )}
          {status === 'waiting_human' && !useResume && (
            <>
              {onApprove && (
                <Button
                  type="primary"
                  size="small"
                  icon={<Check className="w-3.5 h-3.5" />}
                  onClick={() => openApproval('approve')}
                  loading={interveneLoading}
                  className="!bg-[#8B5CF6] !border-[#8B5CF6] hover:!bg-[#7c4fe0]"
                >
                  通过
                </Button>
              )}
              {onReject && (
                <Button danger size="small" icon={<X className="w-3.5 h-3.5" />} onClick={() => openApproval('reject')} loading={interveneLoading}>
                  驳回
                </Button>
              )}
            </>
          )}
          {status === 'failed' && onRetry && (
            <Button type="primary" size="small" icon={<RotateCcw className="w-3.5 h-3.5" />} onClick={() => onRetry(taskDetail)} loading={interveneLoading}>
              重试
            </Button>
          )}
          {(status === 'completed' || status === 'failed' || status === 'cancelled') && onDelete && (
            <Button danger size="small" icon={<Trash2 className="w-3.5 h-3.5" />} onClick={() => onDelete(taskDetail)} loading={deleteLoading}>
              删除
            </Button>
          )}
          {status === 'pending' && (
            <span className="text-[11px] text-[#71717a]">排队中，等待调度…</span>
          )}
        </div>
      )}

      {/* ── Body ── */}
      <div className="flex-1 overflow-y-auto p-5 scrollbar-custom">
        {isLoading && (
          <div className="flex items-center justify-center py-20">
            <Spin size="large" />
          </div>
        )}

        {!isLoading && taskDetail && (
          <div className="flex flex-col gap-6">
            {/* 错误提示（failed 时置顶醒目） */}
            {taskDetail.error && (
              <div className="p-3 rounded-lg border border-rose-500/30 bg-rose-500/5 flex gap-2">
                <AlertTriangle className="w-3.5 h-3.5 text-rose-400 shrink-0 mt-0.5" />
                <div className="min-w-0">
                  <div className="text-xs font-medium text-rose-400">执行错误</div>
                  <div className="text-[11px] text-[#d4d4d8] mt-0.5 break-all">
                    [{taskDetail.error.error_code}] {taskDetail.error.error_message}
                  </div>
                  {(taskDetail.error.node_id || taskDetail.error.node_type) && (
                    <div className="text-[10px] text-[#71717a] mt-1 font-mono">
                      {taskDetail.error.node_type ?? '—'} · {taskDetail.error.node_id ?? '—'}
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* 审批信息（waiting_human 时展示决策上下文） */}
            {taskDetail.status === 'waiting_human' && taskDetail.checkpoint && (
              <section>
                <SectionTitle>
                  <AlertTriangle className="w-3.5 h-3.5 inline mr-1 -mt-0.5" style={{ color: APPROVAL_ACCENT }} />
                  审批信息
                </SectionTitle>
                <div className="space-y-2.5">
                  {taskDetail.checkpoint.human_context?.title && (
                    <InfoRow label="审批标题" value={String(taskDetail.checkpoint.human_context.title)} />
                  )}
                  {taskDetail.checkpoint.human_context?.description && (
                    <div>
                      <div className="text-xs text-[#a1a1aa] mb-1">审批描述</div>
                      <div className="text-xs text-[#d4d4d8] bg-[#09090b] rounded-lg p-3 border border-[#27272a] whitespace-pre-wrap">
                        {String(taskDetail.checkpoint.human_context.description)}
                      </div>
                    </div>
                  )}
                  {taskDetail.checkpoint.timeout_deadline && (
                    <InfoRow
                      label="超时截止"
                      value={`${formatDateTime(taskDetail.checkpoint.timeout_deadline)} (${taskDetail.checkpoint.timeout_action})`}
                    />
                  )}
                  {(() => {
                    const pausedNode = taskDetail.checkpoint.paused_at_node
                    const upstreamVars = Object.entries(taskDetail.variables ?? {})
                      .filter(([key]) => key !== 'input' && key !== pausedNode)
                    if (upstreamVars.length === 0) return null
                    return (
                      <div>
                        <div className="text-xs text-[#a1a1aa] mb-1">上游节点输出</div>
                        <div className="max-h-48 overflow-y-auto space-y-2 scrollbar-custom">
                          {upstreamVars.map(([key, value]) => (
                            <div key={key}>
                              <div className="text-[11px] text-[#71717a] font-medium mb-0.5">{key}</div>
                              <pre className="text-[10px] bg-[#09090b] rounded p-2 overflow-x-auto text-[#d4d4d8] border border-[#27272a] max-h-32">
                                {JSON.stringify(value, null, 2)}
                              </pre>
                            </div>
                          ))}
                        </div>
                      </div>
                    )
                  })()}
                </div>
              </section>
            )}

            {/* 执行流程：双视图切换 */}
            <section>
              <div className="flex items-center justify-between mb-3">
                <SectionTitle>
                  执行流程 <span className="font-normal text-[#71717a]">({taskDetail.timeline?.length ?? 0})</span>
                </SectionTitle>
                {/* 视图切换 tab */}
                <div className={`flex items-center gap-0.5 p-0.5 rounded-md border ${
                  theme === 'dark' ? 'bg-[#09090b] border-[#27272a]' : 'bg-slate-100 border-slate-200'
                }`}>
                  <ViewTab active={flowView === 'timeline'} onClick={() => setFlowView('timeline')} icon={<ListTree className="w-3 h-3" />} label="时间线" theme={theme} />
                  <ViewTab active={flowView === 'graph'} onClick={() => setFlowView('graph')} icon={<Share2 className="w-3 h-3" />} label="流程图" theme={theme} />
                </div>
              </div>
              {flowView === 'timeline'
                ? <TaskFlowTimeline task={taskDetail} theme={theme} />
                : <TaskFlowGraph task={taskDetail} theme={theme} resolveTemplateId={resolveTemplateId} />
              }
            </section>

            {/* 产物（completed/running 均展示，空列表自然不显示） */}
            {(taskDetail.status === 'completed' || taskDetail.status === 'running') && (
              <section>
                <SectionTitle>产物</SectionTitle>
                <TaskOutputFiles taskId={taskDetail.id} />
              </section>
            )}

            {/* 基本信息 */}
            <section>
              <SectionTitle>基本信息</SectionTitle>
              <div className="space-y-2.5">
                <InfoRow label="ID" value={taskDetail.id} mono />
                <InfoRow label="工作流" value={workflowNameMap[taskDetail.workflow_id] ?? taskDetail.workflow_id} />
                <InfoRow label="创建者" value={creatorLabel ? creatorLabel(taskDetail.created_by, taskDetail.created_by_type) : (taskDetail.created_by || '系统')} />
                <InfoRow label="版本" value={`v${taskDetail.version}`} />
                <InfoRow label="创建时间" value={formatDateTime(taskDetail.created_at)} />
                <InfoRow label="更新时间" value={formatDateTime(taskDetail.updated_at)} />
              </div>
            </section>

            {/* 输入参数 */}
            <section>
              <SectionTitle>输入参数</SectionTitle>
              <div className="space-y-1.5">
                {(() => {
                  const entries = Object.entries(taskDetail.input ?? {})
                  if (entries.length === 0) {
                    return <div className="text-xs text-[#71717a] italic">无</div>
                  }
                  return entries.map(([k, v]) => (
                    <div key={k} className="flex gap-2 text-xs">
                      <span className="text-[#a1a1aa] font-medium shrink-0 min-w-[80px]">{k}</span>
                      <span className="text-[#d4d4d8] break-all">
                        {typeof v === 'string' ? v : JSON.stringify(v)}
                      </span>
                    </div>
                  ))
                })()}
              </div>
            </section>
          </div>
        )}
      </div>

      {/* ── 审批弹窗 ── */}
      <Modal
        title={approvalAction === 'approve' ? '通过审批' : '驳回审批'}
        open={!!approvalAction}
        onOk={submitApproval}
        onCancel={closeApproval}
        okText={approvalAction === 'approve' ? '通过' : '驳回'}
        cancelText="取消"
        okButtonProps={{ disabled: interveneLoading }}
      >
        <div className="flex flex-col gap-3 py-2">
          <p className="text-xs text-[#d4d4d8]">
            {approvalAction === 'approve'
              ? `确定通过任务「${taskDetail?.id.slice(-8)}」并继续执行吗？`
              : `确定驳回任务「${taskDetail?.id.slice(-8)}」吗？任务将被标记为失败。`}
          </p>
          <div>
            <label className="block text-xs text-[#a1a1aa] mb-1.5">comment（可选）</label>
            <textarea
              value={approvalComment}
              onChange={(e) => setApprovalComment(e.target.value)}
              placeholder={approvalAction === 'reject' ? '建议填写驳回原因（可选）' : '审批意见（可选）'}
              rows={3}
              className="w-full px-3 py-2 text-xs border border-[#27272a] bg-[#121214] text-[#fafafa] rounded-md focus:outline-none focus:border-[#1E5EFF] resize-none"
            />
          </div>
        </div>
      </Modal>
    </div>
  )
}

/* ─── 子组件 ─── */

function ViewTab({ active, onClick, icon, label, theme = 'dark' }: {
  active: boolean
  onClick: () => void
  icon: React.ReactNode
  label: string
  theme?: 'light' | 'dark'
}) {
  return (
    <button
      onClick={onClick}
      className={`inline-flex items-center gap-1 px-2 py-1 rounded text-[11px] font-medium transition cursor-pointer ${
        active
          ? theme === 'dark'
            ? 'bg-[#27272a] text-[#fafafa]'
            : 'bg-white text-slate-900 shadow-sm'
          : theme === 'dark'
            ? 'text-[#71717a] hover:text-[#fafafa]'
            : 'text-slate-500 hover:text-slate-800'
      }`}
    >
      {icon} {label}
    </button>
  )
}

function SectionTitle({ children }: { children: React.ReactNode }) {
  return (
    <h4 className="text-[11px] font-medium text-[#71717a] uppercase tracking-wider mb-3 flex items-center gap-1">
      {children}
    </h4>
  )
}

function InfoRow({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="flex items-center justify-between gap-3">
      <span className="text-xs text-[#a1a1aa] shrink-0">{label}</span>
      <span className={`text-xs text-[#d4d4d8] text-right max-w-[300px] truncate ${mono ? 'font-mono' : ''}`}>
        {value}
      </span>
    </div>
  )
}

/* ─── 工具函数 ─── */

function formatDateTime(iso: string): string {
  if (!iso) return '-'
  try {
    return new Date(iso).toLocaleString('zh-CN', {
      month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
    })
  } catch {
    return iso
  }
}

export default TaskDetailDrawer

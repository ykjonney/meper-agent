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
 * 详情查询与卡片共用 taskKeys.detail(id) 缓存；刷新由 WebSocket 的 task_status 事件
 * invalidate 驱动（见 use-task-realtime），不做定时轮询。
 * 干预（cancel/retry/approve/reject/resume）交由父级 mutation 统一处理。
 */
import { useState, useMemo } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  X, Ban, RotateCcw, Trash2, Check, AlertTriangle,
} from 'lucide-react'
import {
  tasksApi, taskKeys,
  type TaskSummary, type TaskDetail, type CommentValue,
} from '../../services/tasks-api'
import { agentApi, agentKeys } from '../../services/agent-api'
import { TASK_STATUS_STYLES } from '../../constants/task-status'
import { Button, Modal, Spin } from '../ui'
import { toast } from '../ui/toast'
import { TaskOutputFiles } from './TaskOutputFiles'
import { TaskFlowTimeline } from './TaskFlowTimeline'
import { TaskFlowGraph } from './TaskFlowGraph'
import { APPROVAL_ACCENT } from './TaskBoardCard'
import { DataView, DataViewEnhanceProvider } from './DataView'

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
  onApprove?: (task: TaskSummary | TaskDetail, comment: CommentValue) => void
  onReject?: (task: TaskSummary | TaskDetail, comment: CommentValue) => void
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
    // 刷新由 WebSocket task_status 事件 invalidate 驱动（use-task-realtime），不轮询。
  })

  // 预加载 Agent 列表，建立 agent_id → 名称映射（供 DataView 把 agent_id 渲染成名称）
  const { data: agentListData } = useQuery({
    queryKey: agentKeys.lists(),
    queryFn: () => agentApi.list({ page_size: 100 }),
    enabled: open && !!taskId,
    staleTime: 60_000,
  })
  const agentNameMap = useMemo(() => {
    const map: Record<string, string> = {}
    for (const a of agentListData?.items ?? []) map[a.id] = a.name
    return map
  }, [agentListData])

  // 审批弹窗
  const [approvalAction, setApprovalAction] = useState<'approve' | 'reject' | null>(null)
  const [approvalComment, setApprovalComment] = useState('')
  // comment 输入模式：text 纯文本 / json 结构化（与看板卡片弹窗保持一致）
  const [approvalCommentMode, setApprovalCommentMode] = useState<'text' | 'json'>('text')

  const openApproval = (action: 'approve' | 'reject') => {
    setApprovalAction(action)
    setApprovalComment('')
    setApprovalCommentMode('text')
  }

  const closeApproval = () => {
    if (interveneLoading) return
    setApprovalAction(null)
    setApprovalComment('')
    setApprovalCommentMode('text')
  }

  const submitApproval = () => {
    if (!approvalAction || !taskDetail || interveneLoading) return
    // 按 mode 组装 comment
    let comment: CommentValue
    if (approvalCommentMode === 'json') {
      const trimmed = approvalComment.trim()
      if (!trimmed) {
        comment = { type: 'json', value: '' }
      } else {
        try {
          comment = { type: 'json', value: JSON.parse(trimmed) }
        } catch {
          toast.error('JSON 格式错误，请检查输入')
          return
        }
      }
    } else {
      comment = { type: 'text', value: approvalComment }
    }
    if (approvalAction === 'approve') {
      onApprove?.(taskDetail, comment)
    } else {
      onReject?.(taskDetail, comment)
    }
    setApprovalAction(null)
    setApprovalComment('')
    setApprovalCommentMode('text')
  }

  if (!open || !taskId) return null

  const status = taskDetail?.status
  // waiting_human 且 checkpoint 无人工 options → 用 resume（继续）；有 options → approve/reject
  const humanOptions = (taskDetail?.status === 'waiting_human' && taskDetail.checkpoint?.human_context?.options)
    ? (taskDetail.checkpoint.human_context.options as string[]).filter(Boolean)
    : []
  const useResume = taskDetail?.status === 'waiting_human' && humanOptions.length === 0

  return (
    <DataViewEnhanceProvider agentNameMap={agentNameMap}>
    <div className="w-full max-w-[min(92vw,1080px)] border-l border-[#27272a] h-full flex flex-col bg-[#121214] shadow-2xl fixed right-0 top-0 z-40 animate-slide-left">
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
          <div className="@container grid grid-cols-1 @[900px]:grid-cols-[1.35fr_1fr] gap-6">
            {/* 错误提示（failed 时置顶醒目，横跨双栏） */}
            {taskDetail.error && (
              <div className="@[900px]:col-span-2 p-3 rounded-lg border border-rose-500/30 bg-rose-500/5 flex gap-2">
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

            {/* 审批信息（waiting_human 时展示决策上下文，横跨双栏） */}
            {taskDetail.status === 'waiting_human' && taskDetail.checkpoint && (
              <section className="@[900px]:col-span-2">
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
                              <DataView value={value} context="approval_upstream" showRaw={false} />
                            </div>
                          ))}
                        </div>
                      </div>
                    )
                  })()}
                </div>
              </section>
            )}

            {/* 左栏：执行流程（流程图 + 时间线，平铺不再切换） */}
            <div className="flex flex-col gap-6 min-w-0">
              <section>
                <SectionTitle>流程图</SectionTitle>
                <TaskFlowGraph task={taskDetail} theme={theme} resolveTemplateId={resolveTemplateId} />
              </section>
              <section>
                <SectionTitle>
                  时间线 <span className="font-normal text-[#71717a]">({taskDetail.timeline?.length ?? 0})</span>
                </SectionTitle>
                <TaskFlowTimeline task={taskDetail} theme={theme} resolveTemplateId={resolveTemplateId} />
              </section>
            </div>

            {/* 右栏：基本信息 + 输入参数 + 产物 */}
            <div className="flex flex-col gap-6 min-w-0">
              <section>
                <SectionTitle>基本信息</SectionTitle>
                <div className="space-y-2.5">
                  <InfoRow label="ID" value={taskDetail.id} mono />
                  <InfoRow label="工作流" value={workflowNameMap[taskDetail.workflow_id] ?? taskDetail.workflow_id} />
                  <InfoRow label="创建者" value={creatorLabel ? creatorLabel(taskDetail.created_by, taskDetail.created_by_type) : (taskDetail.created_by || '系统')} />
                  <InfoRow label="版本" value={`v${taskDetail.version}`} />
                  <InfoRow label="创建时间" value={formatDateTime(taskDetail.created_at)} />
                  <InfoRow label="更新时间" value={formatDateTime(taskDetail.updated_at)} />
                  {taskDetail.total_tokens ? (
                    <InfoRow label="Token 消耗" value={`${taskDetail.total_tokens.toLocaleString()} tokens`} />
                  ) : null}
                </div>
              </section>

              <section>
                <SectionTitle>输入参数</SectionTitle>
                {Object.keys(taskDetail.input ?? {}).length === 0 ? (
                  <div className="text-xs text-[#71717a] italic">无</div>
                ) : (
                  <DataView value={taskDetail.input} context="task_input" showRaw={false} />
                )}
              </section>

              {(taskDetail.status === 'completed' || taskDetail.status === 'running') && (
                <section>
                  <SectionTitle>产物</SectionTitle>
                  <TaskOutputFiles taskId={taskDetail.id} />
                </section>
              )}
            </div>
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
          {/* 审核信息：与通过/驳回同界面，审批人据此决策 */}
          {(() => {
            const ctx = taskDetail?.checkpoint?.human_context
            if (!ctx) return null
            return (
              <div className="border border-[#27272a] rounded-lg p-3 bg-[#18181b]">
                {ctx.title && (
                  <div className="text-sm font-medium text-[#fafafa] mb-1.5">{ctx.title}</div>
                )}
                {ctx.description && (
                  <div className="text-xs text-[#a1a1aa] whitespace-pre-wrap break-words leading-relaxed">
                    {ctx.description}
                  </div>
                )}
                {!ctx.title && !ctx.description && (
                  <div className="text-xs text-[#71717a] italic">该审批节点未配置说明</div>
                )}
              </div>
            )
          })()}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="block text-xs text-[#a1a1aa]">comment（可选）</label>
              <div className="flex items-center gap-0.5 bg-[#27272a] rounded-md p-0.5">
                <button
                  type="button"
                  onClick={() => setApprovalCommentMode('text')}
                  className={`px-2 py-0.5 text-[10px] rounded transition-colors border-0 cursor-pointer ${
                    approvalCommentMode === 'text'
                      ? 'bg-[#52525b] text-[#fafafa]'
                      : 'bg-transparent text-[#a1a1aa] hover:text-[#fafafa]'
                  }`}
                >
                  文本
                </button>
                <button
                  type="button"
                  onClick={() => setApprovalCommentMode('json')}
                  className={`px-2 py-0.5 text-[10px] rounded transition-colors border-0 cursor-pointer ${
                    approvalCommentMode === 'json'
                      ? 'bg-[#52525b] text-[#fafafa]'
                      : 'bg-transparent text-[#a1a1aa] hover:text-[#fafafa]'
                  }`}
                >
                  JSON
                </button>
              </div>
            </div>
            <textarea
              value={approvalComment}
              onChange={(e) => setApprovalComment(e.target.value)}
              placeholder={
                approvalCommentMode === 'json'
                  ? '{"score": 8, "note": "ok"}'
                  : approvalAction === 'reject'
                    ? '建议填写驳回原因（可选）'
                    : '审批意见（可选）'
              }
              rows={3}
              className={`w-full px-3 py-2 text-xs border border-[#27272a] bg-[#121214] text-[#fafafa] rounded-md focus:outline-none focus:border-[#1E5EFF] resize-none ${approvalCommentMode === 'json' ? 'font-mono' : ''}`}
            />
          </div>
        </div>
      </Modal>
    </div>
    </DataViewEnhanceProvider>
  )
}

/* ─── 子组件 ─── */

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

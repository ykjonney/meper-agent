/**
 * Task board card — 单卡片组件（看板列表中的任务单元）。
 *
 * 布局：
 * - 左侧 3px 状态色条（style.accent）
 * - 顶部：任务 ID（截断 + mono）+ 状态 Tag
 * - 次行：workflow_id（灰色）
 * - 进度区（仅 progress 存在时渲染）：「已执行 N 个节点」+ 4px 高脉动条
 *   - running 时动画推移
 *   - waiting_human 时静态满格（紫色）
 * - 等待审批（仅 waiting_human 且非终态）：「通过/驳回」两枚快捷按钮
 * - 底部：耗时 · 创建时间
 * - hover 时右上角浮出操作按钮（取消/重试/删除，按状态条件渲染）
 */
import { useState } from 'react'
import { Button, Modal, Segmented, Tag, Tooltip, message } from 'antd'
import {
  CheckOutlined,
  CloseCircleOutlined,
  StopOutlined,
  RedoOutlined,
  DeleteOutlined,
} from '@ant-design/icons'
import type { TaskSummary, NodeProgress, TaskStatusValue, CommentValue } from '../services/tasks-api'
import { TASK_STATUS_STYLES } from '../constants/task-status'

export interface TaskBoardCardProps {
  task: TaskSummary
  progress?: NodeProgress | null
  workflowName?: string
  onClick?: () => void
  onCancel?: (task: TaskSummary) => void
  onRetry?: (task: TaskSummary) => void
  onDelete?: (task: TaskSummary) => void
  onEdit?: (task: TaskSummary) => void
  onApprovalSubmit?: (task: TaskSummary, action: 'approve' | 'reject', comment: CommentValue) => void
  interveneLoading?: boolean
  deleteLoading?: boolean
}

// Brand accent for primary approval actions. Imported by the task detail
// drawer (tasks-page.tsx) so the two surfaces stay in sync.
export const APPROVAL_ACCENT = '#8B5CF6'

function formatDuration(startIso: string, endIso?: string | null) {
  if (!startIso) return '-'
  const start = new Date(startIso).getTime()
  const end = endIso ? new Date(endIso).getTime() : Date.now()
  const diff = end - start
  if (diff < 1000) return '<1s'
  if (diff < 60000) return `${Math.floor(diff / 1000)}s`
  return `${Math.floor(diff / 60000)}m ${Math.floor((diff % 60000) / 1000)}s`
}

function formatTime(iso: string) {
  if (!iso) return '-'
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return '刚刚'
  if (mins < 60) return `${mins} 分钟前`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours} 小时前`
  const days = Math.floor(hours / 24)
  return `${days} 天前`
}

export function TaskBoardCard({
  task,
  progress,
  workflowName,
  onClick,
  onCancel,
  onRetry,
  onDelete,
  onApprovalSubmit,
  interveneLoading = false,
  deleteLoading = false
}: TaskBoardCardProps) {
  const status: TaskStatusValue = task.status
  const style = TASK_STATUS_STYLES[status]
  const isRunning = status === 'running'
  const isWaitingHuman = status === 'waiting_human'
  const isPending = status === 'pending'
  const showProgress = !!progress && (isRunning || isWaitingHuman)
  const isTerminal = status === 'completed' || status === 'failed' || status === 'cancelled'

  // BOARD_CARD_QUICK_APPROVE / BOARD_CARD_QUICK_REJECT — 看板内嵌审批弹窗
  const [approvalModalOpen, setApprovalModalOpen] = useState(false)
  const [approvalAction, setApprovalAction] = useState<'approve' | 'reject' | null>(null)
  const [approvalComment, setApprovalComment] = useState('')
  // comment 输入模式：text 纯文本 / json 结构化（显式选择，避免隐式脆弱解析）
  const [commentMode, setCommentMode] = useState<'text' | 'json'>('text')

  const openApproval = (action: 'approve' | 'reject') => {
    setApprovalAction(action)
    setApprovalComment('')
    setCommentMode('text')
    setApprovalModalOpen(true)
  }

  const closeApproval = () => {
    if (interveneLoading) return
    setApprovalModalOpen(false)
    setApprovalAction(null)
    setApprovalComment('')
    setCommentMode('text')
  }

  const submitApproval = () => {
    if (!approvalAction || interveneLoading) return
    let comment: CommentValue
    if (commentMode === 'json') {
      // JSON 模式：解析校验，失败阻断提交
      const trimmed = approvalComment.trim()
      if (!trimmed) {
        // 空内容统一按无 comment 处理（传空字符串让后端归一化为 ""）
        comment = { type: 'json', value: '' }
      } else {
        let parsed: unknown
        try {
          parsed = JSON.parse(trimmed)
        } catch {
          message.error('JSON 格式错误，请检查输入')
          return
        }
        comment = { type: 'json', value: parsed }
      }
    } else {
      comment = { type: 'text', value: approvalComment }
    }
    onApprovalSubmit?.(task, approvalAction, comment)
    // Defer closing the modal until the mutation completes; the parent's
    // onSuccess / onError will trigger query invalidation and a re-render with
    // the task no longer in `waiting_human`, which hides the card. The parent
    // also flips `interveneLoading` back to false, at which point the user
    // (or the card's remount) can close the modal cleanly. We do not close
    // eagerly here because a failed mutation would leave the user thinking
    // their action succeeded.
  }

  return (
    <div
      onClick={onClick}
      className="group relative bg-canvas rounded-lg border border-line hover:border-txt-muted hover:shadow-md transition-all duration-150 cursor-pointer overflow-hidden"
    >
      {/* 左侧 3px 状态色条 */}
      <div
        className="absolute left-0 top-0 bottom-0 w-[3px]"
        style={{ backgroundColor: style.accent }}
      />

      {/* hover 时右上角浮出的操作按钮组 */}
      <div className="absolute right-2 top-2 opacity-0 group-hover:opacity-100 transition-opacity duration-150 flex items-center gap-0.5 bg-canvas/90 backdrop-blur-sm rounded-md px-1 py-0.5 shadow-sm border border-line-2 z-10">
        {(isRunning || (isPending && onCancel)) && onCancel && (
          <Tooltip title={isPending ? '取消执行' : '取消'}>
            <button
              onClick={(e) => { e.stopPropagation(); onCancel(task) }}
              disabled={interveneLoading}
              className="border-0 bg-transparent w-6 h-6 flex items-center justify-center rounded text-txt-muted hover:text-[#EF4444] hover:bg-surface-muted transition-colors text-xs disabled:opacity-40"
            ><StopOutlined /></button>
          </Tooltip>
        )}
        {status === 'failed' && onRetry && (
          <Tooltip title="重试">
            <button
              onClick={(e) => { e.stopPropagation(); onRetry(task) }}
              disabled={interveneLoading}
              className="border-0 bg-transparent w-6 h-6 flex items-center justify-center rounded text-txt-muted hover:text-primary hover:bg-surface-muted transition-colors text-xs disabled:opacity-40"
            ><RedoOutlined /></button>
          </Tooltip>
        )}
        {isTerminal && onDelete && (
          <Tooltip title="删除">
            <button
              onClick={(e) => { e.stopPropagation(); onDelete(task) }}
              disabled={deleteLoading}
              className="border-0 bg-transparent w-6 h-6 flex items-center justify-center rounded text-txt-muted hover:text-[#EF4444] hover:bg-surface-muted transition-colors text-xs disabled:opacity-40"
            ><DeleteOutlined /></button>
          </Tooltip>
        )}
      </div>

      <div className="pl-3 pr-3 py-2.5">
        {/* 顶部：任务 ID（截断 mono）+ 状态 Tag */}
        <div className="flex items-center justify-between gap-2 mb-1.5">
          <span className="text-[11px] font-mono text-txt-2 truncate flex-1 min-w-0">
            {task.id}
          </span>
          <Tag
            className="!m-0 !inline-flex !items-center !gap-1 !px-1.5 !py-0 !text-[10px] !rounded !border-0 !shrink-0"
            style={{ color: style.color, background: style.bg }}
          >
            <span>{style.icon}</span>
            {style.label}
          </Tag>
        </div>

        {/* 次行：工作流名称（灰色） */}
        <div className="text-xs text-txt-3 truncate mb-2 flex items-center gap-1">
          <span className="truncate">{workflowName ?? task.workflow_id}</span>
        </div>

        {/* 进度区（仅 progress 存在且 running/waiting_human 时渲染） */}
        {showProgress && progress && (
          <div className="mb-2">
            <div className="text-[10px] text-txt-muted mb-1 flex items-center gap-1">
              <span>已执行 {progress.completedCount} 个节点</span>
              {progress.currentNodeType && (
                <span className="text-txt-muted">·</span>
              )}
              {progress.currentNodeType && (
                <span className="truncate" style={{ color: style.color }}>
                  {progress.currentNodeType}
                </span>
              )}
            </div>
            {/* 4px 高脉动条：running 动画推移，waiting_human 静态满格 */}
            <div className="h-1 w-full rounded-full overflow-hidden" style={{ background: `${style.accent}22` }}>
              {isRunning ? (
                <div
                  className="h-full rounded-full"
                  style={{
                    width: '40%',
                    backgroundColor: style.accent,
                    animation: 'task-pulse-slide 1.6s ease-in-out infinite',
                  }}
                />
              ) : (
                <div
                  className="h-full rounded-full"
                  style={{ width: '100%', backgroundColor: style.accent }}
                />
              )}
            </div>
          </div>
        )}

        {/* 等待审批快捷入口（仅 waiting_human 且非终态时显示） */}
        {isWaitingHuman && !isTerminal && onApprovalSubmit && (
          <div
            className="flex items-center gap-1.5 mb-2"
            onClick={(e) => e.stopPropagation()}
          >
            <Button
              type="primary"
              size="small"
              icon={<CheckOutlined />}
              onClick={() => openApproval('approve')}
              loading={interveneLoading}
              style={{ backgroundColor: APPROVAL_ACCENT, borderColor: APPROVAL_ACCENT }}
            >
              通过
            </Button>
            <Button
              danger
              size="small"
              icon={<CloseCircleOutlined />}
              onClick={() => openApproval('reject')}
              loading={interveneLoading}
            >
              驳回
            </Button>
          </div>
        )}

        {/* 底部：耗时 · 创建时间 */}
        <div className="flex items-center justify-between text-[10px] text-txt-muted">
          <span>{formatDuration(task.created_at, task.updated_at)}</span>
          <span>{formatTime(task.created_at)}</span>
        </div>
      </div>

      {/* 脉动动画 keyframes（注入一次即可，重复无害） */}
      <style>{`
        @keyframes task-pulse-slide {
          0% { transform: translateX(-100%); width: 40%; }
          50% { transform: translateX(150%); width: 60%; }
          100% { transform: translateX(300%); width: 40%; }
        }
      `}</style>

      {/* ApprovalModal：看板内嵌审批弹窗，提交后由父级（tasks-page）统一调 interveneMutation */}
      <Modal
        title={approvalAction === 'reject' ? '驳回审批' : '通过审批'}
        open={approvalModalOpen}
        onCancel={closeApproval}
        onOk={submitApproval}
        okText="确认"
        cancelText="取消"
        confirmLoading={interveneLoading}
        okButtonProps={{
          danger: approvalAction === 'reject',
          style:
            approvalAction === 'approve'
              ? { backgroundColor: '#8B5CF6', borderColor: '#8B5CF6' }
              : undefined,
        }}
        destroyOnClose
      >
        <div className="py-2 space-y-3">
          {/* 审核信息：审批人在同一界面看到要审什么，再做通过/驳回决策 */}
          {(() => {
            const ctx = task.checkpoint?.human_context
            if (!ctx) return null
            return (
              <div className="border border-line rounded-lg p-3 bg-[#F8FAFC]">
                {ctx.title && (
                  <div className="text-sm font-medium text-[#0F172A] mb-1.5">{ctx.title}</div>
                )}
                {ctx.description && (
                  <div className="text-xs text-[#475569] whitespace-pre-wrap break-words leading-relaxed">
                    {ctx.description}
                  </div>
                )}
                {!ctx.title && !ctx.description && (
                  <div className="text-xs text-[#94A3B8] italic">该审批节点未配置说明</div>
                )}
              </div>
            )
          })()}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="block text-sm text-[#0F172A]">comment（可选）</label>
            <Segmented
              size="small"
              value={commentMode}
              onChange={(val) => setCommentMode(val as 'text' | 'json')}
              options={[
                { label: '文本', value: 'text' },
                { label: 'JSON', value: 'json' },
              ]}
            />
          </div>
          <textarea
            value={approvalComment}
            onChange={(e) => setApprovalComment(e.target.value)}
            placeholder={
              commentMode === 'json'
                ? '{"score": 8, "note": "ok"}'
                : approvalAction === 'reject'
                  ? '建议填写驳回原因（可选）'
                  : '审批意见（可选）'
            }
            rows={3}
            className="w-full px-3 py-2 text-sm border border-line rounded-md focus:outline-none focus:border-txt-muted resize-none font-mono"
          />
          </div>
        </div>
      </Modal>
    </div>
  )
}

export default TaskBoardCard

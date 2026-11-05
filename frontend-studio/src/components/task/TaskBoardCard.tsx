/**
 * TaskBoardCard — 看板单卡片组件（任务协作看板中的任务单元）。
 *
 * 布局（v3.2 Workbench，规范 §4.2 实体卡节奏）：
 * - 左缘 2px 状态 tick（toneVar；运行态呼吸）
 * - 顶部：工作流名称（主标题）+ 状态 pill（点+词双通道）
 * - meta 行：时间戳 + 创建者（mono；内部 ID 不上卡片，规范 §5.3）
 * - 进度区（仅 progress 存在且 running/waiting_human 时渲染）：
 *   「已执行 N 个节点」+ 4px 高脉动条（running 动画推移 / waiting_human 满格）
 * - 等待审批（仅 waiting_human 且非终态）：「通过/驳回」两枚快捷按钮
 * - 底部：耗时 · 相对时间
 * - hover 时右上角浮出操作按钮（取消/重试/删除，按状态条件渲染）
 * - 整卡 onClick → 打开详情
 */
import { useState } from 'react'
import { RotateCcw, Trash2, Ban, Undo2 } from 'lucide-react'
import type { TaskSummary, NodeProgress, TaskStatusValue, CommentValue } from '../../services/tasks-api'
import { TASK_STATUS_STYLES, toneVar } from '../../constants/task-status'
import { Modal, Tooltip } from '../ui'
import { toast } from '../ui/toast'
import { formatTimeRelative, formatTimeShort } from '../../lib/formatTime'

/** 审批主色（通过按钮），与详情抽屉保持一致（v3.2：品牌蓝） */
export const APPROVAL_ACCENT = 'var(--color-brand)'

export interface TaskBoardCardProps {
  task: TaskSummary
  progress?: NodeProgress | null
  workflowName?: string
  /** 创作者展示名（已由父级解析为可读 username） */
  creatorName?: string
  /** 任务来源：定时（trigger_id 命中）| 手动（默认）——设计稿 src-tag */
  sourceTag?: 'cron' | 'manual'
  onClick?: () => void
  onCancel?: (task: TaskSummary) => void
  onRetry?: (task: TaskSummary) => void
  onDelete?: (task: TaskSummary) => void
  /** 看板内嵌审批：交由父级统一调 interveneMutation */
  onApprovalSubmit?: (task: TaskSummary, action: 'approve' | 'reject', comment: CommentValue) => void
  /** 退回重跑：上抛给父级打开共享 RewindModal（卡片零逻辑） */
  onRewind?: (task: TaskSummary) => void
  interveneLoading?: boolean
  deleteLoading?: boolean
}

/** 耗时：start → end（end 为空时取 now），毫秒差转人类可读 */
function formatDuration(startIso: string, endIso?: string | null): string {
  if (!startIso) return '-'
  const start = new Date(startIso).getTime()
  const end = endIso ? new Date(endIso).getTime() : Date.now()
  const diff = end - start
  if (diff < 0) return '-'
  if (diff < 1000) return '<1s'
  if (diff < 60000) return `${Math.floor(diff / 1000)}s`
  return `${Math.floor(diff / 60000)}m ${Math.floor((diff % 60000) / 1000)}s`
}

export function TaskBoardCard({
  task,
  progress,
  workflowName,
  creatorName,
  sourceTag = 'manual',
  onClick,
  onCancel,
  onRetry,
  onDelete,
  onApprovalSubmit,
  onRewind,
  interveneLoading = false,
  deleteLoading = false,
}: TaskBoardCardProps) {
  const status: TaskStatusValue = task.status
  const style = TASK_STATUS_STYLES[status]
  const isRunning = status === 'running'
  const isWaitingHuman = status === 'waiting_human'
  const showProgress = !!progress && (isRunning || isWaitingHuman)
  const isFail = status === 'failed'
  const isTerminal = status === 'completed' || status === 'failed' || status === 'cancelled'

  // 看板内嵌审批弹窗
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
    onApprovalSubmit?.(task, approvalAction, comment)
    // 不立即关闭：等父级 mutation 完成后任务状态变更，卡片消失；失败时 loading 复位可重试。
  }

  // 执行者首字彩块：与 AgentSpace ENT_COLORS 同板，按创建者名恒定取色
  const ENT_COLORS = ['#4A6CF7', '#8B5CF6', '#EC4899', '#14B8A6', '#F59E0B', '#22C55E'];
  const avaChar = (creatorName ?? task.created_by ?? '·').trim().slice(0, 1).toUpperCase() || '·';

  // 等待卡内容摘要：checkpoint.human_context（审批计划/提问）
  const ctx = task.checkpoint?.human_context;
  const errMsg = task.error?.error_message ?? '';

  return (
    <div
      onClick={onClick}
      className={`group relative bg-panel border border-line rounded-[11px] px-[13px] py-3 cursor-pointer transition-all duration-150 hover:border-line-strong hover:shadow-[var(--shadow-card)] ${
        isWaitingHuman ? 'border-l-[3px] border-l-sig-wait' : isFail ? 'border-l-[3px] border-l-sig-fail' : ''
      }`}
    >
      {/* hover 浮出操作（取消 / 重试 / 删除——按状态条件渲染） */}
      <div className="absolute right-1.5 top-1.5 opacity-0 group-hover:opacity-100 transition-opacity duration-150 flex items-center gap-0.5 bg-well/90 backdrop-blur-sm rounded-md px-0.5 py-0.5 shadow-sm border border-line z-10">
        {isRunning && onCancel && (
          <Tooltip title="取消">
            <button
              onClick={(e) => { e.stopPropagation(); onCancel(task) }}
              disabled={interveneLoading}
              className="border-0 bg-transparent w-5 h-5 flex items-center justify-center rounded text-ink-dim hover:text-sig-fail hover:bg-line transition-colors disabled:opacity-40"
            >
              <Ban size={12} />
            </button>
          </Tooltip>
        )}
        {isFail && onRetry && (
          <Tooltip title="重试">
            <button
              onClick={(e) => { e.stopPropagation(); onRetry(task) }}
              disabled={interveneLoading}
              className="border-0 bg-transparent w-5 h-5 flex items-center justify-center rounded text-ink-dim hover:text-brand hover:bg-line transition-colors disabled:opacity-40"
            >
              <RotateCcw size={12} />
            </button>
          </Tooltip>
        )}
        {isTerminal && onDelete && (
          <Tooltip title="删除">
            <button
              onClick={(e) => { e.stopPropagation(); onDelete(task) }}
              disabled={deleteLoading}
              className="border-0 bg-transparent w-5 h-5 flex items-center justify-center rounded text-ink-dim hover:text-sig-fail hover:bg-line transition-colors disabled:opacity-40"
            >
              <Trash2 size={12} />
            </button>
          </Tooltip>
        )}
      </div>

      {/* 标题 */}
      <div className="text-[13px] font-bold text-ink leading-[1.4] pr-5">
        {workflowName ?? task.workflow_id}
      </div>

      {/* 来源行（设计稿 t-src）：src-tag + 执行者 */}
      <div className="flex items-center gap-1.5 mt-1 font-mono text-[10px] text-ink-faint flex-wrap">
        {sourceTag === 'cron' ? (
          <span className="inline-flex items-center gap-[3px] text-[9.5px] px-1.5 py-[1.5px] rounded-[5px] bg-sig-wait-soft text-sig-wait not-italic">⏱ 定时</span>
        ) : (
          <span className="inline-flex items-center text-[9.5px] px-1.5 py-[1.5px] rounded-[5px] bg-raise text-ink-dim">手动</span>
        )}
        {creatorName && <span>{creatorName}</span>}
      </div>

      {/* 等待卡：审批内容摘要（计划 / 提问） */}
      {isWaitingHuman && ctx && (ctx.title || ctx.description) && (
        <div className="mt-[9px] px-2.5 py-2 bg-raise rounded-lg text-[11px] text-ink-dim leading-[1.6]">
          {ctx.title && <div className="font-medium text-ink-soft">{ctx.title}</div>}
          {ctx.description && <div className="whitespace-pre-wrap">{ctx.description}</div>}
        </div>
      )}

      {/* 进行中：t-node 进度行（光标动画 + 当前节点 + 已完成步数） */}
      {showProgress && progress && (
        <div className="flex items-center gap-[7px] mt-[9px] px-[9px] py-[7px] bg-raise rounded-lg">
          <span className={`w-[2px] h-3 rounded-sm shrink-0 ${isRunning ? 'animate-pulse' : ''} bg-brand`} />
          <span className="text-[11px] text-ink-soft truncate flex-1">
            {progress.currentNodeType ?? (isRunning ? '执行中' : '等待人工输入')}
          </span>
          <span className="ml-auto font-mono text-[10px] text-brand font-bold shrink-0">{progress.completedCount} 步</span>
        </div>
      )}

      {/* 失败卡：失败原因（设计稿 fail-reason） */}
      {isFail && errMsg && (
        <div className="mt-[9px] px-2.5 py-2 bg-sig-fail-soft rounded-lg text-[11px] text-sig-fail truncate">
          {errMsg}
        </div>
      )}

      {/* 等待审批操作（设计稿 t-act） */}
      {isWaitingHuman && !isTerminal && onApprovalSubmit && (
        <div className="flex gap-[7px] mt-[9px]" onClick={(e) => e.stopPropagation()}>
          {onRewind && (
            <button
              onClick={() => onRewind(task)}
              disabled={interveneLoading}
              title="退回重跑"
              className="px-3 py-1.5 rounded-[7px] bg-transparent border border-line-strong text-ink-dim text-[11.5px] font-semibold cursor-pointer disabled:opacity-50 shrink-0"
            >
              <Undo2 size={12} />
            </button>
          )}
          <button
            onClick={() => openApproval('reject')}
            disabled={interveneLoading}
            className="flex-1 py-1.5 rounded-[7px] bg-transparent border border-line-strong text-ink-dim text-[11.5px] font-semibold cursor-pointer disabled:opacity-50"
          >
            驳回
          </button>
          <button
            onClick={() => openApproval('approve')}
            disabled={interveneLoading}
            className="flex-1 py-1.5 rounded-[7px] bg-brand text-white border-0 text-[11.5px] font-bold cursor-pointer disabled:opacity-50"
          >
            批准并继续
          </button>
        </div>
      )}

      {/* foot meta：状态相关时间 · 耗时 / tokens */}
      <div className="flex items-center gap-2 mt-[9px] font-mono text-[10px] text-ink-faint">
        {isWaitingHuman ? (
          <span className="text-sig-wait">等待 {formatTimeRelative(task.updated_at || task.created_at)}</span>
        ) : isRunning ? (
          <span>已 {formatDuration(task.created_at)}</span>
        ) : (
          <span>
            {formatTimeShort(task.created_at)}
            {task.updated_at && task.updated_at !== task.created_at && <span> · {formatDuration(task.created_at, task.updated_at)}</span>}
          </span>
        )}
        {!!task.total_tokens && task.total_tokens > 0 && (
          <span className="ml-auto">{task.total_tokens >= 1000 ? `${(task.total_tokens / 1000).toFixed(1)}k` : task.total_tokens} tokens</span>
        )}
      </div>

      {/* 审批弹窗：看板内嵌审批，提交后由父级统一调 interveneMutation */}
      <Modal
        title={approvalAction === 'reject' ? '驳回审批' : '通过审批'}
        open={approvalModalOpen}
        onCancel={closeApproval}
        onOk={submitApproval}
        okText="确认"
        cancelText="取消"
        okButtonProps={{ disabled: interveneLoading }}
      >
        <div className="py-2 space-y-3">
          {ctx && (ctx.title || ctx.description) && (
            <div className="border border-line rounded-lg p-3 bg-panel">
              {ctx.title && <div className="text-sm font-medium text-ink mb-1.5">{ctx.title}</div>}
              {ctx.description && (
                <div className="text-xs text-ink-dim whitespace-pre-wrap break-words leading-relaxed">{ctx.description}</div>
              )}
            </div>
          )}
          <div>
            <div className="flex items-center justify-between mb-1.5">
              <label className="block text-xs text-ink-dim">comment（可选）</label>
              <div className="flex items-center gap-0.5 bg-raise rounded-md p-0.5">
                <button type="button" onClick={() => setCommentMode('text')}
                  className={`px-2 py-0.5 text-[11px] rounded transition-colors border-0 cursor-pointer ${
                    commentMode === 'text' ? 'bg-line-strong text-ink' : 'bg-transparent text-ink-dim hover:text-ink'
                  }`}>
                  文本
                </button>
                <button type="button" onClick={() => setCommentMode('json')}
                  className={`px-2 py-0.5 text-[11px] rounded transition-colors border-0 cursor-pointer ${
                    commentMode === 'json' ? 'bg-line-strong text-ink' : 'bg-transparent text-ink-dim hover:text-ink'
                  }`}>
                  JSON
                </button>
              </div>
            </div>
            <textarea
              value={approvalComment}
              onChange={(e) => setApprovalComment(e.target.value)}
              placeholder={commentMode === 'json' ? '{"score": 8, "note": "ok"}' : approvalAction === 'reject' ? '建议填写驳回原因（可选）' : '审批意见（可选）'}
              rows={3}
              className={`w-full px-3 py-2 text-xs border border-line bg-page text-ink rounded-md focus:outline-none focus:border-brand resize-none ${commentMode === 'json' ? 'font-mono' : ''}`}
            />
          </div>
        </div>
      </Modal>
    </div>
  );
}

export default TaskBoardCard

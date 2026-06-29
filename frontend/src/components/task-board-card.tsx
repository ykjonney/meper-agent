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
 * - 底部：耗时 · 创建时间
 * - hover 时右上角浮出操作按钮（取消/重试/删除，按状态条件渲染）
 */
import { Tag, Tooltip } from 'antd'
import {
  StopOutlined,
  RedoOutlined,
  DeleteOutlined,
} from '@ant-design/icons'
import type { TaskSummary, NodeProgress, TaskStatusValue } from '../services/tasks-api'
import { TASK_STATUS_STYLES } from '../constants/task-status'

export interface TaskBoardCardProps {
  task: TaskSummary
  progress?: NodeProgress | null
  workflowName?: string
  onClick?: () => void
  onCancel?: (task: TaskSummary) => void
  onRetry?: (task: TaskSummary) => void
  onDelete?: (task: TaskSummary) => void
  interveneLoading?: boolean
  deleteLoading?: boolean
}

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
  interveneLoading = false,
  deleteLoading = false,
}: TaskBoardCardProps) {
  const status: TaskStatusValue = task.status
  const style = TASK_STATUS_STYLES[status]
  const isRunning = status === 'running'
  const isWaitingHuman = status === 'waiting_human'
  const showProgress = !!progress && (isRunning || isWaitingHuman)
  const isTerminal = status === 'completed' || status === 'failed' || status === 'cancelled'

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
        {isRunning && onCancel && (
          <Tooltip title="取消">
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
        <div className="text-xs text-txt-3 truncate mb-2">
          {workflowName ?? task.workflow_id}
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
    </div>
  )
}

export default TaskBoardCard

/**
 * Task board column — 单列组件（看板中的一列）。
 *
 * 布局：
 * - 固定宽度 min-w-[320px] flex-shrink-0，列高撑满
 * - 列头：状态色背景（10% 透明度）+ 圆点（running 脉动）+ 状态名 + 数量 <Badge>
 * - 卡片区：flex-1 overflow-y-auto，空时显示 antd <Empty>
 */
import { Badge, Empty, Spin } from 'antd'
import type { TaskSummary, NodeProgress } from '../services/tasks-api'
import type { TaskStatusStyle } from '../constants/task-status'
import { TaskBoardCard } from './task-board-card'

export interface TaskBoardColumnProps {
  style: TaskStatusStyle
  tasks: TaskSummary[]
  progressMap: Record<string, NodeProgress | null | undefined>
  workflowNameMap: Record<string, string>
  loading?: boolean
  onCardClick?: (task: TaskSummary) => void
  onCancel?: (task: TaskSummary) => void
  onRetry?: (task: TaskSummary) => void
  onDelete?: (task: TaskSummary) => void
  onApprovalSubmit?: (task: TaskSummary, action: 'approve' | 'reject', comment: string) => void
  interveneLoading?: boolean
  deleteLoading?: boolean
}

export function TaskBoardColumn({
  style,
  tasks,
  progressMap,
  workflowNameMap,
  loading = false,
  onCardClick,
  onCancel,
  onRetry,
  onDelete,
  onApprovalSubmit,
  interveneLoading = false,
  deleteLoading = false,
}: TaskBoardColumnProps) {
  return (
    <div className="min-w-[300px] w-[300px] flex-shrink-0 flex flex-col bg-surface rounded-xl border border-line">
      {/* 列头 */}
      <div
        className="flex items-center justify-between gap-2 px-3 py-2.5 rounded-t-xl border-b border-line"
        style={{ background: style.bg }}
      >
        <div className="flex items-center gap-2 min-w-0">
          {/* 圆点：running 脉动 */}
          <span
            className={`w-2 h-2 rounded-full shrink-0 ${style.pulse ? 'animate-pulse' : ''}`}
            style={{ backgroundColor: style.accent }}
          />
          <span
            className="text-sm font-medium truncate"
            style={{ color: style.color }}
          >
            {style.icon} {style.label}
          </span>
        </div>
        <Badge
          count={tasks.length}
          style={{
            backgroundColor: style.accent,
            color: '#fff',
            fontSize: 11,
            minWidth: 20,
            height: 20,
            lineHeight: '20px',
            borderRadius: 10,
          }}
        />
      </div>

      {/* 卡片区 */}
      <div className="flex-1 overflow-y-auto p-2 space-y-2 min-h-[120px]">
        {loading ? (
          <div className="flex items-center justify-center py-8">
            <Spin size="small" />
          </div>
        ) : tasks.length === 0 ? (
          <div className="flex items-center justify-center py-8">
            <Empty
              description={<span className="text-xs text-txt-muted">暂无</span>}
              image={Empty.PRESENTED_IMAGE_SIMPLE}
            />
          </div>
        ) : (
          tasks.map((task) => (
            <TaskBoardCard
              key={task.id}
              task={task}
              progress={progressMap[task.id]}
              workflowName={workflowNameMap[task.workflow_id]}
              onClick={() => onCardClick?.(task)}
              onCancel={onCancel}
              onRetry={onRetry}
              onDelete={onDelete}
              onApprovalSubmit={onApprovalSubmit}
              interveneLoading={interveneLoading}
              deleteLoading={deleteLoading}
            />
          ))
        )}
      </div>
    </div>
  )
}

export default TaskBoardColumn

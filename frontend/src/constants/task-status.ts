/**
 * Shared task status style constants for the task board.
 *
 * 6 状态色系（严格按主人指定）：
 * - pending 琥珀 #F59E0B
 * - running 蓝   #2563EB
 * - waiting_human 紫 #8B5CF6
 * - completed 绿 #10B981
 * - failed 红    #EF4444
 * - cancelled 灰 #94A3B8
 *
 * accent 为列头与卡片左侧色条主色；bg 为列头背景（10% 透明度近似）。
 */
import type { TaskStatusValue } from '../services/tasks-api'

export interface TaskStatusStyle {
  /** 中文标签 */
  label: string
  /** 主色（文字/色条/圆点） */
  color: string
  /** 列头浅色背景 */
  bg: string
  /** 列头与卡片左侧色条主色 */
  accent: string
  /** emoji 图标（避免依赖额外 icon 库） */
  icon: string
  /** running 时为 true，列头圆点与进度条启用脉动 */
  pulse?: boolean
}

export const TASK_STATUS_STYLES: Record<TaskStatusValue, TaskStatusStyle> = {
  pending: { label: '待执行', color: '#F59E0B', bg: '#FEF3C7', accent: '#F59E0B', icon: '🕒' },
  running: { label: '执行中', color: '#2563EB', bg: '#DBEAFE', accent: '#2563EB', icon: '⚡', pulse: true },
  waiting_human: { label: '等待人工', color: '#8B5CF6', bg: '#EDE9FE', accent: '#8B5CF6', icon: '🧑‍⚖️' },
  completed: { label: '已完成', color: '#10B981', bg: '#D1FAE5', accent: '#10B981', icon: '✅' },
  failed: { label: '已失败', color: '#EF4444', bg: '#FEE2E2', accent: '#EF4444', icon: '❌' },
  cancelled: { label: '已取消', color: '#94A3B8', bg: '#F1F5F9', accent: '#94A3B8', icon: '⏹️' },
}

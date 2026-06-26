/**
 * Shared task status style constants for the studio task board.
 *
 * 6 状态色系（对齐旧版 frontend/src/constants/task-status.ts，适配 studio 暗色风）：
 * - pending 待执行     琥珀 #F59E0B
 * - running 执行中     蓝   #3B82F6
 * - waiting_human 等待 紫   #8B5CF6
 * - completed 已完成   绿   #10B981
 * - failed 已失败      红   #EF4444
 * - cancelled 已取消   灰   #94A3B8
 *
 * accent 为列头与卡片左侧色条主色；bg 为列头浅色背景（暗色低透明度近似）。
 */
import type { TaskStatusValue } from '../services/tasks-api'

export interface TaskStatusStyle {
  /** 中文标签 */
  label: string
  /** 主色（文字/色条/圆点） */
  color: string
  /** 列头浅色背景（暗色用低透明度 hex） */
  bg: string
  /** 列头与卡片左侧色条主色 */
  accent: string
  /** lucide 图标名称（在组件内映射为 lucide 组件） */
  icon: 'clock' | 'zap' | 'gavel' | 'check' | 'x' | 'minus'
  /** running 时为 true，列头圆点与进度条启用脉动 */
  pulse?: boolean
}

export const TASK_STATUS_STYLES: Record<TaskStatusValue, TaskStatusStyle> = {
  pending: { label: '待执行', color: '#F59E0B', bg: 'rgba(245,158,11,0.10)', accent: '#F59E0B', icon: 'clock' },
  running: { label: '执行中', color: '#3B82F6', bg: 'rgba(59,130,246,0.10)', accent: '#3B82F6', icon: 'zap', pulse: true },
  waiting_human: { label: '等待人工', color: '#8B5CF6', bg: 'rgba(139,92,246,0.10)', accent: '#8B5CF6', icon: 'gavel' },
  completed: { label: '已完成', color: '#10B981', bg: 'rgba(16,185,129,0.10)', accent: '#10B981', icon: 'check' },
  failed: { label: '已失败', color: '#EF4444', bg: 'rgba(239,68,68,0.10)', accent: '#EF4444', icon: 'x' },
  cancelled: { label: '已取消', color: '#94A3B8', bg: 'rgba(148,163,184,0.10)', accent: '#94A3B8', icon: 'minus' },
}

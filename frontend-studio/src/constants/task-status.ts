/**
 * Shared task status style constants for the studio task board.
 *
 * v3.2 Workbench（规范 §1.3）：状态信号收敛为四语义 tone，色彩经 CSS 变量
 * 引用 index.css 的 token（--color-sig-* / --color-ink-*），两主题自动适配。
 * 彩色只属于"需要注意"的状态：
 * - ok   正向·运行中（绿 + 呼吸）
 * - wait 需要注意·等待人工（琥珀）
 * - fail 异常·失败（红）
 * - mute 中性·待执行/已完成/已取消（灰，终态降噪）
 *
 * 消费方通过 toneVar(tone) 取 CSS 变量名（内联样式场景），或直接使用
 * af-dot-* / af-pill-* / af-tick-* 工具类（见 index.css）。
 */
import type { TaskStatusValue } from '../services/tasks-api'

export type StatusTone = 'ok' | 'wait' | 'fail' | 'mute'

export interface TaskStatusStyle {
  /** 中文标签 */
  label: string
  /** 语义信号 tone → CSS 变量 --color-sig-ok / -wait / -fail / 中性灰 */
  tone: StatusTone
  /** lucide 图标名称（在组件内映射为 lucide 组件） */
  icon: 'clock' | 'zap' | 'gavel' | 'check' | 'x' | 'minus'
  /** 运行中为 true：状态点/进度启用呼吸脉动 */
  pulse?: boolean
}

/** tone → token CSS 变量值（内联 style 场景用；mute 映射到 ink-faint）。 */
export function toneVar(tone: StatusTone): string {
  if (tone === 'ok') return 'var(--color-sig-ok)'
  if (tone === 'wait') return 'var(--color-sig-wait)'
  if (tone === 'fail') return 'var(--color-sig-fail)'
  return 'var(--color-ink-faint)'
}

/** tone → soft 底（pill/高亮底色场景）。 */
export function toneSoftVar(tone: StatusTone): string {
  if (tone === 'ok') return 'var(--color-sig-ok-soft)'
  if (tone === 'wait') return 'var(--color-sig-wait-soft)'
  if (tone === 'fail') return 'var(--color-sig-fail-soft)'
  return 'var(--color-raise)'
}

export const TASK_STATUS_STYLES: Record<TaskStatusValue, TaskStatusStyle> = {
  pending: { label: '待执行', tone: 'mute', icon: 'clock' },
  running: { label: '执行中', tone: 'ok', icon: 'zap', pulse: true },
  waiting_human: { label: '等待人工', tone: 'wait', icon: 'gavel' },
  completed: { label: '已完成', tone: 'mute', icon: 'check' },
  failed: { label: '已失败', tone: 'fail', icon: 'x' },
  cancelled: { label: '已取消', tone: 'mute', icon: 'minus' },
}

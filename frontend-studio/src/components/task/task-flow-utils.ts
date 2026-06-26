/**
 * task-flow-utils — 执行流程可视化共享工具。
 *
 * TaskFlowTimeline（阶段时间线）与 TaskFlowGraph（xyflow 节点图）共用：
 * - 节点执行状态推导
 * - 节点类型 → 中文标签 / 颜色
 *
 * 节点 id（node_id）是 timeline 事件、variables、checkpoint 之间的 join key，
 * 与 WorkflowDesigner 的 WorkflowNode.node_id 同源。
 */
import type { TimelineEvent } from '../../services/tasks-api'

/** 单个节点的执行状态（用于徽标颜色 / 图标 / 节点高亮） */
export type NodeExecState = 'completed' | 'executing' | 'failed' | 'waiting' | 'pending'

/** 执行状态 → 主色（与 TaskFlowTimeline 的 STATE_META 对齐） */
export const STATE_COLOR: Record<NodeExecState, string> = {
  completed: '#10B981',
  executing: '#3B82F6',
  failed: '#EF4444',
  waiting: '#8B5CF6',
  pending: '#71717a',
}

/** 节点类型 → 中文标签（与 NODE_TYPE_LABEL 对齐） */
export const NODE_TYPE_LABEL: Record<string, string> = {
  start: '输入节点', end: '输出节点', agent: 'Agent 节点',
  tool: '工具节点', gateway: '网关节点', parallel: '并行节点', human: '人工审批节点',
}

/**
 * 从一个节点的相关 timeline 事件推导其执行状态。
 *
 * 规则（按优先级）：
 * 1. 有 node_failed → failed
 * 2. pausedAtThisNode（checkpoint.paused_at_node 命中）→ waiting（人工审批中）
 * 3. 有 node_complete → completed
 * 4. 有 node_start 但无 complete/failed → executing
 * 5. 否则 → pending
 */
export function getNodeExecState(events: TimelineEvent[], pausedAtThisNode: boolean): NodeExecState {
  const types = new Set(events.map((e) => e.event_type))
  if (types.has('node_failed')) return 'failed'
  if (pausedAtThisNode) return 'waiting'
  if (types.has('node_complete')) return 'completed'
  if (types.has('node_start')) return 'executing'
  return 'pending'
}

/** 阶段时间线用：一个节点的聚合信息 */
export interface NodeStageInfo {
  nodeId: string
  nodeType: string
  state: NodeExecState
  events: TimelineEvent[]
  duration?: string
  /** 节点标签（可选，来自事件 data.node_label） */
  label?: string
}

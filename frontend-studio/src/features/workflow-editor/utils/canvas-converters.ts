/**
 * WorkflowNode / WorkflowEdge ↔ @xyflow/react Node / Edge 互转函数。
 */
import type { Node, Edge } from '@xyflow/react'
import type { WorkflowNode, WorkflowEdge, NextNodeRef } from '../../../services/workflows-api'

/** xyflow 自定义节点的 data 类型 */
export interface WorkflowNodeData extends Record<string, unknown> {
  /** 原始 WorkflowNode */
  workflowNode: WorkflowNode
  /** 节点类型标签 */
  typeLabel: string
  /** 类型颜色 */
  typeColor: string
  /** 类型背景色 */
  typeBg: string
  /** 节点标签 */
  label: string
  /** 是否被选中 */
  isSelected?: boolean
}

/**
 * 将 WorkflowNode 数组转为 xyflow Node 数组。
 */
export function toXyflowNodes(
  workflowNodes: WorkflowNode[],
  selectedNodeId?: string | null,
): Node<WorkflowNodeData>[] {
  return workflowNodes.map((wn) => {
    const typeLabel = getTypeLabel(wn.type)
    const typeColor = getTypeColor(wn.type)
    const typeBg = getTypeBg(wn.type)
    return {
      id: wn.node_id,
      type: 'workflow',
      position: wn.position ?? { x: 0, y: 0 },
      data: {
        workflowNode: wn,
        typeLabel,
        typeColor,
        typeBg,
        label: wn.label || typeLabel,
        isSelected: wn.node_id === selectedNodeId,
      },
    }
  })
}

/**
 * 将 WorkflowEdge 数组转为 xyflow Edge 数组。
 */
export function toXyflowEdges(
  workflowEdges: WorkflowEdge[],
): Edge[] {
  return workflowEdges.map((we) => ({
    id: we.edge_id,
    source: we.source,
    target: we.target,
    label: we.label || undefined,
    type: 'default',
    animated: !!we.condition,
    style: we.condition
      ? { stroke: '#8B5CF6', strokeWidth: 1.2, borderRadius: 8 }
      : { stroke: '#94A3B8', strokeWidth: 0.8 },
    labelStyle: { fontSize: 10, color: '#64748B' },
    data: { workflowEdge: we },
  }))
}

/**
 * 将 xyflow Node 数组转回 WorkflowNode 数组。
 */
export function fromXyflowNodes(
  xyflowNodes: Node[],
): WorkflowNode[] {
  return xyflowNodes.map((xn) => {
    const data = xn.data as WorkflowNodeData
    return {
      ...data.workflowNode,
      position: { x: Math.round(xn.position.x), y: Math.round(xn.position.y) },
    }
  })
}

/* ─── 内联类型元数据（避免循环依赖） ─── */

const TYPE_META: Record<string, { label: string; color: string; bg: string }> = {
  start: { label: '开始', color: '#10B981', bg: '#D1FAE5' },
  end: { label: '结束', color: '#EF4444', bg: '#FEE2E2' },
  agent: { label: 'Agent', color: '#3B82F6', bg: '#DBEAFE' },
  tool: { label: '工具', color: '#F59E0B', bg: '#FEF3C7' },
  gateway: { label: '网关', color: '#8B5CF6', bg: '#EDE9FE' },
  parallel: { label: '并行', color: '#06B6D4', bg: '#CFFAFE' },
  human: { label: '人工审批', color: '#F97316', bg: '#FFF7ED' },
}

function getTypeLabel(type: string): string {
  return TYPE_META[type]?.label ?? type
}
function getTypeColor(type: string): string {
  return TYPE_META[type]?.color ?? '#64748B'
}
function getTypeBg(type: string): string {
  return TYPE_META[type]?.bg ?? '#F1F5F9'
}

/* ─── next_nodes → xyflow Edges（新路由方式） ─── */

/**
 * 从节点 config 中推导出 xyflow Edge 数组。
 *
 * 支持三种来源：
 * 1. 普通节点：config.next_nodes
 * 2. gateway 节点：config.conditions[].target + config.default_branch
 * 3. parallel 节点：config.branches[].start_node
 */
export function deriveXyflowEdgesFromNodes(nodes: WorkflowNode[]): Edge[] {
  const edges: Edge[] = []

  for (const node of nodes) {
    const config = (node.config ?? {}) as Record<string, unknown>
    const nodeType = node.type

    if (nodeType === 'gateway') {
      // gateway: conditions[].target + default_branch
      const conditions = config.conditions as Array<{ target?: string; expression?: string; label?: string }> | undefined
      if (conditions) {
        for (const cond of conditions) {
          if (cond.target) {
            edges.push(makeDerivedEdge(node.node_id, cond.target, cond.label ?? '', cond.expression))
          }
        }
      }
      const defaultBranch = config.default_branch as string | undefined
      if (defaultBranch) {
        edges.push(makeDerivedEdge(node.node_id, defaultBranch, '默认'))
      }
    } else if (nodeType === 'parallel') {
      // parallel: branches[].start_node
      const branches = config.branches as Array<{ start_node?: string; label?: string }> | undefined
      if (branches) {
        for (const branch of branches) {
          if (branch.start_node) {
            edges.push(makeDerivedEdge(node.node_id, branch.start_node, branch.label ?? ''))
          }
        }
      }
    } else {
      // 普通节点: config.next_nodes
      const nextNodes = config.next_nodes as NextNodeRef[] | undefined
      if (nextNodes) {
        for (const nxt of nextNodes) {
          edges.push(makeDerivedEdge(node.node_id, nxt.target, nxt.label ?? '', nxt.condition ?? undefined))
        }
      }
      // agent 节点额外派生 insufficient_branch（信息不足澄清分支，条件边样式）
      if (nodeType === 'agent') {
        const insufficient = config.insufficient_branch as string | undefined
        if (insufficient) {
          edges.push({
            ...makeDerivedEdge(node.node_id, insufficient, '信息不足', 'insufficient'),
            id: `e-${node.node_id}-${insufficient}-insufficient`,
          })
        }
      }
    }
  }

  return edges
}

/** 创建一条推导出的 xyflow Edge */
function makeDerivedEdge(
  source: string,
  target: string,
  label: string,
  condition?: string | null,
): Edge {
  const hasCondition = !!condition
  return {
    id: `e-${source}-${target}`,
    source,
    target,
    label: label || undefined,
    animated: hasCondition,
    selectable: true,
    deletable: true,
    className: hasCondition ? 'workflow-edge--condition' : undefined,
    labelStyle: hasCondition ? { fill: '#8B5CF6' } : undefined,
  }
}

/**
 * 拖线/删线时同步更新 source 节点的 config。
 *
 * gateway/parallel 的有效出边只能来自 conditions/branches（派生边也只渲染
 * 这两处）——拖线转新增条件/分支（默认值与配置面板一致），**不写
 * next_nodes**：派生边不渲染它们的 next_nodes，写了就是看不见且删不掉的
 * 幽灵引用，保存后在运行期被 DANGLING_NEXT_TARGET 校验拦下。
 * remove 时清完 conditions/branches 后 fall through 继续清 next_nodes，
 * 顺带回收历史版本可能写入的幽灵 next_nodes。
 */
export function syncEdgeChangesToNodes(
  action: 'add' | 'remove',
  nodes: WorkflowNode[],
  source: string,
  target: string,
  label?: string,
  condition?: string | null,
): WorkflowNode[] {
  return nodes.map((n) => {
    if (n.node_id !== source) return n
    const config = { ...(n.config ?? {}) } as Record<string, unknown>

    if (action === 'add') {
      // gateway 拖线 → 新增条件（默认值与 GatewayNodeConfig.addCondition 一致）
      if (n.type === 'gateway') {
        const conditions = [
          ...((config.conditions as Array<{
            target?: string
            expression?: string
            operator?: string
            expected?: boolean
          }>) ?? []),
        ]
        if (!conditions.some((c) => c.target === target)) {
          conditions.push({ expression: '', operator: '==', expected: true, target })
        }
        config.conditions = conditions
        return { ...n, config }
      }
      // parallel 拖线 → 新增分支
      if (n.type === 'parallel') {
        const branches = [
          ...((config.branches as Array<{ start_node?: string; label?: string }>) ?? []),
        ]
        if (!branches.some((b) => b.start_node === target)) {
          branches.push({ start_node: target, label: label ?? '' })
        }
        config.branches = branches
        return { ...n, config }
      }
    } else {
      // remove
      if (n.type === 'gateway' && Array.isArray(config.conditions)) {
        config.conditions = (config.conditions as Array<{ target?: string }>).filter(
          (c) => c.target !== target,
        )
        if (config.default_branch === target) {
          config.default_branch = ''
        }
        // 不 return——若历史版本拖线写入过幽灵 next_nodes，下方一并清掉
      }
      if (n.type === 'parallel' && Array.isArray(config.branches)) {
        config.branches = (config.branches as Array<{ start_node?: string }>).filter(
          (b) => b.start_node !== target,
        )
        // 不 return——同上，fall through 清幽灵 next_nodes
      }
      // agent: 删除信息不足分支边 → 清空 insufficient_branch（target 可能
      // 同时在 next_nodes 中，继续走下方 next_nodes 清理）
      if (n.type === 'agent' && config.insufficient_branch === target) {
        config.insufficient_branch = null
      }
    }

    // 普通节点（含 add 和 remove）：操作 next_nodes
    const nextNodes = [...((config.next_nodes as NextNodeRef[]) ?? [])]

    if (action === 'add') {
      // 避免重复
      if (!nextNodes.some((nn) => nn.target === target)) {
        nextNodes.push({ target, label: label ?? '', condition: condition ?? null })
      }
    } else {
      // remove
      const idx = nextNodes.findIndex((nn) => nn.target === target)
      if (idx >= 0) nextNodes.splice(idx, 1)
    }

    config.next_nodes = nextNodes
    return { ...n, config }
  })
}

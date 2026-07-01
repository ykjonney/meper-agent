/**
 * DAG 工具函数（从 nodes 推导拓扑关系，无需独立 edges）。
 */
import type { WorkflowNode, NextNodeRef } from '../../../services/workflows-api'
import { NODE_TYPE_CONFIGS } from './node-type-configs'

/**
 * 从所有节点构建"反向邻接表"——谁连向我。
 *
 * 支持：
 * - 普通节点：config.next_nodes[].target
 * - gateway：config.conditions[].target + config.default_branch
 * - parallel：config.branches[].start_node
 */
function buildReverseAdjacency(nodes: WorkflowNode[]): Map<string, string[]> {
  const rev = new Map<string, string[]>()
  for (const node of nodes) {
    const config = (node.config ?? {}) as Record<string, unknown>
    const targets: string[] = []

    if (node.type === 'gateway') {
      const conditions = config.conditions as Array<{ target?: string }> | undefined
      if (conditions) {
        for (const c of conditions) {
          if (c.target) targets.push(c.target)
        }
      }
      const def = config.default_branch as string | undefined
      if (def) targets.push(def)
    } else if (node.type === 'parallel') {
      const branches = config.branches as Array<{ start_node?: string }> | undefined
      if (branches) {
        for (const b of branches) {
          if (b.start_node) targets.push(b.start_node)
        }
      }
    } else {
      const nextNodes = config.next_nodes as NextNodeRef[] | undefined
      if (nextNodes) {
        for (const nn of nextNodes) {
          if (nn.target) targets.push(nn.target)
        }
      }
    }

    for (const t of targets) {
      rev.set(t, [...(rev.get(t) ?? []), node.node_id])
    }
  }
  return rev
}

/**
 * 计算指定节点的所有上游节点（拓扑顺序）。
 *
 * 从 nodes 推导关系，不再依赖独立的 edges 数组。
 */
export function computeUpstreamNodes(
  nodeId: string,
  nodes: WorkflowNode[],
): Map<string, WorkflowNode> {
  const nodeMap = new Map(nodes.map((n) => [n.node_id, n]))
  const rev = buildReverseAdjacency(nodes)
  const result = new Map<string, WorkflowNode>()
  const visited = new Set<string>()
  const queue: string[] = []

  // 初始入队：直接上游
  for (const src of rev.get(nodeId) ?? []) {
    if (!visited.has(src)) {
      visited.add(src)
      queue.push(src)
    }
  }

  // BFS 遍历
  while (queue.length > 0) {
    const cur = queue.shift()!
    const n = nodeMap.get(cur)
    if (n) result.set(cur, n)
    for (const src of rev.get(cur) ?? []) {
      if (!visited.has(src)) {
        visited.add(src)
        queue.push(src)
      }
    }
  }

  return result
}

/**
 * 根据 target node_id 查找直接 source 节点列表。
 */
export function findSourceNodes(
  nodeId: string,
  nodes: WorkflowNode[],
): WorkflowNode[] {
  const nodeMap = new Map(nodes.map((n) => [n.node_id, n]))
  const rev = buildReverseAdjacency(nodes)
  const sources: WorkflowNode[] = []
  for (const srcId of rev.get(nodeId) ?? []) {
    const n = nodeMap.get(srcId)
    if (n) sources.push(n)
  }
  return sources
}

/**
 * 生成节点下拉选项（排除自身）。
 */
export function getNodeOptions(
  nodes: WorkflowNode[],
  excludeId?: string,
): Array<{ value: string; label: string }> {
  return nodes
    .filter((n) => n.node_id !== excludeId)
    .map((n) => ({
      value: n.node_id,
      label: n.label || NODE_TYPE_CONFIGS[n.type]?.label || n.node_id,
    }))
}

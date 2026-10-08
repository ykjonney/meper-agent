/**
 * loop-derive — 从画布连线自动推导循环体（用户零概念配置的核心）。
 *
 * 约定（所见即所得）：
 * - 体尾节点连回 loop 节点的边 = 回边（画布上一个环 = 循环）
 * - loop 的出边中，沿链可达回边的 = 循环体（链头 = 每轮起点）
 * - loop 的其余出边 = 循环结束后的出口
 *
 * 保存时由 WorkflowDesigner 物化推导结果进 loop 节点 config（引擎照旧
 * 按 config.body 执行，校验器按 body 校验——推导层只服务交互）。
 */
import type { WorkflowNode } from '../../../services/workflows-api'

export interface LoopBodyDeriveResult {
  /** 体成员（按链拓扑序，起点在前） */
  body: string[]
  /** 每轮起点（loop 的进体边目标） */
  bodyEntry: string
}

export type LoopBodyDeriveError =
  | 'no-return-edge'      // 无回边：循环未闭合
  | 'ambiguous'           // 多条独立回边链（暂不支持多体循环）
  | 'entry-outside'       // 链未接回 loop（旁路）

/** 构建边索引（next_nodes + gateway 条件/默认 + parallel 分支起点） */
export function buildEdgeIndex(nodes: WorkflowNode[]): {
  out: Map<string, string[]>
  in: Map<string, string[]>
} {
  const out = new Map<string, string[]>()
  const inn = new Map<string, string[]>()
  const add = (s: string, t: string) => {
    if (!s || !t) return
    out.set(s, [...(out.get(s) ?? []), t])
    inn.set(t, [...(inn.get(t) ?? []), s])
  }
  for (const n of nodes) {
    const cfg = (n.config ?? {}) as Record<string, unknown>
    for (const nxt of (cfg.next_nodes as { target?: string }[] | undefined) ?? []) {
      add(n.node_id, String(nxt?.target ?? ''))
    }
    if (n.type === 'gateway') {
      for (const c of (cfg.conditions as { target?: string }[] | undefined) ?? []) {
        add(n.node_id, String(c?.target ?? ''))
      }
      add(n.node_id, String(cfg.default_branch ?? ''))
    }
    if (n.type === 'parallel') {
      for (const b of (cfg.branches as { start_node?: string }[] | undefined) ?? []) {
        add(n.node_id, String(b?.start_node ?? ''))
      }
    }
  }
  return { out, in: inn }
}

/**
 * 推导某个 loop 节点的循环体。
 * 返回 null + reason 时，调用方给用户中文引导（见 LoopNodeConfig）。
 */
export function deriveLoopBody(
  nodes: WorkflowNode[],
  loopNodeId: string,
): { ok: true; result: LoopBodyDeriveResult } | { ok: false; reason: LoopBodyDeriveError } {
  const { out } = buildEdgeIndex(nodes)
  const nodeIds = new Set(nodes.map((n) => n.node_id))
  const loopOutTargets = (out.get(loopNodeId) ?? []).filter((t) => nodeIds.has(t) && t !== loopNodeId)
  if (loopOutTargets.length === 0) {
    return { ok: false, reason: 'no-return-edge' }
  }

  // 从 loop 的每个出边目标正向 BFS；遇"边指向 loop"即该链闭合为循环体
  let hitChain: { entry: string; members: string[] } | null = null
  let hitCount = 0
  for (const entry of loopOutTargets) {
    const visited = new Set<string>([entry])
    const queue = [entry]
    const members: string[] = []
    let closed = false
    while (queue.length) {
      const cur = queue.shift()!
      members.push(cur)
      for (const tgt of out.get(cur) ?? []) {
        if (tgt === loopNodeId) { closed = true; continue }
        if (!nodeIds.has(tgt) || visited.has(tgt)) continue
        visited.add(tgt)
        queue.push(tgt)
      }
    }
    if (closed) {
      hitCount += 1
      if (!hitChain) hitChain = { entry, members }
    }
  }
  if (hitCount === 0) return { ok: false, reason: 'no-return-edge' }
  if (hitCount > 1) return { ok: false, reason: 'ambiguous' }
  return { ok: true, result: { body: hitChain!.members, bodyEntry: hitChain!.entry } }
}

/** 对全部节点物化 loop 推导结果（保存前调用）。返回更新后的节点数组。 */
export function materializeLoopBodies(nodes: WorkflowNode[]): WorkflowNode[] {
  return nodes.map((n) => {
    if (n.type !== 'loop') return n
    const derived = deriveLoopBody(nodes, n.node_id)
    if (!derived.ok) {
      // 推导失败保留现状（校验器按 LOOP_* 码拦截，面板给中文引导）
      return n
    }
    return {
      ...n,
      config: {
        ...n.config,
        body: derived.result.body,
        body_entry: derived.result.bodyEntry,
      },
    }
  })
}

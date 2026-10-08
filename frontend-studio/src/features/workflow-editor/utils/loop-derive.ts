/**
 * loop-derive — 循环节点内部编辑模式的辅助工具。
 *
 * 交互模式（M3.2）：循环体在循环节点内部编辑（双击进入），body 由交互
 * 层显式维护（内部加节点/删节点），保存时轻量物化（入口默认/清死成员）。
 * deriveLoopChain 按 config.body + 成员连线推导链序（面板展示用）。
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
 * body 已有成员时直接用（内部编辑模式维护）；为空时按回边推导一次
 * （旧数据/主画布模式兼容）。返回 reason 时调用方给中文引导。
 */
export function deriveLoopBody(
  nodes: WorkflowNode[],
  loopNodeId: string,
): { ok: true; result: LoopBodyDeriveResult } | { ok: false; reason: LoopBodyDeriveError } {
  const { out } = buildEdgeIndex(nodes)
  const nodeIds = new Set(nodes.map((n) => n.node_id))
  const loopNode = nodes.find((n) => n.node_id === loopNodeId)
  const existingBody = (((loopNode?.config ?? {}) as Record<string, unknown>).body as string[] | undefined) ?? []
  const validBody = existingBody.filter((m) => nodeIds.has(m))
  if (validBody.length > 0) {
    const entry = String(((loopNode?.config ?? {}) as Record<string, unknown>).body_entry ?? '') || validBody[0]
    return { ok: true, result: { body: validBody, bodyEntry: entry } }
  }
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

/** 保存前轻量物化：body 由内部编辑显式维护（不动），仅补默认入口 +
 * 清理已删除成员；body 为空的旧数据按回边推导一次。 */
export function materializeLoopBodies(nodes: WorkflowNode[]): WorkflowNode[] {
  const nodeIds = new Set(nodes.map((n) => n.node_id))
  return nodes.map((n) => {
    if (n.type !== 'loop') return n
    const cfg = (n.config ?? {}) as Record<string, unknown>
    const rawBody = (cfg.body as string[] | undefined) ?? []
    const body = rawBody.filter((m) => nodeIds.has(m))
    if (body.length === 0) {
      // 旧数据/主画布模式：按回边推导一次
      const derived = deriveLoopBody(nodes, n.node_id)
      if (derived.ok) {
        return { ...n, config: { ...cfg, body: derived.result.body, body_entry: derived.result.bodyEntry } }
      }
      return { ...n, config: { ...cfg, body: [], body_entry: '' } }
    }
    const entry = String(cfg.body_entry ?? '')
    return { ...n, config: { ...cfg, body, body_entry: entry && body.includes(entry) ? entry : body[0] } }
  })
}

/** 链序推导：按 body_entry 起点沿成员间连线 BFS 得展示序（面板"每轮执行"）。 */
export function deriveLoopChain(nodes: WorkflowNode[], loopNodeId: string): string[] {
  const loopNode = nodes.find((n) => n.node_id === loopNodeId)
  if (!loopNode) return []
  const cfg = (loopNode.config ?? {}) as Record<string, unknown>
  const body = new Set(((cfg.body as string[] | undefined) ?? []).filter(Boolean))
  const entry = String(cfg.body_entry ?? '') || [...body][0] || ''
  if (!entry || !body.has(entry)) return [...body]
  const { out } = buildEdgeIndex(nodes)
  const visited = new Set<string>([entry])
  const chain: string[] = []
  const queue = [entry]
  while (queue.length) {
    const cur = queue.shift()!
    chain.push(cur)
    for (const tgt of out.get(cur) ?? []) {
      if (body.has(tgt) && !visited.has(tgt)) {
        visited.add(tgt)
        queue.push(tgt)
      }
    }
  }
  // 环外成员（不可达）附后，保证全部展示
  for (const m of body) if (!visited.has(m)) chain.push(m)
  return chain
}

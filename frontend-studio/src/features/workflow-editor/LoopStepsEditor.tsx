/**
 * LoopStepsEditor — 循环节点内部编辑器（垂直步骤流，M3.3）。
 *
 * 循环步骤本质是有序序列：垂直步骤流直接表达"每轮第 1 步 → 第 2 步…"，
 * 顺序即执行顺序（无需连线）——加步骤/排序/删除即完成配置，选中步骤
 * 在右侧复用现有配置面板。
 *
 * 线性保护：循环体含分支结构（任一步骤有多出边/网关/并行）时降级为
 * 只读展示（步骤流以序列呈现），编辑操作禁用并提示——避免步骤流把
 * 分支语义抹平成线性。
 */
import { useMemo } from 'react'
import { ArrowDown, ArrowUp, ChevronLeft, Plus, X } from 'lucide-react'
import type { WorkflowNode } from '../../services/workflows-api'
import { NODE_TYPE_CONFIGS } from './utils/node-type-configs'
import { generateNodeId, getDefaultNodeConfig } from './utils/node-defaults'
import { deriveLoopChain } from './utils/loop-derive'

/** 可添加的线性步骤类型（分支类节点不提供，保持步骤流线性语义） */
const ADDABLE_TYPES = ['agent', 'tool', 'human', 'kb_search', 'subflow'] as const

interface Props {
  loopNode: WorkflowNode
  allNodes: WorkflowNode[]
  selectedNodeId: string | null
  onSelectNode: (n: WorkflowNode | null) => void
  /** 结构性变更（加/删/排序/重建线性链）回调 */
  onNodesChange: (nodes: WorkflowNode[]) => void
  onExit: () => void
}

export default function LoopStepsEditor({
  loopNode,
  allNodes,
  selectedNodeId,
  onSelectNode,
  onNodesChange,
  onExit,
}: Props) {
  const cfg = (loopNode.config ?? {}) as Record<string, unknown>
  const body = useMemo(
    () => (((cfg.body as string[] | undefined) ?? []).filter((id) =>
      allNodes.some((n) => n.node_id === id),
    )),
    [cfg.body, allNodes],
  )
  const chain = useMemo(() => deriveLoopChain(allNodes, loopNode.node_id), [allNodes, loopNode.node_id])
  const nodeById = useMemo(() => new Map(allNodes.map((n) => [n.node_id, n])), [allNodes])

  // 分叉检测：任一成员有 >1 个指向体内的出边，或成员是 gateway/parallel
  const bodySet = useMemo(() => new Set(body), [body])
  const isBranchy = useMemo(
    () =>
      body.some((id) => {
        const n = nodeById.get(id)
        if (!n) return false
        if (n.type === 'gateway' || n.type === 'parallel') return true
        const nexts = ((n.config as Record<string, unknown>).next_nodes as { target?: string }[] | undefined) ?? []
        return nexts.filter((nn) => bodySet.has(String(nn?.target ?? ''))).length > 1
      }),
    [body, nodeById, bodySet],
  )

  /** 结构性变更后重建线性链：steps[i].next = steps[i+1]，末步无下游 */
  const rebuildLinearChain = (steps: string[]): WorkflowNode[] => {
    const stepSet = new Set(steps)
    return allNodes.map((n) => {
      if (!stepSet.has(n.node_id)) {
        // 非成员节点若还指向旧成员（残留边），一并清掉
        const nexts = ((n.config as Record<string, unknown>).next_nodes as { target?: string }[] | undefined) ?? []
        const cleaned = nexts.filter((nn) => !stepSet.has(String(nn?.target ?? '')))
        if (cleaned.length !== nexts.length) {
          return { ...n, config: { ...n.config, next_nodes: cleaned } }
        }
        return n
      }
      const idx = steps.indexOf(n.node_id)
      const nextTarget = idx >= 0 && idx < steps.length - 1 ? steps[idx + 1] : null
      return {
        ...n,
        config: {
          ...n.config,
          next_nodes: nextTarget ? [{ target: nextTarget }] : [],
        },
      }
    })
  }

  const updateLoopBody = (nodes: WorkflowNode[], newBody: string[], entry?: string): WorkflowNode[] =>
    nodes.map((n) => {
      if (n.node_id !== loopNode.node_id) return n
      const c = { ...(n.config as Record<string, unknown>) }
      c.body = newBody
      c.body_entry = entry ?? (newBody.length ? newBody[0] : '')
      return { ...n, config: c }
    })

  const handleAddStep = (type: string) => {
    const newNode: WorkflowNode = {
      node_id: generateNodeId(),
      type,
      label: NODE_TYPE_CONFIGS[type]?.label ?? type,
      config: getDefaultNodeConfig(type),
      position: {
        x: 200 + ((body.length % 3) * 40),
        y: 150 + body.length * 110,
      },
    }
    const newBody = [...body, newNode.node_id]
    let nodes = [...allNodes, newNode]
    nodes = updateLoopBody(nodes, newBody, (cfg.body_entry as string | undefined) || newBody[0])
    nodes = rebuildLinearChain(newBody)
    onNodesChange(nodes)
    onSelectNode(newNode)
  }

  const handleRemoveStep = (id: string) => {
    const newBody = body.filter((x) => x !== id)
    let nodes = allNodes.filter((n) => n.node_id !== id)
    nodes = updateLoopBody(nodes, newBody, (cfg.body_entry as string | undefined) === id ? newBody[0] : undefined)
    nodes = rebuildLinearChain(newBody)
    onNodesChange(nodes)
    if (selectedNodeId === id) onSelectNode(null)
  }

  const handleMove = (id: string, dir: -1 | 1) => {
    const idx = chain.indexOf(id)
    const swapWith = idx + dir
    if (idx < 0 || swapWith < 0 || swapWith >= chain.length) return
    const steps = chain.slice()
    ;[steps[idx], steps[swapWith]] = [steps[swapWith], steps[idx]]
    let nodes = updateLoopBody(allNodes, steps)
    nodes = rebuildLinearChain(steps)
    onNodesChange(nodes)
  }

  return (
    <div className="absolute inset-0 z-30 bg-[#0a0a0c] flex flex-col">
      {/* 顶部面包屑 */}
      <div className="shrink-0 flex items-center gap-2 px-4 py-2.5 border-b border-[#27272a] bg-[#18181b]">
        <button
          onClick={onExit}
          className="flex items-center gap-1 text-xs text-[#d8b4fe] hover:text-white cursor-pointer px-2 py-1 rounded hover:bg-[#A855F7]/10"
        >
          <ChevronLeft size={14} /> 返回主流程
        </button>
        <span className="text-[#3f3f46]">╱</span>
        <span className="text-xs font-medium text-[#d8b4fe]">
          🔁 {loopNode.label || '循环'} 内部
        </span>
        <span className="text-[11px] text-[#71717a]">每轮按以下步骤依次执行</span>
      </div>

      {/* 步骤流 */}
      <div className="flex-1 overflow-y-auto scrollbar-custom px-6 py-5">
        <div className="max-w-md mx-auto">
          <div className="flex items-center gap-2 text-xs text-[#71717a] mb-3">
            <span className="w-6 h-6 rounded-full bg-[#A855F7]/20 text-[#d8b4fe] flex items-center justify-center text-[11px]">⟳</span>
            每轮开始
          </div>

          {chain.length === 0 && (
            <div className="rounded-lg border border-dashed border-[#A855F7]/40 bg-[#A855F7]/5 px-4 py-6 text-center text-xs text-[#a78bfa] mb-3">
              循环内还没有步骤，点击下方按钮添加
            </div>
          )}

          {chain.map((id, i) => {
            const n = nodeById.get(id)
            if (!n) return null
            const meta = NODE_TYPE_CONFIGS[n.type]
            const selected = selectedNodeId === id
            const label = String(n.label || (n.config as Record<string, unknown>).agent_name || meta?.label || n.type)
            return (
              <div key={id}>
                <div
                  onClick={() => onSelectNode(n)}
                  className={`group relative flex items-center gap-2.5 rounded-lg border px-3 py-2.5 cursor-pointer transition-colors ${
                    selected
                      ? 'border-[#1E5EFF] bg-[#1E5EFF]/10'
                      : 'border-[#27272a] bg-[#18181b] hover:border-[#A855F7]/50'
                  }`}
                >
                  <span
                    className="shrink-0 w-6 h-6 rounded flex items-center justify-center text-[11px] font-semibold"
                    style={{ backgroundColor: `${meta?.color ?? '#71717a'}22`, color: meta?.color ?? '#71717a' }}
                  >
                    {i + 1}
                  </span>
                  <span className="text-xs text-slate-200 truncate flex-1">{label}</span>
                  <span
                    className="shrink-0 px-1.5 py-0.5 rounded text-[9px]"
                    style={{ backgroundColor: `${meta?.color ?? '#71717a'}18`, color: meta?.color ?? '#71717a' }}
                  >
                    {meta?.label ?? n.type}
                  </span>
                  {!isBranchy && (
                    <span className="shrink-0 flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                      <button
                        onClick={(e) => { e.stopPropagation(); handleMove(id, -1) }}
                        disabled={i === 0}
                        title="上移"
                        className="p-1 rounded text-[#71717a] hover:text-white hover:bg-[#27272a] disabled:opacity-30 cursor-pointer"
                      >
                        <ArrowUp size={12} />
                      </button>
                      <button
                        onClick={(e) => { e.stopPropagation(); handleMove(id, 1) }}
                        disabled={i === chain.length - 1}
                        title="下移"
                        className="p-1 rounded text-[#71717a] hover:text-white hover:bg-[#27272a] disabled:opacity-30 cursor-pointer"
                      >
                        <ArrowDown size={12} />
                      </button>
                      <button
                        onClick={(e) => { e.stopPropagation(); handleRemoveStep(id) }}
                        title="删除步骤"
                        className="p-1 rounded text-[#71717a] hover:text-red-400 hover:bg-[#27272a] cursor-pointer"
                      >
                        <X size={12} />
                      </button>
                    </span>
                  )}
                </div>
                {i < chain.length - 1 && (
                  <div className="flex justify-center py-1 text-[#3f3f46]">
                    <span className="text-[10px]">↓</span>
                  </div>
                )}
              </div>
            )
          })}

          <div className="flex items-center gap-2 text-xs text-[#71717a] mt-3 mb-4">
            <span className="w-6 h-6 rounded-full bg-[#A855F7]/20 text-[#d8b4fe] flex items-center justify-center text-[11px]">↻</span>
            进入下一轮（满足条件则结束）
          </div>

          {!isBranchy ? (
            <div className="flex flex-wrap gap-1.5">
              {ADDABLE_TYPES.map((t) => (
                <button
                  key={t}
                  onClick={() => handleAddStep(t)}
                  className="flex items-center gap-1 px-2.5 py-1.5 rounded-lg border border-dashed border-[#A855F7]/40 text-xs text-[#c4b5fd] hover:bg-[#A855F7]/10 hover:border-[#A855F7] transition-colors cursor-pointer"
                >
                  <Plus size={12} />
                  {NODE_TYPE_CONFIGS[t]?.label ?? t}
                </button>
              ))}
            </div>
          ) : (
            <div className="rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-300">
              此循环包含分支/并行结构，步骤流以只读展示（调整顺序会破坏分支）。
              分支循环请在主画布选中循环节点配置收敛条件。
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

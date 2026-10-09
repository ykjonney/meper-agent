/**
 * LoopNodeConfig — 循环节点配置面板（右侧面板内完成一切）。
 *
 * 选中循环节点即见全部配置：步骤管理（查看/添加/删除/排序，顺序即每轮
 * 执行顺序，免连线）+ 两个人话参数（最多重复/提前结束）。点击某步骤 →
 * 面板切到该步骤自己的配置，点画布上的循环节点可回来。
 *
 * 分支保护：循环体含分支结构时步骤列表只读（防线性化抹平分支语义）。
 */
import { useMemo } from 'react'
import { ArrowDown, ArrowUp, Plus, X } from 'lucide-react'
import { Input, Select } from '../../../components/ui'
import HelpHint from '../HelpHint'
import { NODE_TYPE_CONFIGS } from '../utils/node-type-configs'
import { generateNodeId, getDefaultNodeConfig } from '../utils/node-defaults'
import { deriveLoopChain } from '../utils/loop-derive'
import type { WorkflowNode } from '../../../services/workflows-api'

/** 可添加的线性步骤类型（分支类不提供，保持步骤流线性语义） */
const ADDABLE_TYPES = ['agent', 'tool', 'human', 'kb_search', 'subflow'] as const

interface Props {
  config: Record<string, unknown>
  onChange: (c: Record<string, unknown>) => void
  allNodes: WorkflowNode[]
  currentNodeId: string
  /** 结构性变更（加/删步骤节点 + 重建线性链） */
  onNodesChange?: (nodes: WorkflowNode[]) => void
  /** 点击步骤 → 选中该节点（面板切到步骤配置） */
  onSelectNode?: (n: WorkflowNode) => void
}

function parseConverge(expr: string): { source: string; field: string; op: string; value: string } {
  const m = /\{\{\s*([\w]+)\.([\w.]+)\s*(==|!=)\s*'([^']*)'\s*\}\}/.exec(expr || '')
  return m
    ? { source: m[1], field: m[2], op: m[3], value: m[4] }
    : { source: '', field: '', op: '==', value: '' }
}

export default function LoopNodeConfig({
  config, onChange, allNodes, currentNodeId, onNodesChange, onSelectNode,
}: Props) {
  // 单一事实源：永远读 allNodes 里的最新循环节点——props config 可能是
  // selectedNode 的过期快照（结构变更后 Designer 未同步选中对象时，读旧
  // 快照会显示"步骤全没了"）。config prop 仅在节点暂不可见时兜底。
  const liveConfig = useMemo(
    () =>
      ((allNodes.find((n) => n.node_id === currentNodeId)?.config ?? config) as Record<string, unknown>),
    [allNodes, currentNodeId, config],
  )
  const maxIter = (liveConfig.max_iterations as number) ?? 5
  const convergeExpr = (liveConfig.converge_expr as string) ?? ''
  const body = useMemo(
    () => (((liveConfig.body as string[] | undefined) ?? []).filter((id) =>
      allNodes.some((n) => n.node_id === id))),
    [liveConfig.body, allNodes],
  )
  const chain = useMemo(() => deriveLoopChain(allNodes, currentNodeId), [allNodes, currentNodeId])
  const nodeById = useMemo(() => new Map(allNodes.map((n) => [n.node_id, n])), [allNodes])

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

  const nodeLabel = (id: string): string => {
    const n = nodeById.get(id)
    const cfg = (n?.config ?? {}) as Record<string, unknown>
    // agent_name/tool_name（选中后缓存）优先于节点 label——类型默认 label
    // （"Agent"/"工具"）无法区分多个同类步骤
    return String(
      cfg.agent_name || cfg.tool_name || n?.label || NODE_TYPE_CONFIGS[n?.type ?? '']?.label || id,
    )
  }

  /** 结构性变更：更新 body + 重建线性链（steps[i].next = steps[i+1]） */
  const applySteps = (steps: string[]) => {
    const stepSet = new Set(steps)
    let nodes = allNodes.map((n) => {
      if (n.node_id === currentNodeId) {
        const c = { ...(n.config as Record<string, unknown>) }
        c.body = steps
        c.body_entry = steps[0] ?? ''
        return { ...n, config: c }
      }
      if (stepSet.has(n.node_id)) {
        const idx = steps.indexOf(n.node_id)
        const nextTarget = idx >= 0 && idx < steps.length - 1 ? steps[idx + 1] : null
        return { ...n, config: { ...n.config, next_nodes: nextTarget ? [{ target: nextTarget }] : [] } }
      }
      // 非成员节点指向旧成员的残留边清掉
      const nexts = ((n.config as Record<string, unknown>).next_nodes as { target?: string }[] | undefined) ?? []
      const cleaned = nexts.filter((nn) => !stepSet.has(String(nn?.target ?? '')))
      if (cleaned.length !== nexts.length) {
        return { ...n, config: { ...n.config, next_nodes: cleaned } }
      }
      return n
    })
    onNodesChange(nodes)
  }

  const editable = !!onNodesChange

  const handleAddStep = (type: string) => {
    if (!onNodesChange) return
    const newNode: WorkflowNode = {
      node_id: generateNodeId(),
      type,
      label: NODE_TYPE_CONFIGS[type]?.label ?? type,
      config: getDefaultNodeConfig(type),
      position: { x: 200 + ((body.length % 3) * 40), y: 150 + body.length * 110 },
    }
    const steps = [...chain, newNode.node_id]
    const stepSet = new Set(steps)
    let nodes = allNodes.map((n) => {
      if (n.node_id === currentNodeId) {
        const c = { ...(n.config as Record<string, unknown>) }
        c.body = steps
        c.body_entry = (c.body_entry as string | undefined) || steps[0]
        return { ...n, config: c }
      }
      if (stepSet.has(n.node_id)) {
        const idx = steps.indexOf(n.node_id)
        const nextTarget = idx >= 0 && idx < steps.length - 1 ? steps[idx + 1] : null
        return { ...n, config: { ...n.config, next_nodes: nextTarget ? [{ target: nextTarget }] : [] } }
      }
      return n
    })
    nodes = [...nodes, newNode]
    onNodesChange(nodes)
    // 不自动切到新节点配置——连续添加多个步骤时不打断；完成后点步骤行配置
  }

  const handleMove = (id: string, dir: -1 | 1) => {
    if (!onNodesChange) return
    const idx = chain.indexOf(id)
    const j = idx + dir
    if (idx < 0 || j < 0 || j >= chain.length) return
    const steps = chain.slice()
    ;[steps[idx], steps[j]] = [steps[j], steps[idx]]
    applySteps(steps)
  }

  const handleRemoveStep = (id: string) => {
    if (!onNodesChange) return
    const steps = chain.filter((x) => x !== id)
    const nodes = allNodes
      .filter((n) => n.node_id !== id)
      .map((n) => {
        if (n.node_id === currentNodeId) {
          const c = { ...(n.config as Record<string, unknown>) }
          c.body = steps
          c.body_entry = (c.body_entry as string | undefined) === id ? (steps[0] ?? '') : c.body_entry
          return { ...n, config: c }
        }
        return n
      })
    onNodesChange(nodes)
  }

  const parsed = parseConverge(convergeExpr)
  const tail = chain.length ? chain[chain.length - 1] : ''
  const convergeParts = {
    source: parsed.source || tail,
    field: parsed.field || 'verdict',
    op: parsed.op || '==',
    value: parsed.value || 'approve',
  }
  const convergeEnabled = convergeExpr !== ''

  const setConvergePart = (patch: Partial<typeof convergeParts>) => {
    const next = { ...convergeParts, ...patch }
    onChange({
      ...liveConfig,
      converge_expr: `{{ ${next.source}.${next.field} ${next.op} '${next.value}' }}`,
    })
  }

  return (
    <div className="space-y-3">
      {/* 步骤管理：顺序即每轮执行顺序 */}
      <div>
        <label className="block text-xs text-slate-400 mb-1 flex items-center gap-1">
          每轮执行
          <HelpHint text="循环每轮从上到下依次执行这些步骤。点击步骤可配置其内容；用 ↑↓ 调整顺序，✕ 删除。" />
        </label>

        {chain.length === 0 && (
          <div className="rounded border border-dashed border-[#A855F7]/40 bg-[#A855F7]/5 px-3 py-3 text-center text-xs text-[#a78bfa] mb-2">
            还没有步骤，点击下方按钮添加
          </div>
        )}

        <div className="space-y-1">
          {chain.map((id, i) => {
            const n = nodeById.get(id)
            if (!n) return null
            const meta = NODE_TYPE_CONFIGS[n.type]
            return (
              <div
                key={id}
                onClick={() => onSelectNode(n)}
                className="group flex items-center gap-2 rounded-lg border border-[#27272a] bg-[#18181b] px-2 py-1.5 cursor-pointer hover:border-[#A855F7]/50 transition-colors"
              >
                <span
                  className="shrink-0 w-5 h-5 rounded flex items-center justify-center text-[10px] font-semibold"
                  style={{ backgroundColor: `${meta?.color ?? '#71717a'}22`, color: meta?.color ?? '#71717a' }}
                >
                  {i + 1}
                </span>
                <span className="text-xs text-slate-200 truncate flex-1">{nodeLabel(id)}</span>
                {!isBranchy && (
                  <span className="shrink-0 flex items-center gap-0.5 opacity-0 group-hover:opacity-100 transition-opacity">
                    <button
                      onClick={(e) => { e.stopPropagation(); handleMove(id, -1) }}
                      disabled={i === 0}
                      title="上移"
                      className="p-0.5 rounded text-[#71717a] hover:text-white hover:bg-[#27272a] disabled:opacity-30 cursor-pointer"
                    >
                      <ArrowUp size={11} />
                    </button>
                    <button
                      onClick={(e) => { e.stopPropagation(); handleMove(id, 1) }}
                      disabled={i === chain.length - 1}
                      title="下移"
                      className="p-0.5 rounded text-[#71717a] hover:text-white hover:bg-[#27272a] disabled:opacity-30 cursor-pointer"
                    >
                      <ArrowDown size={11} />
                    </button>
                    <button
                      onClick={(e) => { e.stopPropagation(); handleRemoveStep(id) }}
                      title="删除步骤"
                      className="p-0.5 rounded text-[#71717a] hover:text-red-400 hover:bg-[#27272a] cursor-pointer"
                    >
                      <X size={11} />
                    </button>
                  </span>
                )}
              </div>
            )
          })}
        </div>

        {!isBranchy && editable ? (
          <div className="flex flex-wrap gap-1.5 mt-2">
            {ADDABLE_TYPES.map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => handleAddStep(t)}
                className="flex items-center gap-0.5 px-2 py-1 rounded border border-dashed border-[#A855F7]/40 text-[11px] text-[#c4b5fd] hover:bg-[#A855F7]/10 hover:border-[#A855F7] transition-colors cursor-pointer"
              >
                <Plus size={11} />
                {NODE_TYPE_CONFIGS[t]?.label ?? t}
              </button>
            ))}
          </div>
        ) : !isBranchy && !editable ? (
          <div className="text-[10px] text-slate-500 mt-2">编辑不可用（请刷新页面重试）</div>
        ) : (
          <div className="rounded border border-amber-500/40 bg-amber-500/10 px-2 py-1.5 text-[10px] text-amber-300 mt-2">
            此循环包含分支/并行结构，步骤只读（调整顺序会破坏分支）
          </div>
        )}
      </div>

      <div>
        <label className="block text-xs text-slate-400 mb-1 flex items-center gap-1">
          最多重复
          <HelpHint text="防失控的兜底上限。循环通常由「提前结束条件」提前退出；到上限仍未通过也会结束，可在下游按是否通过分别处理。" />
        </label>
        <div className="flex items-center gap-2">
          <Input
            type="number"
            min={1}
            max={20}
            value={String(maxIter)}
            onChange={(e) =>
              onChange({
                ...liveConfig,
                max_iterations: Math.min(20, Math.max(1, parseInt(e.target.value) || 5)),
              })
            }
            className="w-20"
          />
          <span className="text-xs text-slate-400">次</span>
        </div>
      </div>

      <div>
        <label className="block text-xs text-slate-400 mb-1 flex items-center gap-1">
          提前结束条件
          <HelpHint text="每轮结束检查一次，满足就提前结束。最常用：最后一步（审核者）输出 approve 即通过。不勾选 = 固定跑满上面的次数（适合批量处理）。" />
        </label>
        <label className="flex items-center gap-2 mb-1.5 cursor-pointer">
          <input
            type="checkbox"
            checked={convergeEnabled}
            onChange={(e) =>
              onChange({
                ...liveConfig,
                converge_expr: e.target.checked
                  ? `{{ ${convergeParts.source}.${convergeParts.field} ${convergeParts.op} '${convergeParts.value}' }}`
                  : '',
              })
            }
            className="accent-[#A855F7]"
          />
          <span className="text-xs text-slate-300">满足条件时提前结束</span>
        </label>
        {convergeEnabled && body.length > 0 && (
          <div className="grid grid-cols-[1fr_1fr_56px_1fr] gap-1">
            <Select
              className="w-full"
              value={convergeParts.source || null}
              onChange={(val) => setConvergePart({ source: val ?? '' })}
              options={body.map((id) => ({ value: id, label: nodeLabel(id) }))}
            />
            <Input
              placeholder="字段"
              value={convergeParts.field}
              onChange={(e) => setConvergePart({ field: e.target.value })}
            />
            <Select
              className="w-full"
              value={convergeParts.op}
              onChange={(val) => setConvergePart({ op: val ?? '==' })}
              options={[
                { value: '==', label: '等于' },
                { value: '!=', label: '不等于' },
              ]}
            />
            <Input
              placeholder="值"
              value={convergeParts.value}
              onChange={(e) => setConvergePart({ value: e.target.value })}
            />
          </div>
        )}
      </div>

      {body.length > 0 && (
        <div className="text-[11px] text-slate-500 border-t border-[#27272a] pt-2">
          循环结束后可接条件分支，按{' '}
          <code className="text-[#a1a1aa]">{'{{'}{currentNodeId}.converged{'}}'}</code>{' '}
          （通过/未通过）分别走不同下游。
        </div>
      )}
    </div>
  )
}

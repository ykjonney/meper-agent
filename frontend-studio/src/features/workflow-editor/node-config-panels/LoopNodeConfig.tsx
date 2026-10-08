/**
 * LoopNodeConfig — 循环节点配置面板（M3，ADR docs/loop-node-adr.md）。
 *
 * 易用性原则：用户不碰裸 config——
 * - 循环体成员：chips 点选画布节点（排除 start/end/loop 自身）
 * - 体入口：下拉（限已选成员）
 * - 收敛条件：结构化三段式（成员.字段 操作符 值）自动生成表达式；
 *   留空 = 跑满轮数（批量映射模式）
 * - 体内部连线在画布上完成（writer → critic），封闭性由校验器把关
 */
import { useMemo } from 'react'
import { Input, Select } from '../../../components/ui'
import HelpHint from '../HelpHint'
import type { WorkflowNode } from '../../../services/workflows-api'

interface Props {
  config: Record<string, unknown>
  onChange: (c: Record<string, unknown>) => void
  allNodes: WorkflowNode[]
  currentNodeId: string
}

/** 可入体的节点（排除结构性节点与 loop 自身） */
function bodyCandidates(allNodes: WorkflowNode[], currentNodeId: string): WorkflowNode[] {
  return allNodes.filter((n) => n.node_id !== currentNodeId && !['start', 'end', 'loop'].includes(n.type))
}

/** 解析收敛表达式回填三段式（{{ src.field == 'value' }} / !=） */
function parseConverge(expr: string): { source: string; field: string; op: string; value: string } | null {
  const m = /\{\{\s*([\w]+)\.([\w.]+)\s*(==|!=)\s*'([^']*)'\s*\}\}/.exec(expr || '')
  if (!m) return null
  return { source: m[1], field: m[2], op: m[3], value: m[4] }
}

export default function LoopNodeConfig({ config, onChange, allNodes, currentNodeId }: Props) {
  const body = (config.body as string[]) ?? []
  const bodyEntry = (config.body_entry as string) ?? ''
  const maxIter = (config.max_iterations as number) ?? 5
  const convergeExpr = (config.converge_expr as string) ?? ''

  const candidates = useMemo(
    () => bodyCandidates(allNodes, currentNodeId),
    [allNodes, currentNodeId],
  )
  const nodeLabel = (id: string): string => {
    const n = allNodes.find((x) => x.node_id === id)
    return String(n?.label || (n?.config as Record<string, unknown> | undefined)?.agent_name || id)
  }

  const toggleBody = (id: string) => {
    const next = body.includes(id) ? body.filter((x) => x !== id) : [...body, id]
    const patch: Record<string, unknown> = { body: next }
    // 入口被移除时清空入口；首个成员自动成为入口（省一次选择）
    if (!next.includes(bodyEntry)) {
      patch.body_entry = next.length ? next[0] : ''
    }
    onChange({ ...config, ...patch })
  }

  const parsed = parseConverge(convergeExpr)
  const convergeParts = parsed ?? { source: '', field: '', op: '==', value: '' }

  const setConvergePart = (patch: Partial<typeof convergeParts>) => {
    const next = { ...convergeParts, ...patch }
    // 三段齐全才生成表达式；否则清空（= 跑满轮数）
    const expr =
      next.source && next.field
        ? `{{ ${next.source}.${next.field} ${next.op} '${next.value}' }}`
        : ''
    onChange({ ...config, converge_expr: expr })
  }

  return (
    <div className="space-y-3">
      <div>
        <label className="block text-xs text-slate-400 mb-1 flex items-center gap-1">
          循环体成员
          <HelpHint text="每轮依次执行这些节点（体内部连线请在画布上完成，如 写稿 → 审核；成员不得连到循环体外）。典型组合：写稿+审核（迭代改进）、单 Agent（批量映射）。" />
        </label>
        <div className="flex flex-wrap gap-1">
          {candidates.length === 0 && (
            <span className="text-[11px] text-slate-500">画布上暂无可入循环节点（先创建 Agent/工具等节点）</span>
          )}
          {candidates.map((n) => {
            const active = body.includes(n.node_id)
            return (
              <button
                key={n.node_id}
                type="button"
                onClick={() => toggleBody(n.node_id)}
                className={`px-2 py-1 rounded text-xs border transition-colors ${
                  active
                    ? 'bg-[#A855F7]/20 border-[#A855F7] text-[#d8b4fe]'
                    : 'bg-[#18181b] border-[#27272a] text-slate-300 hover:border-[#52525b]'
                }`}
              >
                {active ? '✓ ' : ''}{n.label || n.node_id}
              </button>
            )
          })}
        </div>
      </div>

      {body.length > 0 && (
        <>
          <div>
            <label className="block text-xs text-slate-400 mb-1 flex items-center gap-1">
              循环起点
              <HelpHint text="每轮从该节点开始执行。" />
            </label>
            <Select
              className="w-full"
              value={bodyEntry || null}
              onChange={(val) => onChange({ ...config, body_entry: val ?? '' })}
              options={body.map((id) => ({ value: id, label: nodeLabel(id) }))}
              placeholder="选择每轮的起始节点..."
            />
          </div>

          <div>
            <label className="block text-xs text-slate-400 mb-1 flex items-center gap-1">
              最大轮数
              <HelpHint text="硬上限（1-20）。防失控的兜底；正常情况由收敛条件提前退出。" />
            </label>
            <Input
              type="number"
              min={1}
              max={20}
              value={String(maxIter)}
              onChange={(e) =>
                onChange({ ...config, max_iterations: Math.min(20, Math.max(1, parseInt(e.target.value) || 5)) })
              }
            />
          </div>

          <div>
            <label className="block text-xs text-slate-400 mb-1 flex items-center gap-1">
              收敛条件（可选）
              <HelpHint text="每轮结束检查：满足即退出循环。典型：审核节点的 verdict 字段等于 approve。留空 = 跑满最大轮数（适合批量映射：每轮处理一项）。" />
            </label>
            <div className="grid grid-cols-[1fr_1fr_64px_1fr] gap-1.5">
              <Select
                className="w-full"
                value={convergeParts.source || null}
                onChange={(val) => setConvergePart({ source: val ?? '' })}
                options={body.map((id) => ({ value: id, label: nodeLabel(id) }))}
                placeholder="节点"
              />
              <Input
                placeholder="字段（如 verdict）"
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
                placeholder="值（如 approve）"
                value={convergeParts.value}
                onChange={(e) => setConvergePart({ value: e.target.value })}
              />
            </div>
            {convergeExpr && (
              <div className="text-[10px] text-slate-500 mt-1 font-mono break-all">{convergeExpr}</div>
            )}
          </div>

          <div className="text-[11px] text-slate-500 border-t border-[#27272a] pt-2">
            循环结束后下游可引用：<code className="text-[#a1a1aa]">{'{{'}{currentNodeId}.iterations{'}}'}</code>（实际轮数）、
            <code className="text-[#a1a1aa]">{'{{'}{currentNodeId}.converged{'}}'}</code>（是否收敛，可接条件分支）；
            体成员输出引用最新一轮，历史轮用 <code className="text-[#a1a1aa]">rounds.N</code>。
          </div>
        </>
      )}
    </div>
  )
}

/**
 * LoopNodeConfig — 循环节点配置面板（内部编辑模式）。
 *
 * 循环体在节点内部编辑（双击循环节点进入内部画布），本面板只负责：
 * - 展示每轮执行链（从内部连线自动推导）
 * - 循环起点（默认第一个加入的节点，一般无需改）
 * - 最多重复几次 / 提前结束条件（两个人话设置）
 */
import { useMemo } from 'react'
import { Input, Select } from '../../../components/ui'
import HelpHint from '../HelpHint'
import { deriveLoopChain } from '../utils/loop-derive'
import type { WorkflowNode } from '../../../services/workflows-api'

interface Props {
  config: Record<string, unknown>
  onChange: (c: Record<string, unknown>) => void
  allNodes: WorkflowNode[]
  currentNodeId: string
}

function parseConverge(expr: string): { source: string; field: string; op: string; value: string } {
  const m = /\{\{\s*([\w]+)\.([\w.]+)\s*(==|!=)\s*'([^']*)'\s*\}\}/.exec(expr || '')
  return m
    ? { source: m[1], field: m[2], op: m[3], value: m[4] }
    : { source: '', field: '', op: '==', value: '' }
}

export default function LoopNodeConfig({ config, onChange, allNodes, currentNodeId }: Props) {
  const maxIter = (config.max_iterations as number) ?? 5
  const convergeExpr = (config.converge_expr as string) ?? ''
  const body = ((config.body as string[]) ?? []).filter((id) =>
    allNodes.some((n) => n.node_id === id),
  )
  const bodyEntry = (config.body_entry as string) ?? ''

  const chain = useMemo(
    () => deriveLoopChain(allNodes, currentNodeId),
    [allNodes, currentNodeId],
  )

  const nodeLabel = (id: string): string => {
    const n = allNodes.find((x) => x.node_id === id)
    return String(n?.label || (n?.config as Record<string, unknown> | undefined)?.agent_name || id)
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
      ...config,
      converge_expr: `{{ ${next.source}.${next.field} ${next.op} '${next.value}' }}`,
    })
  }

  return (
    <div className="space-y-3">
      <div className="rounded border border-[#A855F7]/50 bg-[#A855F7]/10 px-2 py-1.5 text-xs text-[#d8b4fe]">
        💡 双击循环节点可进入内部，编辑每轮要执行的步骤
      </div>

      <div>
        <label className="block text-xs text-slate-400 mb-1 flex items-center gap-1">
          每轮执行
          <HelpHint text="循环节点每轮按内部连线执行一圈。要增删步骤或改顺序，双击循环节点进入内部编辑。" />
        </label>
        {body.length > 0 ? (
          <div className="rounded border border-[#A855F7]/50 bg-[#A855F7]/10 px-2 py-1.5 text-xs text-[#d8b4fe]">
            ✓ {chain.map(nodeLabel).join(' → ')}
          </div>
        ) : (
          <div className="rounded border border-amber-500/50 bg-amber-500/10 px-2 py-1.5 text-xs text-amber-300">
            循环内还没有步骤——双击循环节点进入内部，从左侧拖入节点
          </div>
        )}
      </div>

      {body.length > 0 && (
        <div>
          <label className="block text-xs text-slate-400 mb-1 flex items-center gap-1">
            每轮从哪开始
            <HelpHint text="默认第一个加入的步骤，一般无需修改。" />
          </label>
          <Select
            className="w-full"
            value={bodyEntry || body[0] || null}
            onChange={(val) => onChange({ ...config, body_entry: val ?? body[0] ?? '' })}
            options={body.map((id) => ({ value: id, label: nodeLabel(id) }))}
          />
        </div>
      )}

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
                ...config,
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
                ...config,
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
          <div className="grid grid-cols-[1fr_1fr_64px_1fr] gap-1.5">
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

/**
 * LoopNodeConfig — 循环节点配置面板（M3，连线驱动交互）。
 *
 * 用户零概念：循环体从画布连线自动识别（体尾连回循环节点 = 一个环），
 * 面板只展示识别结果 + 两个人话设置：
 * - 最多重复几次（防失控兜底）
 * - 什么时候提前结束（默认体尾节点 verdict=approve，可改；不勾选=跑满）
 */
import { useMemo } from 'react'
import { Input, Select } from '../../../components/ui'
import HelpHint from '../HelpHint'
import { deriveLoopBody } from '../utils/loop-derive'
import type { WorkflowNode } from '../../../services/workflows-api'

interface Props {
  config: Record<string, unknown>
  onChange: (c: Record<string, unknown>) => void
  allNodes: WorkflowNode[]
  currentNodeId: string
}

/** 解析收敛表达式回填三段式（{{ src.field == 'value' }} / !=） */
function parseConverge(expr: string): { source: string; field: string; op: string; value: string } {
  const m = /\{\{\s*([\w]+)\.([\w.]+)\s*(==|!=)\s*'([^']*)'\s*\}\}/.exec(expr || '')
  return m
    ? { source: m[1], field: m[2], op: m[3], value: m[4] }
    : { source: '', field: '', op: '==', value: '' }
}

const DERIVE_HINTS: Record<string, string> = {
  'no-return-edge':
    '未识别到循环：请从循环节点连出第一步（如「写稿」），最后一步再连回循环节点——画布上形成一个环',
  ambiguous: '检测到多条独立循环链：目前支持一条循环链，请合并（只有最后一步连回循环节点）',
}

export default function LoopNodeConfig({ config, onChange, allNodes, currentNodeId }: Props) {
  const maxIter = (config.max_iterations as number) ?? 5
  const convergeExpr = (config.converge_expr as string) ?? ''

  const derived = useMemo(
    () => deriveLoopBody(allNodes, currentNodeId),
    [allNodes, currentNodeId],
  )

  const nodeLabel = (id: string): string => {
    const n = allNodes.find((x) => x.node_id === id)
    return String(n?.label || (n?.config as Record<string, unknown> | undefined)?.agent_name || id)
  }

  const bodyChain = derived.ok ? derived.result.body : []
  let deriveHint: string | null = null
  if (!derived.ok && 'reason' in derived) {
    deriveHint = DERIVE_HINTS[derived.reason] ?? '循环连线未识别，请检查画布连线'
  }
  const bodyTail = bodyChain.length ? bodyChain[bodyChain.length - 1] : ''

  const parsed = parseConverge(convergeExpr)
  const convergeParts = {
    source: parsed.source || bodyTail,
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
      {/* 循环体识别结果（从连线自动推导，用户不配置成员） */}
      <div>
        <label className="block text-xs text-slate-400 mb-1 flex items-center gap-1">
          循环内容
          <HelpHint text="循环节点每轮执行一圈：从它连出的第一步开始，到最后一步连回循环节点结束。要改循环里有哪些步骤，直接在画布上增删节点和连线。" />
        </label>
        {derived.ok ? (
          <div className="rounded border border-[#A855F7]/50 bg-[#A855F7]/10 px-2 py-1.5 text-xs text-[#d8b4fe]">
            ✓ 每轮执行：{bodyChain.map(nodeLabel).join(' → ')}
          </div>
        ) : (
          <div className="rounded border border-amber-500/50 bg-amber-500/10 px-2 py-1.5 text-xs text-amber-300">
            {deriveHint}
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
          <HelpHint text="每轮结束检查一次，满足就提前结束。最常用：最后一步（审核者）输出 approve 即通过。不勾选 = 固定跑满上面的次数（适合批量处理：每轮做一项）。" />
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
        {convergeEnabled && derived.ok && bodyChain.length > 0 && (
          <>
            <div className="grid grid-cols-[1fr_1fr_64px_1fr] gap-1.5">
              <Select
                className="w-full"
                value={convergeParts.source || null}
                onChange={(val) => setConvergePart({ source: val ?? '' })}
                options={bodyChain.map((id) => ({ value: id, label: nodeLabel(id) }))}
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
            <div className="text-[10px] text-slate-500 mt-1">
              例：审核者输出 verdict 字段等于 approve 时结束
            </div>
          </>
        )}
      </div>

      {derived.ok && (
        <div className="text-[11px] text-slate-500 border-t border-[#27272a] pt-2">
          循环结束后可接条件分支，按{' '}
          <code className="text-[#a1a1aa]">{'{{'}{currentNodeId}.converged{'}}'}</code>{' '}
          （通过/未通过）分别走不同下游。
        </div>
      )}
    </div>
  )
}

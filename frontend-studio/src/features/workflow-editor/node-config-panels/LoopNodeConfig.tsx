/**
 * LoopNodeConfig — 循环节点配置面板（右侧面板内完成一切）。
 *
 * 选中循环节点即见全部配置：步骤管理（查看/添加/删除/排序，顺序即每轮
 * 执行顺序，免连线）+ 两个人话参数（最多重复/提前结束）。点击某步骤 →
 * 面板切到该步骤自己的配置，点画布上的循环节点可回来。
 *
 * 分支保护：循环体含分支结构时步骤列表只读（防线性化抹平分支语义）。
 */
import { useMemo, useState } from 'react'
import { ArrowDown, ArrowUp, ChevronDown, Plus, X } from 'lucide-react'
import { Input, Popover, Select, Tag } from '../../../components/ui'
import HelpHint from '../HelpHint'
import { NODE_TYPE_CONFIGS } from '../utils/node-type-configs'
import { generateNodeId, getDefaultNodeConfig } from '../utils/node-defaults'
import { deriveLoopChain, applyLinearBodySteps } from '../utils/loop-derive'
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

/* ─── 结束条件（converge）表达式的组装与解析 ───
 * 形式：{{ src.field op value }}（比较类）或 {{ 'value' in src.field }}（包含）。
 * 数值裸写（Jinja2 数值比较）、字符串加引号；未定义变量后端 fail-safe 为不收敛。 */
const CONVERGE_OPS = [
  { value: '==', label: '等于' },
  { value: '!=', label: '不等于' },
  { value: '>', label: '大于' },
  { value: '>=', label: '大于等于' },
  { value: '<', label: '小于' },
  { value: '<=', label: '小于等于' },
  { value: 'in', label: '包含' },
] as const

type ConvergeOp = (typeof CONVERGE_OPS)[number]['value']
interface ConvergeParts { source: string; field: string; op: ConvergeOp; value: string }

/** 值序列化：数字裸写（数值比较），其他加引号（字符串） */
function fmtConvergeValue(v: string): string {
  const t = v.trim()
  return t !== '' && Number.isFinite(Number(t)) ? t : `'${v}'`
}

function buildConvergeExpr(p: ConvergeParts): string {
  return p.op === 'in'
    ? `{{ ${fmtConvergeValue(p.value)} in ${p.source}.${p.field} }}`
    : `{{ ${p.source}.${p.field} ${p.op} ${fmtConvergeValue(p.value)} }}`
}

function parseConverge(expr: string): ConvergeParts {
  // 包含形式：{{ '值' in src.field }}
  let m = /\{\{\s*'([^']*)'\s+in\s+([\w]+)\.([\w.]+)\s*\}\}/.exec(expr || '')
  if (m) return { value: m[1], source: m[2], field: m[3], op: 'in' }
  // 比较形式：{{ src.field op '值'|数字 }}（>= 等在前防被 > 吞掉）
  m = /\{\{\s*([\w]+)\.([\w.]+)\s*(==|!=|>=|<=|>|<)\s*(?:'([^']*)'|([-+]?\d+(?:\.\d+)?))\s*\}\}/.exec(expr || '')
  if (m) return { source: m[1], field: m[2], op: m[3] as ConvergeOp, value: m[4] ?? m[5] ?? '' }
  return { source: '', field: '', op: '==', value: '' }
}

/** 读取步骤的可选条件字段——按节点类型的真实输出契约给地址：
 * agent 的 response_schema 字段是 response 的内容（object 模式解析后
 * 写池在 response.<name>，node_executor.py 契约注释），不是顶层键。 */
function convergeFieldOptions(node: WorkflowNode | undefined): { value: string; label: string }[] {
  if (!node) return []
  const cfg = (node.config ?? {}) as Record<string, unknown>
  if (node.type === 'agent') {
    const opts = [{ value: 'response', label: 'response · 回答全文' }]
    const schema = cfg.response_schema as { fields?: Array<{ name?: string }> } | undefined
    for (const f of schema?.fields ?? []) {
      if (f?.name) opts.push({ value: `response.${f.name}`, label: `${f.name} · 契约字段` })
    }
    opts.push({ value: 'files', label: 'files · 产出文件' })
    return opts
  }
  if (node.type === 'tool') {
    return [
      { value: 'result', label: 'result · 工具返回' },
      { value: 'files', label: 'files · 产出文件' },
    ]
  }
  if (node.type === 'kb_search') {
    return [{ value: 'results', label: 'results · 检索结果' }]
  }
  // human 是暂停审批点，其输出不适用作收敛条件源
  return []
}

/** 收敛条件的变量选择器：按步骤分组点选字段（与 agent 输入的「选择变量」同交互语言） */
function ConvergeVarPicker({
  body, nodeLabel, nodeById, value, onPick,
}: {
  body: string[]
  nodeLabel: (id: string) => string
  nodeById: Map<string, WorkflowNode>
  value: { source: string; field: string }
  onPick: (source: string, field: string) => void
}) {
  const [open, setOpen] = useState(false)
  const selected = value.source && value.field
  return (
    <Popover
      trigger="click"
      open={open}
      onOpenChange={setOpen}
      title={<span className="text-xs">选择变量</span>}
      content={
        <div className="w-64 max-h-64 overflow-y-auto scrollbar-custom">
          {body.map((id) => {
            const fields = convergeFieldOptions(nodeById.get(id))
            return (
              <div key={id} className="mb-2.5 last:mb-0">
                <div className="flex items-center gap-1.5 mb-1.5 px-0.5">
                  <span className="w-1.5 h-1.5 rounded-full bg-[#A855F7] shrink-0" />
                  <span className="text-xs font-medium text-[#fafafa] truncate">{nodeLabel(id)}</span>
                </div>
                {fields.length === 0 ? (
                  <div className="text-[10px] text-[#71717a] px-0.5">该步骤类型不适用作条件源</div>
                ) : (
                  <div className="flex flex-wrap gap-1">
                    {fields.map((o) => (
                      <Tag
                        key={o.value}
                        className="!m-0 !cursor-pointer !text-[11px] !px-1.5 !py-0.5 !rounded hover:!opacity-80 transition-opacity"
                        color="purple"
                        onClick={() => {
                          onPick(id, o.value)
                          setOpen(false)
                        }}
                      >
                        {o.label}
                      </Tag>
                    ))}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      }
    >
      <button
        type="button"
        className={`w-full min-w-0 h-8 px-2 flex items-center gap-1 rounded-md border text-xs transition-colors cursor-pointer ${
          selected
            ? 'border-[#A855F7]/50 bg-[#A855F7]/10 text-[#c4b5fd] hover:border-[#A855F7]'
            : 'border-[#27272a] bg-[#18181b] text-[#71717a] hover:border-[#A855F7]/40'
        }`}
      >
        <span className="truncate flex-1 text-left">
          {selected ? `${nodeLabel(value.source)} · ${value.field}` : '选择变量'}
        </span>
        <ChevronDown size={12} className="shrink-0 opacity-60" />
      </button>
    </Popover>
  )
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
  const chainRaw = useMemo(() => deriveLoopChain(allNodes, currentNodeId), [allNodes, currentNodeId])
  // 显示/操作序列以 body 为准：chain 仅作拓扑排序，推导异常（空/缺成员）
  // 时退回 body 原序——列表永远显示全部成员
  const chain = useMemo(() => {
    const missing = body.filter((id) => !chainRaw.includes(id))
    return chainRaw.length >= body.length ? chainRaw : [...chainRaw, ...missing]
  }, [chainRaw, body])
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

  const editable = !!onNodesChange

  const handleAddStep = (type: string) => {
    if (!onNodesChange) return
    // 新节点即尾步：next_nodes 直接连回循环节点（回边，引擎轮内推进依赖）
    const newNode: WorkflowNode = {
      node_id: generateNodeId(),
      type,
      label: NODE_TYPE_CONFIGS[type]?.label ?? type,
      config: { ...getDefaultNodeConfig(type), next_nodes: [{ target: currentNodeId }] },
      position: { x: 200 + ((body.length % 3) * 40), y: 150 + body.length * 110 },
    }
    const steps = [...chain, newNode.node_id]
    const nodes = [...applyLinearBodySteps(allNodes, currentNodeId, steps), newNode]
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
    onNodesChange(applyLinearBodySteps(allNodes, currentNodeId, steps))
  }

  const handleRemoveStep = (id: string) => {
    if (!onNodesChange) return
    const steps = chain.filter((x) => x !== id)
    const nodesLeft = allNodes.filter((n) => n.node_id !== id)
    onNodesChange(applyLinearBodySteps(nodesLeft, currentNodeId, steps))
  }

  const parsed = parseConverge(convergeExpr)
  const tail = chain.length ? chain[chain.length - 1] : ''
  // 字段默认值从 source 步骤的输出契约取第一个字段（审核场景通常配了
  // verdict/approve 类字段），无契约回退 verdict——不再让用户盲猜字符串
  const defaultSource = parsed.source || tail
  const defaultField = useMemo(() => {
    if (parsed.field) return parsed.field
    const schemaFields = convergeFieldOptions(nodeById.get(defaultSource)).filter(
      (o) => o.value !== 'response' && o.value !== 'files',
    )
    return schemaFields[0]?.value ?? 'response'
  }, [parsed.field, defaultSource, nodeById])
  const convergeParts: ConvergeParts = {
    source: defaultSource,
    field: defaultField,
    op: parsed.op || '==',
    value: parsed.value || 'approve',
  }
  const convergeEnabled = convergeExpr !== ''

  const setConvergePart = (patch: Partial<ConvergeParts>) => {
    const next = { ...convergeParts, ...patch }
    onChange({ ...liveConfig, converge_expr: buildConvergeExpr(next) })
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
          结束方式
          <HelpHint text="两种结束：跑满次数适合批量处理（每个输入处理 N 遍）；满足条件提前结束适合迭代改进（写到审核通过为止）。到上限仍未满足也会结束，下游可按 converged 区分通过/未通过。" />
        </label>
        <div className="space-y-1">
          <label className="flex items-start gap-2 rounded-lg border border-[#27272a] bg-[#18181b] px-2.5 py-2 cursor-pointer hover:border-[#A855F7]/40 transition-colors">
            <input
              type="radio"
              name={`loop-end-${currentNodeId}`}
              checked={!convergeEnabled}
              onChange={() => onChange({ ...liveConfig, converge_expr: '' })}
              className="mt-0.5 accent-[#A855F7]"
            />
            <span className="text-xs text-slate-200">
              跑满上面的次数
              <span className="block text-[10px] text-slate-500">固定执行，适合批量处理</span>
            </span>
          </label>
          <label className="flex items-start gap-2 rounded-lg border border-[#27272a] bg-[#18181b] px-2.5 py-2 cursor-pointer hover:border-[#A855F7]/40 transition-colors">
            <input
              type="radio"
              name={`loop-end-${currentNodeId}`}
              checked={convergeEnabled}
              onChange={() =>
                onChange({ ...liveConfig, converge_expr: buildConvergeExpr(convergeParts) })
              }
              className="mt-0.5 accent-[#A855F7]"
            />
            <span className="text-xs text-slate-200">
              满足条件时提前结束
              <span className="block text-[10px] text-slate-500">每轮结束检查一次，适合迭代改进（如：审核通过即停）</span>
            </span>
          </label>
        </div>
        {convergeEnabled && body.length === 0 && (
          <div className="rounded border border-amber-500/40 bg-amber-500/10 px-2 py-1.5 text-[10px] text-amber-300 mt-1.5">
            先添加步骤，再定义结束条件
          </div>
        )}
        {convergeEnabled && body.length > 0 && (
          <div className="mt-2 space-y-1">
            <div className="grid grid-cols-[1fr_72px_1fr] gap-1">
              {/* 变量选择：与 agent 输入的「选择变量」同交互语言——按步骤
                  分组点选字段，按钮上显示 chip 样式的"步骤 · 字段" */}
              <ConvergeVarPicker
                body={body}
                nodeLabel={nodeLabel}
                nodeById={nodeById}
                value={{ source: convergeParts.source, field: convergeParts.field }}
                onPick={(source, field) => setConvergePart({ source, field })}
              />
              <Select
                className="w-full"
                value={convergeParts.op}
                onChange={(val) => setConvergePart({ op: (val ?? '==') as ConvergeOp })}
                options={CONVERGE_OPS.map((o) => ({ value: o.value, label: o.label }))}
              />
              <Input
                placeholder="值，如 approve 或 8"
                value={convergeParts.value}
                onChange={(e) => setConvergePart({ value: e.target.value })}
              />
            </div>
            {/* 生成的表达式原文：透明可核对，也教用户语法 */}
            <div className="text-[10px] text-slate-500 font-mono truncate" title={convergeExpr}>
              {convergeExpr}
            </div>
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

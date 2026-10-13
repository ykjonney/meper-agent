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
import VariableSelector from '../VariableSelector'
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
interface ConvergeCondition { source: string; field: string; op: ConvergeOp; value: string }

/** 值序列化：数字裸写（数值比较），其他加引号（字符串） */
function fmtConvergeValue(v: string): string {
  const t = v.trim()
  return t !== '' && Number.isFinite(Number(t)) ? t : `'${v}'`
}

/** 单条件 → 表达式片段（无花括号；列表用 and 连接后再包） */
function buildCondExpr(c: ConvergeCondition): string {
  return c.op === 'in'
    ? `${fmtConvergeValue(c.value)} in ${c.source}.${c.field}`
    : `${c.source}.${c.field} ${c.op} ${fmtConvergeValue(c.value)}`
}

/** 组装收敛表达式：多条件按选定关系（and=全部满足 / or=任一满足）连接 */
function buildConvergeExpr(cs: ConvergeCondition[], joiner: 'and' | 'or' = 'and'): string {
  if (cs.length === 0) return ''
  return `{{ ${cs.map(buildCondExpr).join(joiner === 'or' ? ' or ' : ' and ')} }}`
}

/** 表达式片段 → 单条件；不匹配返回 null */
function parseCondExpr(str: string): ConvergeCondition | null {
  // 包含形式：'值' in src.field
  let m = /^'([^']*)'\s+in\s+([\w]+)\.([\w.]+)$/.exec(str)
  if (m) return { value: m[1], source: m[2], field: m[3], op: 'in' }
  // 比较形式：src.field op '值'|数字（>= 等在前防被 > 吞掉）
  m = /^([\w]+)\.([\w.]+)\s*(==|!=|>=|<=|>|<)\s*(?:'([^']*)'|([-+]?\d+(?:\.\d+)?))$/.exec(str)
  if (m) return { source: m[1], field: m[2], op: m[3] as ConvergeOp, value: m[4] ?? m[5] ?? '' }
  return null
}

/** 解析收敛表达式 → {条件列表, 块间关系}。按 and/or 切分逐条解析；
 *  混合关系（and+or 无括号语义歧义）或不认识的结构返回 null——调用方
 *  显示原文与提示，绝不用表单默认值覆盖用户手写的表达式。 */
function parseConvergeList(expr: string): { conds: ConvergeCondition[]; joiner: 'and' | 'or' } | null {
  const m = /\{\{([\s\S]+)\}\}/.exec((expr || '').trim())
  if (!m) return null
  const body = m[1]
  const hasAnd = /\s+and\s+/i.test(body)
  const hasOr = /\s+or\s+/i.test(body)
  if (hasAnd && hasOr) return null
  const joiner: 'and' | 'or' = hasOr ? 'or' : 'and'
  const out: ConvergeCondition[] = []
  for (const part of body.split(/\s+(?:and|or)\s+/i)) {
    const c = parseCondExpr(part.trim())
    if (!c) return null
    out.push(c)
  }
  return out.length ? { conds: out, joiner } : null
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
            ? 'border-[#A855F7]/50 bg-[#18181b] text-[#d6c8ff] hover:border-[#A855F7]'
            : 'border-[#27272a] bg-[#18181b] text-[#a1a1aa] hover:border-[#A855F7]/40'
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
  const wsGoal = (liveConfig.workspace_goal as string | undefined) ?? ''
  const wsEnabled = wsGoal !== ''
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
    if (!n) return id
    const cfg = (n.config ?? {}) as Record<string, unknown>
    const typeDefault = NODE_TYPE_CONFIGS[n.type]?.label
    // 节点名称优先——两个步骤共用同一 agent 时靠节点名区分（如"写手/
    // 审核"）；label 仍是类型默认名（未改名）时回退 agent/工具显示名
    const customLabel = n.label && n.label !== typeDefault ? n.label : ''
    return String(customLabel || cfg.agent_name || cfg.tool_name || typeDefault || id)
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

  const tail = chain.length ? chain[chain.length - 1] : ''
  // 条件块：按 and/or 解析。混合关系或复杂结构 → 自定义模式，显示原文，
  // 表单不覆盖
  const parsed = parseConvergeList(convergeExpr)
  const conditions = parsed?.conds ?? []
  const joiner: 'and' | 'or' = parsed?.joiner ?? 'and'
  const isCustomExpr = convergeExpr !== '' && parsed === null

  /** 新条件的默认值：从尾步（或指定步骤）的输出契约取第一个字段 */
  const defaultCond = useMemo((): ConvergeCondition => {
    const schemaFields = convergeFieldOptions(nodeById.get(tail)).filter(
      (o) => o.value !== 'response' && o.value !== 'files',
    )
    return {
      source: tail,
      field: schemaFields[0]?.value ?? 'response',
      op: '==',
      value: 'approve',
    }
  }, [tail, nodeById])

  const setCondition = (idx: number, patch: Partial<ConvergeCondition>) => {
    const next = conditions.map((c, i) => (i === idx ? { ...c, ...patch } : c))
    onChange({ ...liveConfig, converge_expr: buildConvergeExpr(next, joiner) })
  }
  const removeCondition = (idx: number) => {
    // 删到最后一条 = 回到"无结束条件"（跑满次数），而非空表达式
    onChange({ ...liveConfig, converge_expr: buildConvergeExpr(conditions.filter((_, i) => i !== idx), joiner) })
  }
  const addCondition = () => {
    onChange({ ...liveConfig, converge_expr: buildConvergeExpr([...conditions, { ...defaultCond, source: tail }], joiner) })
  }
  const setJoiner = (j: 'and' | 'or') => {
    if (conditions.length > 0) {
      onChange({ ...liveConfig, converge_expr: buildConvergeExpr(conditions, j) })
    }
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

      {/* 循环工作台（refine 模板）：共享状态台——目标只此一份、待解决问题
          双向流转、产物带版本。启用后步骤每轮自动收到工作台视图/增量
          （引擎注入，步骤侧零配置），input_query 只写本轮动作指令。 */}
      <div>
        <label className="flex items-center gap-2 cursor-pointer mb-1">
          <input
            type="checkbox"
            checked={wsEnabled}
            onChange={(e) => {
              if (e.target.checked) {
                onChange({ ...liveConfig, workspace_goal: wsGoal || '（描述这个循环要完成的目标，可插入 {{变量}}）' })
              } else {
                const next = { ...liveConfig }
                delete next.workspace_goal
                onChange(next)
              }
            }}
            className="accent-[#A855F7]"
          />
          <span className="text-xs text-slate-300">共享工作台</span>
          <HelpHint text="各步骤围绕同一个状态台工作：任务目标只此一份（不再每轮重复）、待解决问题谁提的谁关、产物带版本可追踪。步骤每轮自动收到工作台视图，input_query 只需写本轮做什么。适合多轮打磨/审核类循环。" />
        </label>
        {wsEnabled && (
          <VariableSelector
            label="任务目标"
            required
            value={wsGoal}
            onChange={(v) => onChange({ ...liveConfig, workspace_goal: v })}
            currentNodeId={currentNodeId}
            allNodes={allNodes}
            placeholder="这个循环要完成什么（每轮注入工作台，只此一份），如：围绕主题写一段80字文案。主题：{{开始节点.topic}}"
            rows={2}
          />
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
          结束条件
          <HelpHint text={'每轮结束检查一次，满足即提前结束；不添加条件 = 跑满上面的次数。多个条件间可设为「且」（全部满足）或「或」（任一满足）。'} />
        </label>

        {body.length === 0 && (
          <div className="rounded border border-dashed border-[#27272a] px-2.5 py-2 text-[10px] text-[#71717a]">
            先添加步骤，再定义结束条件
          </div>
        )}

        {body.length > 0 && conditions.length === 0 && !isCustomExpr && (
          <div className="space-y-1.5">
            <div className="rounded border border-dashed border-[#A855F7]/40 bg-[#A855F7]/5 px-2.5 py-2 text-[10px] text-[#a78bfa]">
              未设置结束条件——循环将跑满上方设定的次数
            </div>
            <button
              type="button"
              onClick={addCondition}
              className="flex items-center gap-0.5 px-2 py-1 rounded border border-dashed border-[#A855F7]/40 text-[11px] text-[#c4b5fd] hover:bg-[#A855F7]/10 hover:border-[#A855F7] transition-colors cursor-pointer"
            >
              <Plus size={11} />
              添加条件
            </button>
          </div>
        )}

        {body.length > 0 && conditions.length > 0 && (
          <div className="space-y-1.5">
            {conditions.map((c, i) => (
              <div
                key={i}
                className="relative rounded-lg bg-[#3f3f46] px-1.5 py-2 pr-6 transition-colors hover:bg-[#484851]"
              >
                <button
                  type="button"
                  title="删除该条件"
                  onClick={() => removeCondition(i)}
                  className="absolute top-1.5 right-1.5 p-0.5 rounded text-[#71717a] hover:text-red-400 hover:bg-[#27272a] cursor-pointer"
                >
                  <X size={11} />
                </button>
                {/* 上行：变量 + 操作符（无边框——块本身用微暗底色界定，
                    突出控件主体） */}
                <div className="flex gap-1 pb-1.5">
                  <div className="flex-1 min-w-0">
                    <ConvergeVarPicker
                      body={body}
                      nodeLabel={nodeLabel}
                      nodeById={nodeById}
                      value={{ source: c.source, field: c.field }}
                      onPick={(source, field) => setCondition(i, { source, field })}
                    />
                  </div>
                  <Select
                    className="w-[64px] shrink-0"
                    value={c.op}
                    onChange={(val) => setCondition(i, { op: (val ?? '==') as ConvergeOp })}
                    options={CONVERGE_OPS.map((o) => ({ value: o.value, label: o.label }))}
                  />
                </div>
                {/* 下行：值——上下行之间一条隔离线 */}
                <div className="border-t border-[#27272a]/40 pt-1.5">
                  <Input
                    placeholder="值，如 approve 或 8"
                    value={c.value}
                    onChange={(e) => setCondition(i, { value: e.target.value })}
                  />
                </div>
              </div>
            ))}

            {conditions.length > 1 && (
              <div className="flex items-center gap-1.5 text-[10px] text-slate-500">
                条件间关系
                <Select
                  className="w-32"
                  value={joiner}
                  onChange={(val) => setJoiner((val ?? 'and') === 'or' ? 'or' : 'and')}
                  options={[
                    { value: 'and', label: '且（全部满足）' },
                    { value: 'or', label: '或（任一满足）' },
                  ]}
                />
              </div>
            )}

            <button
              type="button"
              onClick={addCondition}
              className="flex items-center gap-0.5 px-2 py-1 rounded border border-dashed border-[#A855F7]/40 text-[11px] text-[#c4b5fd] hover:bg-[#A855F7]/10 hover:border-[#A855F7] transition-colors cursor-pointer"
            >
              <Plus size={11} />
              添加条件
            </button>
            {/* 生成的表达式原文：透明可核对，也教用户语法 */}
            <div className="text-[10px] text-slate-500 font-mono break-all" title={convergeExpr}>
              {convergeExpr}
            </div>
          </div>
        )}

        {body.length > 0 && isCustomExpr && (
          <div className="space-y-1">
            <div className="rounded border border-amber-500/40 bg-amber-500/10 px-2 py-1.5 text-[10px] text-amber-300">
              当前为自定义表达式（含表单不支持的结构，如且/或混用），表单不覆盖、仅展示原文
            </div>
            <div className="text-[10px] text-slate-500 font-mono break-all" title={convergeExpr}>
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

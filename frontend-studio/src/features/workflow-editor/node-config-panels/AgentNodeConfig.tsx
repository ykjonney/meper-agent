/**
 * AgentNodeConfig — Agent 节点配置面板。
 *
 * 输出模型（API 返回体，v3 契约）：
 * - 固定字段（response/agent_id/files/usage）由引擎恒定提供，无需用户配置；
 *   下游直接 {{node.response}}、{{node.files.0.file_id}}。abort 时未配信息
 *   不足分支则节点直接失败（原因见 error_message），配了则 response 承载
 *   abort 原因并走该分支。
 * - response 是核心内容：默认文本（零配置）；通过「返回结构」声明为
 *   对象/数组（字段+说明，嵌套最多两层），运行时引擎按契约把 Agent 的
 *   JSON 回复解析为原生结构写入 response，下游 {{node.response.field.sub}}
 *   直接取值（不依赖 JSON 字符串深解析）。
 *
 * - Agent ID 通过 Select 选择
 * - 查询（input_query）：必填，作为 user message，支持变量池
 * - 上下文（input_prompt）：可选，注入 Agent 的 context 卡槽，支持变量池
 * - 超时（timeout_ms）；temperature/max_retry 沿用节点默认配置（引擎侧
 *   消费），信息不足分支（insufficient_branch）已从面板下线（后端能力保留）
 *
 * antd 组件 → 原生 Tailwind ui 封装；保留 @tanstack/react-query（指向 studio agent-api）。
 */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Select, Input, Spin, Switch, Button, Modal } from '../../../components/ui'
import { agentApi, agentKeys } from '../../../services/agent-api'
import VariableSelector from '../VariableSelector'
import HelpHint from '../HelpHint'
import type { WorkflowNode } from '../../../services/workflows-api'

/** response 结构字段（与后端 _VALID_FIELD_TYPES 一致） */
interface ResponseField {
  name: string
  type: 'string' | 'number' | 'boolean' | 'enum' | 'object'
  /** 列表标志：任何基础类型都可为列表（string 列表 / enum 列表 / object 列表） */
  is_list?: boolean
  required?: boolean
  enum_values?: string[]
  description?: string
  /** object 类型字段的子字段（可继续嵌套，建议 ≤3 层，后端防御上限 5 层） */
  fields?: ResponseField[]
}

interface ResponseSchema {
  type: 'text' | 'object' | 'array'
  fields?: ResponseField[]
}

const RESPONSE_TYPE_OPTIONS = [
  { value: 'text', label: '文本（默认）' },
  { value: 'object', label: '对象 { }' },
  { value: 'array', label: '数组 [ ]' },
]

/** 类型下拉（所有层级统一；列表/嵌套由开关组合表达） */
const FIELD_TYPE_OPTIONS = [
  { value: 'string', label: '文本' },
  { value: 'number', label: '数字' },
  { value: 'boolean', label: '布尔' },
  { value: 'enum', label: '枚举' },
  { value: 'object', label: '对象' },
]

/* ─── 路径式字段树操作（支持任意层嵌套的不可变更新的） ─── */

type FieldPath = number[]

function mapAt(
  list: ResponseField[], path: FieldPath, fn: (f: ResponseField) => ResponseField,
): ResponseField[] {
  const [head, ...rest] = path
  return list.map((f, i) => {
    if (i !== head) return f
    if (rest.length === 0) return fn(f)
    return { ...f, fields: mapAt(f.fields ?? [], rest, fn) }
  })
}

function removeAt(list: ResponseField[], path: FieldPath): ResponseField[] {
  const [head, ...rest] = path
  if (rest.length === 0) return list.filter((_, i) => i !== head)
  return list.map((f, i) => (i === head ? { ...f, fields: removeAt(f.fields ?? [], rest) } : f))
}

/** 「自评模式」一键模板：模糊自判变成封闭枚举，配合网关/信息不足分支路由 */
const SELF_ASSESS_TEMPLATE: ResponseField[] = [
  {
    name: 'status',
    type: 'enum',
    required: true,
    enum_values: ['completed', 'insufficient_info'],
    description: 'completed=任务完成；insufficient_info=信息不足（建议同时配置信息不足分支）',
  },
  { name: 'summary', type: 'string', required: true, description: '结果摘要（信息不足时说明缺什么）' },
  { name: 'assumptions', type: 'string', required: false, description: '执行中所做的关键假设' },
]

/* ─── 结构预览：根据当前契约生成示例 JSON，让用户所见即所得 ─── */

/** 生成字段示例占位值（尖括号包字段名，类型可辨；enum 用第一个枚举值） */
function sampleValue(field: ResponseField): unknown {
  const base = (): unknown => {
    switch (field.type) {
      case 'number':
        return 0
      case 'boolean':
        return true
      case 'enum':
        return field.enum_values?.[0] ?? `<${field.name || '值'}>`
      case 'object': {
        const obj: Record<string, unknown> = {}
        for (const g of field.fields ?? []) {
          if (g.name) obj[g.name] = sampleValue(g)
        }
        return obj
      }
      default:
        return `<${field.name || '文本'}>`
    }
  }
  return field.is_list ? [base()] : base()
}

/** response 的完整示例结构（text = 纯文本示例；array = 单元素示例数组） */
function buildResponseSample(schema: ResponseSchema | null): unknown {
  if (!schema || schema.type === 'text') return '<Agent 回复的文本内容>'
  const obj: Record<string, unknown> = {}
  for (const f of schema.fields ?? []) {
    if (f.name) obj[f.name] = sampleValue(f)
  }
  return schema.type === 'array' ? [obj] : obj
}

/** 首个可引用字段的路径（递归钻到第一个叶子；列表带 .0 示例下标） */
function firstRefPath(schema: ResponseSchema | null): string {
  if (!schema || schema.type === 'text') return ''
  const walk = (fields: ResponseField[]): string => {
    for (const f of fields) {
      if (!f.name) continue
      const prefix = f.is_list ? `${f.name}.0` : f.name
      if (f.type === 'object' && f.fields?.length) {
        const sub = walk(f.fields)
        if (sub) return `${prefix}.${sub}`
      }
      return prefix
    }
    return ''
  }
  return walk(schema.fields ?? [])
}

interface Props {
  config: Record<string, unknown>
  onChange: (c: Record<string, unknown>) => void
  currentNodeId: string
  allNodes: WorkflowNode[]
}

export default function AgentNodeConfig({ config, onChange, currentNodeId, allNodes }: Props) {
  const { data: agentsData, isLoading } = useQuery({
    queryKey: agentKeys.list({ page: 1, page_size: 100, status: 'published' }),
    queryFn: () => agentApi.list({ page: 1, page_size: 100, status: 'published' }),
  })

  const agents = agentsData?.items ?? []
  const agentOptions = agents.map((a) => ({
    value: a.id,
    label: `${a.name} (${a.id.substring(0, 8)}...)`,
  }))

  // 选择 Agent 时同步缓存 agent_name / agent_model——画布节点卡信息区
  // 展示用，避免跨组件拉取名称映射（改名后需重选才会刷新缓存）。
  const handleAgentChange = (val: string | null) => {
    const agent = val ? agents.find((a) => a.id === val) : undefined
    onChange({
      ...config,
      agent_id: val ?? '',
      agent_name: agent?.name ?? '',
      agent_model: agent?.default_model ?? '',
    })
  }

  // 查询内容变更（作为 user message）
  const handleInputQueryChange = (val: string) => {
    onChange({ ...config, input_query: val })
  }

  // 上下文变更（注入 Agent 的 context 卡槽）
  const handleContextChange = (val: string) => {
    onChange({ ...config, input_prompt: val })
  }

  // ── 返回结构（response_schema）──
  const responseSchema = (config.response_schema as ResponseSchema | null) ?? null
  const schemaType: ResponseSchema['type'] = responseSchema?.type ?? 'text'
  const fields = responseSchema?.fields ?? []

  const setSchema = (schema: ResponseSchema | null) => {
    onChange({ ...config, response_schema: schema })
  }

  const setSchemaType = (t: string | null) => {
    const nextType = (t ?? 'text') as ResponseSchema['type']
    if (nextType === 'text') {
      setSchema(null)
      return
    }
    setSchema({ type: nextType, fields: fields.length > 0 ? fields : [{ name: '', type: 'string' }] })
  }

  const setFields = (next: ResponseField[]) => {
    setSchema({ ...(responseSchema as ResponseSchema), fields: next })
  }

  /** 路径式更新：patch 指定位置的字段（任意嵌套深度） */
  const updateAt = (path: FieldPath, patch: Partial<ResponseField>) => {
    setFields(mapAt(fields, path, (f) => ({ ...f, ...patch })))
  }

  /**
   * 表单式字段行（任意层通用）：字段名 / 类型 / 必填 / 列表 / 删除 +
   * 枚举值行 + 说明行；对象（或对象列表）行下递归渲染缩进的子字段区。
   */
  const renderFieldRow = (
    field: ResponseField,
    path: FieldPath,
  ) => {
    const onPatch = (patch: Partial<ResponseField>) => updateAt(path, patch)
    return (
      <div key={path.join('.')} className="space-y-1.5 border-t border-[#27272a] pt-2">
        <div className="grid grid-cols-[1fr_92px_32px_32px_44px] gap-1.5 items-center">
          <Input
            placeholder="字段名（如 status）"
            value={field.name}
            onChange={(e) => onPatch({ name: e.target.value })}
          />
          <Select
            className="w-full"
            value={field.type}
            onChange={(val) => onPatch({ type: (val ?? 'string') as ResponseField['type'] })}
            options={FIELD_TYPE_OPTIONS}
          />
          <div className="flex items-center justify-center" title="必填">
            <Switch
              size="small"
              checked={!!field.required}
              onChange={(checked) => onPatch({ required: checked })}
            />
          </div>
          <div className="flex items-center justify-center" title="列表（任何类型都可为列表，如对象列表）">
            <Switch
              size="small"
              checked={!!field.is_list}
              onChange={(checked) => onPatch({ is_list: checked })}
            />
          </div>
          <Button size="small" onClick={() => setFields(removeAt(fields, path))}>删除</Button>
        </div>
        {field.type === 'enum' && (
          <Input
            placeholder="枚举值（逗号分隔，如 completed,insufficient_info）"
            value={(field.enum_values ?? []).join(',')}
            onChange={(e) =>
              onPatch({
                enum_values: e.target.value.split(',').map((s) => s.trim()).filter(Boolean),
              })
            }
          />
        )}
        <Input
          placeholder="说明（可选，写入 Agent 提示帮助其理解字段含义）"
          value={field.description ?? ''}
          onChange={(e) => onPatch({ description: e.target.value })}
        />

        {/* 对象（或对象列表）：行下递归渲染缩进的子字段区，任意层可继续嵌套（建议 ≤3 层） */}
        {field.type === 'object' && (
          <div className="ml-3 border-l-2 border-[#3f3f46] pl-2.5 space-y-1.5">
            <div className="flex items-center justify-between">
              <span className="text-[10px] text-[#71717a]">
                {field.name || '（未命名）'}的子字段
                {field.is_list ? '（对象列表的元素结构）' : '（嵌套对象）'}
              </span>
              <Button
                size="small"
                onClick={() =>
                  onPatch({ fields: [...(field.fields ?? []), { name: '', type: 'string' }] })
                }
              >
                加子字段
              </Button>
            </div>
            {(field.fields ?? []).map((sub, subIdx) => renderFieldRow(sub, [...path, subIdx]))}
          </div>
        )}
      </div>
    )
  }

  // ── 放大编辑（Modal 大空间填写，与面板内嵌编辑实时同步同一份 config） ──
  const [zoomOpen, setZoomOpen] = useState(false)

  /** 结构预览：示例 JSON + 下游引用写法（改字段即时刷新，所见即所得） */
  const renderSchemaPreview = () => {
    const sample = buildResponseSample(responseSchema)
    const refPath = firstRefPath(responseSchema)
    const refExample = refPath
      ? `{{${currentNodeId}.response.${refPath}}}`
      : `{{${currentNodeId}.response}}`
    return (
      <div className="rounded bg-[#09090b] border border-[#27272a] p-2 min-w-0">
        <div className="text-[10px] text-[#a1a1aa] mb-1">response 数据结构预览</div>
        <pre className="text-[11px] leading-relaxed font-mono text-[#d4d4d8] whitespace-pre-wrap break-all">
          {JSON.stringify(sample, null, 2)}
        </pre>
        <div className="text-[10px] text-[#a1a1aa] mt-1.5 pt-1.5 border-t border-[#27272a]">
          下游引用示例：<code className="font-mono text-[#60A5FA] break-all">{refExample}</code>
        </div>
      </div>
    )
  }

  /** response 行摘要（面板内不展开字段详情，点击进弹窗查看/编辑）。 */
  const responseSummary =
    schemaType === 'text'
      ? '纯文本'
      : `${schemaType === 'object' ? '对象' : '数组'} · ${
          fields.length === 0 ? '未定义字段' : `${fields.length} 个字段`
        }`

  /** 返回结构编辑区：类型选择 + JSON 形态的字段树（操作即展示） */
  const renderSchemaEditor = () => (
    <>
      <Select
        className="w-full"
        value={schemaType}
        onChange={setSchemaType}
        options={RESPONSE_TYPE_OPTIONS}
      />

      {schemaType !== 'text' && (
        <div className="rounded bg-[#09090b] border border-[#27272a] px-2.5 py-2 space-y-2">
          {fields.map((field, idx) => renderFieldRow(field, [idx]))}
          <button
            type="button"
            onClick={() => setFields([...fields, { name: '', type: 'string' }])}
            className="text-[10px] text-[#60A5FA] hover:underline cursor-pointer"
          >
            + 加字段
          </button>
        </div>
      )}

      {schemaType !== 'text' && (
        <div className="flex gap-1.5 justify-end">
          <Button
            size="small"
            onClick={() =>
              setFields(SELF_ASSESS_TEMPLATE.map((f) => ({
                ...f,
                enum_values: [...(f.enum_values ?? [])],
              })))
            }
          >
            自评模式模板
          </Button>
        </div>
      )}
    </>
  )

  return (
    <div className="space-y-3">
      {/* Agent 选择 */}
      <div>
        <label className="block text-xs text-slate-400 mb-1">Agent</label>
        {isLoading ? (
          <Spin size="small" />
        ) : (
          <Select
            className="w-full"
            value={(config.agent_id as string) || null}
            onChange={handleAgentChange}
            options={agentOptions}
            placeholder="选择 Agent..."
            showSearch
            filterOption={(input, option) =>
              (String(option?.label ?? '').toLowerCase().includes(input.toLowerCase()))
            }
            allowClear
          />
        )}
      </div>

      {/* 查询（必填）→ user message */}
      <div>
        <VariableSelector
          label="查询"
          value={config.input_query as string ?? ''}
          onChange={handleInputQueryChange}
          currentNodeId={currentNodeId}
          allNodes={allNodes}
          placeholder="作为用户消息发送给 Agent，支持 {{变量}} ..."
          rows={2}
          required
        />
      </div>

      {/* 上下文（可选）→ 注入 context 卡槽 */}
      <div>
        <VariableSelector
          label="上下文"
          labelExtra={<HelpHint text="此内容会作为工作流上下文注入 Agent 的「上下文」提示卡槽，覆盖其默认值。角色、任务、约束等仍由 Agent 自身配置决定。" />}
          value={config.input_prompt as string ?? ''}
          onChange={handleContextChange}
          currentNodeId={currentNodeId}
          allNodes={allNodes}
          placeholder="注入到 Agent 的 context 卡槽，支持 {{变量}} ..."
          rows={3}
        />
      </div>

      {/* 超时（temperature/max_retry/信息不足分支已从面板移除——引擎按
          默认值执行：温度与重试沿用节点默认配置，abort 诚实终止） */}
      <div>
        <label className="block text-xs text-slate-400 mb-1 flex items-center gap-1">
          超时 (ms)
          <HelpHint text="Agent 节点无人值守执行（不会暂停询问用户），超时后按失败处理并触发重试。" />
        </label>
        <Input
          type="number"
          value={(config.timeout_ms as number) ?? 300000}
          onChange={(e) => onChange({ ...config, timeout_ms: parseInt(e.target.value) || 300000 })}
          min={1000}
          step={1000}
        />
      </div>

      {/* 输出变量：全部引擎输出变量一览（用户知道下游可用什么）。
          仅 response 可编辑（弹窗内查看/编辑结构），其余为固定只读。 */}
      <div className="border border-slate-700/60 rounded-md p-2.5 space-y-1.5">
        <div className="flex items-center gap-1">
          <label className="text-xs text-slate-400">输出变量</label>
          <HelpHint
            text={
              '下游节点可引用的输出变量。response 是 Agent 的核心返回内容——默认纯文本，' +
              '点击它可改为对象/数组并定义字段结构（Agent 回复不符合结构时会自动重试一次）；' +
              '其余变量由引擎固定提供，无需配置。'
            }
          />
        </div>

        {/* response：唯一可编辑项（面板内仅显示摘要，详情在弹窗） */}
        <button
          type="button"
          onClick={() => setZoomOpen(true)}
          className="w-full flex items-center gap-1.5 text-left rounded border border-[#27272a] bg-[#09090b] px-2 py-1.5 hover:border-[#1E5EFF]/50 transition-colors cursor-pointer"
        >
          <span className="text-[10px] font-medium text-[#60A5FA]">response</span>
          <span className="text-[9px] text-[#71717a] truncate">{responseSummary}</span>
          <span className="ml-auto shrink-0 text-[9px] text-[#60A5FA]">查看 / 编辑</span>
        </button>

        {/* 引擎固定输出（只读） */}
        {[
          { name: 'agent_id', desc: '执行的 Agent' },
          { name: 'files', desc: '产出文件列表' },
          { name: 'usage', desc: 'Token 用量' },
        ].map((v) => (
          <div
            key={v.name}
            className="flex items-center gap-1.5 rounded border border-[#27272a] px-2 py-1.5"
          >
            <span className="text-[10px] font-medium text-[#a1a1aa]">{v.name}</span>
            <span className="text-[9px] text-[#71717a]">
              {v.desc} · 固定
            </span>
          </div>
        ))}
      </div>

      {/* 放大编辑：左编辑右预览，改字段即时看到最终数据结构 */}
      <Modal
        open={zoomOpen}
        title="返回结构（response）"
        width={720}
        okText="完成"
        cancelText="关闭"
        onOk={() => setZoomOpen(false)}
        onCancel={() => setZoomOpen(false)}
      >
        <div className="grid grid-cols-[1fr_260px] gap-3 items-start">
          <div className="space-y-2 max-h-[65vh] overflow-y-auto pr-1">
            {renderSchemaEditor()}
          </div>
          <div className="sticky top-0 max-h-[65vh] overflow-y-auto">
            {renderSchemaPreview()}
          </div>
        </div>
      </Modal>
    </div>
  )
}

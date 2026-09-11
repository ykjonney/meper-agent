/**
 * ToolNodeConfig — 工具节点配置面板。
 *
 * - 工具选择为左右 Tab 选择器：「工具库」（组织治理 openapi/code，
 *   listEnabled 单一来源）与「MCP 工具」（按连接折叠分组，默认收起）；
 *   技能（markdown/skill）不是工具——不进候选，由 Agent 节点绑定使用
 * - Params 按所选工具的 llm_args_schema 结构化渲染（参数名/说明/必填，
 *   值支持 {{ node.field }} 引用上游输出）；schema 缺失时回退 JSON 文本域
 * - JSON 回退域非法时不写回 config（防脏数据）
 */
import { useEffect, useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, Search } from 'lucide-react'
import { Input, Popover, Spin } from '../../../components/ui'
import { toolsApi, toolKeys, type Tool } from '../../../services/tools-api'
import { userToolsApi, userToolKeys, type EnabledToolItem } from '../../../services/user-tools-api'
import { mcpApi, mcpKeys } from '../../../services/mcp-api'
import VariableSelector from '../VariableSelector'
import HelpHint from '../HelpHint'
import type { WorkflowNode } from '../../../services/workflows-api'

interface Props {
  config: Record<string, unknown>
  onChange: (c: Record<string, unknown>) => void
  currentNodeId: string
  allNodes: WorkflowNode[]
}

/** JSON 文本域：合法时提交 config，非法时保留草稿并标错（不写脏数据） */
function JsonField({
  label,
  helpText,
  value,
  onCommit,
  currentNodeId,
  allNodes,
  rows = 4,
  placeholder,
}: {
  label: string
  helpText?: string
  value: Record<string, unknown> | undefined
  onCommit: (parsed: Record<string, unknown>) => void
  currentNodeId: string
  allNodes: WorkflowNode[]
  rows?: number
  placeholder?: string
}) {
  const [draft, setDraft] = useState(() => JSON.stringify(value ?? {}, null, 2))
  const [invalid, setInvalid] = useState(false)

  // 外部 config 变化（节点切换 / 变量插入）时重置草稿
  useEffect(() => {
    setDraft(JSON.stringify(value ?? {}, null, 2))
    setInvalid(false)
  }, [value])

  return (
    <div>
      <label className="flex items-center gap-1 text-xs text-slate-400 mb-1">
        {label}
        {helpText && <HelpHint text={helpText} />}
      </label>
      <VariableSelector
        value={draft}
        onChange={(val) => {
          setDraft(val)
          try {
            onCommit(JSON.parse(val))
            setInvalid(false)
          } catch {
            setInvalid(true)
          }
        }}
        currentNodeId={currentNodeId}
        allNodes={allNodes}
        placeholder={placeholder}
        rows={rows}
      />
      {invalid && <p className="text-xs text-red-500 mt-1">JSON 格式有误，修正后才会保存</p>}
    </div>
  )
}

interface McpGroup {
  connId: string
  label: string
  tools: Tool[]
}

/**
 * 工具选择器：左右 Tab（工具库 / MCP 工具）。
 * 工具库平铺（已开启，治理模型）；MCP 按连接折叠分组（默认收起，工具多不淹没）。
 * 选中即关闭；支持在当前 Tab 内搜索。
 */
function ToolPicker({
  value,
  onSelect,
  enabledTools,
  mcpGroups,
  loading,
}: {
  value: string
  onSelect: (id: string) => void
  enabledTools: EnabledToolItem[]
  mcpGroups: McpGroup[]
  loading: boolean
}) {
  const [open, setOpen] = useState(false)
  const [tab, setTab] = useState<'library' | 'mcp'>('library')
  const [search, setSearch] = useState('')
  const [expandedConns, setExpandedConns] = useState<Set<string>>(new Set())

  const q = search.trim().toLowerCase()
  const filteredLibrary = q
    ? enabledTools.filter((t) => t.name.toLowerCase().includes(q) || t.description?.toLowerCase().includes(q))
    : enabledTools
  const filteredGroups = useMemo(() => mcpGroups.map((g) => ({
    ...g,
    tools: q ? g.tools.filter((t) => t.name.toLowerCase().includes(q)) : g.tools,
  })).filter((g) => g.tools.length > 0), [mcpGroups, q])

  // 打开时重置交互态（搜索清空、MCP 分组收起、回到默认 Tab）
  useEffect(() => {
    if (open) {
      setSearch('')
      setExpandedConns(new Set())
    }
  }, [open])

  const selectedName = (id: string) =>
    enabledTools.find((t) => t.id === id)?.name
    ?? mcpGroups.flatMap((g) => g.tools).find((t) => t.id === id)?.name
    ?? ''

  const toggleConn = (connId: string) => {
    setExpandedConns((prev) => {
      const next = new Set(prev)
      if (next.has(connId)) next.delete(connId)
      else next.add(connId)
      return next
    })
  }

  const rowCls = (active: boolean) =>
    `w-full text-left px-2.5 py-1.5 rounded-md text-xs cursor-pointer transition-colors ${
      active
        ? 'bg-blue-600/15 text-blue-400'
        : 'text-slate-300 hover:bg-[#1c1c1f]'
    }`

  return (
    <Popover
      open={open}
      onOpenChange={setOpen}
      trigger="click"
      content={
        <div className="w-[300px]">
          {/* 左右 Tab */}
          <div className="flex border-b border-[#27272a]">
            {([['library', `工具库（${enabledTools.length}）`], ['mcp', `MCP 工具（${mcpGroups.reduce((n, g) => n + g.tools.length, 0)}）`]] as const).map(([key, label]) => (
              <button
                key={key}
                onClick={() => { setTab(key); setSearch('') }}
                className={`flex-1 px-3 py-2 text-xs font-medium cursor-pointer border-b-2 -mb-px transition-colors ${
                  tab === key
                    ? 'border-blue-600 text-blue-400'
                    : 'border-transparent text-slate-500 hover:text-slate-300'
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {/* 搜索 */}
          <div className="relative p-2">
            <Search size={12} className="absolute left-4 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder={`搜索${tab === 'library' ? '工具库' : 'MCP 工具'}…`}
              className="w-full pl-7 pr-2 py-1.5 rounded-md text-xs border border-[#27272a] bg-[#121214] text-slate-200 outline-none focus:border-blue-500"
            />
          </div>

          <div className="max-h-64 overflow-y-auto px-2 pb-2 space-y-0.5">
            {loading && <div className="py-6 flex justify-center"><Spin size="small" /></div>}
            {!loading && tab === 'library' && (
              filteredLibrary.length === 0
                ? <p className="py-6 text-center text-xs text-slate-400">暂无已开启的工具</p>
                : filteredLibrary.map((t) => (
                  <button key={t.id} onClick={() => { onSelect(t.id); setOpen(false) }}
                    className={rowCls(value === t.id)}>
                    <span className="font-medium">{t.name}</span>
                    {t.description && (
                      <span className="block text-[10px] text-slate-400 truncate">{t.description}</span>
                    )}
                  </button>
                ))
            )}
            {!loading && tab === 'mcp' && (
              filteredGroups.length === 0
                ? <p className="py-6 text-center text-xs text-slate-400">暂无 MCP 工具</p>
                : filteredGroups.map((g) => (
                  <div key={g.connId}>
                    <button
                      onClick={() => toggleConn(g.connId)}
                      className="w-full flex items-center gap-1.5 px-2 py-1.5 rounded-md text-xs font-medium text-slate-400 hover:bg-[#1c1c1f] cursor-pointer"
                    >
                      <ChevronRight size={12} className={`transition-transform ${expandedConns.has(g.connId) ? 'rotate-90' : ''}`} />
                      {g.label}
                      <span className="ml-auto text-[10px] text-slate-400">{g.tools.length}</span>
                    </button>
                    {expandedConns.has(g.connId) && (
                      <div className="ml-4 space-y-0.5">
                        {g.tools.map((t) => (
                          <button key={t.id} onClick={() => { onSelect(t.id); setOpen(false) }}
                            className={rowCls(value === t.id)}>
                            <span className="font-medium">{t.name}</span>
                            {t.description && (
                              <span className="block text-[10px] text-slate-400 truncate">{t.description}</span>
                            )}
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                ))
            )}
          </div>
        </div>
      }
    >
      {/* 触发器（样式对齐 Select） */}
      <div className="w-full flex items-center justify-between gap-2 px-2.5 py-1.5 rounded-md text-xs border border-[#27272a] bg-[#121214] cursor-pointer hover:border-blue-500 transition-colors">
        <span className={value && selectedName(value) ? 'text-slate-100' : 'text-slate-500'}>
          {value && selectedName(value) ? selectedName(value) : '选择工具…'}
        </span>
        <ChevronDown size={13} className="text-slate-400 shrink-0" />
      </div>
    </Popover>
  )
}

export default function ToolNodeConfig({ config, onChange, currentNodeId, allNodes }: Props) {
  // 候选：工具库（openapi/code 官方 active + 组织库已开启，listEnabled 单一来源）
  // + tools 表的 mcp（技能 markdown/skill 不是工具，不进候选——由 Agent 节点使用）
  const { data: toolsData, isLoading } = useQuery({
    queryKey: toolKeys.list({ page: 1, page_size: 100 }),
    queryFn: () => toolsApi.list({ page: 1, page_size: 100 }),
  })
  const { data: enabledTools = [] } = useQuery({
    queryKey: userToolKeys.enabled(),
    queryFn: () => userToolsApi.listEnabled(),
  })
  // MCP 连接（工具按连接分组展示）
  const { data: connData } = useQuery({
    queryKey: mcpKeys.list({ page: 1, page_size: 100 }),
    queryFn: () => mcpApi.list({ page: 1, page_size: 100 }),
  })

  const mcpTools: Tool[] = (toolsData?.items ?? []).filter(
    (t) => !t.id.startsWith('uto_') && t.source === 'mcp',
  )
  const connNameById = new Map((connData?.items ?? []).map((c) => [c.id, c.name]))
  const mcpGroups: McpGroup[] = (() => {
    const byConn = new Map<string, Tool[]>()
    for (const t of mcpTools) {
      const connId = t.mcp_connection_id || ''
      if (!byConn.has(connId)) byConn.set(connId, [])
      byConn.get(connId)!.push(t)
    }
    return [...byConn.entries()].map(([connId, tools]) => ({
      connId,
      label: connNameById.get(connId) ?? '未分组连接',
      tools,
    }))
  })()

  const selected: EnabledToolItem | undefined = enabledTools.find((t) => t.id === config.tool_id)
  const schemaProps = (((selected?.llm_args_schema ?? {}) as Record<string, unknown>)
    .properties ?? {}) as Record<string, { type?: string; description?: string }>
  const schemaRequired = new Set(
    (((selected?.llm_args_schema ?? {}) as Record<string, unknown>).required as string[]) ?? [],
  )
  const paramKeys = Object.keys(schemaProps)
  const params = (config.params as Record<string, unknown>) ?? {}

  const findToolName = (id: string) =>
    enabledTools.find((t) => t.id === id)?.name
    ?? mcpTools.find((t) => t.id === id)?.name
    ?? ''

  const handleToolChange = (val: string) => {
    onChange({
      ...config,
      tool_id: val,
      tool_name: findToolName(val),
      tool_source: enabledTools.find((t) => t.id === val)?.source
        ?? (mcpTools.find((t) => t.id === val) ? 'mcp' : ''),
      // 返回字段声明快照：变量选择器按此平铺 {{node.result.字段}}（重新选择工具即刷新）
      tool_output_schema: (enabledTools.find((t) => t.id === val)?.output_schema ?? {}) as Record<string, unknown>,
      params: {}, // 换工具后参数定义不同——清空旧值防误传
    })
  }

  const setParam = (key: string, value: string) => {
    const next = { ...params }
    if (value === '') delete next[key]
    else next[key] = value
    onChange({ ...config, params: next })
  }

  return (
    <div className="space-y-3">
      <div>
        <label className="flex items-center gap-1 text-xs text-slate-400 mb-1">
          工具
          <HelpHint text="「工具库」为组织治理工具（已开启可直接调用）；「MCP 工具」按外部连接分组（点击连接展开）。技能类由 Agent 节点绑定使用，不在工具节点选择" />
        </label>
        <ToolPicker
          value={(config.tool_id as string) || ''}
          onSelect={handleToolChange}
          enabledTools={enabledTools}
          mcpGroups={mcpGroups}
          loading={isLoading}
        />
      </div>

      {paramKeys.length > 0 ? (
        <div>
          <label className="flex items-center gap-1 text-xs text-slate-400 mb-1">
            参数（{paramKeys.length} 项）
            <HelpHint text="按工具定义的运行参数填写；值可输入固定文本或 {{ node.field }} 引用上游节点输出" />
          </label>
          <div className="space-y-1.5">
            {paramKeys.map((key) => (
              <div key={key} className="flex items-center gap-2">
                <label className="w-24 shrink-0 text-xs text-slate-400 truncate" title={key}>
                  {key}
                  {schemaRequired.has(key) && <span className="text-red-500"> *</span>}
                </label>
                <div className="flex-1 min-w-0">
                  <VariableSelector
                    value={(params[key] as string) ?? ''}
                    onChange={(val) => setParam(key, val)}
                    currentNodeId={currentNodeId}
                    allNodes={allNodes}
                    placeholder={schemaProps[key]?.description || ''}
                    rows={1}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      ) : (
        selected && (
          <JsonField
            label="Params (JSON，支持模板变量)"
            helpText="该工具未定义运行参数——如需传额外字段可在此填写，值支持 {{ node.field }} 模板变量"
            value={config.params as Record<string, unknown> | undefined}
            onCommit={(parsed) => onChange({ ...config, params: parsed })}
            currentNodeId={currentNodeId}
            allNodes={allNodes}
            placeholder='{"key": "{{ node.field }}"}'
          />
        )
      )}
      <div>
        <label className="block text-xs text-slate-400 mb-1">超时 (ms)</label>
        <Input
          type="number"
          value={(config.timeout_ms as number) ?? 30000}
          onChange={(e) => onChange({ ...config, timeout_ms: parseInt(e.target.value) || 30000 })}
          min={1000}
          step={1000}
        />
      </div>
    </div>
  )
}

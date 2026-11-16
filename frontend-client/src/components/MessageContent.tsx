import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  CopyOutlined,
  FileOutlined,
  FileTextOutlined,
  OrderedListOutlined,
  CheckOutlined,
  LoadingOutlined,
  QuestionCircleOutlined,
  RedoOutlined,
  RobotOutlined,
  SafetyCertificateOutlined,
  ToolOutlined,
} from '@ant-design/icons'
import { Mermaid } from '@ant-design/x'
import { App, Button, Collapse, Image, Tag, Tooltip, Typography } from 'antd'
import { isValidElement, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'

import { downloadSessionFile, downloadUploadedFile } from '../api/chat'
import {
  DISMISSED_CLARIFICATION_TEXT,
  type AttachmentView,
  type ChatMessage,
  type ContentBlock,
  type ToolRun,
} from '../types'
import { ChartBlock } from './ChartBlock'
import { parseTaskCreated } from './WorkflowTaskCard'
import { WorkflowTaskInlineCard } from './WorkflowTaskInlineCard'

/** 特殊工具:不参与聚合,各自独立渲染(WorkflowTaskCard / chat 层 HITL)。 */
const SPECIAL_TOOLS = new Set([
  'dispatch_workflow',
  'ask_clarification',
  'confirm_workflow',
  'request_app_authorization',
  'delegate_to_subagent',
  'todo_write',
])

/** 一段连续的普通工具分组。特殊工具作为独立的 ToolRun 单独渲染,打断聚合。 */
type ToolGroup =
  | { kind: 'group'; tools: ToolRun[] }
  | { kind: 'single'; tool: ToolRun }

/** 渲染段:把 content blocks 拆成有序的渲染单元,保留 text/reasoning/tool 的交错顺序。 */
type RenderSegment =
  | { kind: 'text'; text: string }
  | { kind: 'reasoning'; text: string }
  | { kind: 'tools'; group: ToolGroup }

/** 遍历 content blocks,产出按原始顺序排列的渲染段。
 * - text block → text 段(Markdown)
 * - reasoning block → reasoning 段(思考过程 Collapse)
 * - 连续的 tool block → 用 groupTools 聚合(≥2 个普通工具合成一个卡片)
 * text 和 reasoning 不合并,各自独立成段。 */
function toRenderSegments(blocks: ContentBlock[]): RenderSegment[] {
  const segments: RenderSegment[] = []
  let toolBuffer: ToolRun[] = []
  const flushTools = () => {
    if (!toolBuffer.length) return
    for (const group of groupTools(toolBuffer)) {
      segments.push({ kind: 'tools', group })
    }
    toolBuffer = []
  }
  for (const block of blocks) {
    if (block.type === 'tool') {
      toolBuffer.push(block.tool)
    } else {
      flushTools()
      segments.push(
        block.type === 'text'
          ? { kind: 'text', text: block.text }
          : { kind: 'reasoning', text: block.text },
      )
    }
  }
  flushTools()
  return segments
}

/** ── v7.1 过程段聚合（主人定稿）：
 *  连续的 thinking/tool 块（无 text 隔断）= 一个执行段，合并为
 *  「执行了 x 个工具」一行（含思考——展开看段内思考折叠行 + 每工具明细）。
 *  例外：段内只有 thinking 无 tool → 不出合并行，只显示思考行本身。 */
type FlatSegment =
  | { kind: 'text'; text: string }
  | {
      kind: 'process'
      items: Array<{ type: 'thinking'; text: string } | { type: 'tool'; tool: ToolRun }>
    }

function toFlatSegments(blocks: ContentBlock[]): FlatSegment[] {
  const segs: FlatSegment[] = []
  let buf: Extract<FlatSegment, { kind: 'process' }> | null = null
  const flush = () => {
    if (buf) {
      segs.push(buf)
      buf = null
    }
  }
  for (const block of blocks) {
    if (block.type === 'text') {
      flush()
      segs.push({ kind: 'text', text: block.text })
      continue
    }
    const item =
      block.type === 'reasoning'
        ? ({ type: 'thinking', text: block.text } as const)
        : ({ type: 'tool', tool: block.tool } as const)
    if (!buf) buf = { kind: 'process', items: [item] }
    else buf.items.push(item)
  }
  flush()
  return segs
}

/** 共享的 react-markdown components 配置(无光标)。 */
const MARKDOWN_COMPONENTS: Components = {
  a: ({ href, children: label }) => (
    <a href={href} target="_blank" rel="noreferrer">
      {label}
    </a>
  ),
  code: ({ className, children: codeChildren, ...props }) => {
    const language = /language-([^\s]+)/.exec(className ?? '')?.[1]
    const source = String(codeChildren).replace(/\n$/, '')
    if (language === 'echarts' || language === 'chart') {
      return <ChartBlock source={source} />
    }
    if (language === 'mermaid') {
      return <Mermaid>{source}</Mermaid>
    }
    return (
      <code className={className} {...props}>
        {codeChildren}
      </code>
    )
  },
  pre: ({ children: preChildren, ...props }) =>
    isValidElement(preChildren) &&
    (preChildren.type === ChartBlock || preChildren.type === Mermaid) ? (
      preChildren
    ) : (
      <pre {...props}>{preChildren}</pre>
    ),
  table: ({ children: tableChildren, ...props }) => (
    <div className="markdown-table-wrap">
      <table {...props}>{tableChildren}</table>
    </div>
  ),
}

/** Markdown 渲染(带统一的 components 配置)。 */
function Markdown({ children }: { children: string }) {
  return (
    <div className="md-host">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={MARKDOWN_COMPONENTS}>
        {children}
      </ReactMarkdown>
    </div>
  )
}

/** 中文"字数"口径（Word/WPS 同款，与 studio countZi 一致）：CJK 字符（含中文
 *  标点）每字计 1，连续的非 CJK 非空白串（英文单词、数字、emoji 等）整体计 1。
 *  思考内容多为英文，逐字符计数会数倍虚高于视觉感知。 */
const countZi = (s: string): number => {
  const cjkRe = /[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\u3000-\u30ff\uff00-\uffef]/
  let n = 0
  let inRun = false
  for (const ch of s) {
    if (cjkRe.test(ch)) {
      n += 1
      inRun = false
    } else if (/\s/.test(ch)) {
      inRun = false
    } else if (!inRun) {
      n += 1
      inRun = true
    }
  }
  return n
}

/** 思考面板 —— 对齐 studio ThinkingEntryCard 行为：
 * - 流式期间（streaming）：展开 + 头部三点动效 + 内容贴底跟随 + 末尾打字光标；
 * - 本轮思考结束（后续 text/tool 块到达）：自动收起（用户手动操作过则尊重用户），
 *   头部变静态「思考过程」+ 字数；
 * - 内容按纯文本 pre-wrap 渲染（思考是原始文本，流式期间半截 Markdown 会渲染错乱），
 *   限高内部滚动，长思考不撑爆消息流。 */
function ReasoningPanel({ text, streaming }: { text: string; streaming: boolean }) {
  const [open, setOpen] = useState(streaming)
  const [userToggled, setUserToggled] = useState(false)
  const contentRef = useRef<HTMLDivElement>(null)

  // 流式状态切换时跟随展开/收起（用户手动操作过则不再自动）
  useEffect(() => {
    if (userToggled) return
    setOpen(streaming)
  }, [streaming, userToggled])

  // 流式期间内容超出限高时，内部滚动贴底跟随最新输出
  useEffect(() => {
    if (streaming && contentRef.current) {
      contentRef.current.scrollTop = contentRef.current.scrollHeight
    }
  }, [text, streaming])

  return (
    <Collapse
      className={`reasoning-panel${streaming ? ' reasoning-panel-streaming' : ''}`}
      ghost
      size="small"
      activeKey={open ? ['reasoning'] : []}
      onChange={(keys) => {
        setUserToggled(true)
        setOpen((Array.isArray(keys) ? keys : [keys]).length > 0)
      }}
      items={[
        {
          key: 'reasoning',
          label: (
            <span className="reasoning-label">
              {streaming ? (
                <>
                  正在思考
                  <span className="streaming-dots" aria-hidden="true">
                    <span />
                    <span />
                    <span />
                  </span>
                </>
              ) : (
                <>
                  思考过程
                  {text ? (
                    <span className="reasoning-count">{countZi(text)} 字</span>
                  ) : null}
                </>
              )}
            </span>
          ),
          children: (
            <div ref={contentRef} className="reasoning-text">
              {text}
              {streaming ? <span className="reasoning-caret">▍</span> : null}
            </div>
          ),
        },
      ]}
    />
  )
}

function promotedCharts(blocks: ContentBlock[]): string[] {
  const seen = new Set<string>()
  const charts: string[] = []
  for (const block of blocks) {
    if (block.type !== 'tool') continue
    const tool = block.tool
    if (tool.name !== 'render_chart' || !tool.result) continue
    const match = tool.result.match(/```(?:echarts|chart)\s*\n([\s\S]*?)\n```/i)
    const source = match?.[1]?.trim()
    if (!source || seen.has(source)) continue
    seen.add(source)
    charts.push(source)
  }
  return charts
}

function statusIcon(tool: ToolRun): ReactNode {
  if (tool.status === 'running') return <ClockCircleOutlined spin />
  if (tool.status === 'error') return <CloseCircleOutlined />
  return <CheckCircleOutlined />
}

/** 从 parse_file 的 args(JSON 字符串)里取展示文件名(path basename 或 file_id)。 */
function parseFileName(args?: string): string {
  try {
    const a: { path?: string; file_id?: string } = args ? JSON.parse(args) : {}
    const raw = String(a.path || a.file_id || '')
    return raw.split('/').pop() || '文件'
  } catch {
    return '文件'
  }
}

/** parse_file 成功结果 → 专属文件解析卡片(FileText 图标 + 文件名 + 元信息 Tag，
 * 内容 Markdown 渲染)。失败([parse_file] 前缀错误)回落到通用工具卡。 */
function ParseFileCard({ tool }: { tool: ToolRun }) {
  const meta = /^# .+（(.+?)）/.exec(tool.result ?? '')
  return (
    <Collapse
      className={`tool-run tool-run-${tool.status}`}
      size="small"
      ghost
      items={[
        {
          key: tool.id,
          label: (
            <div className="tool-title">
              {statusIcon(tool)}
              <FileTextOutlined />
              <span>文件解析 · {parseFileName(tool.args)}</span>
              {meta ? <Tag style={{ margin: 0 }}>{meta[1]}</Tag> : null}
            </div>
          ),
          children: (
            <div className="tool-details">
              <div className="tool-result-body">
                <Markdown>{tool.result ?? ''}</Markdown>
              </div>
            </div>
          ),
        },
      ]}
    />
  )
}

/** 从 delegate_to_subagent 的 args 里解析 {subagent_name, task}。 */
function parseSubagentArgs(args?: string): { name: string; task: string } {
  try {
    const a: { subagent_name?: string; task?: string } = args ? JSON.parse(args) : {}
    return { name: String(a.subagent_name || '子 Agent'), task: String(a.task || '') }
  } catch {
    return { name: '子 Agent', task: '' }
  }
}

/** 委派子 Agent 专属卡片:标题直接显示"哪个子 Agent 在执行什么"——
 * 用户一眼看到执行主体,而不是一个叫 delegate_to_subagent 的工具名。
 * 执行中显示动态文案;完成展开可见委派任务与结论。 */
function SubagentCard({ tool }: { tool: ToolRun }) {
  const { name, task } = parseSubagentArgs(tool.args)
  const running = tool.status === 'running'
  return (
    <Collapse
      className={`tool-run tool-run-${tool.status}`}
      size="small"
      ghost
      items={[
        {
          key: tool.id,
          label: (
            <div className="tool-title">
              {statusIcon(tool)}
              <RobotOutlined />
              <span>{running ? `${name} 正在执行子任务…` : `子 Agent · ${name}`}</span>
            </div>
          ),
          children: (
            <div className="tool-details">
              {task ? (
                <div className="tool-delegation-task">
                  <Typography.Text type="secondary">委派任务</Typography.Text>
                  <Typography.Paragraph
                    style={{ marginBottom: 8, whiteSpace: 'pre-wrap' }}
                    ellipsis={{ rows: 6, expandable: true, symbol: '展开全部' }}
                  >
                    {task}
                  </Typography.Paragraph>
                </div>
              ) : null}
              <div className="tool-result-body">
                <Markdown>{tool.result ?? ''}</Markdown>
              </div>
            </div>
          ),
        },
      ]}
    />
  )
}

/** 解析 todo_write 的 args → 清单项数组(失败回退空,走通用卡片)。 */
function parseTodoArgs(args?: string): { content: string; status: string }[] {
  try {
    const a: { todos?: { content?: unknown; status?: unknown }[] } = args
      ? JSON.parse(args)
      : {}
    if (!Array.isArray(a.todos)) return []
    return a.todos
      .filter((t): t is { content: string; status: string } => typeof t === 'object' && t !== null)
      .map((t) => ({
        content: String(t.content ?? ''),
        status: String(t.status ?? 'pending'),
      }))
  } catch {
    return []
  }
}

const TODO_STATUS_GLYPH: Record<string, string> = {
  pending: '☐',
  in_progress: '◐',
  completed: '☑',
}

/** todo_write 专属卡片:checkbox 清单(全量替换语义,卡片展示该次更新的
 * 完整清单快照)。完成项划线灰显、进行中高亮,摘要行显示完成度。 */
function TodoCard({ tool }: { tool: ToolRun }) {
  const todos = parseTodoArgs(tool.args)
  if (!todos.length) return null
  const done = todos.filter((t) => t.status === 'completed').length
  return (
    <div className={`todo-card tool-run-${tool.status}`}>
      <div className="todo-card-header">
        <OrderedListOutlined />
        <span className="todo-card-label">任务清单</span>
        <span className="todo-card-count">
          {done}/{todos.length} 完成
        </span>
      </div>
      <ul className="todo-card-list">
        {todos.map((t, i) => (
          <li key={i} className={`todo-item todo-item-${t.status}`}>
            <span className="todo-item-glyph">{TODO_STATUS_GLYPH[t.status] ?? '☐'}</span>
            <span className="todo-item-content">{t.content}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** 把扁平的 tools 数组按连续性分成"普通工具组"和"特殊工具"交替序列。
 * 特殊工具(dispatch_workflow / ask_clarification / confirm_workflow)独立成项,
 * 打断前后普通工具的聚合;连续的普通工具合并成一个 group。 */
function groupTools(tools: ToolRun[]): ToolGroup[] {
  const groups: ToolGroup[] = []
  let buffer: ToolRun[] = []
  for (const tool of tools) {
    if (SPECIAL_TOOLS.has(tool.name)) {
      if (buffer.length) {
        groups.push({ kind: 'group', tools: buffer })
        buffer = []
      }
      groups.push({ kind: 'single', tool })
    } else {
      buffer.push(tool)
    }
  }
  if (buffer.length) groups.push({ kind: 'group', tools: buffer })
  return groups
}

/** 工具名改写（对齐 studio chat/tool-details.tsx 的 toolSummary）：
 *  用户读的是「在做什么」（动词 + 关键参数）而非工具名。 */
function toolSummary(name: string, argsJson?: string): { verb: string; detail: string } {
  let args: Record<string, unknown> = {}
  try {
    args = argsJson ? (JSON.parse(argsJson) as Record<string, unknown>) : {}
  } catch { /* ignore */ }
  const pick = (...keys: string[]) => {
    for (const k of keys) if (args[k] != null && String(args[k])) return String(args[k])
    return ''
  }
  if (name === 'bash' || name === 'run_command' || name === 'execute')
    return { verb: '执行命令', detail: pick('command', 'cmd', 'script').replace(/\s*\n\s*/g, ' ').trim() }
  if (name === 'read_file' || name === 'read')
    return { verb: '读取文件', detail: pick('path', 'file_path', 'file_id', 'file') }
  if (name === 'write_file' || name === 'write' || name === 'create_file')
    return { verb: '写入文件', detail: pick('path', 'file_path', 'file') }
  if (name === 'edit_file' || name === 'edit' || name === 'apply_patch')
    return { verb: '编辑文件', detail: pick('path', 'file_path', 'file') }
  if (name === 'glob' || name === 'list_files' || name === 'list_dir')
    return { verb: '查找文件', detail: pick('pattern', 'path', 'dir') }
  if (name === 'grep' || name === 'search_content')
    return { verb: '搜索内容', detail: pick('pattern', 'query', 'keyword') }
  if (name === 'web_search' || name === 'search_web')
    return { verb: '搜索网页', detail: pick('query', 'keyword', 'q') }
  if (name === 'fetch_url' || name === 'open_url')
    return { verb: '访问网页', detail: pick('url', 'link') }
  if (name === 'render_chart')
    return { verb: '生成图表', detail: pick('title', 'chart_type') }
  if (name === 'parse_file')
    return { verb: '解析文件', detail: pick('path', 'file_id', 'file') }
  if (name === 'load_skill' || name === 'load_skills')
    return { verb: '加载技能', detail: pick('skill_name', 'name', 'skill') }
  if (name === 'delegate_to_subagent')
    return { verb: '委派子任务', detail: pick('subagent_name', 'task') }
  if (name === 'propose_plan')
    return { verb: '提交执行计划', detail: '' }
  if (name === 'dispatch_workflow')
    return { verb: '调度工作流', detail: pick('workflow_name', 'workflow_id') }
  if (name === 'ask_clarification')
    return { verb: '发起澄清', detail: '' }
  if (name === 'kb_retrieve' || name === 'search_kb')
    return { verb: '知识库检索', detail: pick('query', 'keyword') }
  if (name === 'todo_write')
    return { verb: '更新任务清单', detail: '' }
  // MCP 工具名剥掉 mcp__<server>__ 前缀（未映射工具的可读化兜底）
  return { verb: name.replace(/^mcp__[^_]+__/, '') || '调用工具', detail: '' }
}

/** 改写摘要单行：「动词 · 关键参数」（detail 为空则只返回动词）。 */
function toolSummaryText(name: string, argsJson?: string): string {
  const { verb, detail } = toolSummary(name, argsJson)
  return detail ? `${verb} · ${detail}` : verb
}

/** 单个工具节点的详情(请求参数 / 执行结果),timeline 中点击节点后行内展开。
 *  load_skill 不展示内容（技能全文对终端用户无意义）。 */
function ToolNodeDetails({ tool }: { tool: ToolRun }) {
  if (tool.name === 'load_skill' || tool.name === 'load_skills') return null
  return (
    <div className="tool-node-details">
      {tool.args ? (
        <section>
          <Typography.Text type="secondary">请求参数</Typography.Text>
          <pre>{tool.args}</pre>
        </section>
      ) : null}
      {tool.result ? (
        <section>
          <Typography.Text type="secondary">执行结果</Typography.Text>
          <div className="tool-result-body">
            <Markdown>{tool.result}</Markdown>
          </div>
        </section>
      ) : tool.status === 'running' ? (
        <Typography.Text type="secondary">正在执行...</Typography.Text>
      ) : null}
    </div>
  )
}

/** 聚合工具组:一行摘要(数量 + 状态)+ 展开后以 timeline(节点 + 竖线串联)列出工具,
 * 让用户清楚看到执行了哪些工具、进行到第几步。每个 timeline 节点可点击,行内展开
 * 该工具的请求参数/执行结果。折叠/展开交给 antd Collapse,不做「结束自动收缩」。 */
function ToolRunsGroup({ tools }: { tools: ToolRun[] }) {
  const running = tools.filter((t) => t.status === 'running')
  const errored = tools.filter((t) => t.status === 'error')
  const completedCount = tools.length - running.length - errored.length
  const isRunning = running.length > 0
  const hasError = errored.length > 0

  // 行内展开详情的工具 id(null = 都不展开)
  const [expandedToolId, setExpandedToolId] = useState<string | null>(null)

  // ── 执行中直接暴露（v6.2，Manus 同款时序）：running 时 timeline 自动展开
  //  （每个工具行实时可见：✓ 已完成的 + ● 当前执行带完整参数摘要），
  //  整组落定后自动收起合并为「使用了 N 个工具」。用户手动收起过则尊重。 */
  const [userToggled, setUserToggled] = useState(false)
  const [open, setOpen] = useState(isRunning)
  useEffect(() => {
    if (userToggled) return
    setOpen(isRunning)
  }, [isRunning, userToggled])

  // 整体状态图标:任一 running→转圈,任一 error→红叉,否则→绿勾
  const overallIcon = isRunning ? (
    <ClockCircleOutlined spin />
  ) : hasError ? (
    <CloseCircleOutlined />
  ) : (
    <CheckCircleOutlined />
  )

  // 卡片状态类:运行中 tool-run-running;整组落定后回中性(失败红底)。
  const cls = isRunning ? 'running' : hasError ? 'error' : 'complete'

  // 摘要文案：running 时「N/M 完成 · 动词 参数摘要」——detail 截断防长命令
  // 撑爆摘要行；不再叠加「正在执行」（spinner 已表达进行中，双动词冗余）。
  const runningVerb = running.length === 1 ? toolSummary(running[0].name, running[0].args).verb : ''
  const runningDetail = running.length === 1 ? toolSummary(running[0].name, running[0].args).detail : ''
  const runningShort = runningDetail.length > 36 ? `${runningDetail.slice(0, 36)}…` : runningDetail
  const durSum = tools.reduce((s, t) => s + (t.durationMs ?? 0), 0)
  const durLabel = durSum > 0 ? ` · ${(durSum / 1000).toFixed(1)}s` : ''
  const summary = isRunning
    ? running.length === 1
      ? `${completedCount}/${tools.length} 完成 · ${runningVerb}${runningShort ? ` ${runningShort}` : ''}`
      : `${completedCount}/${tools.length} 完成 · 正在执行 ${running.length} 个工具`
    : `执行了 ${tools.length} 个工具${durLabel}`

  return (
    <Collapse
      className={`tool-run tool-run-group tool-run-${cls}`}
      size="small"
      ghost
      activeKey={open ? ['group'] : []}
      onChange={(keys) => {
        setUserToggled(true)
        setOpen((Array.isArray(keys) ? keys : [keys]).length > 0)
      }}
      items={[
        {
          key: 'group',
          label: (
            <div className="tool-title">
              {overallIcon}
              <ToolOutlined />
              <span>{summary}</span>
            </div>
          ),
          children: (
            <ol className="tool-timeline-list">
              {(() => {
                const segments = batchSegments(tools)
                return segments.map((seg, segIndex) => {
                const isLast = segIndex === segments.length - 1
                // 并行批（≥2 个连续 tool_call）：整体一行「执行了 x 个命令/工具」
                if (seg.length >= 2) {
                  const allBash = seg.every((t) =>
                    ['bash', 'run_command', 'execute'].includes(t.name),
                  )
                  const durSum = seg.reduce((s, t) => s + (t.durationMs ?? 0), 0)
                  const label = allBash
                    ? `执行了 ${seg.length} 个命令`
                    : `执行了 ${seg.length} 个工具`
                  return (
                    <li
                      key={`batch-${seg[0].id}`}
                      className={`tool-timeline-node tool-timeline-node-batch${isLast ? ' tool-timeline-node-last' : ''}`}
                    >
                      <div className="tool-timeline-node-row">
                        <span className="tool-timeline-node-icon">
                          {seg.some((t) => t.status === 'error') ? (
                            <CloseCircleOutlined />
                          ) : (
                            <CheckCircleOutlined />
                          )}
                        </span>
                        <span className="tool-timeline-node-label">
                          <ToolOutlined />
                          <span className="tool-timeline-node-name">{label}</span>
                          {durSum > 0 ? (
                            <span className="tool-timeline-node-dur">{(durSum / 1000).toFixed(1)}s</span>
                          ) : null}
                        </span>
                      </div>
                    </li>
                  )
                }
                const tool = seg[0]
                const isOpen = expandedToolId === tool.id
                return (
                  <li
                    key={tool.id}
                    className={`tool-timeline-node tool-timeline-node-${tool.status}${isOpen ? ' tool-timeline-node-open' : ''}${isLast ? ' tool-timeline-node-last' : ''}`}
                  >
                    <button
                      type="button"
                      className="tool-timeline-node-row"
                      onClick={() => setExpandedToolId(isOpen ? null : tool.id)}
                      aria-expanded={isOpen}
                    >
                      <span className="tool-timeline-node-icon">{statusIcon(tool)}</span>
                      <span className="tool-timeline-node-label">
                        <ToolOutlined />
                        <span className="tool-timeline-node-name">{toolSummaryText(tool.name, tool.args)}</span>
                        {tool.auto ? <Tag className="tool-timeline-node-tag">自动召回</Tag> : null}
                        {tool.durationMs ? (
                          <span className="tool-timeline-node-dur">{(tool.durationMs / 1000).toFixed(1)}s</span>
                        ) : null}
                      </span>
                    </button>
                    {isOpen ? (
                      <div className="tool-timeline-node-details-wrap">
                        <ToolNodeDetails tool={tool} />
                      </div>
                    ) : null}
                  </li>
                )
                })
              })()}
            </ol>
          ),
        },
      ]}
    />
  )
}

/** 按 batchId 分段：同批（一轮并行 tool_call）聚合为一段，单工具独立段。
 *  batchId undefined（旧数据）各自成段，保持逐行显示。 */
function batchSegments(tools: ToolRun[]): ToolRun[][] {
  const segments: ToolRun[][] = []
  for (const tool of tools) {
    const last = segments[segments.length - 1]
    if (tool.batchId != null && last && last[0].batchId === tool.batchId) {
      last.push(tool)
    } else {
      segments.push([tool])
    }
  }
  return segments
}

/** 解析 tool.args(JSON 字符串)为对象,失败返回空对象。 */
function parseToolArgs(tool: ToolRun): Record<string, unknown> {
  try {
    return tool.args ? JSON.parse(tool.args) : {}
  } catch {
    return {}
  }
}

/** ask_clarification 已答卡片:显示问题 + 用户的回答(参考 studio ClarificationCard 已答态)。
 * 等待回答时(tool 无 result)显示精简的"等待回答"提示(实际交互在 ChatView HITL Alert)。
 * 配色:蓝色(问答/澄清语义)。 */
function ClarificationAnsweredCard({ tool }: { tool: ToolRun }) {
  const args = parseToolArgs(tool)
  const question = String(args.question ?? '请补充信息后继续。')
  const answered = !!tool.result
  const dismissed = tool.result === DISMISSED_CLARIFICATION_TEXT

  // 解析 fields 拿到 name→label 映射
  const rawFields = args.fields
  let fieldLabels: Record<string, string> = {}
  if (Array.isArray(rawFields)) {
    for (const f of rawFields as Array<Record<string, unknown>>) {
      if (f.name && f.label) fieldLabels[String(f.name)] = String(f.label)
    }
  } else if (typeof rawFields === 'string' && rawFields) {
    try {
      const parsed = JSON.parse(rawFields)
      if (Array.isArray(parsed)) {
        for (const f of parsed) {
          if (f.name && f.label) fieldLabels[f.name] = f.label
        }
      }
    } catch { /* ignore */ }
  }

  // 解析回答结果（JSON 字符串 → 键值对）
  let answerPairs: Array<[string, string]> | null = null
  if (answered && tool.result) {
    try {
      const parsed = JSON.parse(tool.result)
      if (typeof parsed === 'object' && parsed && !Array.isArray(parsed)) {
        answerPairs = Object.entries(parsed).map(([k, v]) => [
          fieldLabels[k] || k,
          typeof v === 'boolean' ? (v ? '是' : '否') : String(v),
        ])
      }
    } catch { /* not JSON, show raw */ }
  }

  return (
    <div className="interactive-card interactive-card-clarification">
      <div className="interactive-card-header">
        <QuestionCircleOutlined />
        <span className="interactive-card-label">澄清提问</span>
        {answered ? (
          dismissed ? (
            <Tag style={{ margin: 0 }}>已忽略</Tag>
          ) : (
            <Tag color="blue" style={{ margin: 0 }}>已回答</Tag>
          )
        ) : (
          <Tag style={{ margin: 0 }}>等待回答</Tag>
        )}
      </div>
      <div className="interactive-card-inner">
        <div className="interactive-card-question">{question}</div>
        {dismissed ? (
          <div className="interactive-card-answer">
            <span>已忽略此问题——可直接在输入框重新描述需求或上传文件</span>
          </div>
        ) : answered && tool.result ? (
          <div className="interactive-card-answer">
            {answerPairs ? (
              <div className="clarification-form-answered">
                {answerPairs.map(([label, val]) => (
                  <div key={label} className="clarification-form-row">
                    <span className="clarification-form-key">{label}</span>
                    <span className="clarification-form-val">{val}</span>
                  </div>
                ))}
              </div>
            ) : (
              <span>{tool.result}</span>
            )}
          </div>
        ) : null}
      </div>
    </div>
  )
}

/** confirm_workflow 已答卡片:显示工作流信息 + 确认/拒绝结果。
 * 等待回答时显示精简的"等待确认"提示。
 * 配色:紫色(工作流/自动化语义)。 */
function WorkflowConfirmAnsweredCard({ tool }: { tool: ToolRun }) {
  const args = parseToolArgs(tool)
  const workflowName = String(args.workflow_name ?? '')
  const description = String(args.description ?? '')
  const params = (args.params ?? {}) as Record<string, unknown>
  const answered = !!tool.result
  const isConfirmed = answered && !/取消|拒绝|忽略|cancel/i.test(tool.result ?? '')

  return (
    <div className="interactive-card interactive-card-workflow">
      <div className="interactive-card-header">
        <RobotOutlined />
        <span className="interactive-card-label">工作流确认</span>
        {answered ? (
          <Tag color={isConfirmed ? 'success' : 'default'} style={{ margin: 0 }}>
            {isConfirmed ? '已确认' : '已取消'}
          </Tag>
        ) : (
          <Tag style={{ margin: 0 }}>等待确认</Tag>
        )}
      </div>
      <div className="interactive-card-inner">
        {workflowName ? (
          <div className="interactive-card-row">
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>工作流:</Typography.Text>
            <Tag color="purple" style={{ margin: 0 }}>{workflowName}</Tag>
          </div>
        ) : null}
        {description ? (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>{description}</Typography.Text>
        ) : null}
        {Object.keys(params).length > 0 ? (
          <div className="interactive-card-params">
            <Typography.Text type="secondary" style={{ fontSize: 12 }}>输入参数:</Typography.Text>
            {Object.entries(params).map(([key, value]) => (
              <div key={key} className="interactive-card-param">
                <span className="interactive-card-param-key">{key}</span>
                <span className="interactive-card-param-value">
                  {typeof value === 'string' ? value : JSON.stringify(value)}
                </span>
              </div>
            ))}
          </div>
        ) : null}
      </div>
    </div>
  )
}

/** request_app_authorization 已答卡片：显示待授权应用 + 处理结果。
 * 等待授权时(tool 无 result)显示"等待授权"提示（实际交互在 ChatView 的
 * 授权表单卡）。独立成卡而非并入工具组——等待期间若作为普通工具渲染，
 * 会让同组已完成/失败的工具跟着变 running 样式。
 * 注意：tool.result 是给 LLM 的恢复指令（"请继续执行任务…"），不展示原文，
 * 只以固定文案表达结果。配色:琥珀(授权/凭证语义)。 */
function AppAuthorizationCard({ tool }: { tool: ToolRun }) {
  const args = parseToolArgs(tool)
  const appName = String(args.app_name ?? args.app_id ?? '应用')
  const answered = !!tool.result
  const declined = answered && /暂不授权|拒绝/.test(tool.result ?? '')

  return (
    <div className="interactive-card interactive-card-auth">
      <div className="interactive-card-header">
        <SafetyCertificateOutlined />
        <span className="interactive-card-label">应用授权</span>
        {answered ? (
          <Tag color={declined ? 'default' : 'success'} style={{ margin: 0 }}>
            {declined ? '✗ 已拒绝' : '✓ 已授权'}
          </Tag>
        ) : (
          <Tag style={{ margin: 0 }}>等待授权</Tag>
        )}
      </div>
      <div className="interactive-card-inner">
        <div className="interactive-card-question">{appName}</div>
        {answered ? (
          <div className="interactive-card-answer">
            <span>{declined ? '已按你的选择跳过授权' : '授权完成，任务继续执行'}</span>
          </div>
        ) : (
          <Typography.Text type="secondary" style={{ fontSize: 12 }}>
            请在下方完成授权（或选择暂不授权）
          </Typography.Text>
        )}
      </div>
    </div>
  )
}

function ToolResult({
  tool,
  onOpenTaskBoard,
}: {
  tool: ToolRun
  onOpenTaskBoard?: (taskId: string) => void
}) {
  // dispatch_workflow：解析 task_created → 单行状态卡（详情/轮询/操作在任务看板）。
  // 解析失败则落到下方通用工具结果渲染。
  if (tool.name === 'dispatch_workflow') {
    const created = parseTaskCreated(tool.result)
    if (created)
      return <WorkflowTaskInlineCard created={created} onOpenBoard={onOpenTaskBoard} />
  }
  // ask_clarification：已答时显示"问题→回答"卡片(参考 studio ClarificationCard 已答态)。
  if (tool.name === 'ask_clarification') {
    return <ClarificationAnsweredCard tool={tool} />
  }
  // confirm_workflow：已答时显示"工作流确认→确认/拒绝"卡片。
  if (tool.name === 'confirm_workflow') {
    return <WorkflowConfirmAnsweredCard tool={tool} />
  }
  // request_app_authorization：等待授权/已授权/已拒绝 独立卡片。
  if (tool.name === 'request_app_authorization') {
    return <AppAuthorizationCard tool={tool} />
  }
  // parse_file：成功解析 → 专属文件解析卡片(文件名 + 元信息 + Markdown 内容)。
  if (
    tool.name === 'parse_file' &&
    tool.result &&
    !tool.result.startsWith('[parse_file]')
  ) {
    return <ParseFileCard tool={tool} />
  }
  // delegate_to_subagent：子 Agent 委派专属卡片(直接显示执行主体名)。
  if (tool.name === 'delegate_to_subagent') {
    return <SubagentCard tool={tool} />
  }
  // todo_write：任务清单专属卡片(checkbox 清单快照)。解析失败落通用卡片。
  if (tool.name === 'todo_write' && parseTodoArgs(tool.args).length) {
    return <TodoCard tool={tool} />
  }
  // load_skill：只显示「加载技能 · 技能名」一行，内容（技能全文）不展示。
  if (tool.name === 'load_skill' || tool.name === 'load_skills') {
    return (
      <div className={`tool-run tool-run-${tool.status} tool-run-plain`}>
        <div className="tool-title">
          {statusIcon(tool)}
          <span>{toolSummaryText(tool.name, tool.args)}</span>
        </div>
      </div>
    )
  }
  return (
    <Collapse
      className={`tool-run tool-run-${tool.status}`}
      size="small"
      ghost
      items={[
        {
          key: tool.id,
          label: (
            <div className="tool-title">
              {statusIcon(tool)}
              <ToolOutlined />
              <span>{toolSummaryText(tool.name, tool.args)}</span>
              {tool.auto ? <Tag>自动召回</Tag> : null}
              {tool.durationMs ? (
                <span className="tool-dur">{(tool.durationMs / 1000).toFixed(1)}s</span>
              ) : null}
            </div>
          ),
          children: (
            <div className="tool-details">
              {tool.args ? (
                <section>
                  <Typography.Text type="secondary">请求参数</Typography.Text>
                  <pre>{tool.args}</pre>
                </section>
              ) : null}
              {tool.result ? (
                <section>
                  <Typography.Text type="secondary">执行结果</Typography.Text>
                  <div className="tool-result-body">
                    <Markdown>{tool.result}</Markdown>
                  </div>
                </section>
              ) : tool.status === 'running' ? (
                <Typography.Text type="secondary">正在执行...</Typography.Text>
              ) : null}
            </div>
          ),
        },
      ]}
    />
  )
}

function AttachmentItem({
  attachment,
  sessionId,
}: {
  attachment: AttachmentView
  sessionId: string
}) {
  const { message } = App.useApp()
  if (attachment.kind === 'image' && attachment.url) {
    return (
      <Image
        className="message-image"
        src={attachment.url}
        alt={attachment.name}
        preview
      />
    )
  }
  return (
    <Button
      className="message-file"
      icon={<FileOutlined />}
      onClick={() => {
        const download =
          attachment.source === 'upload'
            ? downloadUploadedFile(attachment.id, attachment.name)
            : downloadSessionFile(sessionId, attachment.name)
        void download.catch(() =>
          message.error('文件下载失败'),
        )
      }}
    >
      {attachment.name}
    </Button>
  )
}

interface MessageContentProps {
  message: ChatMessage
  sessionId: string
  /** dispatch_workflow 一行状态卡点击 → ChatView 打开工作流任务看板并定位。 */
  onOpenTaskBoard?: (taskId: string) => void
  /** 重新生成（仅最后一条 assistant 消息传入）：用上一条用户输入重发。 */
  onRegenerate?: () => void
}


/** 执行段合并行（v7.3 主人定稿）：文本之间的一段执行过程（连续 thinking+tool，
 *  含思考）合并为「执行了 x 个工具」一行，点击展开——段内思考折叠行 + 工具命令
 *  直显行交错（renderProcessItems），并行批仍合并「执行了 x 命令」。 */
function ProcessGroup({ items, onOpenTaskBoard }: {
  items: Extract<FlatSegment, { kind: 'process' }>['items']
  onOpenTaskBoard?: (taskId: string) => void
}) {
  const [open, setOpen] = useState(false)
  const tools = items
    .filter((i): i is Extract<typeof items[number], { type: 'tool' }> => i.type === 'tool')
    .map((i) => i.tool)
  const running = tools.some((t) => t.status === 'running')
  const durSum = tools.reduce((s, t) => s + (t.durationMs ?? 0), 0)
  return (
    <div className="process-group">
      <div
        className="process-group-head"
        onClick={() => setOpen((v) => !v)}
        role="button"
        tabIndex={0}
      >
        <span className={`activity-dot ${running ? 'is-running' : 'is-done'}`}>
          {running ? <LoadingOutlined /> : <CheckOutlined />}
        </span>
        <span className="process-group-title">执行了 {tools.length} 个工具</span>
        {durSum > 0 ? (
          <span className="process-group-dur">{(durSum / 1000).toFixed(1)}s</span>
        ) : null}
      </div>
      {open ? (
        <div className="process-group-body">{renderProcessItems(items, onOpenTaskBoard)}</div>
      ) : null}
    </div>
  )
}

/** 单工具直接行（v7.1 终稿）：命令直接显示，点击展开请求参数/结果明细。 */
function ToolLine({ tool, onOpenTaskBoard }: {
  tool: ToolRun
  onOpenTaskBoard?: (taskId: string) => void
}) {
  const [open, setOpen] = useState(false)
  return (
    <div className="tool-line">
      <button
        type="button"
        className="tool-line-row"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className="tool-timeline-node-icon">{statusIcon(tool)}</span>
        <span className="tool-timeline-node-label">
          <span className="tool-timeline-node-name">{toolSummaryText(tool.name, tool.args)}</span>
          {tool.durationMs ? (
            <span className="tool-timeline-node-dur">{(tool.durationMs / 1000).toFixed(1)}s</span>
          ) : null}
        </span>
      </button>
      {open ? (
        <div className="tool-line-details">
          <ToolNodeDetails tool={tool} />
        </div>
      ) : null}
    </div>
  )
}

/** 并行批合并行（例外规则）：一轮调用了多个工具 → 整体一行「执行了 x 命令/工具」，
 *  点击展开批内每工具明细。 */
function BatchRow({ tools }: { tools: ToolRun[] }) {
  const [open, setOpen] = useState(false)
  const allBash = tools.every((t) => ['bash', 'run_command', 'execute'].includes(t.name))
  const durSum = tools.reduce((s, t) => s + (t.durationMs ?? 0), 0)
  return (
    <div className="tool-line">
      <button
        type="button"
        className="tool-line-row"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className="tool-timeline-node-icon">{statusIcon(tools[0])}</span>
        <span className="tool-timeline-node-label">
          <span className="tool-line-batch-label">
            执行了 {tools.length} {allBash ? '命令' : '工具'}
          </span>
          {durSum > 0 ? (
            <span className="tool-timeline-node-dur">{(durSum / 1000).toFixed(1)}s</span>
          ) : null}
        </span>
      </button>
      {open ? (
        <div className="tool-line-details">
          {tools.map((tool) => (
            <div key={tool.id} className="tool-line-sub">
              <div className="tool-line-row" style={{ cursor: 'default' }}>
                <span className="tool-timeline-node-icon">{statusIcon(tool)}</span>
                <span className="tool-timeline-node-label">
                  <span className="tool-timeline-node-name">{toolSummaryText(tool.name, tool.args)}</span>
                  {tool.durationMs ? (
                    <span className="tool-timeline-node-dur">{(tool.durationMs / 1000).toFixed(1)}s</span>
                  ) : null}
                </span>
              </div>
              <ToolNodeDetails tool={tool} />
            </div>
          ))}
        </div>
      ) : null}
    </div>
  )
}

/** 过程段内容渲染（v7.1 终稿）：思考行与工具行按原始顺序交错；
 *  一轮并行多工具（同 batchId）合并为一行「执行了 x 命令/工具」。 */
function renderProcessItems(
  items: Array<{ type: 'thinking'; text: string } | { type: 'tool'; tool: ToolRun }>,
  onOpenTaskBoard?: (taskId: string) => void,
): ReactNode[] {
  const rows: ReactNode[] = []
  const done = new Set<string>()
  items.forEach((item, i) => {
    if (item.type === 'thinking') {
      rows.push(<ReasoningPanel key={`p-think:${i}`} text={item.text} streaming={false} />)
      return
    }
    if (done.has(item.tool.id)) return
    const batch =
      item.tool.batchId != null
        ? items
            .filter(
              (x): x is Extract<typeof items[number], { type: 'tool' }> =>
                x.type === 'tool' && x.tool.batchId === item.tool.batchId,
            )
            .map((x) => x.tool)
        : []
    if (batch.length >= 2) {
      batch.forEach((t) => done.add(t.id))
      rows.push(
        <BatchRow
          key={`p-batch:${batch[0].id}`}
          tools={batch}
        />,
      )
    } else {
      done.add(item.tool.id)
      rows.push(<ToolLine key={`p-tool:${item.tool.id}`} tool={item.tool} onOpenTaskBoard={onOpenTaskBoard} />)
    }
  })
  return rows
}

/** 过程外壳（v7.1 主人定稿）：最外部唯一一行——「✓ 已完成 · 执行了 N 个工具 · 用时」，
 *  点击展开内部过程（思考折叠行 / 文本之间的工具组合并行 / 中间叙述文本平铺）。 */
function ActivityCard({ durationLabel, children }: {
  durationLabel?: string
  children: ReactNode
}) {
  const [open, setOpen] = useState(false)
  return (
    <div className="activity-card">
      <div
        className="activity-card-head"
        onClick={() => setOpen((v) => !v)}
        role="button"
        tabIndex={0}
      >
        <span className="activity-dot is-done">
          <CheckOutlined />
        </span>
        <span className="activity-title">已完成</span>
        {/* v7.3：外壳只显示状态 + 用时——「执行了 x 个工具」在内部文本之间 */}
        {durationLabel ? <span className="activity-meta">{durationLabel}</span> : null}
      </div>
      {open ? <div className="activity-body">{children}</div> : null}
    </div>
  )
}

export function MessageContent({ message, sessionId, onOpenTaskBoard, onRegenerate }: MessageContentProps) {
  const { message: toast } = App.useApp()
  // 快捷指令消息：user 气泡只渲染展示文案（label），隐藏实际发送给 AI 的指令。
  // 下游 segments / charts / fullText（复制）全部基于替换后的内容，保证不泄漏。
  const content: ContentBlock[] =
    message.role === 'user' && message.displayText
      ? [{ type: 'text', text: message.displayText }]
      : message.content
  const charts = [...promotedCharts(content), ...message.charts]
  const segments = toRenderSegments(content)
  // ── 过程/回答分割（final 权威锚点，对齐 studio MessageItem 语义）──
  // anchor = 最后一个 final=true 的 text block。流式中只认真 final（挂起/
  // 中间态无 final → 全量平铺，澄清卡等 HITL 卡正常渲染）；非流式兜底最后
  // 一个 text（历史终态，旧数据无 final 标志时最后 text 即答案）。
  // 完成后：anchor 之前的 reasoning/tool 聚合为过程折叠卡，final text 平铺
  // 在卡外作为回答；复制内容也只取回答区。 */
  const isStreaming = message.status === 'loading'
  let finalAnchor = -1
  let lastTextIdx = -1
  content.forEach((b, i) => {
    if (b.type !== 'text') return
    lastTextIdx = i
    if (b.final) finalAnchor = i
  })
  const anchor = finalAnchor >= 0 ? finalAnchor : isStreaming ? -1 : lastTextIdx
  const activityBlocks = anchor > 0 ? content.slice(0, anchor) : []
  const answerContent = anchor >= 0 ? content.slice(anchor) : content
  const answerSegments = anchor >= 0 ? toRenderSegments(answerContent) : segments
  const activityToolCount = activityBlocks.filter((b) => b.type === 'tool').length
  // 执行耗时（「已完成 · 用时X」）：llm+tool 毫秒求和 → 秒（1 位小数）
  const durationLabel = (() => {
    const ms = (message.execDuration?.llm ?? 0) + (message.execDuration?.tool ?? 0)
    if (!ms) return undefined
    return `${(ms / 1000).toFixed(1)}s`
  })()
  /** 渲染单个段（reasoning 折叠面板 / text Markdown / 工具卡）——过程卡明细
   *  与回答区共用同一套段渲染。 */
  const renderSegment = (segment: ReturnType<typeof toRenderSegments>[number], index: number) => {
    if (segment.kind === 'reasoning') {
      const streaming = message.status === 'loading' && index === (segments.length - 1)
      return <ReasoningPanel key={`seg:${index}`} text={segment.text} streaming={streaming} />
    }
    if (segment.kind === 'text') {
      return <Markdown key={`seg:${index}`}>{segment.text}</Markdown>
    }
    const { group } = segment
    if (group.kind === 'single') {
      return (
        <ToolResult
          key={group.tool.id}
          tool={group.tool}
          onOpenTaskBoard={onOpenTaskBoard}
        />
      )
    }
    return <ToolRunsGroup key={`group:${index}`} tools={group.tools} />
  }
  // 兜底去重:同名附件可能被上游重复收集,按 id 收敛,避免重复渲染 + 重复 React key
  const uniqueAttachments = useMemo(() => {
    const map = new Map<string, AttachmentView>()
    for (const att of message.attachments) map.set(att.id, att)
    return Array.from(map.values())
  }, [message.attachments])
  // 复制内容 = 回答区 text（final 锚点之后）；过程区 reasoning 不进复制
  const fullText = answerContent
    .filter((b): b is ContentBlock & { type: 'text' } => b.type === 'text')
    .map((b) => b.text)
    .join('')
  return (
    <div className={`message-content message-content-${message.role}`}>
      {/* v7.1 外壳（主人定稿）：「✓ 已完成 · 用时」最外部唯一一行（不显示工具数），
          点击展开内部过程——执行段合并行「执行了 x 个工具」（含思考）/ 中间叙述文本平铺。
          流式中不渲染外壳（过程平铺可见：思考行 + 工具组摘要实时表达当前阶段）。 */}
      {activityBlocks.length > 0 ? (
        <ActivityCard durationLabel={durationLabel}>
          {toFlatSegments(activityBlocks).map((seg, index) => {
            if (seg.kind === 'text') {
              return <Markdown key={`flat:${index}`}>{seg.text}</Markdown>
            }
            // 纯思考段（无工具）：不出合并行，只显示思考行（「只有一个思考」例外）
            const hasTool = seg.items.some((i) => i.type === 'tool')
            if (!hasTool) {
              return (
                <div key={`flat:${index}`}>
                  {seg.items.map((item, i) =>
                    item.type === 'thinking' ? (
                      <ReasoningPanel key={`flat-think:${index}:${i}`} text={item.text} streaming={false} />
                    ) : null,
                  )}
                </div>
              )
            }
            return <ProcessGroup key={`flat:${index}`} items={seg.items} onOpenTaskBoard={onOpenTaskBoard} />
          })}
        </ActivityCard>
      ) : null}
      {answerSegments.map((segment, index) => renderSegment(segment, index + activityBlocks.length))}
      {uniqueAttachments.length > 0 ? (
        <div
          className={`message-attachments ${
            uniqueAttachments.filter((a) => a.kind === 'image' && a.url).length >= 2
              ? 'multi-image'
              : ''
          }`}
        >
          {uniqueAttachments.map((attachment) => (
            <AttachmentItem
              key={attachment.id}
              attachment={attachment}
              sessionId={sessionId}
            />
          ))}
        </div>
      ) : null}
      {charts.map((source, index) => (
        <ChartBlock key={`chart:${index}:${source.slice(0, 32)}`} source={source} />
      ))}
      {/* 执行中动效:三点跳动,放在消息末尾(不碰 markdown 内部,稳定不抖)。
          首 token 前额外显示「正在响应」文字,内容开始后只剩三点。 */}
      {message.role === 'assistant' && message.status === 'loading' ? (
        <div className="streaming-loading">
          {segments.length === 0 ? (
            <Typography.Text type="secondary">正在响应</Typography.Text>
          ) : null}
          <span className="streaming-dots" aria-hidden="true">
            <span />
            <span />
            <span />
          </span>
        </div>
      ) : null}
      {message.error ? (
        <Typography.Text type="danger">{message.error}</Typography.Text>
      ) : null}
      {message.role === 'assistant' && fullText ? (
        <div className="message-actions">
          <Tooltip title="复制回答">
            <Button
              type="text"
              size="small"
              icon={<CopyOutlined />}
              onClick={() => {
                void navigator.clipboard.writeText(fullText)
                void toast.success('已复制')
              }}
              aria-label="复制回答"
            />
          </Tooltip>
          {onRegenerate ? (
            <Tooltip title="用上一条输入重新生成">
              <Button
                type="text"
                size="small"
                icon={<RedoOutlined />}
                onClick={onRegenerate}
                aria-label="重新生成"
              />
            </Tooltip>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}

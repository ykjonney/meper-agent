/**
 * Execution log dashboard views — 仪表盘「运行账」tab 的执行记录组件族。
 *
 * 原独立「执行记录」页已按需求移除：筛选（来源/状态/Agent/会话）、分页
 * （默认 20/页、可调）与详情弹窗全部内聚在仪表盘的执行记录 tab 中。
 * 深色风格与 Dashboard 板块一致（Dashboard 为深色硬编码主题）。
 */
import { useEffect, useState } from 'react'
import { useQuery, keepPreviousData } from '@tanstack/react-query'
import { Activity, X, Search, ChevronLeft, ChevronRight } from 'lucide-react'
import {
  executionLogApi,
  executionLogKeys,
  type ExecutionEvent,
  type ExecutionLogItem,
} from '../services/execution-logs-api'
import { usePermission } from '../hooks/use-permission'

type Theme = 'dark' | 'light'

const SOURCE_LABELS: Record<string, string> = {
  internal: '平台用户',
  api_key: 'API Key',
  im: 'IM 渠道',
}

const STATUS_META: Record<string, { text: string; cls: string }> = {
  success: { text: '成功', cls: 'bg-green-500/10 text-green-500 border-green-500/20' },
  error: { text: '失败', cls: 'bg-red-500/10 text-red-500 border-red-500/20' },
  cancelled: { text: '已取消', cls: 'bg-slate-500/10 text-slate-400 border-slate-500/20' },
}

/** 可选分页数（任务/执行记录两个 tab 共用）。 */
export const PAGE_SIZE_OPTIONS = [10, 20, 50, 100]

function fmtTime(ts: string): string {
  if (!ts) return ''
  try {
    return new Date(ts).toLocaleString('zh-CN', { hour12: false })
  } catch {
    return ts
  }
}

function fmtMs(ms?: number): string {
  if (ms == null) return '—'
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`
  return `${ms}ms`
}

function fmtTok(n?: number): string {
  if (n == null) return '—'
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`
  return String(n)
}

/* ─── 分页脚注（页大小可调；任务/执行记录共用） ─── */

export function PagerBar({
  page, totalPages, pageSize, total, onPage, onPageSize,
}: {
  page: number
  totalPages: number
  pageSize: number
  total?: number
  onPage: (p: number) => void
  onPageSize: (n: number) => void
}) {
  return (
    <div className="flex items-center justify-end gap-3 pt-1 text-xs text-[#71717a]">
      <span>{total != null ? `共 ${total} 条 · ` : ''}第 {page} / {totalPages} 页</span>
      <select
        value={pageSize}
        onChange={(e) => onPageSize(Number(e.target.value))}
        className="bg-[#121214] border border-[#27272a] rounded-md px-1.5 py-1 text-xs text-[#d4d4d8] cursor-pointer"
      >
        {PAGE_SIZE_OPTIONS.map((n) => (
          <option key={n} value={n}>{n} 条/页</option>
        ))}
      </select>
      <button
        disabled={page <= 1}
        onClick={() => onPage(Math.max(1, page - 1))}
        className="disabled:opacity-30 cursor-pointer hover:text-[#fafafa]"
      >
        <ChevronLeft size={14} />
      </button>
      <button
        disabled={page >= totalPages}
        onClick={() => onPage(page + 1)}
        className="disabled:opacity-30 cursor-pointer hover:text-[#fafafa]"
      >
        <ChevronRight size={14} />
      </button>
    </div>
  )
}

/* ─── 过程事件渲染（紧凑键 → 可读行） ─── */

const EVENT_DOT_CLS: Record<string, string> = {
  tools_resolved: 'bg-indigo-500',
  request_begin: 'bg-blue-500',
  request_end: 'bg-blue-500',
  tool_call: 'bg-zinc-500',
  tool_result: 'bg-green-500',
  compaction: 'bg-amber-500',
  interrupt: 'bg-orange-500',
  error: 'bg-red-500',
  events_truncated: 'bg-amber-500',
}

function EventLabel({ ev }: { ev: ExecutionEvent }) {
  switch (ev.e) {
    case 'tools_resolved':
      return (
        <span>
          <span className="text-indigo-400">工具装配</span>
          {ev.ctx && <span className="opacity-60"> · {ev.ctx} / {ev.model || '—'}</span>}
          {ev.tools && ev.tools.length > 0 && (
            <span className="opacity-75"> · {ev.tools.join(', ')}</span>
          )}
          {(ev.load_errors ?? []).map((le, i) => (
            <div key={i} className="text-red-400 font-mono text-[10px] break-all mt-0.5">
              加载失败 {le.tool}: {le.error}
            </div>
          ))}
        </span>
      )
    case 'request_begin':
      return <span className="text-blue-400">LLM 请求 #{ev.i ?? '?'}</span>
    case 'request_end':
      return (
        <span>
          <span className="text-blue-400">LLM 请求 #{ev.i ?? '?'} 完成</span>
          <span className="opacity-75">
            {' '}· {fmtMs(ev.dur)} · ↑{fmtTok(ev.in_tok)} ↓{fmtTok(ev.out_tok)}
          </span>
        </span>
      )
    case 'tool_call':
      return (
        <span>
          <span className="text-zinc-300">调用 {ev.n || ev.id}</span>
          {ev.args && (
            <pre className="text-[10px] opacity-70 whitespace-pre-wrap break-all font-mono mt-0.5 max-h-24 overflow-y-auto">{ev.args}</pre>
          )}
        </span>
      )
    case 'tool_result':
      return (
        <span className={ev.ok === false ? 'text-red-400' : 'text-green-500'}>
          {(ev.ok === false ? '✕ ' : '') + (ev.n || ev.id) + ' 返回'}
          <span className="opacity-75"> · {fmtMs(ev.dur)} · {ev.size ?? 0} 字符</span>
        </span>
      )
    case 'interrupt':
      return <span className="text-orange-400">中断 · {ev.kind || '—'}</span>
    case 'compaction':
      return (
        <span className="text-amber-500">
          上下文压缩 · {ev.level || '—'}
          {ev.before != null && (
            <span className="opacity-75"> · 原文 {ev.before} 字符已归档（可 recall 回取）</span>
          )}
        </span>
      )
    case 'error':
      return (
        <span className="text-red-400">
          错误 · {ev.source || '—'}
          {ev.msg && <pre className="text-[10px] opacity-80 whitespace-pre-wrap break-all font-mono mt-0.5">{ev.msg}</pre>}
        </span>
      )
    case 'events_truncated':
      return (
        <span className="text-amber-500">
          过程事件超限截断 · 丢弃 {ev.dropped ?? 0} 条中段工具事件
        </span>
      )
    default:
      return <span className="opacity-75">{ev.e} {JSON.stringify(ev)}</span>
  }
}

function EventTimeline({ events }: { events: ExecutionEvent[] }) {
  if (events.length === 0) {
    return <p className="text-xs opacity-50 text-center py-6">暂无过程事件（旧版本记录）</p>
  }
  return (
    <div className="space-y-2">
      {events.map((ev, idx) => (
        <div key={idx} className="flex gap-3 text-[11px] leading-relaxed">
          <span className="opacity-50 font-mono shrink-0 w-16 text-right">
            +{ev.t >= 1000 ? `${(ev.t / 1000).toFixed(1)}s` : `${ev.t}ms`}
          </span>
          <span className={`shrink-0 w-2 h-2 rounded-full mt-1 ${EVENT_DOT_CLS[ev.e] ?? 'bg-zinc-600'}`} />
          <div className="flex-1 min-w-0"><EventLabel ev={ev} /></div>
        </div>
      ))}
    </div>
  )
}

/* ─── 详情弹窗 ─── */

export function DetailModal({
  logId, theme, onClose,
}: { logId: string; theme: Theme; onClose: () => void }) {
  const dark = theme === 'dark'
  const { data: log, isLoading } = useQuery({
    queryKey: executionLogKeys.detail(logId),
    queryFn: () => executionLogApi.get(logId),
  })

  const metaRows: [string, string][] = log
    ? [
        ['Agent', log.agent_id || '—'],
        ['会话', log.session_id || '—'],
        ['request_id', log.request_id || '—'],
        ['来源', `${SOURCE_LABELS[log.source] ?? log.source}${log.caller_name ? ` · ${log.caller_name}` : ''}`],
        ['状态', `${STATUS_META[log.status]?.text ?? log.status} (${log.status_code})`],
        ['耗时', `${fmtMs(log.latency_ms)}（LLM ${fmtMs(log.llm_duration_ms)} / 工具 ${fmtMs(log.tool_duration_ms)} / 其他 ${fmtMs(log.other_duration_ms)}${log.ttft_ms ? ` / 首token ${fmtMs(log.ttft_ms)}` : ''}）`],
        ['Token', `${fmtTok(log.total_tokens)}（↑${fmtTok(log.input_tokens)} ↓${fmtTok(log.output_tokens)} · ${log.llm_calls} 次请求）`],
        ['时间', fmtTime(log.timestamp)],
      ]
    : []

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={onClose}>
      <div
        className={`rounded-xl shadow-2xl w-[720px] max-w-[calc(100vw-2rem)] max-h-[82vh] flex flex-col border ${
          dark ? 'bg-[#18181b] border-[#27272a]' : 'bg-white border-slate-200'
        }`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className={`flex items-center justify-between px-5 py-3.5 border-b ${dark ? 'border-[#27272a]' : 'border-slate-200'}`}>
          <div className={`flex items-center gap-2 text-sm font-medium ${dark ? 'text-[#fafafa]' : 'text-slate-800'}`}>
            <Activity size={14} className="text-indigo-400" />
            执行详情
            {log && (
              <span className={`text-[10px] px-1.5 py-0.5 rounded border ${STATUS_META[log.status]?.cls ?? ''}`}>
                {STATUS_META[log.status]?.text ?? log.status}
              </span>
            )}
          </div>
          <X size={16} className="opacity-50 cursor-pointer hover:opacity-100" onClick={onClose} />
        </div>

        {isLoading || !log ? (
          <div className={`px-5 py-10 text-center text-xs ${dark ? 'text-[#71717a]' : 'text-slate-400'}`}>加载中…</div>
        ) : (
          <>
            <div className={`px-5 py-3 border-b grid grid-cols-2 gap-x-6 gap-y-2 text-[11px] ${dark ? 'border-[#27272a]' : 'border-slate-200'}`}>
              {metaRows.map(([k, v]) => (
                <div key={k} className="min-w-0">
                  <div className={dark ? 'text-[#71717a]' : 'text-slate-400'}>{k}</div>
                  <div className={`font-mono break-all ${dark ? 'text-[#fafafa]' : 'text-slate-800'}`}>{v}</div>
                </div>
              ))}
            </div>
            <div className="flex-1 overflow-y-auto px-5 py-4">
              <EventTimeline events={log.events ?? []} />
            </div>
          </>
        )}
      </div>
    </div>
  )
}

/* ─── 执行记录筛选（Dashboard 卡片头右上方，与任务搜索框同位） ─── */

export interface ExecFilters {
  source: string
  status: string
  agent_id: string
  session_id: string
}

export const EMPTY_EXEC_FILTERS: ExecFilters = {
  source: '', status: '', agent_id: '', session_id: '',
}

/** 筛选控件（紧凑横排）：状态由 Dashboard 持有，草稿态回车或按钮提交。 */
export function ExecFilterBar({
  draft, onChange, onApply,
}: {
  draft: ExecFilters
  onChange: (d: ExecFilters) => void
  onApply: () => void
}) {
  const selectCls =
    'bg-[#121214] border border-[#27272a] rounded-md px-2 py-1.5 text-xs text-[#d4d4d8] cursor-pointer outline-none'
  const inputCls =
    'bg-[#121214] border border-[#27272a] rounded-md px-2 py-1.5 text-xs text-[#d4d4d8] placeholder-[#52525b] outline-none w-32 font-mono'

  return (
    <div className="flex flex-wrap items-center gap-2">
      <select className={selectCls} value={draft.source} onChange={(e) => onChange({ ...draft, source: e.target.value })}>
        <option value="">全部来源</option>
        <option value="internal">平台用户</option>
        <option value="api_key">API Key</option>
        <option value="im">IM 渠道</option>
      </select>
      <select className={selectCls} value={draft.status} onChange={(e) => onChange({ ...draft, status: e.target.value })}>
        <option value="">全部状态</option>
        <option value="success">成功</option>
        <option value="error">失败</option>
        <option value="cancelled">已取消</option>
      </select>
      <input
        className={inputCls}
        placeholder="Agent ID"
        value={draft.agent_id}
        onChange={(e) => onChange({ ...draft, agent_id: e.target.value })}
        onKeyDown={(e) => e.key === 'Enter' && onApply()}
      />
      <input
        className={inputCls}
        placeholder="会话 ID"
        value={draft.session_id}
        onChange={(e) => onChange({ ...draft, session_id: e.target.value })}
        onKeyDown={(e) => e.key === 'Enter' && onApply()}
      />
      <button
        onClick={onApply}
        className="flex items-center gap-1 rounded-md bg-indigo-500 hover:bg-indigo-600 text-white text-xs px-3 py-1.5 cursor-pointer"
      >
        <Search size={12} /> 筛选
      </button>
    </div>
  )
}

/* ─── 仪表盘执行记录 tab：表格 + 分页 + 详情（筛选控件在卡片头，经 props 注入） ─── */

export function RecentExecutionsTable({ filters }: { filters: ExecFilters }) {
  const canReadAll = usePermission('execution:read:all')
  const [openLogId, setOpenLogId] = useState<string | null>(null)
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState(20)
  // 筛选变化回第 1 页（组件保持挂载——observer 延续，keepPreviousData
  // 才能在新查询期间继续展示旧数据，而不是整块闪加载态）。
  useEffect(() => {
    setPage(1)
  }, [filters])

  const { data, isLoading, isFetching } = useQuery({
    queryKey: executionLogKeys.list({ ...filters, page, page_size: pageSize }),
    queryFn: () => executionLogApi.list({ ...filters, page, page_size: pageSize }),
    enabled: canReadAll,
    staleTime: 15_000,
    // 翻页/筛选期间保留上一份数据（半透明过渡），仅首次加载显示加载态。
    placeholderData: keepPreviousData,
  })

  if (!canReadAll) return null
  const items: ExecutionLogItem[] = data?.items ?? []
  const total = data?.total ?? 0
  const totalPages = Math.max(1, Math.ceil(total / pageSize))

  const th = 'py-2.5 px-3 uppercase tracking-wider text-[10px] text-[#71717a] font-bold'

  return (
    <div className="space-y-3">
      {isLoading ? (
        <div className="flex items-center justify-center py-8 text-[#71717a] text-xs">加载执行记录…</div>
      ) : items.length === 0 ? (
        <div className="text-center py-8 text-[#71717a] text-xs">暂无执行记录</div>
      ) : (
        <div className={`overflow-x-auto transition-opacity ${isFetching ? 'opacity-60' : ''}`}>
          <table className="w-full text-xs text-left text-[#a1a1aa] leading-normal">
            <thead>
              <tr className="border-b border-[#27272a]">
                <th className={th}>时间</th>
                <th className={th}>来源</th>
                <th className={th}>调用者</th>
                <th className={th}>Agent</th>
                <th className={th}>状态</th>
                <th className={th}>耗时</th>
                <th className={th}>Token</th>
                <th className={`${th} text-right`}>操作</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#27272a]/40">
              {items.map((it) => (
                <tr key={it._id} className="hover:bg-[#121214]/60 transition-colors">
                  <td className="py-3 px-3 text-[#71717a] whitespace-nowrap">{fmtTime(it.timestamp)}</td>
                  <td className="py-3 px-3 whitespace-nowrap">{SOURCE_LABELS[it.source] ?? it.source}</td>
                  <td className="py-3 px-3 max-w-28 truncate" title={it.user_id}>{it.caller_name || it.user_id}</td>
                  <td className="py-3 px-3 font-mono text-[11px] text-[#fafafa] max-w-28 truncate" title={it.agent_id}>{it.agent_id || '—'}</td>
                  <td className="py-3 px-3">
                    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold ${STATUS_META[it.status]?.cls ?? ''}`}>
                      <span className="w-1 h-1 rounded-full bg-current" />
                      {STATUS_META[it.status]?.text ?? it.status}
                    </span>
                  </td>
                  <td className="py-3 px-3 whitespace-nowrap" title={`LLM ${fmtMs(it.llm_duration_ms)} · 工具 ${fmtMs(it.tool_duration_ms)} · 其他 ${fmtMs(it.other_duration_ms)}`}>
                    {fmtMs(it.latency_ms)}
                  </td>
                  <td className="py-3 px-3 whitespace-nowrap">{fmtTok(it.total_tokens)}</td>
                  <td className="py-3 px-3 text-right">
                    <button
                      onClick={() => setOpenLogId(it._id)}
                      className="text-indigo-400 hover:text-indigo-300 font-bold hover:underline cursor-pointer"
                    >
                      详情
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {!isLoading && items.length > 0 && (
        <PagerBar
          page={page}
          totalPages={totalPages}
          pageSize={pageSize}
          total={total}
          onPage={setPage}
          onPageSize={(n) => {
            setPageSize(n)
            setPage(1)
          }}
        />
      )}

      {openLogId && (
        <DetailModal logId={openLogId} theme="dark" onClose={() => setOpenLogId(null)} />
      )}
    </div>
  )
}

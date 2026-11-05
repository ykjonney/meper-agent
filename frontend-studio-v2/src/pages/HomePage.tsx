/**
 * HomePage — 首页（预览稿视觉 + v1 Dashboard 全功能对齐）。
 *
 * 功能清单（v1 Dashboard 695 行逐项对齐）：
 *  - MetricCard ×6：Agent 总数 / 运行中（并发 note）/ 任务总数 / 待执行 / 调用总数（+今日）/ 成功率
 *  - 双趋势：近 7 天任务创建趋势（tasksApi 按天）+ 近 7 天 Agent 调用趋势（getDailyTrend）
 *  - 容量 StatRow：并发上限 / 运行 / 待执行 / 触发用户数
 *  - 任务运行历史：搜索 + 分页 + 表格（ID/工作流/创建时间/状态/版本/查看追踪）
 *  - 待我处理 / 最近会话
 */
import { useMemo, useState } from 'react';
import { useQuery, keepPreviousData } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { useAuthStore } from '../stores/auth-store';
import { sessionApi, sessionKeys, type Session } from '../services/session-api';
import { tasksApi, type TaskSummary, type TaskStatusValue } from '../services/tasks-api';
import { agentApi } from '../services/agent-api';
import { executionLogApi, type ExecutionLogItem } from '../services/execution-logs-api';
import { Panel, KpiCard, Pill } from '../components/ui';

function fmtAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  if (diff < 60_000) return '刚刚';
  if (diff < 3600_000) return `${Math.floor(diff / 60_000)} 分钟前`;
  if (diff < 86400_000) return `${Math.floor(diff / 3600_000)} 小时前`;
  return new Date(iso).toLocaleDateString('zh-CN');
}

function fmtTok(n?: number): string {
  if (!n) return '0';
  return n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : `${Math.round(n / 1000)}k`;
}

// 执行日志：来源/状态语义（v1 ExecutionLogsPage 同款）
const SOURCE_LABELS: Record<string, string> = {
  internal: '平台用户', api_key: 'API Key', im: 'IM 渠道',
};
const EXEC_STATUS: Record<string, { t: string; tone: 'success' | 'danger' | 'neutral' }> = {
  success: { t: '成功', tone: 'success' },
  error: { t: '失败', tone: 'danger' },
  cancelled: { t: '已取消', tone: 'neutral' },
};

const STATUS_LABEL: Record<TaskStatusValue, string> = {
  running: '执行中', pending: '排队中', waiting_human: '待人工',
  completed: '已完成', failed: '失败', cancelled: '已取消',
};
function statusTone(s: TaskStatusValue): 'success' | 'brand' | 'warning' | 'danger' | 'neutral' {
  if (s === 'completed') return 'success';
  if (s === 'running') return 'brand';
  if (s === 'waiting_human' || s === 'pending') return 'warning';
  if (s === 'failed' || s === 'cancelled') return 'danger';
  return 'neutral';
}

const CSS = `
.hp { height:100%; overflow-y:auto; background:var(--color-canvas-deep); font-family:var(--font-sans); font-size:14px; color:var(--color-ink); }
.hp-inner { width:100%; padding:19px 26px; }
.hp * { box-sizing:border-box; }
.hp .srch { margin-left:auto; background:var(--color-panel); border:1px solid var(--color-line); border-radius:99px; padding:7px 19px; font-size:13px; color:var(--color-ink-faint); width:264px; }
.hp .bell { width:36px; height:36px; border-radius:99px; background:var(--color-panel); border:1px solid var(--color-line); display:flex; align-items:center; justify-content:center; position:relative; font-size:16px; cursor:pointer; }
.hp .bell i { position:absolute; top:-2px; right:-2px; width:17px; height:17px; border-radius:50%; background:var(--color-danger); color:#fff; font-size:10px; font-style:normal; display:flex; align-items:center; justify-content:center; font-weight:700; }
.hp .hist-search { background:var(--color-panel); border:1px solid var(--color-line); border-radius:9px; padding:6px 14px; font-size:12px; color:var(--color-ink); outline:none; width:220px; }
.hp .hist-search::placeholder { color:var(--color-ink-faint); }
.hp .hist-tab { border-radius:8px; padding:5px 14px; font-size:12px; font-weight:600; cursor:pointer; color:var(--color-ink-dim); }
.hp .hist-tab.on { background:var(--color-line); color:var(--color-ink); }
.hp .htbl { width:100%; border-collapse:collapse; font-size:12.5px; text-align:left; }
.hp .htbl th { padding:10px 12px; text-transform:uppercase; letter-spacing:.4px; font-size:11px; color:var(--color-ink-dim); border-bottom:1px solid var(--color-line); font-weight:700; }
.hp .htbl td { padding:11px 12px; border-bottom:1px solid var(--color-line); color:var(--color-ink-dim); }
.hp .htbl tr:hover td { background:var(--color-panel-hover); }
.hp .pgbtn { border:1px solid var(--color-line); background:var(--color-panel); border-radius:7px; padding:4px 12px; font-size:11.5px; color:var(--color-ink-soft); cursor:pointer; }
.hp .pgbtn:disabled { opacity:.4; cursor:default; }
.hp .trace { color:var(--color-brand); font-weight:700; cursor:pointer; font-size:12px; }
.hp .trace:hover { text-decoration:underline; }
`;

export function HomePage() {
  const nav = useNavigate();
  const user = useAuthStore((s) => s.user);

  // ── 数据（v1 同源）──
  const { data: execStats } = useQuery({ queryKey: ['exec-stats', 'today'], queryFn: () => executionLogApi.getStats(), refetchInterval: 20_000 });
  const { data: execStatsAll } = useQuery({ queryKey: ['exec-stats', 'all'], queryFn: () => executionLogApi.getStats({ start: '2020-01-01', end: '2099-12-31' }) });
  const { data: trend } = useQuery({ queryKey: ['exec-trend', 7], queryFn: () => executionLogApi.getDailyTrend(7), refetchInterval: 60_000 });
  const { data: taskStats } = useQuery({ queryKey: ['task-stats'], queryFn: () => tasksApi.getStats(), refetchInterval: 15_000 });
  const [taskPage, setTaskPage] = useState(1);
  const [filterSearch, setFilterSearch] = useState('');
  const [historyTab, setHistoryTab] = useState<'tasks' | 'execs'>('tasks');
  const [execPage, setExecPage] = useState(1);
  const [execSource, setExecSource] = useState('');
  const [execStatus, setExecStatus] = useState('');
  const { data: taskList, isFetching: tasksFetching } = useQuery({
    queryKey: ['tasks', 'home', taskPage], queryFn: () => tasksApi.list({ page: taskPage, page_size: 10 }),
    placeholderData: keepPreviousData, refetchInterval: 15_000,
  });
  // 全量（近 7 天趋势用）
  const { data: taskAll } = useQuery({ queryKey: ['tasks', 'home-all'], queryFn: () => tasksApi.list({ page_size: 50 }) });
  // 执行日志 Tab（真实 executionLogApi）
  const { data: execList, isFetching: execFetching } = useQuery({
    queryKey: ['exec-logs', 'home', execPage, execSource, execStatus], queryFn: () => executionLogApi.list({ page: execPage, page_size: 10, source: execSource || undefined, status: execStatus || undefined }),
    placeholderData: keepPreviousData, enabled: historyTab === 'execs', refetchInterval: 20_000,
  });
  const { data: agentList } = useQuery({ queryKey: ['agents', 'home'], queryFn: () => agentApi.list({ page_size: 1, status: 'all' }) });
  const { data: sessionList } = useQuery({ queryKey: sessionKeys.lists(), queryFn: () => sessionApi.list({ page_size: 4 }) });

  const totals = execStats?.totals;
  const totalsAll = execStatsAll?.totals;
  const successRate = totals?.success_rate != null ? `${Math.round(totals.success_rate * 100)}%` : '—';

  // ── 任务派生 ──
  const allTasks = useMemo(() => (taskAll?.items ?? []) as TaskSummary[], [taskAll]);
  const running = useMemo(() => allTasks.filter((t) => t.status === 'running'), [allTasks]);
  const waiting = useMemo(() => allTasks.filter((t) => t.status === 'waiting_human'), [allTasks]);
  const taskTokens = useMemo(() => allTasks.reduce((n, t) => n + (t.total_tokens ?? 0), 0), [allTasks]);

  // 历史表：搜索 + 分页（当前页数据由接口分页）
  const history = useMemo(() => ((taskList?.items ?? []) as TaskSummary[]).filter((t) => {
    if (!filterSearch) return true;
    const k = filterSearch.toLowerCase();
    return t.workflow_id.toLowerCase().includes(k) || t.id.toLowerCase().includes(k);
  }), [taskList, filterSearch]);
  const totalPages = Math.max(1, taskList?.total ? Math.ceil(taskList.total / 10) : 1);

  // 双趋势：任务创建（真实按天）+ Agent 调用（getDailyTrend）
  const taskTrend = useMemo(() => {
    const days: { label: string; n: number }[] = [];
    for (let i = 6; i >= 0; i--) {
      const d = new Date();
      d.setHours(0, 0, 0, 0);
      const start = d.getTime() - i * 86_400_000;
      const n = allTasks.filter((t) => {
        const ts = new Date(t.created_at).getTime();
        return ts >= start && ts < start + 86_400_000;
      }).length;
      days.push({ label: i === 0 ? '今天' : new Date(start).toLocaleDateString('zh-CN', { weekday: 'short' }), n });
    }
    return days;
  }, [allTasks]);
  const maxTaskTrend = Math.max(1, ...taskTrend.map((d) => d.n));
  const maxCalls = Math.max(1, ...(trend ?? []).map((d) => d.calls));

  return (
    <div className="hp">
      <style>{CSS}</style>
      <div className="hp-inner">
        {/* ── 顶部 ── */}
        <header style={{ display: 'flex', alignItems: 'center', gap: 14, marginBottom: 18 }}>
          <div>
            <h2 style={{ margin: 0, fontSize: 20, fontWeight: 800 }}>
              {greeting()}，{user?.username ?? ''}{' 👋'}
            </h2>
            <div style={{ fontSize: 12.5, color: 'var(--color-ink-dim)', marginTop: 2 }}>
              {new Date().toLocaleDateString('zh-CN', { month: 'long', day: 'numeric', weekday: 'long' })}
              {running.length > 0 && ` · ${running.length} 个任务在跑`}
              {waiting.length > 0 && ` · ${waiting.length} 件等你处理`}
            </div>
          </div>
          <div className="srch">🔍 搜索会话、智能体、任务… ⌘K</div>
          <div className="bell" onClick={() => nav('/tasks')}>
            🔔{waiting.length > 0 && <i>{waiting.length}</i>}
          </div>
        </header>

        {/* ── KPI ×6（v1 MetricCard 全量） ── */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(6,1fr)', gap: 14, marginBottom: 18 }}>
          <KpiCard icon="🤖" label="Agent 总数" value={agentList?.total ?? 0} sub="已创建的智能体" onClick={() => nav('/agents')} />
          <KpiCard icon="⚡" label="运行中" value={taskStats?.global_running ?? running.length} sub={`并发上限 ${taskStats?.global_max ?? 10} · 待执行 ${taskStats?.global_pending ?? 0}`} tone="brand" onClick={() => nav('/tasks')} />
          <KpiCard icon="🗂" label="任务总数" value={taskStats ? `${taskStats.global_running + taskStats.global_pending}` : '—'} sub={`近期涉及 ${allTasks.length} 条`} onClick={() => nav('/tasks')} />
          <KpiCard icon="📥" label="待执行 (pending)" value={taskStats?.global_pending ?? 0} sub="排队等待调度" tone="danger" onClick={() => nav('/tasks')} />
          <KpiCard icon="📞" label="Agent 调用总数" value={totalsAll ? totalsAll.calls.toLocaleString() : '—'} sub={`今日 ${totals?.calls ?? 0} 次`} onClick={() => nav('/tasks')} />
          <KpiCard icon="🔥" label="成功率 / Token" value={successRate} sub={`今日 ${fmtTok(totals?.tokens)} · 任务 ${fmtTok(taskTokens)}`} onClick={() => nav('/tasks')} />
        </div>

        {/* ── 双趋势 ── */}
        <div style={{ display: 'flex', gap: 14, marginBottom: 18 }}>
          <Panel title="近 7 天任务创建趋势">
            <div style={{ display: 'flex', alignItems: 'flex-end', gap: 8, height: 100, flex: 1 }}>
              {taskTrend.map((d) => (
                <div key={d.label} style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'flex-end', alignItems: 'center', gap: 3 }} title={`${d.label}：${d.n} 个任务`}>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--color-ink-dim)' }}>{d.n || ''}</span>
                  <i style={{ display: 'block', width: '70%', height: (d.n / maxTaskTrend) * 88, minHeight: d.n ? 4 : 1, borderRadius: '5px 5px 0 0', background: 'linear-gradient(180deg, var(--color-brand-grad-from), var(--color-brand-grad-to))' }} />
                </div>
              ))}
            </div>
            <div style={{ display: 'flex', gap: 8, marginTop: 6, fontSize: 10, color: 'var(--color-ink-faint)' }}>
              {taskTrend.map((d) => <span key={d.label} style={{ flex: 1, textAlign: 'center' }}>{d.label}</span>)}
            </div>
          </Panel>
          <Panel title="近 7 天 Agent 调用趋势" more="执行日志 →" onMore={() => nav('/tasks')}>
            <div style={{ display: 'flex', gap: 14, fontSize: 11, color: 'var(--color-ink-dim)', marginBottom: 8 }}>
              <span><i style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 3, marginRight: 5, verticalAlign: -1, background: 'linear-gradient(180deg, var(--color-brand-grad-from), var(--color-brand-grad-to))' }} />调用</span>
              <span><i style={{ display: 'inline-block', width: 10, height: 10, borderRadius: 3, marginRight: 5, verticalAlign: -1, background: 'var(--color-danger)' }} />失败</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'flex-end', gap: 8, height: 100, flex: 1 }}>
              {(trend ?? []).map((d) => (
                <div key={d.date} style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'flex-end' }} title={`${d.date}：${d.calls} 次调用 · ${d.failed} 失败`}>
                  <i style={{ display: 'block', height: (d.calls / maxCalls) * 92, minHeight: d.calls ? 4 : 1, borderRadius: '5px 5px 0 0', background: 'linear-gradient(180deg, var(--color-brand-grad-from), var(--color-brand-grad-to))' }} />
                  <i style={{ display: 'block', height: (d.failed / maxCalls) * 92, minHeight: d.failed ? 4 : 0, background: 'var(--color-danger)' }} />
                </div>
              ))}
              {(trend ?? []).length === 0 && <div style={{ color: 'var(--color-ink-faint)', fontSize: 12 }}>暂无执行数据</div>}
            </div>
            <div style={{ display: 'flex', gap: 8, marginTop: 6, fontSize: 10, color: 'var(--color-ink-faint)' }}>
              {(trend ?? []).map((d) => <span key={d.date} style={{ flex: 1, textAlign: 'center' }}>{new Date(d.date).toLocaleDateString('zh-CN', { weekday: 'short' })}</span>)}
            </div>
          </Panel>
        </div>

        <div style={{ display: 'flex', gap: 14, marginBottom: 18 }}>
          {/* ── 左：任务运行历史（v1 主体：搜索+分页+查看追踪） ── */}
          <div style={{ flex: 1.6, minWidth: 0 }}>
            <Panel title="任务运行历史" style={{ flex: 'none' }}>
              {/* Tab + 搜索 */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 10 }}>
                <span className={`hist-tab ${historyTab === 'tasks' ? 'on' : ''}`} onClick={() => setHistoryTab('tasks')}>任务</span>
                <span className={`hist-tab ${historyTab === 'execs' ? 'on' : ''}`} onClick={() => setHistoryTab('execs')}>执行日志</span>
                {historyTab === 'execs' && (
                  <div style={{ display: 'flex', gap: 8, marginLeft: 4 }}>
                    <select className="hist-search" style={{ width: 120 }} value={execSource} onChange={(e) => { setExecSource(e.target.value); setExecPage(1); }}>
                      <option value="">来源：全部</option>
                      <option value="internal">平台用户</option>
                      <option value="api_key">API Key</option>
                      <option value="im">IM 渠道</option>
                    </select>
                    <select className="hist-search" style={{ width: 110 }} value={execStatus} onChange={(e) => { setExecStatus(e.target.value); setExecPage(1); }}>
                      <option value="">状态：全部</option>
                      <option value="success">成功</option>
                      <option value="error">失败</option>
                      <option value="cancelled">已取消</option>
                    </select>
                  </div>
                )}
                {historyTab === 'tasks' && (
                  <input
                    className="hist-search"
                    style={{ marginLeft: 'auto' }}
                    value={filterSearch}
                    onChange={(e) => { setFilterSearch(e.target.value); setTaskPage(1); }}
                    placeholder="搜索任务 ID / 工作流…"
                  />
                )}
              </div>
              {historyTab === 'execs' && (
                <div style={{ overflowX: 'auto', opacity: execFetching ? 0.6 : 1, transition: 'opacity .15s' }}>
                  <table className="htbl">
                    <thead>
                      <tr>{['时间', '来源', '调用者', 'Agent', '状态', '耗时', 'Token', '操作'].map((h) => <th key={h}>{h}</th>)}</tr>
                    </thead>
                    <tbody>
                      {(execList?.items ?? []).map((log: ExecutionLogItem) => {
                        const meta = EXEC_STATUS[String(log.status)] ?? { t: String(log.status), tone: 'neutral' as const };
                        return (
                          <tr key={String(log._id ?? log.request_id)}>
                            <td style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-ink)', whiteSpace: 'nowrap' }}>
                              {new Date(String(log.timestamp)).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}
                            </td>
                            <td style={{ whiteSpace: 'nowrap' }}>{SOURCE_LABELS[String(log.source)] ?? String(log.source ?? '—')}</td>
                            <td style={{ maxWidth: 110, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={String(log.user_id ?? '')}>
                              {String(log.caller_name || log.user_id || '—')}
                            </td>
                            <td style={{ fontFamily: 'var(--font-mono)', fontSize: 11, maxWidth: 110, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={String(log.agent_id ?? '')}>
                              {String(log.agent_id || '—')}
                            </td>
                            <td><Pill tone={meta.tone}>{meta.t}</Pill></td>
                            <td style={{ fontFamily: 'var(--font-mono)', whiteSpace: 'nowrap' }}>
                              {log.latency_ms ? `${(Number(log.latency_ms) / 1000).toFixed(1)}s` : '—'}
                            </td>
                            <td style={{ fontFamily: 'var(--font-mono)' }}>{fmtTok(Number(log.total_tokens ?? 0))}</td>
                            <td style={{ textAlign: 'right' }}>
                              <span className="trace" title="详情（P4.5 接入日志详情弹窗）">详情</span>
                            </td>
                          </tr>
                        );
                      })}
                      {((execList?.items ?? []).length === 0) && (
                        <tr><td colSpan={8} style={{ textAlign: 'center', padding: '32px 0', color: 'var(--color-ink-faint)' }}>暂无执行日志</td></tr>
                      )}
                    </tbody>
                  </table>
                </div>
              )}
              {historyTab === 'execs' && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 12 }}>
                  <span style={{ fontSize: 11.5, color: 'var(--color-ink-faint)' }}>共 {execList?.total ?? 0} 条</span>
                  <div style={{ marginLeft: 'auto', display: 'flex', gap: 6, alignItems: 'center' }}>
                    <button className="pgbtn" disabled={execPage <= 1} onClick={() => setExecPage((p) => Math.max(1, p - 1))}>← 上一页</button>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11.5 }}>{execPage} / {Math.max(1, execList?.total ? Math.ceil(execList.total / 10) : 1)}</span>
                    <button className="pgbtn" disabled={execPage >= (execList?.total ? Math.ceil(execList.total / 10) : 1)} onClick={() => setExecPage((p) => p + 1)}>下一页 →</button>
                  </div>
                </div>
              )}
              <div style={{ overflowX: 'auto', opacity: tasksFetching ? 0.6 : 1, transition: 'opacity .15s', display: historyTab === 'tasks' ? 'block' : 'none' }}>
                <table className="htbl">
                  <thead>
                    <tr>{['任务 ID', '工作流', '创建时间', '状态', '版本', '操作'].map((h) => <th key={h}>{h}</th>)}</tr>
                  </thead>
                  <tbody>
                    {history.map((t) => (
                      <tr key={t.id}>
                        <td style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-ink)' }}>{t.id.slice(-10)}</td>
                        <td style={{ fontFamily: 'var(--font-mono)', color: 'var(--color-ink)', fontWeight: 600 }}>{t.workflow_id}</td>
                        <td>{fmtAgo(t.created_at)}</td>
                        <td><Pill tone={statusTone(t.status)}>{STATUS_LABEL[t.status] ?? t.status}</Pill></td>
                        <td style={{ fontFamily: 'var(--font-mono)' }}>v{t.workflow_version}</td>
                        <td style={{ textAlign: 'right' }}>
                          <span className="trace" onClick={() => nav('/tasks')}>查看追踪 ↗</span>
                        </td>
                      </tr>
                    ))}
                    {history.length === 0 && (
                      <tr><td colSpan={6} style={{ textAlign: 'center', padding: '32px 0', color: 'var(--color-ink-faint)' }}>
                        {filterSearch ? '无匹配任务' : '暂无任务 — 从对话或定时触发开始'}
                      </td></tr>
                    )}
                  </tbody>
                </table>
              </div>
              {/* 分页 */}
              <div style={{ display: historyTab === 'tasks' ? 'flex' : 'none', alignItems: 'center', gap: 10, marginTop: 12 }}>
                <span style={{ fontSize: 11.5, color: 'var(--color-ink-faint)' }}>共 {taskList?.total ?? 0} 条</span>
                <div style={{ marginLeft: 'auto', display: 'flex', gap: 6, alignItems: 'center' }}>
                  <button className="pgbtn" disabled={taskPage <= 1} onClick={() => setTaskPage((p) => Math.max(1, p - 1))}>← 上一页</button>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11.5 }}>{taskPage} / {totalPages}</span>
                  <button className="pgbtn" disabled={taskPage >= totalPages} onClick={() => setTaskPage((p) => Math.min(totalPages, p + 1))}>下一页 →</button>
                </div>
              </div>
            </Panel>
          </div>

          {/* ── 右列 ── */}
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 14, minWidth: 0 }}>
            {/* 容量 StatRow（v1 对齐） */}
            <Panel title="执行容量" style={{ flex: 'none' }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                <CapRow label="全局并发上限" value={`${taskStats?.global_max ?? 10}`} desc="来自 /tasks/stats" />
                <CapRow label="运行中任务" value={`${taskStats?.global_running ?? running.length}`} desc="global_running" warn={(taskStats?.global_running ?? 0) > 0} />
                <CapRow label="待执行任务" value={`${taskStats?.global_pending ?? 0}`} desc="global_pending" warn={(taskStats?.global_pending ?? 0) > 0} />
                <CapRow label="触发用户数" value={`${taskStats?.user_stats?.length ?? 0}`} desc="user_stats" />
              </div>
            </Panel>

            {/* 待我处理 */}
            <Panel title={`待我处理${waiting.length ? ` · ${waiting.length}` : ''}`} more="→" onMore={() => nav('/tasks')}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 11, flex: 1 }}>
                {waiting.length === 0 ? (
                  <div className="af-card" style={{ border: '1px solid var(--color-line)', borderRadius: 13, padding: '11px 14px' }}>
                    <div style={{ fontSize: 13, fontWeight: 700 }}>✓ 没有等待你的事项</div>
                    <div style={{ fontSize: 11.5, color: 'var(--color-ink-dim)', marginTop: 3 }}>计划审批、澄清提问会出现在这里</div>
                  </div>
                ) : waiting.slice(0, 2).map((t) => (
                  <div key={t.id} className="af-card" style={{
                    border: '1px solid var(--color-line)', borderLeft: '3px solid var(--color-brand)',
                    borderRadius: 13, padding: '11px 14px',
                  }}>
                    <div style={{ display: 'flex', gap: 7, alignItems: 'center', fontSize: 13, fontWeight: 700, color: '#4C3A9E' }}>
                      🖐 任务 #{t.id.slice(-8)}
                      <span style={{ fontSize: 10, background: 'var(--color-brand-soft)', color: 'var(--color-brand)', borderRadius: 99, padding: '1.5px 8px', marginLeft: 'auto' }}>
                        {fmtAgo(t.created_at)}
                      </span>
                    </div>
                    <div style={{ display: 'flex', gap: 7, marginTop: 8 }}>
                      <span className="af-btn" onClick={() => nav('/chat')} style={{ cursor: 'pointer' }}>去处理</span>
                      <span className="af-btn-ghost" onClick={() => nav('/tasks')} style={{ cursor: 'pointer' }}>查看详情</span>
                    </div>
                  </div>
                ))}
              </div>
            </Panel>

            {/* 最近会话 */}
            <Panel title="最近会话" more="全部 →" onMore={() => nav('/chat')} style={{ flex: 'none' }}>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 11, flex: 1 }}>
                {(sessionList?.items ?? []).slice(0, 3).map((sess: Session) => (
                  <div key={sess._id} onClick={() => nav('/chat')} className="af-card" style={{
                    border: '1px solid var(--color-line)', borderRadius: 13, padding: '11px 14px', cursor: 'pointer',
                  }}>
                    <div style={{ fontSize: 13, fontWeight: 700 }}>{sess.title || '未命名会话'}</div>
                    <div style={{ fontSize: 11.5, color: 'var(--color-ink-dim)', marginTop: 3 }}>
                      {sess.message_count} 条消息 · {fmtAgo(sess.updated_at)}
                    </div>
                  </div>
                ))}
                {(sessionList?.items ?? []).length === 0 && (
                  <div onClick={() => nav('/chat')} className="af-card" style={{ border: '1px solid var(--color-line)', borderRadius: 13, padding: '11px 14px', cursor: 'pointer' }}>
                    <div style={{ fontSize: 13, fontWeight: 700 }}>💬 开始第一个对话</div>
                  </div>
                )}
              </div>
            </Panel>
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── 局部 ── */
function CapRow({ label, value, desc, warn }: { label: string; value: string; desc: string; warn?: boolean }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
      <span style={{ fontSize: 12, color: 'var(--color-ink-soft)', minWidth: 90 }}>{label}</span>
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, fontWeight: 700, color: warn ? 'var(--color-warning)' : 'var(--color-ink)' }}>{value}</span>
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--color-ink-faint)', marginLeft: 'auto' }}>{desc}</span>
    </div>
  );
}

function greeting(): string {
  const h = new Date().getHours();
  return h < 6 ? '夜深了' : h < 12 ? '早上好' : h < 18 ? '下午好' : '晚上好';
}

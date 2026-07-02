import { useState } from 'react';
import {
  Cpu, RotateCcw, CheckCircle, TrendingUp, Calendar, Search, Loader2,
  ExternalLink, Brain, Terminal,
} from 'lucide-react';
import { useQuery } from '@tanstack/react-query';
import {
  tasksApi, taskKeys, type TaskSummary, type TaskDetail, type TimelineEvent,
} from '../services/tasks-api';
import { agentApi, agentKeys } from '../services/agent-api';

interface DashboardProps {
  onSelectTab: (tab: string) => void;
  /**
   * Called when the user opens a task trace. The studio trace slide-over
   * (App.tsx) renders the returned task detail timeline.
   */
  onViewTask: (task: TaskDetail) => void;
}

/**
 * Studio Dashboard — aggregates several backend endpoints since there is no
 * single aggregation endpoint.
 *
 * GAP (spec): there is no dedicated 7-day time-series endpoint, so the chart
 * approximates daily activity from task `created_at` timestamps over the last
 * 7 days. If insufficient data exists, the chart renders zeros (annotated).
 */
export function Dashboard({ onSelectTab, onViewTask }: DashboardProps) {
  const [filterSearch, setFilterSearch] = useState('');

  // ── Aggregation queries ──
  const { data: statsData, isLoading: statsLoading } = useQuery({
    queryKey: taskKeys.stats(),
    queryFn: () => tasksApi.getStats(),
    staleTime: 15_000,
  });

  const { data: tasksData, isLoading: tasksLoading } = useQuery({
    queryKey: taskKeys.list({ page: 1, page_size: 20 }),
    queryFn: () => tasksApi.list({ page: 1, page_size: 20 }),
    staleTime: 10_000,
  });

  const { data: agentsData } = useQuery({
    queryKey: agentKeys.list({ page: 1, page_size: 1 }),
    queryFn: () => agentApi.list({ page: 1, page_size: 1 }),
    staleTime: 60_000,
  });

  const tasks: TaskSummary[] = tasksData?.items ?? [];
  const totalTasks = tasksData?.total ?? 0;
  const agentTotal = agentsData?.total ?? 0;
  const running = statsData?.global_running ?? 0;
  const pending = statsData?.global_pending ?? 0;
  const maxConcurrent = statsData?.global_max ?? 0;

  // ── 7-day chart approximation from task created_at ──
  const chartPoints = build7DayChart(tasks);

  const maxVal = Math.max(...chartPoints.map((p) => p.val), 1);
  const svgWidth = 500;
  const svgHeight = 160;

  const pathData = chartPoints
    .map((p, i) => {
      const x = (i / (chartPoints.length - 1)) * (svgWidth - 60) + 30;
      const y = svgHeight - 20 - (p.val / maxVal) * (svgHeight - 40);
      return `${i === 0 ? 'M' : 'L'} ${x} ${y}`;
    })
    .join(' ');

  const filteredTasks = tasks.filter(
    (t) =>
      t.workflow_id.toLowerCase().includes(filterSearch.toLowerCase()) ||
      t.id.toLowerCase().includes(filterSearch.toLowerCase()),
  );

  return (
    <div className="space-y-6">
      {/* Welcome Banner */}
      <div className="flex flex-col md:flex-row md:items-center justify-between p-6 bg-gradient-to-br from-[#121214] to-[#18181b] rounded-xl border border-[#27272a] shadow-xl overflow-hidden relative">
        <div className="absolute top-0 right-0 w-80 h-40 bg-indigo-500/10 blur-[80px] rounded-full pointer-events-none" />
        <div className="space-y-1 relative z-10">
          <h1 className="text-xl font-bold text-[#fafafa] tracking-tight flex items-center gap-2 font-sans">
            仪表盘 <span className="text-xl">📊</span>
          </h1>
          <p className="text-[#a1a1aa] text-xs max-w-xl">
            聚合自 /tasks/stats、/agents、/tasks。当前并发上限 {maxConcurrent}，运行中 {running}，待执行 {pending}。
          </p>
        </div>
        <div className="mt-4 md:mt-0 flex gap-3 relative z-10">
          <button
            onClick={() => onSelectTab('workflows')}
            className="px-4 py-2 text-xs font-semibold text-[#a1a1aa] hover:text-white bg-[#121214] hover:bg-[#1c1c1f] rounded-lg border border-[#27272a] transition shadow-inner flex items-center gap-1.5 cursor-pointer"
          >
            <Brain className="w-4 h-4 text-indigo-400" />
            设计工作流
          </button>
          <button
            onClick={() => onSelectTab('agents')}
            className="px-4 py-2 text-xs font-semibold text-white bg-indigo-600 hover:bg-indigo-700 rounded-lg shadow-md cursor-pointer transition flex items-center gap-1.5"
          >
            <Cpu className="w-4 h-4" />
            进入 Agent 空间
          </button>
        </div>
      </div>

      {/* Metric cards (real data) */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <MetricCard
          title="Agent 总数"
          value={statsLoading ? '…' : String(agentTotal)}
          note="已创建的智能体"
          icon={Cpu}
          color="text-indigo-400"
          bg="bg-indigo-500/10 border-indigo-500/20"
          loading={statsLoading}
        />
        <MetricCard
          title="运行中任务"
          value={statsLoading ? '…' : String(running)}
          note={`并发上限 ${maxConcurrent} · 待执行 ${pending}`}
          icon={RotateCcw}
          color="text-teal-400"
          bg="bg-teal-500/10 border-teal-500/20"
          loading={statsLoading}
        />
        <MetricCard
          title="任务总数"
          value={statsLoading ? '…' : totalTasks.toLocaleString()}
          note="全部历史任务"
          icon={CheckCircle}
          color="text-emerald-400"
          bg="bg-emerald-500/10 border-emerald-500/20"
          loading={statsLoading}
        />
        <MetricCard
          title="待执行 (pending)"
          value={statsLoading ? '…' : String(pending)}
          note="排队等待调度"
          icon={TrendingUp}
          color="text-amber-400"
          bg="bg-amber-500/10 border-amber-500/20"
          loading={statsLoading}
        />
      </div>

      {/* Chart + node health */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
        <div className="lg:col-span-8 p-5 bg-[#18181b] rounded-xl border border-[#27272a] flex flex-col justify-between">
          <div>
            <div className="flex justify-between items-center mb-4">
              <h3 className="text-xs font-bold text-[#fafafa] flex items-center gap-1.5">
                <TrendingUp className="w-4 h-4 text-indigo-400" />
                近 7 天任务创建趋势
              </h3>
              <span className="text-amber-400 text-[10px] font-mono">
                GAP: 由 task created_at 近似，非专用时序端点
              </span>
            </div>

            <div className="relative w-full h-44 flex items-end">
              <svg className="w-full h-full overflow-visible">
                {[0, 0.25, 0.5, 0.75, 1].map((p, i) => {
                  const y = 15 + p * (svgHeight - 40);
                  return (
                    <line
                      key={i}
                      x1="30"
                      y1={y}
                      x2={svgWidth + 30}
                      y2={y}
                      stroke="rgba(113, 113, 122, 0.15)"
                      strokeDasharray="4 4"
                    />
                  );
                })}
                <defs>
                  <linearGradient id="chart-grad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor="rgb(99, 102, 241)" stopOpacity="0.18" />
                    <stop offset="100%" stopColor="rgb(99, 102, 241)" stopOpacity="0" />
                  </linearGradient>
                </defs>
                <path
                  d={`${pathData} L ${(chartPoints.length - 1) * ((svgWidth - 60) / (chartPoints.length - 1)) + 30} ${svgHeight - 20} L 30 ${svgHeight - 20} Z`}
                  fill="url(#chart-grad)"
                />
                <path d={pathData} fill="none" stroke="#6366f1" strokeWidth="2.5" />
                {chartPoints.map((p, i) => {
                  const x = (i / (chartPoints.length - 1)) * (svgWidth - 60) + 30;
                  const y = svgHeight - 20 - (p.val / maxVal) * (svgHeight - 40);
                  return (
                    <g key={i}>
                      <circle cx={x} cy={y} r="5" fill="#1e1b4b" stroke="#818cf8" strokeWidth="2" />
                      <text x={x} y={y - 10} textAnchor="middle" className="fill-[#a1a1aa] text-[10px] font-mono font-semibold">
                        {p.val}
                      </text>
                    </g>
                  );
                })}
              </svg>
            </div>
          </div>

          <div className="flex justify-between border-t border-[#27272a] pt-3 mt-4 text-[10px] text-[#71717a] font-mono font-semibold">
            {chartPoints.map((p, idx) => (
              <span key={idx}>{p.label}</span>
            ))}
          </div>
        </div>

        {/* Concurrency / stats panel */}
        <div className="lg:col-span-4 p-5 bg-[#18181b] rounded-xl border border-[#27272a] flex flex-col justify-between">
          <div className="space-y-4">
            <h3 className="text-xs font-bold text-[#fafafa] flex items-center gap-1.5">
              <Terminal className="w-4 h-4 text-emerald-400" />
              任务执行引擎状态
            </h3>
            <div className="space-y-3">
              <StatRow name="全局并发上限" value={String(maxConcurrent)} status="normal" desc="来自 /tasks/stats" />
              <StatRow name="运行中任务" value={String(running)} status={running > 0 ? 'building' : 'normal'} desc="global_running" />
              <StatRow name="待执行任务" value={String(pending)} status={pending > 0 ? 'building' : 'normal'} desc="global_pending" />
              <StatRow
                name="活跃用户数"
                value={String(statsData?.user_stats?.length ?? 0)}
                status="normal"
                desc="有运行任务的用户"
              />
            </div>
          </div>
        </div>
      </div>

      {/* Recent executions (from /tasks) */}
      <div className="p-5 bg-[#18181b] rounded-xl border border-[#27272a] space-y-4">
        <div className="flex flex-col sm:flex-row justify-between sm:items-center gap-3">
          <div className="space-y-1">
            <h3 className="text-sm font-bold text-[#fafafa]">运行历史 (GET /tasks)</h3>
            <p className="text-xs text-[#71717a]">最近任务列表，点击查看追踪渲染 GET /tasks/{'{id}'} 的 timeline。</p>
          </div>
          <div className="relative">
            <Search className="w-3.5 h-3.5 pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
            <input
              type="text"
              value={filterSearch}
              onChange={(e) => setFilterSearch(e.target.value)}
              placeholder="搜索工作流或ID..."
              className="pl-8 pr-3 py-1.5 w-60 text-xs bg-[#121214] border border-[#27272a] rounded-lg text-[#fafafa] focus:outline-none focus:border-indigo-500 transition font-sans font-medium"
            />
          </div>
        </div>

        {tasksLoading ? (
          <div className="flex items-center justify-center py-8 text-[#71717a] text-xs">
            <Loader2 className="w-4 h-4 animate-spin mr-2" /> 加载任务…
          </div>
        ) : filteredTasks.length === 0 ? (
          <div className="text-center py-8 text-[#71717a] text-xs">暂无任务记录</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs text-left text-[#a1a1aa] leading-normal font-sans">
              <thead>
                <tr className="border-b border-[#27272a] text-[#71717a] font-bold">
                  <th className="py-2.5 px-3 uppercase tracking-wider text-[10px]">任务 ID</th>
                  <th className="py-2.5 px-3 uppercase tracking-wider text-[10px]">工作流</th>
                  <th className="py-2.5 px-3 uppercase tracking-wider text-[10px]">创建时间</th>
                  <th className="py-2.5 px-3 uppercase tracking-wider text-[10px]">状态</th>
                  <th className="py-2.5 px-3 uppercase tracking-wider text-[10px]">版本</th>
                  <th className="py-2.5 px-3 text-right uppercase tracking-wider text-[10px]">操作</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[#27272a]/40">
                {filteredTasks.map((task) => (
                  <tr key={task.id} className="hover:bg-[#121214]/60 transition-colors">
                    <td className="py-3 px-3 font-mono text-[#fafafa] text-[11px]">{task.id.slice(-10)}</td>
                    <td className="py-3 px-3">
                      <span className="font-semibold text-[#fafafa] font-mono text-[11px]">{task.workflow_id}</span>
                    </td>
                    <td className="py-3 px-3 text-[#71717a] flex items-center gap-1">
                      <Calendar className="w-3 h-3 text-slate-600" />
                      {formatTime(task.created_at)}
                    </td>
                    <td className="py-3 px-3">
                      <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold ${taskStatusBadge(task.status)}`}>
                        <span className={`w-1 h-1 rounded-full ${taskStatusDot(task.status)}`} />
                        {task.status}
                      </span>
                    </td>
                    <td className="py-3 px-3 font-mono text-[#a1a1aa]">v{task.version}</td>
                    <td className="py-3 px-3 text-right">
                      <button
                        onClick={() => openTrace(task, onViewTask)}
                        className="text-indigo-400 hover:text-indigo-300 font-bold inline-flex items-center gap-0.5 hover:underline cursor-pointer"
                      >
                        查看追踪
                        <ExternalLink className="w-2.5 h-2.5" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

/** Fetch task detail and hand it to the trace slide-over. */
function openTrace(task: TaskSummary, onViewTask: (t: TaskDetail) => void) {
  tasksApi
    .get(task.id)
    .then(onViewTask)
    .catch(() => {
      // Silently ignore — the table row still shows summary data.
    });
}

interface MetricCardProps {
  title: string;
  value: string;
  note: string;
  icon: typeof Cpu;
  color: string;
  bg: string;
  loading?: boolean;
}

function MetricCard({ title, value, note, icon: Icon, color, bg, loading }: MetricCardProps) {
  return (
    <div className="p-5 rounded-xl border bg-[#121214] border-[#27272a] shadow-sm flex items-start justify-between relative overflow-hidden transition-all duration-250 hover:border-[#71717a]">
      <div className="space-y-1">
        <span className="text-[#a1a1aa] text-xs font-semibold tracking-wide">{title}</span>
        <p className="text-xl font-bold text-[#fafafa] font-mono">
          {loading ? <Loader2 className="w-4 h-4 animate-spin inline" /> : value}
        </p>
        <p className="text-[#71717a] text-[11px]">{note}</p>
      </div>
      <div className={`p-2.5 rounded-lg ${bg}`}>
        <Icon className={`w-4 h-4 ${color}`} />
      </div>
    </div>
  );
}

function StatRow({ name, value, status, desc }: { name: string; value: string; status: 'normal' | 'building'; desc: string }) {
  return (
    <div className="p-2.5 bg-[#121214]/60 rounded-lg border border-[#27272a] text-[11px]">
      <div className="flex justify-between items-center mb-1">
        <span className="font-semibold text-[#fafafa]">{name}</span>
        <span className={`px-1.5 py-0.5 rounded text-[10px] font-mono font-bold ${status === 'normal' ? 'bg-emerald-500/10 text-emerald-400' : 'bg-indigo-500/10 text-indigo-400'}`}>
          {value}
        </span>
      </div>
      <span className="text-[#71717a]">{desc}</span>
    </div>
  );
}

/** Build a 7-bucket chart from task created_at timestamps (best-effort). */
function build7DayChart(tasks: TaskSummary[]): { label: string; val: number }[] {
  const days: { label: string; val: number; key: string }[] = [];
  const now = new Date();
  for (let i = 6; i >= 0; i--) {
    const d = new Date(now);
    d.setDate(now.getDate() - i);
    const key = d.toISOString().slice(0, 10);
    const label = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][d.getDay()];
    days.push({ label, val: 0, key });
  }
  const byKey = new Map(days.map((d) => [d.key, d]));
  for (const t of tasks) {
    const key = t.created_at?.slice(0, 10);
    const day = key ? byKey.get(key) : undefined;
    if (day) day.val += 1;
  }
  return days.map(({ label, val }) => ({ label, val }));
}

function formatTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

function taskStatusBadge(status: string): string {
  switch (status) {
    case 'running':
      return 'bg-amber-500/10 text-amber-400';
    case 'waiting_human':
      return 'bg-emerald-500/10 text-emerald-400';
    case 'completed':
      return 'bg-indigo-500/10 text-indigo-400';
    case 'failed':
    case 'cancelled':
      return 'bg-red-500/10 text-red-400';
    default:
      return 'bg-[#27272a] text-[#a1a1aa]';
  }
}

function taskStatusDot(status: string): string {
  switch (status) {
    case 'running':
      return 'bg-amber-400 animate-pulse';
    case 'completed':
      return 'bg-indigo-400';
    case 'failed':
    case 'cancelled':
      return 'bg-red-400';
    default:
      return 'bg-[#71717a]';
  }
}

// Re-export the TimelineEvent type so App.tsx's trace slide-over can use it.
export type { TimelineEvent };

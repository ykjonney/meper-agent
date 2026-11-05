/**
 * TasksPage — 视觉照抄 all-pages-review ③④，功能对齐 v1 TaskBoard + TriggersPage：
 *  - 看板六列（cancelled 独立）+ 统计卡 ×4 + intervene 干预（取消/重试，version 乐观锁）
 *  - 定时 Tab：scope 我的/全部（trigger:manage 门控）+ 归属用户列 + workflow 名称映射
 *    + stats 三卡 + 搜索 + 删除 + 启停
 * TODO-API: 任务名（G5）、新建任务/编辑触发器表单（P4.5，ConfigModal v1 已有可移植）。
 */
import { useMemo, useState } from 'react';
import { useQuery, useQueryClient, useMutation } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { tasksApi, type TaskSummary, type TaskStatusValue } from '../services/tasks-api';
import { triggersApi as trigApi, type TriggerConfig } from '../services/triggers-api';
import { useAuthStore } from '../stores/auth-store';
import TriggerConfigModal from '../components/trigger/TriggerConfigModal';

const CSS = `
.tw { height:100%; overflow-y:auto; background:var(--color-canvas); font-family:-apple-system,'PingFang SC','Segoe UI',sans-serif; font-size:14px; color:#1E1B2E; }
.tw-inner { padding:14px; min-height:100%; }
.tw * { box-sizing:border-box; }
.K-card { background:#fff; border-radius:13px; padding:14px 17px; box-shadow:0 1px 3px rgba(42,38,64,.05); }
.K-pill { font-size:10px; border-radius:99px; padding:2px 10px; font-weight:700; display:inline-block; }
.K-pg { background:#E8F6EE; color:#1F8A55; } .K-pr { background:#EFEAFD; color:#6D4AE0; }
.K-pw { background:#FDF3E1; color:#B97A0F; } .K-pe { background:#FEE2E2; color:#DC2626; }
.K-pd { background:#F1EFF8; color:#8A85A3; }
.K-bp { background:linear-gradient(135deg,#8B5CF6,#6D4AE0); color:#fff; border-radius:8px; padding:5px 15px; font-size:12px; font-weight:700; display:inline-block; cursor:pointer; }
.K-bg { border:1px solid #DDD3F8; color:#6D4AE0; border-radius:8px; padding:5px 15px; font-size:12px; font-weight:700; background:#fff; display:inline-block; cursor:pointer; }
.K-meter { height:5px; background:#F1EEF9; border-radius:99px; overflow:hidden; }
.K-meter i { display:block; height:100%; background:linear-gradient(90deg,#8B5CF6,#6D4AE0); border-radius:99px; }
.K-meter i.pulse { width:100%; animation: tw-pulse 1.6s ease-in-out infinite; }
@keyframes tw-pulse { 0%,100% { opacity:.4 } 50% { opacity:1 } }
.K-tabs { display:flex; gap:4px; background:#ECE8F8; border-radius:11px; padding:4px; }
.K-tab { padding:4px 14px; border-radius:8px; font-size:13px; color:#8A85A3; font-weight:600; cursor:pointer; }
.K-tab.on { background:#fff; color:#6D4AE0; box-shadow:0 1px 3px rgba(42,38,64,.08); }
.K-tg { width:29px; height:17px; border-radius:99px; background:#8B5CF6; position:relative; display:inline-block; vertical-align:middle; cursor:pointer; }
.K-tg i { position:absolute; top:2px; right:2px; width:13px; height:13px; border-radius:50%; background:#fff; transition: left .15s; }
.K-tg.off { background:#DDD6E8; } .K-tg.off i { right:auto; left:2px; }
.K-tbl { width:100%; border-collapse:collapse; font-size:13px; }
.K-tbl th { text-align:left; font-size:11px; color:#9A95B0; text-transform:uppercase; letter-spacing:.4px; padding:8px 10px; border-bottom:1px solid #EFEDF7; }
.K-tbl td { padding:9px 10px; border-bottom:1px solid #F4F2FA; color:#55506E; }
.K-tbl tr:last-child td { border-bottom:none; }
.col-head { display:flex; align-items:center; gap:7px; font-size:12.5px; font-weight:700; }
.stat-card { flex:1; background:#fff; border-radius:13px; padding:14px 17px; box-shadow:0 1px 3px rgba(42,38,64,.05); }
.stat-card .l { font-size:12px; color:#8A85A3; }
.stat-card .v { font-size:26px; font-weight:800; margin-top:3px; font-family:var(--font-mono); }
.ag-srch { background:#fff; border:1px solid #E2DCF5; border-radius:10px; padding:6px 14px; font-size:13px; color:#B6B1C9; width:240px; outline:none; }
`;

// 排队（pending）为瞬态 — 调度器直接执行，用户视角无排队概念：不设列
const SIX_COLS: { key: Exclude<TaskStatusValue, 'pending'>; head: string; color: string; pill: string }[] = [
  { key: 'running', head: '⚡ 执行中', color: '#6D4AE0', pill: 'K-pr' },
  { key: 'waiting_human', head: '🖐 待人工', color: '#B97A0F', pill: 'K-pw' },
  { key: 'completed', head: '✅ 已完成', color: '#1F8A55', pill: 'K-pg' },
  { key: 'failed', head: '❌ 已失败', color: '#DC2626', pill: 'K-pe' },
  { key: 'cancelled', head: '🚫 已取消', color: '#8A85A3', pill: 'K-pd' },
];

function fmtAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  if (diff < 60_000) return '刚刚';
  if (diff < 3600_000) return `${Math.floor(diff / 60_000)} 分钟前`;
  if (diff < 86400_000) return `${Math.floor(diff / 3600_000)} 小时前`;
  return new Date(iso).toLocaleDateString('zh-CN');
}

function runDuration(iso: string): string {
  const sec = Math.max(1, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  return sec >= 60 ? `${Math.floor(sec / 60)}m ${sec % 60}s` : `${sec}s`;
}

export function TasksPage() {
  const [tab, setTab] = useState<'board' | 'schedule'>('board');
  const [trigModal, setTrigModal] = useState<{ open: boolean; mode: 'create' | 'edit'; trigger: TriggerConfig | null }>({ open: false, mode: 'create', trigger: null });
  const qc = useQueryClient();
  const nav = useNavigate();
  const permissions = useAuthStore((s) => s.user?.permissions);
  const canManage = permissions?.includes('trigger:manage') ?? false;

  // ── 看板：六列并发查询（v1 同款分桶） ──
  const { data: boardData, isLoading } = useQuery({
    queryKey: ['tasks', 'board'],
    queryFn: async () => {
      const statuses: TaskStatusValue[] = ['running', 'waiting_human', 'completed', 'failed', 'cancelled'];
      const results = await Promise.all(statuses.map((st) => tasksApi.list({ status: st, page_size: 30 })));
      return {
        running: results[0].items as TaskSummary[],
        waiting_human: results[1].items as TaskSummary[],
        completed: results[2].items as TaskSummary[],
        failed: results[3].items as TaskSummary[],
        cancelled: results[4].items as TaskSummary[],
      };
    },
    refetchInterval: 15_000,
  });
  const byStatus = boardData ?? {
    running: [], waiting_human: [], completed: [], failed: [], cancelled: [],
  } as unknown as Record<Exclude<TaskStatusValue, 'pending'>, TaskSummary[]>;

  // ── intervene 干预（v1 同款：cancel/retry，version 乐观锁） ──
  const [actionError, setActionError] = useState<string | null>(null);
  const intervene = useMutation({
    mutationFn: (vars: { taskId: string; action: string; version: number }) =>
      tasksApi.intervene(vars.taskId, { action: vars.action as never, version: vars.version, comment: undefined }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ['tasks'] }); setActionError(null); },
    onError: (e) => setActionError((e as Error).message || '操作失败'),
  });
  const confirmIntervene = (task: TaskSummary, action: 'cancel' | 'retry') => {
    const label = action === 'cancel'
      ? `取消任务「${task.id.slice(-8)}」？\n任务将被中止，无法恢复。`
      : `重试任务「${task.id.slice(-8)}」？`;
    if (window.confirm(label.replace('\n', '\n'))) intervene.mutate({ taskId: task.id, action, version: task.version });
  };

  // ── 定时：scope + 名称映射 + CRUD ──
  const [scope, setScope] = useState<'own' | 'all'>('own');
  const [trigSearch, setTrigSearch] = useState('');
  const { data: trig, isLoading: trigLoading } = useQuery({
    queryKey: ['triggers', scope],
    queryFn: () => trigApi.list(scope === 'all'),
    enabled: tab === 'schedule',
  });
  const { data: wfRegistry } = useQuery({
    queryKey: ['workflow-registry'], queryFn: () => tasksApi.listWorkflows(), enabled: tab === 'schedule',
  });
  const wfNameMap = useMemo(() => {
    const map: Record<string, string> = {};
    for (const w of (wfRegistry?.items ?? []) as unknown as Array<Record<string, unknown>>) {
      const id1 = String(w._id ?? ''), id2 = String(w.workflow_id ?? ''), name = String(w.name ?? '');
      if (id1) map[id1] = name;
      if (id2) map[id2] = name;
    }
    return map;
  }, [wfRegistry]);
  const wfName = (id: string) => wfNameMap[id] || `工作流 ${id.slice(-8)}`;

  const triggers = useMemo(() => {
    const list = (trig?.items ?? []) as TriggerConfig[];
    if (!trigSearch.trim()) return list;
    const q = trigSearch.trim().toLowerCase();
    return list.filter((t) =>
      (wfNameMap[t.workflow_id] ?? '').toLowerCase().includes(q) ||
      (t.cron_expression ?? '').toLowerCase().includes(q) ||
      t.workflow_id.toLowerCase().includes(q),
    );
  }, [trig, trigSearch, wfNameMap]);
  const trigStats = useMemo(() => {
    const enabled = triggers.filter((t) => t.enabled).length;
    return { total: triggers.length, enabled, disabled: triggers.length - enabled };
  }, [triggers]);

  const toggleTrigger = async (t: TriggerConfig) => {
    const id = t.id ?? t._id;
    if (!id) return;
    await trigApi.toggle(id, !t.enabled);
    qc.invalidateQueries({ queryKey: ['triggers'] });
  };
  const removeTrigger = async (t: TriggerConfig) => {
    const id = t.id ?? t._id;
    if (!id || !window.confirm(`删除定时任务「${wfName(t.workflow_id)}」？\n删除后将永久停止，已触发记录不受影响。`)) return;
    await trigApi.remove(id);
    qc.invalidateQueries({ queryKey: ['triggers'] });
  };

  const statCards = [
    { label: '⚡ 运行中', value: byStatus.running.length, color: '#6D4AE0' },
    { label: '🖐 等待人工', value: byStatus.waiting_human.length, color: '#B97A0F' },
    { label: '✅ 已完成', value: byStatus.completed.length, color: '#1F8A55' },
    { label: '❌ 已失败', value: byStatus.failed.length, color: '#DC2626' },
    { label: '🚫 已取消', value: byStatus.cancelled.length, color: '#8A85A3' },
  ];

  return (
    <div className="tw">
      <style>{CSS}</style>
      <div className="tw-inner">
        {/* 页头 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 13 }}>
          <b style={{ fontSize: 18, fontWeight: 800 }}>任务</b>
          <div className="K-tabs">
            <span className={`K-tab ${tab === 'board' ? 'on' : ''}`} onClick={() => setTab('board')}>看板</span>
            <span className={`K-tab ${tab === 'schedule' ? 'on' : ''}`} onClick={() => setTab('schedule')}>
              定时任务{trig ? ` · ${trig.total}` : ''}
            </span>
          </div>
        </div>

        {actionError && (
          <div style={{ marginBottom: 10, padding: '8px 14px', borderRadius: 10, background: 'var(--color-danger-soft)', border: '1px solid var(--color-danger)', color: 'var(--color-danger)', fontSize: 12, display: 'flex', justifyContent: 'space-between' }}>
            <span>⚠ {actionError}</span>
            <span style={{ cursor: 'pointer' }} onClick={() => setActionError(null)}>✕</span>
          </div>
        )}

        {tab === 'board' ? (
          <>
            {/* 统计卡 ×4（v1 同款） */}
            <div style={{ display: 'flex', gap: 12, marginBottom: 13 }}>
              {statCards.map((st) => (
                <div key={st.label} className="stat-card">
                  <div className="l">{st.label}</div>
                  <div className="v" style={{ color: st.color }}>{st.value}</div>
                </div>
              ))}
            </div>

            {isLoading ? (
              <div style={{ padding: 40, textAlign: 'center', color: '#9A95B0' }}>加载中…</div>
            ) : (
              <div style={{ display: 'flex', gap: 12, alignItems: 'flex-start', overflowX: 'auto', paddingBottom: 8 }}>
                {SIX_COLS.map((col) => {
                  const items = byStatus[col.key];
                  return (
                    <div key={col.key} style={{ flex: 1, minWidth: 210, display: 'flex', flexDirection: 'column', gap: 10 }}>
                      <div className="col-head" style={{ color: col.color }}>
                        {col.head} <span className={`K-pill ${col.pill}`}>{items.length}</span>
                      </div>
                      {items.map((t) => {
                        const isWait = t.status === 'waiting_human';
                        const canCancel = t.status === 'running' || isWait;
                        const canRetry = t.status === 'failed' || t.status === 'cancelled';
                        return (
                          <div
                            key={t.id}
                            className="K-card"
                            onClick={() => nav(`/tasks/${t.id}`)}
                            style={{
                              padding: '12px 13px', cursor: 'pointer', minHeight: 118,
                              display: 'flex', flexDirection: 'column',
                              border: isWait ? '1px solid var(--color-warn-border)' : t.status === 'running' ? '1px solid #DDD3F8' : t.status === 'failed' ? '1px solid var(--color-danger)' : undefined,
                              background: isWait ? 'var(--color-warn-bg)' : undefined,
                            }}
                          >
                            <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                              <b style={{ fontSize: 12.5 }}>
                                {isWait ? '🖐' : t.trigger_id ? '🕒' : '💬'} 任务 #{t.id.slice(-8)}
                              </b>
                            </div>
                            <div style={{ fontSize: 11, color: isWait ? 'var(--color-warning)' : '#9A95B0', margin: '4px 0' }}>
                              {isWait
                                ? `⏳ 等待人工介入 · ${fmtAgo(t.created_at)}`
                                : t.trigger_id
                                  ? `🕒 定时触发 · 工作流 ${t.workflow_id.slice(-8)}`
                                  : `💬 会话发起 · 工作流 ${t.workflow_id.slice(-8)}`}
                            </div>
                            {t.status === 'running' && (
                              <div className="K-meter"><i className="pulse" /></div>
                            )}
                            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10.5, color: '#B6B1C9', marginTop: 5 }}>
                              <span>{t.status === 'running' ? `已运行 ${runDuration(t.created_at)}` : fmtAgo(t.updated_at)}</span>
                              {t.total_tokens ? <span style={{ fontFamily: 'Menlo,monospace' }}>{(t.total_tokens / 1000).toFixed(1)}k tok</span> : null}
                            </div>
                            {t.status === 'failed' && t.error && (
                              <div style={{ marginTop: 5, fontSize: 11, color: 'var(--color-danger)' }}>
                                ✗ {t.error.error_message || t.error.error_code}
                              </div>
                            )}
                            {isWait && (
                              <div style={{ display: 'flex', gap: 6, marginTop: 7 }}>
                                <span className="K-bp" style={{ fontSize: 11 }} onClick={(e) => { e.stopPropagation(); nav('/chat'); }}>去处理 →</span>
                                <span className="K-bg" style={{ fontSize: 11 }} onClick={(e) => { e.stopPropagation(); nav(`/tasks/${t.id}`); }}>详情</span>
                              </div>
                            )}
                            {(canCancel || canRetry) && (
                              <div style={{ display: 'flex', gap: 6, marginTop: 7 }}>
                                {canRetry && (
                                  <span className="K-bg" style={{ fontSize: 10.5, padding: '3px 10px' }}
                                        onClick={(e) => { e.stopPropagation(); confirmIntervene(t, 'retry'); }}>↻ 重试</span>
                                )}
                                {canCancel && (
                                  <span className="K-bg" style={{ fontSize: 10.5, padding: '3px 10px', color: 'var(--color-danger)', borderColor: 'var(--color-danger)' }}
                                        onClick={(e) => { e.stopPropagation(); confirmIntervene(t, 'cancel'); }}>取消任务</span>
                                )}
                              </div>
                            )}
                          </div>
                        );
                      })}
                      {items.length === 0 && (
                        <div style={{ borderRadius: 12, border: '1px dashed #DDD3F8', padding: '16px 10px', textAlign: 'center', fontSize: 11, color: '#B6B1C9' }}>空</div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </>
        ) : (
          <>
            {/* stats 三卡（v1 同款） */}
            <div style={{ display: 'flex', gap: 12, marginBottom: 13 }}>
              {[
                { label: '定时任务总数', v: trigStats.total, c: '#6D4AE0' },
                { label: '启用中', v: trigStats.enabled, c: '#1F8A55' },
                { label: '已停用', v: trigStats.disabled, c: '#8A85A3' },
              ].map((st) => (
                <div key={st.label} className="stat-card">
                  <div className="l">{st.label}</div>
                  <div className="v" style={{ color: st.c }}>{st.v}</div>
                </div>
              ))}
            </div>

            {tab === 'schedule' && (
              <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12 }}>
                <span className="K-bp" onClick={() => setTrigModal({ open: true, mode: 'create', trigger: null })}>＋ 新建定时</span>
              </div>
            )}

            {/* scope 切换（trigger:manage）+ 搜索 */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
              {canManage && (
                <div className="K-tabs">
                  <span className={`K-tab ${scope === 'own' ? 'on' : ''}`} onClick={() => setScope('own')}>我的</span>
                  <span className={`K-tab ${scope === 'all' ? 'on' : ''}`} onClick={() => setScope('all')}>全部用户</span>
                </div>
              )}
              <input
                className="ag-srch"
                style={{ marginLeft: canManage ? 0 : 'auto' }}
                value={trigSearch}
                onChange={(e) => setTrigSearch(e.target.value)}
                placeholder="🔍 搜索工作流名 / cron 表达式"
              />
            </div>

            <div className="K-card" style={{ overflow: 'hidden' }}>
              <table className="K-tbl">
                <thead>
                  <tr>
                    {canManage && scope === 'all' && <th>归属用户</th>}
                    {['工作流', '类型', 'CRON', '下次触发', '最近触发', ''].map((h) => <th key={h}>{h}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {trigLoading && (
                    <tr><td colSpan={canManage && scope === 'all' ? 7 : 6} style={{ padding: 40, textAlign: 'center', color: '#9A95B0' }}>加载中…</td></tr>
                  )}
                  {!trigLoading && triggers.map((t) => {
                    const id = t.id ?? t._id ?? '';
                    return (
                      <tr key={id}>
                        {canManage && scope === 'all' && (
                          <td style={{ fontFamily: 'Menlo,monospace', fontSize: 11, color: '#9A95B0' }}>{t.user_id || '-'}</td>
                        )}
                        <td><b style={{ color: '#2A2640', fontSize: 12.5 }}>{wfName(t.workflow_id)}</b></td>
                        <td><span className="K-pill K-pd">{t.type}</span></td>
                        <td style={{ fontFamily: 'Menlo,monospace', fontSize: 11 }}>{t.cron_expression ?? '—'}</td>
                        <td style={{ fontSize: 12 }}>{t.next_trigger_at ? new Date(t.next_trigger_at).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '—'}</td>
                        <td style={{ fontSize: 12 }}>{t.last_triggered_at ? fmtAgo(t.last_triggered_at) : '—'}</td>
                        <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                          <span className="K-bg" style={{ fontSize: 10.5, padding: '3px 10px', marginRight: 6 }}
                                onClick={() => setTrigModal({ open: true, mode: 'edit', trigger: t })}>编辑</span>
                          <span className="K-bg" style={{ fontSize: 10.5, padding: '3px 10px', marginRight: 6, color: 'var(--color-danger)', borderColor: 'var(--color-danger)' }}
                                onClick={() => removeTrigger(t)}>删除</span>
                          <span className={`K-tg ${t.enabled ? '' : 'off'}`} onClick={() => toggleTrigger(t)}><i /></span>
                        </td>
                      </tr>
                    );
                  })}
                  {!trigLoading && triggers.length === 0 && (
                    <tr><td colSpan={canManage && scope === 'all' ? 7 : 6} style={{ padding: '40px 0', textAlign: 'center', color: '#B6B1C9', fontSize: 12 }}>
                      暂无定时触发器 — 点「＋ 新建定时」创建
                    </td></tr>
                  )}
                </tbody>
              </table>
              {trigModal.open && (
                <TriggerConfigModal
                  open={trigModal.open}
                  mode={trigModal.mode}
                  trigger={trigModal.trigger}
                  workflows={(wfRegistry?.items ?? []) as never}
                  onClose={() => setTrigModal({ open: false, mode: 'create', trigger: null })}
                  onSaved={() => { setTrigModal({ open: false, mode: 'create', trigger: null }); qc.invalidateQueries({ queryKey: ['triggers'] }); }}
                />
              )}
            </div>
          </>
        )}

              </div>
    </div>
  );
}

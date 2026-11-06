/**
 * ExternalAccessPage — 外部接入（设置 Tab，原「通用」）。
 *
 * API Key 管理：供 /ext 嵌入式对话与第三方系统调用 OpenAPI。
 * 布局：左侧创建/编辑表单 + 右侧 Key 列表展示（同页双栏）。
 * 资源绑定（智能体/工作流）用锚定浮层选择（同 AgentEditorPage 能力浮层形态）。
 *
 * RuntimeParamsPage — 全局参数（独立设置 Tab，分组分区形态，持续扩容）。
 *
 * 设计稿：docs/design-mockups/admin-pages.html pane-apikey +
 * apikey-pages.html（下划线输入 + res-chips 形态）。
 */
import { useEffect, useRef, useState, FormEvent, type InputHTMLAttributes } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  ShieldAlert, Plus, Sliders, CheckCircle, Check, Copy,
  AlertTriangle, RefreshCw, Pencil, ArrowLeft, Search, X, Bot, Workflow,
} from 'lucide-react';
import { agentApi } from '../services/agent-api';
import { workflowsApi } from '../services/workflows-api';
import {
  apiKeyApi, apiKeyKeys, ALL_API_KEY_SCOPES, SCOPE_LABELS,
  type ApiKey,
  type ApiKeyCreateInput, type ApiKeyCreated, type ApiKeyUpdateInput,
} from '../services/api-keys-api';
import { applicationApi, applicationKeys } from '../services/application-api';
import { getErrorMessage } from '../lib/api-client';
import { copyToClipboard } from '../lib/clipboard';

/** Fields rendered in the detail panel — satisfied by both list items and the create response. */
type KeyDetailLike = {
  scopes: string[];
  bindings: { agents: string[]; workflows: string[] };
  rate_limit: number;
  expires_at: string | null;
  key_prefix: string;
  introspect_url?: string;
  app_id?: string;
  created_at: string;
  last_used_at?: string | null;
  updated_at?: string;
};

/** ISO timestamp → YYYY-MM-DD, or fallback when null/empty. */
function fmtDate(iso: string | null | undefined, fallback = '—'): string {
  if (!iso) return fallback;
  return iso.length >= 10 ? iso.slice(0, 10) : fallback;
}

function toggleInSet<T>(set: Set<T>, value: T): Set<T> {
  const next = new Set(set);
  if (next.has(value)) next.delete(value);
  else next.add(value);
  return next;
}

/* ── 设计稿小件：kicker 分节标题 / 下划线输入 / 字段标签 ───────────── */

function Kicker({ children, hint }: { children: string; hint?: string }) {
  return (
    <div className="af-label mb-3">
      {children}
      {hint && <span className="normal-case tracking-normal font-medium text-ink-faint ml-2">{hint}</span>}
    </div>
  );
}

/** 字段标签：主标签 + 可选说明（淡色、常规字重） */
function FieldLabel({ label, required, hint }: { label: string; required?: boolean; hint?: string }) {
  return (
    <div className="text-[12px] font-semibold text-ink mb-1.5">
      {label}
      {required && <span className="text-sig-fail ml-0.5">*</span>}
      {hint && <span className="text-ink-faint font-normal text-[11px] ml-2">{hint}</span>}
    </div>
  );
}

/** 下划线输入（设计稿 fld input 形态——禁用 SaaS 边框堆叠） */
function LineInput(props: InputHTMLAttributes<HTMLInputElement>) {
  const { className, ...rest } = props;
  return (
    <input
      {...rest}
      className={`w-full border-0 border-b border-line-strong bg-transparent px-0 py-2 text-[13px] text-ink placeholder:text-ink-faint focus:outline-none focus:border-brand transition ${className ?? ''}`}
    />
  );
}

/* ═══════════════════════ 外部接入：左表单 + 右列表双栏 ═══════════════════════ */

export function ExternalAccessPage() {
  const qc = useQueryClient();

  const { data, isLoading, isFetching } = useQuery({
    queryKey: apiKeyKeys.lists(),
    queryFn: () => apiKeyApi.list(),
  });
  const apiKeys = data?.items ?? [];
  const activeCount = apiKeys.filter((k) => k.status === 'active').length;

  // 编辑态：列表「编辑」→ 左栏表单载入该 Key；取消回创建模式
  const [editingKey, setEditingKey] = useState<ApiKey | null>(null);
  const [createdKey, setCreatedKey] = useState<ApiKeyCreated | null>(null);
  const [copiedValue, setCopiedValue] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // 选项列表——表单浮层 + 详情面板名称解析共用
  const { data: agentsData } = useQuery({
    queryKey: ['api-keys', 'agent-options'],
    queryFn: () => agentApi.list({ page: 1, page_size: 100, status: 'all' }),
  });
  const { data: workflowsData } = useQuery({
    queryKey: ['api-keys', 'workflow-options'],
    queryFn: () => workflowsApi.list({ page: 1, page_size: 100 }),
  });
  const { data: appsData } = useQuery({
    queryKey: applicationKeys.lists(),
    queryFn: () => applicationApi.list(),
  });

  const agentName = (id: string) => agentsData?.items.find((a) => a.id === id)?.name ?? id;
  const workflowName = (id: string) => workflowsData?.items.find((w) => w.id === id)?.name ?? id;
  const appName = (id: string) => appsData?.items.find((a) => a.id === id)?.name ?? id;

  const copy = (text: string) => {
    copyToClipboard(text);
    setCopiedValue(text);
    setTimeout(() => setCopiedValue(null), 2000);
  };

  const revokeMutation = useMutation({
    mutationFn: (id: string) => apiKeyApi.revoke(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: apiKeyKeys.lists() }),
  });

  const handleRevoke = (key: ApiKey) => {
    if (!window.confirm(`确认撤销 Key「${key.name}」？撤销后该 Key 立即失效，且无法恢复。`)) return;
    revokeMutation.mutate(key.id);
  };

  // ── 详情行渲染（plain function） ──
  const renderRow = (label: string, value: string, mono = false) => (
    <div className="flex gap-2" key={label}>
      <span className="text-ink-dim w-20 shrink-0">{label}</span>
      <span className={`text-ink-soft ${mono ? 'font-mono break-all' : ''}`}>{value}</span>
    </div>
  );

  const renderKeyDetail = (info: KeyDetailLike) => {
    const aNames = info.bindings.agents.map(agentName);
    const wNames = info.bindings.workflows.map(workflowName);
    return (
      <div className="space-y-2.5 pt-3 mt-3 border-t border-line text-[11px] font-sans">
        <div className="flex gap-2">
          <span className="text-ink-dim w-20 shrink-0">权限</span>
          <div className="flex flex-wrap gap-1">
            {info.scopes.map((s) => (
              <span key={s} className="px-1.5 py-0.5 rounded bg-raise text-ink-dim text-[11px] font-mono">
                {SCOPE_LABELS[s] ?? s}
              </span>
            ))}
          </div>
        </div>
        <div className="flex gap-2">
          <span className="text-ink-dim w-20 shrink-0">资源绑定</span>
          <div className="space-y-0.5">
            {aNames.length === 0 && wNames.length === 0 ? (
              <span className="text-ink-faint">不限制（可访问全部资源）</span>
            ) : (
              <>
                {aNames.length > 0 && <div className="text-ink-soft">智能体：{aNames.join('、')}</div>}
                {wNames.length > 0 && <div className="text-ink-soft">工作流：{wNames.join('、')}</div>}
              </>
            )}
          </div>
        </div>
        {renderRow('限流', `${info.rate_limit} 次/分`)}
        {info.app_id !== undefined && renderRow('绑定应用', info.app_id ? appName(info.app_id) : '未绑定')}
        {info.introspect_url !== undefined &&
          renderRow('身份校验', info.introspect_url || '未配置', !!info.introspect_url)}
        {renderRow('过期时间', info.expires_at ? fmtDate(info.expires_at) : '永不过期')}
        {renderRow('创建时间', fmtDate(info.created_at))}
        {info.updated_at && renderRow('更新时间', fmtDate(info.updated_at))}
        {info.last_used_at !== undefined &&
          renderRow('上次使用', fmtDate(info.last_used_at, '从未使用'))}
        <div className="flex items-center gap-2 flex-wrap">
          <span className="text-ink-dim w-20 shrink-0">密钥前缀</span>
          <code className="text-ink-dim font-mono">{info.key_prefix || '—'}</code>
          {info.key_prefix && (
            <button
              onClick={() => copy(info.key_prefix)}
              className="text-ink-dim hover:text-ink flex items-center gap-0.5 cursor-pointer transition"
            >
              {copiedValue === info.key_prefix ? (
                <Check className="w-3 h-3 text-sig-ok" />
              ) : (
                <Copy className="w-3 h-3" />
              )}
              <span className="text-[11px]">{copiedValue === info.key_prefix ? '已复制' : '复制'}</span>
            </button>
          )}
          <span className="text-[11px] text-ink-faint">明文仅创建时可见，无法再次获取</span>
        </div>
      </div>
    );
  };

  return (
    <div className="space-y-4">
      {/* One-time raw key reveal（创建成功后置顶提示） */}
      {createdKey && (
        <div className="p-4 bg-sig-ok-soft border border-line rounded-xl space-y-3">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-center gap-2 text-sig-ok text-sm font-bold font-sans">
              <CheckCircle className="w-4 h-4 shrink-0" />
              Key「{createdKey.name}」已创建
            </div>
            <button
              onClick={() => setCreatedKey(null)}
              className="text-ink-dim hover:text-ink transition cursor-pointer"
              aria-label="关闭"
            >
              ✕
            </button>
          </div>

          <div className="flex items-center gap-1.5 text-[11px] text-sig-wait font-sans">
            <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
            明文 Key 仅此一次显示，关闭后无法再次查看，请立即复制保存。
          </div>

          <div className="flex items-center gap-2">
            <code className="flex-1 px-3 py-2 bg-panel border border-line rounded-lg text-ink font-mono text-xs break-all">
              {createdKey.key}
            </code>
            <button onClick={() => copy(createdKey.key)} className="shrink-0 af-btn af-btn-primary">
              {copiedValue === createdKey.key ? (
                <Check className="w-3.5 h-3.5" />
              ) : (
                <Copy className="w-3.5 h-3.5" />
              )}
              {copiedValue === createdKey.key ? '已复制' : '复制 Key'}
            </button>
          </div>

          {renderKeyDetail(createdKey)}
        </div>
      )}

      {/* 双栏：左创建/编辑表单 + 右 Key 列表 */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-5 items-start">
        {/* 左：创建/编辑表单（col-span-5） */}
        <div className="lg:col-span-5 min-w-0">
          <KeyFormCard
            keyItem={editingKey ?? undefined}
            agents={agentsData?.items ?? []}
            workflows={workflowsData?.items ?? []}
            apps={appsData?.items ?? []}
            onCancelEdit={() => setEditingKey(null)}
            onCreated={(res) => {
              setCreatedKey(res);
              qc.invalidateQueries({ queryKey: apiKeyKeys.lists() });
            }}
            onUpdated={() => {
              qc.invalidateQueries({ queryKey: apiKeyKeys.lists() });
              setEditingKey(null);
            }}
          />
        </div>

        {/* 右：stats + Key 列表（col-span-7）——列表区内滚，左表单不被滚走 */}
        <div className="lg:col-span-7 min-w-0 space-y-4 flex flex-col lg:max-h-[calc(100vh-230px)]">
          {/* stats 条（真实数据 + 接入端点） */}
          <div className="flex bg-panel border border-line rounded-xl divide-x divide-line shadow-[var(--shadow-card)] shrink-0">
            <div className="flex-1 px-4 py-3">
              <div className="text-[22px] font-bold text-ink leading-tight">{activeCount}</div>
              <div className="text-[11px] text-ink-dim mt-0.5">活跃 Key · 共 {apiKeys.length} 个</div>
            </div>
            <div className="flex-[1.4] px-4 py-3 flex flex-col justify-center">
              <div className="font-mono text-[13px] text-ink font-semibold">POST /api/v1/ext/*</div>
              <div className="text-[11px] text-ink-dim mt-0.5">接入端点 · 携带 Authorization: Bearer + X-User-Token</div>
            </div>
          </div>

          {/* Key 列表 — cfg-row 配置行（无边框行 + hairline 分隔）；超高内滚（min-h-0
              允许 flex 收缩，内容少时自然高度、撑满 max-h 后压缩滚动） */}
          <div className="bg-panel border border-line rounded-xl shadow-[var(--shadow-card)] min-h-0 overflow-y-auto scrollbar-custom">
            {isLoading && (
              <p className="text-xs text-ink-faint font-sans text-center py-8">加载中…</p>
            )}
            {!isLoading && apiKeys.length === 0 && (
              <p className="text-xs text-ink-faint font-sans text-center py-8">暂无对外 Key，在左侧创建第一个。</p>
            )}
            {apiKeys.map((key, i) => {
              const open = expandedId === key.id;
              const active = key.status === 'active';
              return (
                <div key={key.id} className={i > 0 ? 'border-t border-line' : ''}>
                  <div className="flex items-center gap-3 px-4 py-3.5">
                    {/* KEY 实体块 */}
                    <span
                      className={`w-9 h-9 rounded-lg font-mono text-[9px] font-bold flex items-center justify-center shrink-0 ${
                        active ? 'bg-brand-soft text-brand' : 'bg-raise text-ink-faint'
                      }`}
                    >
                      KEY
                    </span>
                    {/* 名称 + 状态 + mono 描述 */}
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="text-[13px] font-semibold text-ink truncate">{key.name}</span>
                        <span className={`af-pill ${active ? 'af-pill-ok' : 'af-pill-neutral'}`}>
                          {active ? '活跃' : '已撤销'}
                        </span>
                      </div>
                      <div className="text-[11px] text-ink-dim font-mono mt-0.5 truncate">
                        {key.key_prefix || '—'} · {key.scopes.length} 项权限 · 限流 {key.rate_limit}/分 ·{' '}
                        {key.expires_at ? `有效期至 ${fmtDate(key.expires_at)}` : '永不过期'}
                      </div>
                    </div>
                    {/* 上次使用 */}
                    <span className="hidden xl:block text-[11px] text-ink-faint font-mono shrink-0">
                      {key.last_used_at ? `${fmtDate(key.last_used_at)} 使用` : '从未使用'}
                    </span>
                    {/* 操作 */}
                    <div className="flex items-center gap-3 shrink-0 text-xs">
                      <button
                        onClick={() => setExpandedId((prev) => (prev === key.id ? null : key.id))}
                        className="text-brand hover:opacity-75 cursor-pointer font-medium"
                      >
                        {open ? '收起' : '详情'}
                      </button>
                      {active && (
                        <button
                          onClick={() => setEditingKey(key)}
                          className="text-brand hover:opacity-75 cursor-pointer font-medium flex items-center gap-0.5"
                        >
                          <Pencil className="w-3 h-3" />
                          编辑
                        </button>
                      )}
                      {active && (
                        <button
                          onClick={() => handleRevoke(key)}
                          disabled={revokeMutation.isPending}
                          className="text-sig-fail hover:opacity-75 cursor-pointer font-medium disabled:opacity-40"
                        >
                          撤销
                        </button>
                      )}
                    </div>
                  </div>
                  {open && <div className="px-4 pb-4">{renderKeyDetail(key)}</div>}
                </div>
              );
            })}
          </div>

          {/* 底部 mono 说明（设计稿 pane-apikey 脚注） */}
          <p className="text-[10.5px] text-ink-faint font-mono shrink-0">
            Key 创建后仅展示一次完整值（复制保存），此后只显示掩码 · 权限范围与资源绑定在详情中查看
          </p>
        </div>
      </div>
    </div>
  );
}

/* ── 资源选择浮层：智能体/工作流 tab 勾选（形态同 AgentEditorPage 能力浮层） ── */

type PickerItem = { id: string; name: string; description?: string };
type PickerTab = 'agent' | 'workflow';

function ResourcePickerOverlay({
  anchorEl,
  tab,
  onTabChange,
  agents,
  workflows,
  selectedAgents,
  selectedWorkflows,
  onToggleAgent,
  onToggleWorkflow,
  onClose,
}: {
  anchorEl: HTMLElement | null;
  tab: PickerTab;
  onTabChange: (t: PickerTab) => void;
  agents: PickerItem[];
  workflows: PickerItem[];
  selectedAgents: Set<string>;
  selectedWorkflows: Set<string>;
  onToggleAgent: (id: string) => void;
  onToggleWorkflow: (id: string) => void;
  onClose: () => void;
}) {
  const [q, setQ] = useState('');
  const [pos, setPos] = useState<{ top: number; right: number }>({ top: 0, right: 0 });

  // 锚定触发按钮下方（380px 浮层向左展开；底部越界时上收）。
  // 触发钮可能贴近视口左缘：right 需 clamp 保证浮层左缘 ≥ 12px。
  useEffect(() => {
    if (!anchorEl) return;
    const r = anchorEl.getBoundingClientRect();
    setPos({
      top: Math.min(r.bottom + 8, window.innerHeight - 396),
      right: Math.max(12, Math.min(window.innerWidth - r.right, window.innerWidth - 392)),
    });
  }, [anchorEl]);

  const groups: { key: PickerTab; label: string; items: PickerItem[]; selected: Set<string>; toggle: (id: string) => void }[] = [
    { key: 'agent', label: '智能体', items: agents, selected: selectedAgents, toggle: onToggleAgent },
    { key: 'workflow', label: '工作流', items: workflows, selected: selectedWorkflows, toggle: onToggleWorkflow },
  ];
  const cur = groups.find((g) => g.key === tab)!;
  const kw = q.trim().toLowerCase();
  const filtered = kw
    ? cur.items.filter((it) => it.name.toLowerCase().includes(kw) || (it.description ?? '').toLowerCase().includes(kw))
    : cur.items;

  return (
    <>
      <div className="fixed inset-0 z-40" onClick={onClose} />
      <div
        className="fixed w-[380px] bg-panel border border-line rounded-2xl shadow-[var(--shadow-pop)] overflow-hidden z-50 animate-fade-in"
        style={{ top: pos.top, right: pos.right }}
      >
        <div className="flex items-center gap-2.5 px-4 py-3 border-b border-line">
          <Search className="w-3.5 h-3.5 text-ink-faint shrink-0" />
          <input
            autoFocus
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder={`搜索${cur.label}…`}
            className="flex-1 bg-transparent border-0 outline-none text-[12.5px] text-ink placeholder:text-ink-faint"
          />
          <button type="button" onClick={onClose} className="text-ink-faint hover:text-ink cursor-pointer shrink-0" title="关闭">
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
        {/* 类别 tab：选中 = 靛蓝下划线；计数随搜索过滤实时变化 */}
        <div className="flex items-center gap-1 px-3 border-b border-line">
          {groups.map((g) => (
            <button
              key={g.key}
              type="button"
              onClick={() => onTabChange(g.key)}
              className={`flex items-center gap-1.5 px-3 py-2 text-[11.5px] -mb-px border-b-2 transition-colors cursor-pointer ${
                tab === g.key ? 'text-brand border-brand font-semibold' : 'text-ink-dim border-transparent hover:text-ink'
              }`}
            >
              {g.label}
              <span className="font-mono text-[9px] text-ink-faint">{g.items.length}</span>
            </button>
          ))}
        </div>
        <div className="max-h-[300px] overflow-y-auto scrollbar-custom p-1.5">
          {filtered.length === 0 ? (
            <div className="px-3 py-6 text-center text-[11.5px] text-ink-faint">
              {kw ? `没有匹配「${q.trim()}」的${cur.label}` : `暂无可选择的${cur.label}`}
            </div>
          ) : (
            filtered.map((it) => {
              const added = cur.selected.has(it.id);
              const Icon = cur.key === 'agent' ? Bot : Workflow;
              return (
                <button
                  key={it.id}
                  type="button"
                  onClick={() => cur.toggle(it.id)}
                  className={`w-full flex items-center gap-2.5 px-2.5 py-2 rounded-[9px] text-left transition-colors cursor-pointer hover:bg-raise ${added ? 'bg-brand-soft/50' : ''}`}
                >
                  <span className="w-6 h-6 rounded-[7px] flex items-center justify-center shrink-0 bg-[#F5E9E2]">
                    <Icon size={12} className="text-cat-kb" />
                  </span>
                  <span className={`min-w-0 flex-1 text-[12.5px] truncate ${added ? 'text-brand font-medium' : 'text-ink'}`}>
                    {it.name}
                  </span>
                  <span className="min-w-0 w-[110px] text-[10.5px] text-ink-faint truncate text-right">{it.description}</span>
                  {added && <Check className="w-3.5 h-3.5 text-brand shrink-0" />}
                </button>
              );
            })
          )}
        </div>
      </div>
    </>
  );
}

/* ── 左栏：创建/编辑表单卡（下划线输入 + chips + 浮层选择） ── */

function KeyFormCard({
  keyItem,
  agents,
  workflows,
  apps,
  onCancelEdit,
  onCreated,
  onUpdated,
}: {
  keyItem?: ApiKey;
  agents: PickerItem[];
  workflows: PickerItem[];
  apps: { id: string; name: string }[];
  onCancelEdit: () => void;
  onCreated: (res: ApiKeyCreated) => void;
  onUpdated: () => void;
}) {
  const isEdit = !!keyItem;

  const [name, setName] = useState(keyItem?.name ?? '');
  const [scopes, setScopes] = useState<Set<string>>(new Set(keyItem?.scopes ?? ['agents:read', 'agents:invoke']));
  const [rateLimit, setRateLimit] = useState(keyItem?.rate_limit ?? 60);
  const [boundAgents, setBoundAgents] = useState<Set<string>>(new Set(keyItem?.bindings.agents ?? []));
  const [boundWorkflows, setBoundWorkflows] = useState<Set<string>>(new Set(keyItem?.bindings.workflows ?? []));
  const [formIntrospectUrl, setFormIntrospectUrl] = useState(keyItem?.introspect_url ?? '');
  const [formAppId, setFormAppId] = useState(keyItem?.app_id ?? '');
  // 有效期仅创建模式提供（编辑沿用既有能力边界：不改有效期）
  const [expiry, setExpiry] = useState<'never' | '90' | '30'>('never');
  const [error, setError] = useState('');

  // 浮层：锚定触发钮 + 当前 tab
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerTab, setPickerTab] = useState<PickerTab>('agent');
  const anchorRef = useRef<HTMLButtonElement | null>(null);
  const openPicker = (t: PickerTab) => {
    setPickerTab(t);
    setPickerOpen(true);
  };

  const qc = useQueryClient();
  const saveMutation = useMutation<ApiKeyCreated | ApiKey, Error, ApiKeyCreateInput | ApiKeyUpdateInput>({
    mutationFn: async (payload) => {
      if (isEdit) return apiKeyApi.update(keyItem!.id, payload as ApiKeyUpdateInput);
      return apiKeyApi.create(payload as ApiKeyCreateInput);
    },
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: apiKeyKeys.lists() });
      if (!isEdit && 'key' in res) {
        onCreated(res as ApiKeyCreated);
        // 表单复位，回到创建态
        setName('');
        setScopes(new Set(['agents:read', 'agents:invoke']));
        setRateLimit(60);
        setBoundAgents(new Set());
        setBoundWorkflows(new Set());
        setFormIntrospectUrl('');
        setFormAppId('');
        setExpiry('never');
      } else {
        onUpdated();
      }
    },
    onError: (e) => setError(getErrorMessage(e, isEdit ? '保存失败，请重试' : '创建失败，请重试')),
  });

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    setError('');
    if (!name.trim()) return setError('请填写 Key 名称');
    if (scopes.size === 0) return setError('至少选择一项权限');
    const expires_at =
      !isEdit && expiry !== 'never'
        ? new Date(Date.now() + Number(expiry) * 86_400_000).toISOString()
        : null;
    saveMutation.mutate({
      name: name.trim(),
      scopes: [...scopes],
      rate_limit: rateLimit,
      bindings: { agents: [...boundAgents], workflows: [...boundWorkflows] },
      introspect_url: formIntrospectUrl.trim() || null,
      app_id: formAppId,
      ...(isEdit ? {} : { expires_at }),
    });
  };

  /** 已选 chips 行：chips（可×，超 3 行内滚）+ ＋选择虚线钮 */
  const chipRow = (
    selected: Set<string>,
    toggle: (id: string) => void,
    items: PickerItem[],
    tab: PickerTab,
    emptyText: string,
  ) => (
    <div className="flex flex-wrap items-center gap-1.5 max-h-[88px] overflow-y-auto scrollbar-custom">
      {items.filter((it) => selected.has(it.id)).map((it) => (
        <span
          key={it.id}
          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-lg text-[11px] bg-brand-soft text-brand font-medium"
        >
          {it.name}
          <button type="button" onClick={() => toggle(it.id)} className="hover:opacity-70 cursor-pointer" title="移除">
            <X className="w-3 h-3" />
          </button>
        </span>
      ))}
      <button
        type="button"
        ref={tab === 'agent' ? anchorRef : undefined}
        onClick={() => openPicker(tab)}
        className="inline-flex items-center gap-1 px-2 py-0.5 rounded-lg text-[11px] border border-dashed border-line-strong text-ink-dim hover:text-brand hover:border-brand transition cursor-pointer"
      >
        <Plus className="w-3 h-3" />
        {selected.size === 0 ? `选择${tab === 'agent' ? '智能体' : '工作流'}` : '添加'}
      </button>
      {selected.size === 0 && <span className="text-[11px] text-ink-faint">{emptyText}</span>}
    </div>
  );

  return (
    <form
      onSubmit={handleSubmit}
      className="bg-panel border border-line rounded-xl shadow-[var(--shadow-card)] p-5 space-y-5"
    >
      {/* 编辑态提示条 */}
      {isEdit && (
        <div className="flex items-center gap-2 pb-3 border-b border-line">
          <Pencil className="w-3.5 h-3.5 text-brand shrink-0" />
          <span className="text-xs text-ink font-semibold truncate">编辑：{keyItem!.name}</span>
          <button
            type="button"
            onClick={onCancelEdit}
            className="ml-auto text-[11px] text-ink-dim hover:text-ink cursor-pointer flex items-center gap-0.5"
          >
            <ArrowLeft className="w-3 h-3" />
            返回创建
          </button>
        </div>
      )}

      <div>
        <Kicker>BASIC · 基础</Kicker>

        <div className="mb-4">
          <FieldLabel label="名称" required hint="标识调用方" />
          <LineInput
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="如 产线 MES 系统、官网访客"
            maxLength={100}
          />
        </div>

        <div className="mb-4">
          <FieldLabel label="权限范围" required hint="至少一项" />
          <div className="flex flex-wrap gap-2">
            {ALL_API_KEY_SCOPES.map((s) => {
              const active = scopes.has(s);
              return (
                <button
                  type="button"
                  key={s}
                  onClick={() => setScopes((prev) => toggleInSet(prev, s))}
                  className={`px-2.5 py-1 rounded-lg text-[11px] font-mono border transition cursor-pointer ${
                    active
                      ? 'bg-brand-soft border-brand text-brand font-semibold'
                      : 'bg-panel border-line text-ink-dim hover:border-line-strong hover:text-ink'
                  }`}
                >
                  {active && <Check className="w-3 h-3 inline mr-1" />}
                  {SCOPE_LABELS[s]}
                </button>
              );
            })}
          </div>
        </div>

        <div className="mb-4">
          <FieldLabel label="限流" hint="每分钟调用上限（默认 60，超限 429）" />
          <LineInput
            type="number"
            min={1}
            max={10000}
            value={rateLimit}
            onChange={(e) => setRateLimit(Math.max(1, Math.min(10000, Number(e.target.value) || 60)))}
            className="font-mono w-24!"
          />
        </div>

        {!isEdit && (
          <div>
            <FieldLabel label="有效期" hint="可选" />
            <div className="inline-flex items-center rounded-lg bg-raise p-0.5">
              {([['never', '永不过期'], ['90', '90 天'], ['30', '30 天']] as const).map(([v, label]) => (
                <button
                  type="button"
                  key={v}
                  onClick={() => setExpiry(v)}
                  className={`px-3 py-1 rounded-md text-[11px] font-semibold transition cursor-pointer ${
                    expiry === v
                      ? 'bg-panel text-ink shadow-[var(--shadow-card)]'
                      : 'text-ink-dim hover:text-ink'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      <div>
        <Kicker>RESOURCE BINDING · 资源绑定</Kicker>

        <div className="mb-4">
          <FieldLabel label="可访问的智能体" hint={`已选 ${boundAgents.size} · 不选 = 访问全部`} />
          {chipRow(boundAgents, (id) => setBoundAgents((prev) => toggleInSet(prev, id)), agents, 'agent', '不选 = 可访问全部智能体')}
        </div>

        <div>
          <FieldLabel label="可访问的工作流" hint={`已选 ${boundWorkflows.size} · 不选 = 访问全部`} />
          {chipRow(boundWorkflows, (id) => setBoundWorkflows((prev) => toggleInSet(prev, id)), workflows, 'workflow', '不选 = 可访问全部工作流')}
        </div>
      </div>

      <div>
        <Kicker>AUTH · 绑定应用与认证回调</Kicker>

        <div className="mb-4">
          <FieldLabel label="绑定应用" hint="接入方系统——终端用户身份的命名空间" />
          <select
            value={formAppId}
            onChange={(e) => setFormAppId(e.target.value)}
            className="w-full border-0 border-b border-line-strong bg-transparent px-0 py-2 text-[13px] text-ink focus:outline-none focus:border-brand transition cursor-pointer"
          >
            <option value="">不绑定</option>
            {apps.map((a) => (
              <option key={a.id} value={a.id}>{a.name}</option>
            ))}
          </select>
        </div>

        <div>
          <FieldLabel label="用户认证回调" hint={formAppId ? undefined : '配置用户身份校验时必填'} />
          <LineInput
            value={formIntrospectUrl}
            onChange={(e) => setFormIntrospectUrl(e.target.value)}
            placeholder="https://partner.example.com/oauth/introspect"
            maxLength={500}
            className="font-mono text-xs"
          />
          <p className="text-[11px] text-ink-faint mt-1.5 leading-relaxed">
            RFC 7662 introspection 端点——外部终端用户请求携带 X-User-Token，平台回调此端点验证身份
          </p>
        </div>
      </div>

      {error && <p className="text-[11px] text-sig-fail">{error}</p>}

      <div className="pt-1 border-t border-line flex items-center gap-3">
        <span className="flex items-center gap-1.5 text-[10.5px] text-ink-faint flex-1 min-w-0">
          <ShieldAlert className="w-3 h-3 shrink-0" />
          <span className="truncate">明文仅创建时展示一次 · 吊销后调用立即 401</span>
        </span>
        <button type="submit" disabled={saveMutation.isPending} className="af-btn af-btn-primary shrink-0">
          <Plus className="w-3.5 h-3.5" />
          {saveMutation.isPending ? (isEdit ? '保存中…' : '创建中…') : isEdit ? '保存修改' : '创建 Key'}
        </button>
      </div>

      {pickerOpen && (
        <ResourcePickerOverlay
          anchorEl={anchorRef.current}
          tab={pickerTab}
          onTabChange={setPickerTab}
          agents={agents}
          workflows={workflows}
          selectedAgents={boundAgents}
          selectedWorkflows={boundWorkflows}
          onToggleAgent={(id) => setBoundAgents((prev) => toggleInSet(prev, id))}
          onToggleWorkflow={(id) => setBoundWorkflows((prev) => toggleInSet(prev, id))}
          onClose={() => setPickerOpen(false)}
        />
      )}
    </form>
  );
}

/* ═══════════════════════ 全局参数（独立设置 Tab） ═══════════════════════ */

/**
 * RuntimeParamsPage — 全局运行参数。
 *
 * 分组分区形态（kicker + set-rows），后续参数按组扩容。
 * 注意：当前条目为 mock（本地 state 无持久化），接后端后替换。
 */
export function RuntimeParamsPage() {
  const [timeout, setTimeoutVal] = useState(30);
  const [detailedAnimation, setDetailedAnimation] = useState(true);
  const [autoClearCache, setAutoClearCache] = useState(false);
  const [strictSchema, setStrictSchema] = useState(true);

  return (
    <div className="space-y-5 max-w-3xl">
      <p className="text-xs text-ink-dim">
        平台全局运行参数（引擎级默认值，作用于所有工作流执行）
      </p>

      {/* 执行 · EXECUTION */}
      <div className="bg-panel border border-line rounded-xl shadow-[var(--shadow-card)] p-5">
        <Kicker hint="LLM 事务与执行链路">EXECUTION · 执行</Kicker>

        <div className="space-y-2">
          <div className="flex justify-between text-xs">
            <span className="text-ink-dim font-medium">最大 LLM 事务超时时长 (Timeout)</span>
            <span className="text-ink font-mono font-bold">{timeout}s</span>
          </div>
          <input
            type="range"
            min="5"
            max="120"
            step="5"
            value={timeout}
            onChange={(e) => setTimeoutVal(parseInt(e.target.value))}
            className="w-full focus:outline-none accent-brand"
          />
        </div>

        <div className="mt-4 pt-4 border-t border-line flex items-start justify-between gap-4 text-xs">
          <div className="space-y-0.5">
            <span className="font-semibold text-ink-soft">严格模型执行 Schema 校验</span>
            <p className="text-[11px] text-ink-dim leading-normal">
              对每一个 Agent worker 输出的 JSON payload 实施强制格式和数据类型校正，出错则自动重试打回。
            </p>
          </div>
          <Toggle state={strictSchema} onChange={setStrictSchema} />
        </div>
      </div>

      {/* 渲染 · RENDERING */}
      <div className="bg-panel border border-line rounded-xl shadow-[var(--shadow-card)] p-5">
        <Kicker hint="画布与运行时视觉">RENDERING · 渲染</Kicker>

        <div className="flex items-start justify-between gap-4 text-xs">
          <div className="space-y-0.5">
            <span className="font-semibold text-ink-soft">启用图 Dashing 流转连线动效</span>
            <p className="text-[11px] text-ink-dim leading-normal">
              在测试运行工作流时，实时渲染连线的高精度流动虚线轨迹。建议始终开启。
            </p>
          </div>
          <Toggle state={detailedAnimation} onChange={setDetailedAnimation} />
        </div>
      </div>

      {/* 资源 · RESOURCE */}
      <div className="bg-panel border border-line rounded-xl shadow-[var(--shadow-card)] p-5">
        <Kicker hint="内存与缓存治理">RESOURCE · 资源</Kicker>

        <div className="flex items-start justify-between gap-4 text-xs">
          <div className="space-y-0.5">
            <span className="font-semibold text-ink-soft">会话闭环后自清理内存临时变量</span>
            <p className="text-[11px] text-ink-dim leading-normal">
              为了安全性。一旦整个流程图完美流至 END 节点，一键释放在内存中的任务草纲与文件缓存。
            </p>
          </div>
          <Toggle state={autoClearCache} onChange={setAutoClearCache} />
        </div>
      </div>
    </div>
  );
}

/** 开关（实色靛蓝 on 态） */
function Toggle({ state, onChange }: { state: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      onClick={() => onChange(!state)}
      className="shrink-0 w-11 h-6 rounded-full transition relative flex items-center p-0.5 cursor-pointer"
      style={{ backgroundColor: state ? 'var(--color-brand)' : 'var(--color-raise)' }}
    >
      <span
        className="w-5 h-5 rounded-full bg-white shadow-md block transition-transform duration-200"
        style={{ transform: state ? 'translateX(20px)' : 'translateX(0)' }}
      />
    </button>
  );
}

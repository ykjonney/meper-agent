/**
 * ExternalAccessPage — 外部接入（设置 Tab，原「通用」）。
 *
 * API Key 管理：供 /ext 嵌入式对话与第三方系统调用 OpenAPI。
 * 设计稿：docs/design-mockups/admin-pages.html pane-apikey（列表态）+
 * apikey-pages.html（创建/编辑 = 页内全屏双栏，弹窗形态已废弃 §3.1）。
 *
 * 列表态：stats 条 + cfg-row 配置行（KEY 实体块 + 状态 pill + mono 描述）。
 * 创建/编辑：页内切换到 KeyFormPage（下划线输入 + res-chips，非弹窗）。
 */
import { useEffect, useState, FormEvent, type InputHTMLAttributes } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  ShieldAlert, Plus, Sliders, CheckCircle, Check, Copy,
  AlertTriangle, RefreshCw, ChevronDown, ChevronRight, Pencil,
  ArrowLeft,
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

/* ═══════════════════════ 列表态 ═══════════════════════ */

export function ExternalAccessPage() {
  const qc = useQueryClient();

  const { data, isLoading, isFetching } = useQuery({
    queryKey: apiKeyKeys.lists(),
    queryFn: () => apiKeyApi.list(),
  });
  const apiKeys = data?.items ?? [];
  const activeCount = apiKeys.filter((k) => k.status === 'active').length;

  const [mode, setMode] = useState<'list' | 'create'>('list');
  const [editingKey, setEditingKey] = useState<ApiKey | null>(null);
  const [createdKey, setCreatedKey] = useState<ApiKeyCreated | null>(null);
  const [copiedValue, setCopiedValue] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  // 选项列表——详情面板里的 id → 名称解析
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

  // ── 创建/编辑全屏视图 ──
  if (mode === 'create' || editingKey) {
    return (
      <KeyFormPage
        keyItem={editingKey ?? undefined}
        onBack={() => {
          setMode('list');
          setEditingKey(null);
        }}
        onCreated={(res) => {
          setCreatedKey(res);
          setMode('list');
        }}
      />
    );
  }

  // ── 详情行渲染（plain function，同旧实现） ──
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
    <div className="space-y-4 max-w-3xl">
      {/* One-time raw key reveal + full detail */}
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
            <button
              onClick={() => copy(createdKey.key)}
              className="shrink-0 af-btn af-btn-primary"
            >
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

      {/* 说明 + 创建入口（设计稿 page-head 形态：说明行 + 主 CTA） */}
      <div className="flex items-center gap-3">
        <p className="text-xs text-ink-dim font-sans flex-1">
          管理对外接入用的 API Key（供 /ext 嵌入式对话、第三方系统调用 OpenAPI）
        </p>
        <button onClick={() => setMode('create')} className="af-btn af-btn-primary shrink-0">
          <Plus className="w-3.5 h-3.5" />
          创建 API Key
        </button>
      </div>

      {/* stats 条（设计稿 pane-apikey：真实数据 + 接入端点） */}
      <div className="flex bg-panel border border-line rounded-xl divide-x divide-line shadow-[var(--shadow-card)]">
        <div className="flex-1 px-4 py-3">
          <div className="text-[22px] font-bold text-ink leading-tight">{activeCount}</div>
          <div className="text-[11px] text-ink-dim mt-0.5">活跃 Key · 共 {apiKeys.length} 个</div>
        </div>
        <div className="flex-[1.4] px-4 py-3 flex flex-col justify-center">
          <div className="font-mono text-[13px] text-ink font-semibold">POST /api/v1/ext/*</div>
          <div className="text-[11px] text-ink-dim mt-0.5">接入端点 · 携带 Authorization: Bearer + X-User-Token</div>
        </div>
      </div>

      {/* Key 列表 — cfg-row 配置行（无边框行 + hairline 分隔） */}
      <div className="bg-panel border border-line rounded-xl shadow-[var(--shadow-card)]">
        {isLoading && (
          <p className="text-xs text-ink-faint font-sans text-center py-8">加载中…</p>
        )}
        {!isLoading && apiKeys.length === 0 && (
          <p className="text-xs text-ink-faint font-sans text-center py-8">暂无对外 Key，点击右上角「创建 API Key」。</p>
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
                <span className="hidden sm:block text-[11px] text-ink-faint font-mono shrink-0">
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
      <p className="text-[10.5px] text-ink-faint font-mono">
        Key 创建后仅展示一次完整值（复制保存），此后只显示掩码 · 权限范围与资源绑定在详情中查看
      </p>

      {/* 全局运行参数（mock，未接后端——保留原功能位） */}
      <RuntimeParamsCard />
    </div>
  );
}

/* ── 全局运行参数卡（mock：本地 state，无持久化——维持既有占位功能） ── */

function RuntimeParamsCard() {
  const [timeout, setTimeoutVal] = useState(30);
  const [detailedAnimation, setDetailedAnimation] = useState(true);
  const [autoClearCache, setAutoClearCache] = useState(false);
  const [strictSchema, setStrictSchema] = useState(true);

  return (
    <div className="bg-panel border border-line rounded-xl p-5 shadow-[var(--shadow-card)] max-w-3xl mt-8">
      <div className="space-y-1 border-b border-line pb-3 mb-4">
        <h3 className="text-sm font-bold text-ink flex items-center gap-1.5">
          <Sliders className="w-4 h-4 text-brand" />
          虚拟机全局控制参数
        </h3>
        <p className="text-xs text-ink-dim">微调 Dify 以及 LangGraph 工作流运行时系统机制。</p>
      </div>

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

      <div className="space-y-4 pt-4">
        {[
          {
            id: 'detailedAnimation',
            title: '启用图 Dashing 流转连线动效',
            desc: '在测试运行工作流时，实时渲染连线的高精度流动虚线轨迹。建议始终开启。',
            state: detailedAnimation,
            setter: setDetailedAnimation,
          },
          {
            id: 'strictSchema',
            title: '严格模型执行 Schema 校验',
            desc: '对每一个 Agent worker 输出的 JSON payload 实施强制格式和数据类型校正，出错则自动重试打回。',
            state: strictSchema,
            setter: setStrictSchema,
          },
          {
            id: 'autoClearCache',
            title: '会话闭环后自清理内存临时变量',
            desc: '为了安全性。一旦整个流程图完美流至 END 节点，一键释放在内存中的任务草纲与文件缓存。',
            state: autoClearCache,
            setter: setAutoClearCache,
          },
        ].map((flag) => (
          <div key={flag.id} className="flex items-start justify-between gap-4 text-xs">
            <div className="space-y-0.5">
              <span className="font-semibold text-ink-soft">{flag.title}</span>
              <p className="text-[11px] text-ink-dim leading-normal">{flag.desc}</p>
            </div>
            <button
              onClick={() => flag.setter(!flag.state)}
              className="shrink-0 w-11 h-6 rounded-full transition relative flex items-center p-0.5 cursor-pointer"
              style={{ backgroundColor: flag.state ? 'var(--color-brand)' : 'var(--color-raise)' }}
            >
              <span
                className="w-5 h-5 rounded-full bg-white shadow-md block transition-transform duration-200"
                style={{ transform: flag.state ? 'translateX(20px)' : 'translateX(0)' }}
              />
            </button>
          </div>
        ))}
      </div>

      <div className="p-3 bg-raise rounded-lg space-y-1 mt-5">
        <span className="font-semibold flex items-center gap-1.5 text-xs text-ink-soft">
          <ShieldAlert className="w-3.5 h-3.5 text-brand" />
          API 安全提醒
        </span>
        <p className="text-[11px] leading-relaxed text-ink-dim">
          对外 Key 的明文仅在创建时展示一次。请妥善保管；如发现泄露，立即「撤销」并重新生成。
        </p>
      </div>
    </div>
  );
}

/* ═══════════════════ 创建/编辑：页内全屏双栏（弹窗形态已废弃 §3.1） ═══════════════════ */

function KeyFormPage({
  keyItem,
  onBack,
  onCreated,
}: {
  keyItem?: ApiKey;
  onBack: () => void;
  onCreated: (res: ApiKeyCreated) => void;
}) {
  const qc = useQueryClient();
  const isEdit = !!keyItem;

  const [name, setName] = useState(keyItem?.name ?? '');
  const [scopes, setScopes] = useState<Set<string>>(new Set(keyItem?.scopes ?? ['agents:read', 'agents:invoke']));
  const [rateLimit, setRateLimit] = useState(keyItem?.rate_limit ?? 60);
  const [boundAgents, setBoundAgents] = useState<Set<string>>(new Set(keyItem?.bindings.agents ?? []));
  const [boundWorkflows, setBoundWorkflows] = useState<Set<string>>(new Set(keyItem?.bindings.workflows ?? []));
  const [formIntrospectUrl, setFormIntrospectUrl] = useState(keyItem?.introspect_url ?? '');
  const [formAppId, setFormAppId] = useState(keyItem?.app_id ?? '');
  // 有效期 seg 仅创建模式提供（编辑沿用既有能力边界：不改有效期）
  const [expiry, setExpiry] = useState<'never' | '90' | '30'>('never');
  const [error, setError] = useState('');

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onBack();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onBack]);

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

  const saveMutation = useMutation<ApiKeyCreated | ApiKey, Error, ApiKeyCreateInput | ApiKeyUpdateInput>({
    mutationFn: async (payload) => {
      if (isEdit) return apiKeyApi.update(keyItem!.id, payload as ApiKeyUpdateInput);
      return apiKeyApi.create(payload as ApiKeyCreateInput);
    },
    onSuccess: (res) => {
      qc.invalidateQueries({ queryKey: apiKeyKeys.lists() });
      if (!isEdit && 'key' in res) onCreated(res as ApiKeyCreated);
      else onBack();
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

  return (
    <form onSubmit={handleSubmit} className="max-w-5xl">
      {/* 头部：返回 + 面包屑 + 操作 */}
      <div className="flex items-center gap-3 pb-4 border-b border-line">
        <button
          type="button"
          onClick={onBack}
          className="p-1.5 rounded-lg text-ink-dim hover:text-ink hover:bg-raise transition cursor-pointer"
          aria-label="返回"
        >
          <ArrowLeft className="w-4 h-4" />
        </button>
        <div className="text-xs text-ink-dim">
          外部接入 / <span className="text-ink font-semibold">{isEdit ? `编辑 ${keyItem!.name}` : '创建新 Key'}</span>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <button type="button" onClick={onBack} className="af-btn af-btn-ghost">
            取消
          </button>
          <button type="submit" disabled={saveMutation.isPending} className="af-btn af-btn-primary">
            {isEdit ? '保存修改' : '创建 Key'}
          </button>
        </div>
      </div>

      {/* 双栏主体 */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-x-10 gap-y-8 pt-5">
        {/* 左：基础与权限 */}
        <div>
          <Kicker>BASIC · 基础</Kicker>

          <div className="mb-5">
            <FieldLabel label="名称" required hint="标识调用方" />
            <LineInput
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="如 产线 MES 系统、官网访客"
              maxLength={100}
            />
          </div>

          <div className="mb-5">
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

          <div className="mb-5">
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
            <div className="mb-5">
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

          <div className="flex items-start gap-1.5 text-[11px] text-sig-wait">
            <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-px" />
            创建后仅展示一次完整 Key——请立即复制保存，此后只显示掩码
          </div>
        </div>

        {/* 右：资源绑定 + 认证 */}
        <div>
          <Kicker>RESOURCE BINDING · 资源绑定</Kicker>

          <div className="mb-5">
            <FieldLabel label={`可访问的智能体（${boundAgents.size}）`} hint="不选 = 访问全部" />
            <div className="max-h-32 overflow-y-auto flex flex-wrap gap-1.5">
              {(agentsData?.items ?? []).map((a) => {
                const active = boundAgents.has(a.id);
                return (
                  <button
                    type="button"
                    key={a.id}
                    onClick={() => setBoundAgents((prev) => toggleInSet(prev, a.id))}
                    className={`px-2 py-0.5 rounded text-[11px] border transition cursor-pointer ${
                      active
                        ? 'bg-brand-soft border-brand text-brand font-semibold'
                        : 'bg-panel border-line text-ink-dim hover:border-line-strong hover:text-ink'
                    }`}
                  >
                    {a.name}
                  </button>
                );
              })}
              {(agentsData?.items ?? []).length === 0 && (
                <span className="text-[11px] text-ink-faint">暂无智能体</span>
              )}
            </div>
          </div>

          <div className="mb-5">
            <FieldLabel label={`可访问的工作流（${boundWorkflows.size}）`} hint="不选 = 访问全部" />
            <div className="max-h-32 overflow-y-auto flex flex-wrap gap-1.5">
              {(workflowsData?.items ?? []).map((w) => {
                const active = boundWorkflows.has(w.id);
                return (
                  <button
                    type="button"
                    key={w.id}
                    onClick={() => setBoundWorkflows((prev) => toggleInSet(prev, w.id))}
                    className={`px-2 py-0.5 rounded text-[11px] border transition cursor-pointer ${
                      active
                        ? 'bg-brand-soft border-brand text-brand font-semibold'
                        : 'bg-panel border-line text-ink-dim hover:border-line-strong hover:text-ink'
                    }`}
                  >
                    {w.name}
                  </button>
                );
              })}
              {(workflowsData?.items ?? []).length === 0 && (
                <span className="text-[11px] text-ink-faint">暂无工作流</span>
              )}
            </div>
          </div>

          <Kicker>AUTH · 绑定应用与认证回调</Kicker>

          <div className="mb-5">
            <FieldLabel label="绑定应用" hint="接入方系统——终端用户身份的命名空间" />
            <select
              value={formAppId}
              onChange={(e) => setFormAppId(e.target.value)}
              className="w-full border-0 border-b border-line-strong bg-transparent px-0 py-2 text-[13px] text-ink focus:outline-none focus:border-brand transition cursor-pointer"
            >
              <option value="">不绑定</option>
              {(appsData?.items ?? []).map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
          </div>

          <div className="mb-5">
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

          <div className="bg-raise rounded-[10px] p-3 text-[11px] text-ink-dim leading-relaxed flex items-start gap-1.5">
            <ShieldAlert className="w-3.5 h-3.5 shrink-0 mt-0.5 text-ink-dim" />
            <span>
              Key 值 bcrypt 哈希存储（平台不保存明文）· 创建后仅展示一次完整 Key · 吊销后调用立即 401
            </span>
          </div>
        </div>
      </div>

      {error && (
        <p className="text-[11px] text-sig-fail mt-4">{error}</p>
      )}
    </form>
  );
}

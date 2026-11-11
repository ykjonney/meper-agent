/**
 * ModelsPage — standalone LLM model configuration surface.
 *
 * Full CRUD + connectivity test + api_key masking + search/stats. All field
 * handling mirrors the legacy umi models-page but renders with native Tailwind
 * (no antd). Backed by services/model-api.ts (already complete); backend has
 * zero changes for this feature.
 *
 * Permission gating: read needs `model:read`, write/test needs `model:write`
 * (the nav entry hides this page entirely for users lacking model:read).
 */
import { useMemo, useState, type FormEvent, type ReactNode } from 'react';
import { ModelBrandIcon } from './ModelBrandIcon';
import {
  Plus, Search, Server, Zap, Loader2, X, AlertTriangle, CheckCircle2, ChevronRight,
} from 'lucide-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  modelApi,
  modelKeys,
  type Model,
  type ModelCreateInput,
  type CompatibilityType,
  type AuthType,
  type ModelStatus,
  type ModelTestResult,
} from '../services/model-api';
import { Select } from './ui';
import { confirmDialog } from './ui/confirm';
import { usePermission } from '../hooks/use-permission';
import { getErrorMessage } from '../lib/api-client';
import { ResModal, Field, UInput, Seg, VendorCell } from './res-modal';

const COMPATIBILITY_LABELS: Record<CompatibilityType, string> = {
  openai: 'OpenAI',
  anthropic: 'Anthropic',
};

const AUTH_LABELS: Record<AuthType, string> = {
  bearer: 'Bearer Token',
  x_api_key: 'X-API-Key',
  api_key_header: 'API-Key Header',
  custom: '自定义',
};

// Error-code → troubleshooting hint, mirrors the legacy troubleshooting map.
const ERROR_HINTS: Record<string, string> = {
  AUTH_FAILED: '检查 API Key 是否正确、是否已过期或被吊销。',
  MODEL_NOT_FOUND_UPSTREAM: 'model_id 在上游不存在；确认模型名拼写与所属 provider。',
  CONNECTION_ERROR: '无法连接 base_url；检查网络、代理或服务地址是否可达。',
  TIMEOUT: '请求超时；可重试，或确认上游服务响应正常。',
  RATE_LIMITED: '触发上游限流；稍后重试或提升配额。',
  QUOTA_EXCEEDED: 'API 额度已用尽；检查账户余额。',
  SSL_ERROR: 'SSL/TLS 握手失败；确认 base_url 协议与证书有效。',
};

const COMPATIBILITY_OPTIONS: CompatibilityType[] = ['openai', 'anthropic'];
const AUTH_TYPES: AuthType[] = ['bearer', 'x_api_key', 'api_key_header', 'custom'];

/** 厂商网格（设计稿 vendors）：选厂商自动带出官方端点 + 兼容协议 + 常见模型预设。
 * endpoint=官方兼容端点（用户可改为自建网关）；models=模型 ID 快捷 chips。 */
const VENDORS: { key: string; bg: string; fg?: string; compat: CompatibilityType; endpoint: string; models: string[] }[] = [
  { key: '智谱 AI', bg: '#2E5BFF', compat: 'openai', endpoint: 'https://open.bigmodel.cn/api/paas/v4', models: ['glm-5.3-flash', 'glm-5.2', 'glm-4.7'] },
  { key: '阿里云通义', bg: '#FF6A00', compat: 'openai', endpoint: 'https://dashscope.aliyuncs.com/compatible-mode/v1', models: ['qwen3.7-plus', 'qwen-max', 'qwen-plus'] },
  { key: 'DeepSeek', bg: '#4D6BFE', compat: 'openai', endpoint: 'https://api.deepseek.com/v1', models: ['deepseek-chat', 'deepseek-reasoner'] },
  { key: 'OpenAI', bg: '#0D0D0D', compat: 'openai', endpoint: 'https://api.openai.com/v1', models: ['gpt-4o', 'gpt-4o-mini', 'o3-mini'] },
  { key: 'Anthropic', bg: '#D97757', compat: 'anthropic', endpoint: 'https://api.anthropic.com', models: ['claude-opus-4', 'claude-sonnet-4'] },
  { key: 'Google', bg: '#FFFFFF', fg: '#5A6472', compat: 'openai', endpoint: 'https://generativelanguage.googleapis.com/v1beta/openai', models: ['gemini-2.5-pro', 'gemini-2.5-flash'] },
  { key: 'Moonshot AI', bg: '#0B0B1E', compat: 'openai', endpoint: 'https://api.moonshot.cn/v1', models: ['kimi-k2', 'moonshot-v1-128k'] },
  { key: '自定义', bg: '#EDF0F5', fg: '#666E7D', compat: 'openai', endpoint: '', models: [] },
];

/** 编辑回显：provider_tag 可能存的是小写/旧值（anthropic / deepseek…）——宽匹配厂商格 */
function matchVendorKey(tag?: string): string {
  const t = (tag ?? '').toLowerCase();
  if (!t) return '';
  const hit = VENDORS.find((v) => v.key !== '自定义' && (
    v.key.toLowerCase() === t || v.key.toLowerCase().includes(t) || t.includes(v.key.toLowerCase().split(' ')[0])
  ));
  return hit?.key ?? (t ? '自定义' : '');
}

/** 厂商徽章（设计稿 badge-44）：ModelBrandIcon avatar 变体（品牌色方底+白 logo）
 *  替代旧手绘 SVG；embedding 类模型回退青色首字母徽章。 */
function vendorBadge(m: Model): ReactNode {
  if (/embed|bge|text-embedding/i.test(`${m.name} ${m.model_id}`)) {
    return (
      <div className="w-[38px] h-[38px] rounded-[10px] flex items-center justify-center shrink-0 text-white font-bold text-[15px] select-none" style={{ background: '#14B8A6' }}>
        E
      </div>
    );
  }
  return <ModelBrandIcon name={m.name} modelId={m.model_id} providerTag={m.provider_tag} variant="avatar" size={26} />;
}

/** Format an ISO timestamp as a short Chinese relative string ('刚刚' / '3 分钟前'). '' if missing/invalid. */
function formatRelativeTime(iso?: string): string {
  if (!iso) return '';
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return '';
  const sec = Math.floor((Date.now() - then) / 1000);
  if (sec < 60) return '刚刚';
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min} 分钟前`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} 小时前`;
  const day = Math.floor(hr / 24);
  if (day < 30) return `${day} 天前`;
  return new Date(iso).toLocaleDateString('zh-CN');
}

/** Build the editor form state. Editing leaves api_key empty ("leave blank to keep"). */
type ModelForm = Omit<ModelCreateInput, 'api_key'> & { api_key: string };

function emptyForm(): ModelForm {
  return {
    model_id: '',
    name: '',
    base_url: '',
    api_key: '',
    compatibility_type: 'openai',
    auth_type: 'bearer',
    auth_header_format: '',
    default_params: { temperature: 0.7, max_tokens: 4096, context_window: 128000 },
    provider_tag: '',
  };
}

function modelToForm(m: Model): ModelForm {
  return {
    model_id: m.model_id,
    name: m.name,
    base_url: m.base_url,
    api_key: '', // never prefill the masked secret
    compatibility_type: m.compatibility_type,
    auth_type: m.auth_type,
    auth_header_format: m.auth_header_format ?? '',
    default_params: m.default_params ?? { temperature: 0.7, max_tokens: 4096, context_window: 128000 },
    provider_tag: m.provider_tag ?? '',
  };
}

export function ModelsPage() {
  const queryClient = useQueryClient();
  // 写权限门控：新建/编辑/删除为 model:write；"测试连通性"后端为
  // model:read（探针不改配置），与路由同键，无权限时隐藏入口。
  const canWrite = usePermission('model:write');
  const canTest = usePermission('model:read');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<ModelStatus | 'all'>('all');
  const [editing, setEditing] = useState<Model | null>(null);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState<ModelForm>(emptyForm());
  const [error, setError] = useState<string | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);
  // 高级参数折叠（认证方式 / 兼容协议 / 采样与上下文参数）——主流形态：默认只露基础字段
  const [advOpen, setAdvOpen] = useState(false);

  const { data, isLoading } = useQuery({
    queryKey: modelKeys.list({ page_size: 100, ...(statusFilter !== 'all' ? { status: statusFilter } : {}) }),
    queryFn: () =>
      modelApi.list({ page_size: 100, ...(statusFilter !== 'all' ? { status: statusFilter } : {}) }),
  });
  const models = data?.items ?? [];

  // Client-side search over name / model_id / provider_tag (status is backend-filtered).
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return models;
    return models.filter((m) =>
      [m.name, m.model_id, m.provider_tag ?? ''].some((v) => v.toLowerCase().includes(q)),
    );
  }, [models, search]);

  const createM = useMutation({
    mutationFn: (input: ModelCreateInput) => modelApi.create(input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: modelKeys.all });
      setError(null);
      setCreating(false);
    },
    onError: (e: unknown) => setError(getErrorMessage(e, '创建模型失败')),
  });

  const updateM = useMutation({
    mutationFn: ({ id, input }: { id: string; input: ModelCreateInput }) => modelApi.update(id, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: modelKeys.all });
      setError(null);
      setEditing(null);
    },
    onError: (e: unknown) => setError(getErrorMessage(e, '保存模型失败')),
  });

  const deleteM = useMutation({
    mutationFn: (id: string) => modelApi.remove(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: modelKeys.all }),
    onError: (e: unknown) => setError(getErrorMessage(e, '删除失败')),
  });

  const testM = useMutation({
    mutationFn: (id: string) => modelApi.test(id),
    // Backend persists the test outcome; refresh the list so the connectivity badge updates.
    onSuccess: () => queryClient.invalidateQueries({ queryKey: modelKeys.all }),
  });

  const handleOpenCreate = () => {
    setError(null);
    setForm(emptyForm());
    setCreating(true);
  };

  const handleOpenEdit = (m: Model) => {
    setError(null);
    setForm(modelToForm(m));
    setEditing(m);
  };

  const handleOpenTest = (m: Model) => {
    setError(null);
    setTestingId(m.id);
    testM.reset();
    testM.mutate(m.id);
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    // Build payload; for edit, an empty api_key means "keep existing" → omit it.
    const isEdit = editing !== null;
    const payload: ModelCreateInput = {
      model_id: form.model_id.trim(),
      name: form.name.trim(),
      base_url: form.base_url.trim(),
      // 编辑留空 = 保持原密钥：彻底省略字段，避免后端把空串当新值覆盖
      ...(form.api_key ? { api_key: form.api_key } : {}),
      compatibility_type: form.compatibility_type,
      auth_type: form.auth_type,
      ...(form.auth_type === 'custom' ? { auth_header_format: form.auth_header_format } : {}),
      default_params: form.default_params,
      provider_tag: form.provider_tag?.trim() || undefined,
    };
    if (isEdit && editing) {
      updateM.mutate({ id: editing.id, input: payload });
    } else {
      createM.mutate(payload);
    }
  };

  const handleDelete = async (m: Model) => {
    const ok = await confirmDialog({
      title: `删除模型「${m.name}」？`,
      description: '删除后引用该模型的 Agent 将无法执行。',
      okText: '删除',
      danger: true,
    });
    if (!ok) return;
    setError(null);
    deleteM.mutate(m.id);
  };

  const testResult: ModelTestResult | undefined = testM.data;

  return (
    <div className="space-y-4">
      {/* ── 工具栏：搜索 + 状态筛选 + 接入模型 CTA（设计稿 toolbar） ── */}
      <div className="flex items-center gap-3">
        <div className="relative w-[320px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-ink-faint" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索模型名称 / 厂商…"
            className="w-full pl-9 pr-3 h-8 text-xs bg-panel border border-line rounded-[10px] text-ink placeholder:text-ink-faint focus:outline-none focus:border-brand transition font-medium"
          />
        </div>
        <Select
          value={statusFilter}
          onChange={(v) => setStatusFilter((v ?? 'all') as ModelStatus | 'all')}
          placeholder="全部状态"
          className="w-32"
          options={[
            { value: 'all', label: '全部状态' },
            { value: 'active', label: '已启用' },
            { value: 'inactive', label: '已停用' },
          ]}
        />
        {canWrite && (
          <button
            onClick={handleOpenCreate}
            className="af-btn af-btn-primary shrink-0 ml-auto"
          >
            ＋ 接入模型
          </button>
        )}
      </div>

      {error && (
        <div className="flex items-start gap-2 p-3 rounded-lg bg-sig-fail-soft border border-line text-sig-fail text-xs">
          <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
          <span className="font-sans">{error}</span>
        </div>
      )}

      {/* ── 模型签名卡网格（设计稿 pane-models：厂商徽章 + 协议 via + 连通 pill +
          上下文窗口 track + foot 操作） ── */}
      {isLoading ? (
        <div className="flex items-center justify-center py-16 text-ink-dim">
          <Loader2 className="w-5 h-5 animate-spin mr-2" /> 加载中…
        </div>
      ) : filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-16 text-ink-faint">
          <Server className="w-8 h-8 mb-2 opacity-40" />
          <p className="text-sm">暂无模型配置{search ? '匹配搜索' : ''}，点击右上角接入</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 content-start pb-4">
          {filtered.map((m) => {
            const isEmbed = /embed/i.test(`${m.name} ${m.model_id} ${m.provider_tag ?? ''}`);
            // pill 优先级：已停用 > 连通性测试结果
            const pill = m.status !== 'active'
              ? { label: '已停用', tone: 'neutral' as const }
              : m.last_test_success === true
                ? { label: '已连通', tone: 'ok' as const }
                : m.last_test_success === false
                  ? { label: '连接失败', tone: 'fail' as const }
                  : { label: '未验证', tone: 'neutral' as const };
            const ctx = m.default_params?.context_window ?? 0;
            const ctxPct = ctx > 0 ? Math.min(100, Math.round((ctx / 1_000_000) * 100)) : 0;
            return (
              <div
                key={m.id}
                className="bg-panel border border-line rounded-xl p-4 flex flex-col transition hover:shadow-[var(--shadow-card)] hover:border-line-strong"
              >
                {/* 头部：厂商徽章 + 名称 + 厂商/协议行 + 连通 pill */}
                <div className="flex items-start gap-[11px]">
                  <div title={`${m.provider_tag || COMPATIBILITY_LABELS[m.compatibility_type]}`} className="shrink-0">
                    {vendorBadge(m)}
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="text-[13px] font-semibold text-ink truncate" title={m.name}>{m.name}</div>
                    <div className="text-[10.5px] text-ink-dim mt-0.5 truncate flex items-center gap-1.5">
                      {m.provider_tag || COMPATIBILITY_LABELS[m.compatibility_type]}
                      <span className="px-1.5 py-px rounded bg-raise text-[10px] text-ink-dim shrink-0">
                        {COMPATIBILITY_LABELS[m.compatibility_type]} 兼容
                      </span>
                    </div>
                  </div>
                  <span className={`af-pill af-pill-${pill.tone} shrink-0`}>{pill.label}</span>
                </div>

                {/* 能力行：LLM/EMBEDDING 类型 tag */}
                <div className="flex items-center gap-1.5 mt-2.5">
                  <span
                    className={`inline-flex text-[10px] font-bold px-2 py-0.5 rounded-md tracking-[.05em] font-mono ${
                      isEmbed ? 'bg-[rgba(20,184,166,.12)] text-[#0D9488]' : 'bg-brand-soft text-brand'
                    }`}
                  >
                    {isEmbed ? 'EMBEDDING' : 'LLM'}
                  </span>
                </div>

                {/* 上下文窗口 track（mono 数字右对齐） */}
                <div className="mt-3">
                  <div className="h-1 rounded-full bg-raise overflow-hidden">
                    <div className="h-full rounded-full bg-brand" style={{ width: `${ctxPct}%` }} />
                  </div>
                  <div className="flex justify-between font-mono text-[10px] text-ink-faint mt-1.5">
                    <span>上下文窗口</span>
                    <span>{ctx > 0 ? ctx.toLocaleString() : '—'}</span>
                  </div>
                </div>

                {/* foot：接入日期 + 操作（设计稿 c-actions 文字链接） */}
                <div className="flex items-center justify-between border-t border-line mt-3 pt-2.5">
                  <span className="text-[10.5px] text-ink-faint font-mono">
                    {m.created_at ? new Date(m.created_at).toLocaleDateString('zh-CN') : ''}
                  </span>
                  <div className="flex items-center gap-2.5 text-[11px]">
                    {canTest && (
                      <button
                        onClick={() => handleOpenTest(m)}
                        className="text-ink-dim hover:text-ink cursor-pointer"
                      >测试连接</button>
                    )}
                    {canWrite && (
                      <button
                        onClick={() => handleOpenEdit(m)}
                        className="text-brand hover:text-brand-hover cursor-pointer"
                      >编辑</button>
                    )}
                    {canWrite && (
                      <button
                        onClick={() => handleDelete(m)}
                        className="text-sig-fail hover:opacity-75 cursor-pointer"
                      >删除</button>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* ── Create / Edit Modal：设计稿 res-create-edit 形态（厂商网格 + 下划线字段 + 分段） ── */}
      {(creating || editing) && (
        <ResModal
          badge={<svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5"><rect x="4" y="6" width="12" height="8" rx="2" /><circle cx="8" cy="10" r="1" fill="currentColor" stroke="none" /><circle cx="12" cy="10" r="1" fill="currentColor" stroke="none" /><path d="M8 16v2M12 16v2M8 2v2M12 2v2" strokeLinecap="round" /></svg>}
          badgeCls="bg-[#E9EDF7] text-cat-tool"
          title={editing ? '编辑模型' : '接入模型'}
          kicker={editing ? 'MODEL · EDIT' : 'MODEL · CONNECT'}
          onClose={() => { setCreating(false); setEditing(null); setError(null); }}
          formId="model-form"
          footer={{
                       actions: (
              <>
                <button type="button" onClick={() => { setCreating(false); setEditing(null); setError(null); }} className="af-btn af-btn-ghost">取消</button>
                {canWrite && (
                  <button type="submit" form="model-form" disabled={createM.isPending || updateM.isPending}
                    className="af-btn af-btn-primary disabled:opacity-60 flex items-center gap-2">
                    {(createM.isPending || updateM.isPending) && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                    {editing ? '保存' : '创建'}
                  </button>
                )}
              </>
            ),
          }}
        >
          <form id="model-form" onSubmit={handleSubmit}>
            {/* 厂商网格：选厂商 → 官方端点/协议/模型预设自动带出（主流模式） */}
            <Field label="厂商" required hint="选厂商自动带出官方端点与兼容协议；端点可改为自建网关">
              <div className="grid grid-cols-8 gap-2">
                {VENDORS.map((v) => (
                  <VendorCell
                    key={v.key}
                    on={matchVendorKey(form.provider_tag) === v.key}
                    bg="#fff"
                    fg="#666E7D"
                    label={v.key === '自定义'
                      ? <span className="text-[13px]">?</span>
                      : <ModelBrandIcon name={v.key} variant="avatar" size={22} />}
                    title={v.key}
                    onClick={() => {
                      const isEmptyBase = !form.base_url || VENDORS.some((o) => o.endpoint && o.endpoint === form.base_url);
                      setForm({
                        ...form,
                        provider_tag: v.key,
                        compatibility_type: v.compat,
                        ...(v.endpoint ? { base_url: v.endpoint } : {}),
                        ...(v.models.length ? { model_id: form.model_id && v.models.includes(form.model_id) ? form.model_id : v.models[0] } : {}),
                      });
                    }}
                  />
                ))}
              </div>
            </Field>
            {(() => {
              const cur = VENDORS.find((v) => matchVendorKey(form.provider_tag) === v.key);
              if (!cur || cur.models.length === 0) return null;
              return (
                <div className="flex flex-wrap items-center gap-1.5 -mt-2 mb-[18px]">
                  {cur.models.map((m) => (
                    <button
                      key={m}
                      type="button"
                      onClick={() => setForm({ ...form, model_id: m })}
                      className={`px-2 py-1 rounded-md text-[11px] font-mono cursor-pointer transition-colors ${
                        form.model_id === m ? 'bg-brand-soft text-brand font-semibold' : 'bg-raise text-ink-dim hover:text-ink'
                      }`}
                    >
                      {m}
                    </button>
                  ))}
                </div>
              );
            })()}
            <div className="grid grid-cols-2 gap-4">
              <Field label="模型 ID" required hint="调用时发送的 model 参数">
                <UInput mono required value={form.model_id} onChange={(e) => setForm({ ...form, model_id: e.target.value })} placeholder="如 glm-5.2" />
              </Field>
              <Field label="显示名" required>
                <UInput required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="如 GLM-5.2" />
              </Field>
            </div>
            <Field label="接入端点" required>
              <UInput mono required value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} placeholder="https://open.bigmodel.cn/api" />
            </Field>
            {/* API Key：新建必填；编辑态显示已存掩码供确认，留空=保持原密钥
                （后端空值不覆盖，非必填），输入新值则替换——不回显明文（安全红线） */}
            <Field
              label="API Key"
              required={!editing}
              hint={editing && editing.api_key ? `已保存：${editing.api_key}（留空保持不变）` : undefined}
            >
              <UInput
                type="password"
                required={!editing}
                value={form.api_key}
                onChange={(e) => setForm({ ...form, api_key: e.target.value })}
                placeholder={editing ? '留空保持现有 Key，输入新值则替换' : '输入 API Key'}
              />
            </Field>
            {/* 高级参数折叠：认证 / 协议 / 采样与上下文（主流形态——基础流不露） */}
            <div className="border-t border-line pt-3 mt-1">
              <button
                type="button"
                onClick={() => setAdvOpen((v) => !v)}
                className="flex items-center gap-1.5 text-[11.5px] text-ink-dim hover:text-ink cursor-pointer mb-4"
              >
                <ChevronRight className={`w-3.5 h-3.5 transition-transform ${advOpen ? 'rotate-90' : ''}`} />
                高级参数
                <span className="font-mono text-[10px] text-ink-faint">认证 · 协议 · 采样</span>
              </button>
              {advOpen && (
              <div className="space-y-0 max-h-[42vh] overflow-y-auto scrollbar-custom pr-1">
            <Field label="兼容协议" required hint="选厂商时自动带出；自定义网关时手动切换">
              <Seg
                value={form.compatibility_type}
                onChange={(v) => setForm({ ...form, compatibility_type: v })}
                options={COMPATIBILITY_OPTIONS.map((c) => ({ value: c, label: COMPATIBILITY_LABELS[c] }))}
              />
            </Field>
            <Field label="认证方式" required>
              <Seg
                value={form.auth_type}
                onChange={(v) => setForm({ ...form, auth_type: v })}
                options={AUTH_TYPES.map((a) => ({ value: a, label: AUTH_LABELS[a] }))}
              />
            </Field>
            {form.auth_type === 'custom' && (
              <Field label="自定义认证模板" hint="支持 {key} 占位符；纯文本 → 单个 header，JSON → 多个 header">
                <UInput mono value={form.auth_header_format} onChange={(e) => setForm({ ...form, auth_header_format: e.target.value })} placeholder="Authorization: Bearer {key}" />
              </Field>
            )}

            {/* 能力参数（默认参数区） */}
            <div className="pt-1 mt-1">
              <div className="font-mono text-[10.5px] text-ink-faint tracking-[.12em] mt-4 mb-4">DEFAULT PARAMS · 能力参数</div>
              <Field label="Temperature" optional={`当前 ${form.default_params?.temperature ?? 0.7}`}>
                <input
                  type="range" min="0" max="2" step="0.1"
                  value={form.default_params?.temperature ?? 0.7}
                  onChange={(e) => setForm({
                    ...form,
                    default_params: { ...form.default_params!, temperature: Number(e.target.value) },
                  })}
                  className="w-full accent-[var(--color-brand)] cursor-pointer"
                />
              </Field>
              <div className="grid grid-cols-2 gap-4">
                <Field label="Max Tokens">
                  <UInput type="number" min={1} value={form.default_params?.max_tokens ?? 4096} onChange={(e) => setForm({
                    ...form,
                    default_params: { ...form.default_params!, max_tokens: Number(e.target.value) },
                  })} />
                </Field>
                <Field label="Context Window">
                  <UInput type="number" min={1} value={form.default_params?.context_window ?? 128000} onChange={(e) => setForm({
                    ...form,
                    default_params: { ...form.default_params!, context_window: Number(e.target.value) },
                  })} />
                </Field>
              </div>
            </div>
              </div>
            )}
            </div>
            {error && <p className="text-sig-fail text-xs mb-3">{error}</p>}
          </form>
        </ResModal>
      )}

      {/* ── Test Modal ── */}
      {testingId && (
        <div className="fixed inset-0 flex items-center justify-center p-4 z-50 animate-fade-in">
          <div className="w-full max-w-lg max-h-[85vh] overflow-y-auto bg-panel border border-line rounded-2xl shadow-[var(--shadow-pop)]">
            <div className="flex items-center justify-between px-5 py-4 border-b border-line">
              <h3 className="text-sm font-bold text-ink flex items-center gap-2">
                <Zap className="w-4 h-4 text-brand" />
                连通性测试 · {models.find((m) => m.id === testingId)?.name}
              </h3>
              <button
                onClick={() => setTestingId(null)}
                className="p-1 rounded-lg text-ink-dim hover:text-ink hover:bg-raise transition cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>

            <div className="p-5 space-y-3 text-xs">
              {testM.isPending && (
                <div className="flex items-center justify-center py-8 text-ink-dim">
                  <Loader2 className="w-5 h-5 animate-spin mr-2" /> 正在向模型发送测试请求…
                </div>
              )}

              {testResult?.success && !testM.isPending && (
                <div className="space-y-3">
                  <div className="flex items-center gap-2 p-3 rounded-lg border border-sig-ok/30 bg-sig-ok-soft">
                    <CheckCircle2 className="w-4 h-4 text-sig-ok shrink-0" />
                    <span className="font-semibold text-sig-ok">连接成功</span>
                    <span className="ml-auto text-[11px] text-ink-dim font-mono">
                      延迟 {testResult.latency_ms}ms
                    </span>
                  </div>
                  {testResult.reply && (
                    <div>
                      <p className="text-[11px] text-ink-dim uppercase tracking-wider font-bold mb-1">模型回复</p>
                      <pre className="p-3 rounded-lg bg-panel border border-line text-ink-dim whitespace-pre-wrap font-mono text-[11px] max-h-[50vh] overflow-auto">
                        {testResult.reply}
                      </pre>
                    </div>
                  )}
                </div>
              )}

              {testResult && !testResult.success && !testM.isPending && (
                <div className="space-y-3">
                  <div className="flex items-center gap-2 p-3 rounded-lg border border-sig-fail/30 bg-sig-fail-soft">
                    <AlertTriangle className="w-4 h-4 text-sig-fail shrink-0" />
                    <span className="font-semibold text-sig-fail">连接失败</span>
                    {testResult.error_code && (
                      <span className="ml-auto px-2 py-0.5 rounded bg-sig-fail-soft text-sig-fail font-mono text-[11px]">
                        {testResult.error_code}
                      </span>
                    )}
                  </div>
                  {testResult.error && (
                    <div>
                      <p className="text-[11px] text-ink-dim uppercase tracking-wider font-bold mb-1">错误详情</p>
                      <pre className="p-3 rounded-lg bg-panel border border-line text-sig-fail whitespace-pre-wrap font-mono text-[11px] max-h-[50vh] overflow-auto">
                        {testResult.error}
                      </pre>
                    </div>
                  )}
                  {testResult.error_code && ERROR_HINTS[testResult.error_code] && (
                    <div className="flex items-start gap-2 p-3 rounded-lg border border-sig-wait/30 bg-sig-wait-soft text-sig-wait">
                      <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
                      <span className="font-sans">{ERROR_HINTS[testResult.error_code]}</span>
                    </div>
                  )}
                </div>
              )}

              {testM.isError && !testM.isPending && (
                <div className="flex items-start gap-2 p-3 rounded-lg border border-sig-fail/30 bg-sig-fail-soft text-sig-fail">
                  <AlertTriangle className="w-4 h-4 mt-0.5 shrink-0" />
                  <span className="font-sans">
                    {getErrorMessage(testM.error, '测试请求失败（网络或鉴权问题）')}
                  </span>
                </div>
              )}

              <div className="flex justify-end pt-2 border-t border-line">
                <button
                  onClick={() => testingId && testM.mutate(testingId)}
                  disabled={testM.isPending}
                  className="af-btn af-btn-secondary disabled:opacity-60 flex items-center gap-2"
                >
                  <Zap className="w-3.5 h-3.5" />
                  重新测试
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

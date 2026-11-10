/**
 * McpManagePage — MCP connection management.
 *
 * Full CRUD + connectivity test (test → auto-discover) + view-tools modal.
 * Renders connection status with color-coded dots. Ported from
 * frontend/src/pages/mcp-page.tsx, native Tailwind (lucide icons).
 */
import { useState, useMemo, type FormEvent, type ReactNode } from 'react';
import {
  Plug, Plus, Search, Zap, Pencil, Trash2, Eye, X, Loader2,
  CircleCheck, CircleSlash, AlertCircle, PlugZap, Folder,
  ChevronRight, ListTree, Table,
} from 'lucide-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  mcpApi,
  mcpKeys,
  type McpConnection,
  type McpConnectionCreateInput,
  type ConnectionStatus,
  type McpAuthType,
} from '../services/mcp-api';
import {
  mcpCategoryApi,
  mcpCategoryKeys,
  type McpCategory,
  type McpCategoryCreateInput,
} from '../services/mcp-category-api';
import { toolsApi, toolKeys } from '../services/tools-api';
import { Select } from './ui';
import { confirmDialog } from './ui/confirm';
import { toast } from './ui/toast';
import { usePermission } from '../hooks/use-permission';
import { getErrorMessage } from '../lib/api-client';
import { ResModal, Field as ResField, UInput, UTextarea, Seg } from './res-modal';

const STATUS_STYLES: Record<ConnectionStatus, { label: string; color: string; tone: 'ok' | 'wait' | 'neutral' | 'fail'; Icon: typeof CircleCheck }> = {
  connected: { label: '已连接', color: 'text-sig-ok', tone: 'ok', Icon: CircleCheck },
  connecting: { label: '连接中', color: 'text-sig-wait', tone: 'wait', Icon: Loader2 },
  disconnected: { label: '未连接', color: 'text-ink-dim', tone: 'neutral', Icon: CircleSlash },
  error: { label: '错误', color: 'text-sig-fail', tone: 'fail', Icon: AlertCircle },
};

const AUTH_LABELS: Record<McpAuthType, string> = {
  none: '无认证',
  api_key: 'API Key',
  bearer_token: 'Bearer Token',
  basic: 'Basic Auth',
};

/** Inline guidance shown above the structured auth fields. Tells the user what
 * the selected auth_type does and which header it produces. */
const AUTH_HINTS: Record<Exclude<McpAuthType, 'none'>, string> = {
  api_key: '通过自定义请求头携带密钥（默认 X-API-Key）。用于上游服务以 API Key 鉴权的场景。',
  bearer_token: '生成标准请求头 Authorization: Bearer <token>。用于上游服务以 OAuth/JWT 鉴权的场景。',
  basic: '用户名密码做 Base64 编码，生成请求头 Authorization: Basic <base64>。用于 HTTP 基础认证。',
};

const PROTOCOL_OPTIONS = ['streamable-http', 'sse'];
const AUTH_OPTIONS: McpAuthType[] = ['none', 'api_key', 'bearer_token', 'basic'];

type ConnForm = Omit<McpConnectionCreateInput, 'auth_config' | 'default_params' | 'category_id'> & {
  // Structured auth fields — assembled into auth_config on submit. Keep them
  // flat (instead of editing raw JSON) so users pick an auth_type and just fill
  // labeled inputs. auth_config keys follow the backend contract:
  //   api_key:       { api_key, header_name? }
  //   bearer_token:  { token }
  //   basic:         { username, password }
  apiKey: string;
  headerName: string;
  token: string;
  username: string;
  password: string;
  default_params: string; // JSON string
  categoryId: string;
};

function emptyForm(): ConnForm {
  return {
    name: '',
    description: '',
    categoryId: '',
    url: '',
    protocol: 'streamable-http',
    auth_type: 'none',
    apiKey: '',
    headerName: 'X-API-Key',
    token: '',
    username: '',
    password: '',
    timeout: 30,
    default_params: '',
  };
}

function connToForm(c: McpConnection): ConnForm {
  const cfg = c.auth_config ?? {};
  return {
    name: c.name,
    description: c.description ?? '',
    categoryId: c.category_id ?? '',
    url: c.url,
    protocol: c.protocol ?? 'streamable-http',
    auth_type: c.auth_type ?? 'none',
    // Read each auth_config value defensively: older records may use either
    // shape, and masked responses ("***") are preserved for unchanged fields.
    apiKey: String(cfg.api_key ?? ''),
    headerName: String(cfg.header_name ?? 'X-API-Key'),
    token: String(cfg.token ?? ''),
    username: String(cfg.username ?? ''),
    password: String(cfg.password ?? ''),
    timeout: c.timeout ?? 30,
    default_params: c.default_params && Object.keys(c.default_params).length ? JSON.stringify(c.default_params, null, 2) : '',
  };
}

/**
 * Build the auth_config object for the current auth_type from the structured
 * form fields. Mirrors the backend's `_build_headers` contract exactly:
 *   api_key → { api_key, header_name? }  (header_name omitted if default)
 *   bearer_token → { token }
 *   basic → { username, password }
 * Returns undefined for 'none' so the field is omitted from the payload.
 */
function buildAuthConfig(form: ConnForm): Record<string, string> | undefined {
  switch (form.auth_type) {
    case 'api_key': {
      const cfg: Record<string, string> = { api_key: form.apiKey.trim() };
      if (form.headerName.trim() && form.headerName.trim() !== 'X-API-Key') {
        cfg.header_name = form.headerName.trim();
      }
      return Object.keys(cfg).length ? cfg : undefined;
    }
    case 'bearer_token':
      return form.token.trim() ? { token: form.token.trim() } : undefined;
    case 'basic': {
      const u = form.username.trim();
      const p = form.password;
      return u ? { username: u, password: p } : undefined;
    }
    default:
      return undefined;
  }
}

/** Parse a JSON text field, returning {} on empty. Throws on invalid JSON. */
function parseJsonOrEmpty(text: string, field: string): Record<string, unknown> {
  const trimmed = text.trim();
  if (!trimmed) return {};
  try {
    return JSON.parse(trimmed);
  } catch {
    throw new Error(`${field} 不是有效的 JSON`);
  }
}

export function McpManagePage() {
  const queryClient = useQueryClient();
  // 写权限门控：新建/编辑/删除/测试连接（含发现工具）/分组管理后端均为 mcp:write，
  // 无权限时隐藏入口（查看工具列表为只读，保留）
  const canWrite = usePermission('mcp:write');
  const [search, setSearch] = useState('');
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState<McpConnection | null>(null);
  const [form, setForm] = useState<ConnForm>(emptyForm());
  const [error, setError] = useState<string | null>(null);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [viewingConn, setViewingConn] = useState<McpConnection | null>(null);
  const [categoryFilter, setCategoryFilter] = useState('all');
  const [categoryModalOpen, setCategoryModalOpen] = useState(false);
  // 视图模式：默认按分组折叠的树形，可切回平铺表格
  const [viewMode, setViewMode] = useState<'tree' | 'table'>('tree');
  // 已展开的分组 id 集合（默认全部折叠；搜索/过滤时强制展开以露出匹配项）
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());

  const { data, isLoading } = useQuery({
    queryKey: mcpKeys.list({ page: 1, page_size: 100 }),
    queryFn: () => mcpApi.list({ page: 1, page_size: 100 }),
  });
  const connections = data?.items ?? [];

  // 分组列表（用于过滤 / 表单下拉 / 表格显示分组名）
  const { data: categoryData } = useQuery({
    queryKey: mcpCategoryKeys.lists(),
    queryFn: () => mcpCategoryApi.list(),
  });
  const categories = useMemo(() => categoryData?.items ?? [], [categoryData]);
  const categoryMap = useMemo(() => {
    const m = new Map<string, McpCategory>();
    for (const c of categories) m.set(c.id, c);
    return m;
  }, [categories]);

  const filtered = connections
    .filter((c) => (categoryFilter === 'all' ? true : (c.category_id ?? '') === categoryFilter))
    .filter((c) => (search.trim() ? c.name.toLowerCase().includes(search.trim().toLowerCase()) : true));

  // 搜索或按分组过滤时：强制展开所有分组 + 隐藏空分组，保证匹配项可见
  const filterActive = search.trim() !== '' || categoryFilter !== 'all';

  // 树形视图数据：分组（后端已按 sort 升序）→ 连接，未分组桶固定最后
  const treeGroups = useMemo<TreeGroup[]>(() => {
    const buckets: TreeGroup[] = categories.map((c) => ({
      id: c.id,
      name: c.name,
      description: c.description || '',
      conns: [],
    }));
    const ungrouped: TreeGroup = { id: '', name: '未分组', description: '', conns: [] };
    for (const conn of filtered) {
      const bucket = buckets.find((b) => b.id === (conn.category_id ?? ''));
      if (bucket) bucket.conns.push(conn);
      else ungrouped.conns.push(conn);
    }
    const withUngrouped = ungrouped.conns.length ? [...buckets, ungrouped] : buckets;
    return filterActive ? withUngrouped.filter((b) => b.conns.length > 0) : withUngrouped;
  }, [categories, filtered, filterActive]);

  const toggleGroup = (id: string) => {
    setExpandedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const createM = useMutation({
    mutationFn: (input: McpConnectionCreateInput) => mcpApi.create(input),
    onSuccess: async () => {
      queryClient.invalidateQueries({ queryKey: mcpKeys.all });
      setError(null);
      setCreating(false);
    },
    onError: (e) => setError(getErrorMessage(e, '创建连接失败')),
  });

  const updateM = useMutation({
    mutationFn: ({ id, input }: { id: string; input: McpConnectionCreateInput }) => mcpApi.update(id, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: mcpKeys.all });
      setError(null);
      setEditing(null);
    },
    onError: (e) => setError(getErrorMessage(e, '保存连接失败')),
  });

  const deleteM = useMutation({
    mutationFn: (id: string) => mcpApi.remove(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: mcpKeys.all }),
    onError: (e) => setError(getErrorMessage(e, '删除失败')),
  });

  const testM = useMutation({
    mutationFn: async (conn: McpConnection) => {
      const res = await mcpApi.test(conn.id);
      if (res.success) {
        // test ok → auto discover tools
        await mcpApi.discover(conn.id);
        queryClient.invalidateQueries({ queryKey: mcpKeys.all });
        queryClient.invalidateQueries({ queryKey: toolKeys.all });
      }
      return res;
    },
    onSuccess: (res, conn) => {
      setTestingId(null);
      if (res.success) {
        toast.success(`「${conn.name}」连接成功，已发现 ${res.tool_count ?? 0} 个工具`);
      } else {
        toast.error(`「${conn.name}」连接失败：${res.error || '未知错误'}`);
      }
    },
    onError: (e, conn) => {
      setTestingId(null);
    },
  });

  const buildPayload = (): McpConnectionCreateInput => {
    const auth_config = buildAuthConfig(form);
    const default_params = parseJsonOrEmpty(form.default_params, 'default_params');
    return {
      name: form.name.trim(),
      description: form.description.trim() || undefined,
      category_id: form.categoryId || '',
      url: form.url.trim(),
      protocol: form.protocol,
      auth_type: form.auth_type,
      ...(auth_config ? { auth_config } : {}),
      ...(form.timeout ? { timeout: form.timeout } : {}),
      ...(Object.keys(default_params).length ? { default_params } : {}),
    };
  };

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      const payload = buildPayload();
      if (editing) updateM.mutate({ id: editing.id, input: payload });
      else createM.mutate(payload);
    } catch (err) {
      setError(getErrorMessage(err, '表单校验失败'));
    }
  };

  const handleDelete = async (c: McpConnection) => {
    const ok = await confirmDialog({
      title: `删除 MCP 连接「${c.name}」？`,
      description: '关联的 MCP 工具将一并移除。',
      okText: '删除',
      danger: true,
    });
    if (!ok) return;
    setError(null);
    deleteM.mutate(c.id);
  };

  return (
    <div className="h-full min-h-0 flex flex-col gap-4">
      {/* 工具栏：搜索 + 分组筛选 + 管理分组 + 视图切换 + 接入 CTA */}
      <div className="shrink-0 flex items-center gap-3">
        <div className="relative w-[320px]">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-ink-faint" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索 MCP 服务名称…"
            className="w-full pl-9 pr-3 h-8 text-xs bg-panel border border-line rounded-[10px] text-ink placeholder:text-ink-faint focus:outline-none focus:border-brand transition font-medium"
          />
        </div>
        <div className="w-40">
          <Select
            value={categoryFilter}
            onChange={(v) => setCategoryFilter(v ?? 'all')}
            options={[
              { value: 'all', label: '全部分组' },
              { value: '', label: '未分组' },
              ...categories.map((c) => ({ value: c.id, label: c.name })),
            ]}
          />
        </div>
        {canWrite && (
          <button
            onClick={() => setCategoryModalOpen(true)}
            className="af-btn af-btn-ghost shrink-0"
          >
            <Folder className="w-3.5 h-3.5" /> 管理分组
          </button>
        )}
        {/* 视图切换：树形（按分组折叠）/ 列表（签名卡平铺） */}
        <div className="ml-auto flex items-center rounded-lg border border-line overflow-hidden shrink-0">
          <button
            onClick={() => setViewMode('tree')}
            title="树形视图（按分组折叠）"
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold transition cursor-pointer ${
              viewMode === 'tree' ? 'bg-brand text-white' : 'text-ink-dim hover:bg-raise hover:text-ink'
            }`}
          >
            <ListTree className="w-4 h-4" /> 树形
          </button>
          <button
            onClick={() => setViewMode('table')}
            title="列表视图（平铺卡片）"
            className={`flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold transition cursor-pointer border-l border-line ${
              viewMode === 'table' ? 'bg-brand text-white' : 'text-ink-dim hover:bg-raise hover:text-ink'
            }`}
          >
            <Table className="w-4 h-4" /> 列表
          </button>
        </div>
        {canWrite && (
          <button
            onClick={() => { setError(null); setForm(emptyForm()); setCreating(true); }}
            className="af-btn af-btn-primary shrink-0"
          >
            ＋ 接入 MCP
          </button>
        )}
      </div>

      {error && (
        <div className="p-3 rounded-lg bg-sig-fail-soft border border-line text-sig-fail text-xs">{error}</div>
      )}

      {/* Tree / Card view（列表区内部滚动，页头/筛选固定） */}
      <div className="flex-1 min-h-0 overflow-y-auto scrollbar-custom overflow-x-hidden">
        {isLoading ? (
          <div className="flex items-center justify-center py-16 text-ink-dim">
            <Loader2 className="w-5 h-5 animate-spin mr-2" /> 加载中…
          </div>
        ) : filtered.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-ink-dim">
            <Plug className="w-8 h-8 mb-2 opacity-40" />
            <p className="text-sm">暂无 MCP 连接，点击右上角新建</p>
          </div>
        ) : viewMode === 'tree' ? (
          <ConnectionTree
            groups={treeGroups}
            expanded={expandedGroups}
            forceExpand={filterActive}
            onToggleGroup={toggleGroup}
            canWrite={canWrite}
            testingId={testingId}
            onTest={(c) => { setError(null); testM.mutate(c); setTestingId(c.id); }}
            onView={(c) => setViewingConn(c)}
            onEdit={(c) => { setError(null); setForm(connToForm(c)); setEditing(c); }}
            onDelete={handleDelete}
          />
        ) : (
          /* 列表视图：MCP 签名卡（设计稿 pane-mcp：插头徽章 + 协议 via 标签 +
              状态 pill + 工具数统计 + 地址 mono + foot 操作） */
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 content-start pb-4">
            {filtered.map((c) => {
              const st = STATUS_STYLES[c.status] ?? STATUS_STYLES.disconnected;
              // 协议 via 标签：sse=绿 / streamable=琥珀 / 其它=灰
              const proto = (c.protocol ?? '').toLowerCase();
              const viaCls = proto.includes('sse')
                ? 'bg-sig-ok-soft text-sig-ok'
                : proto.includes('stream')
                  ? 'bg-sig-wait-soft text-sig-wait'
                  : 'bg-raise text-ink-dim';
              return (
                <div
                  key={c.id}
                  className={`bg-panel border rounded-xl p-4 flex flex-col transition hover:shadow-[var(--shadow-card)] hover:border-line-strong ${
                    c.status === 'error' ? 'border-sig-fail border-dashed' : 'border-line'
                  }`}
                >
                  {/* 头部：插头徽章 + 名称 + 描述 + 状态 pill */}
                  <div className="flex items-start gap-[11px]">
                    <div className={`w-[38px] h-[38px] rounded-[10px] flex items-center justify-center shrink-0 ${
                      c.status === 'error' ? 'bg-sig-fail-soft text-sig-fail' : 'bg-brand-soft text-brand'
                    }`}>
                      <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5">
                        <circle cx="4" cy="10" r="2" fill="currentColor" stroke="none" />
                        <circle cx="15" cy="4.5" r="2" fill="currentColor" stroke="none" />
                        <circle cx="15" cy="15.5" r="2" fill="currentColor" stroke="none" />
                        <path d="M6 9 L13 5.2 M6 11 L13 14.8" strokeLinecap="round" />
                      </svg>
                    </div>
                    <div className="min-w-0 flex-1">
                      <div className="text-[13px] font-semibold text-ink truncate" title={c.name}>{c.name}</div>
                      <div className="text-[10.5px] text-ink-dim mt-0.5 truncate flex items-center gap-1.5">
                        {c.description ? <span className="truncate">{c.description}</span> : <span className="truncate">{c.category_id && categoryMap.has(c.category_id) ? categoryMap.get(c.category_id)?.name : '未分组'}</span>}
                        {c.protocol && <span className={`px-1.5 py-px rounded text-[10px] font-mono shrink-0 uppercase ${viaCls}`}>{proto}</span>}
                      </div>
                    </div>
                    <span className={`af-pill af-pill-${st.tone} shrink-0`}>
                      <st.Icon className={`w-3 h-3 ${c.status === 'connecting' ? 'animate-spin' : ''}`} />
                      {st.label}
                    </span>
                  </div>

                  {/* 统计行：工具数 + 地址 */}
                  <div className="text-[11px] text-ink-dim mt-3 flex items-center gap-1.5 min-w-0">
                    <b className="text-ink font-semibold">{c.tool_count ?? 0}</b> 工具
                    {c.url && (
                      <>
                        <span className="text-ink-faint">·</span>
                        <span className="font-mono text-[10px] text-ink-faint truncate" title={c.url}>{c.url}</span>
                      </>
                    )}
                  </div>

                  {/* foot：操作（设计稿 c-actions 文字链接） */}
                  <div className="flex items-center justify-end gap-2.5 border-t border-line mt-3 pt-2.5 text-[11px]">
                    <button onClick={() => setViewingConn(c)} className="text-brand hover:text-brand-hover cursor-pointer">工具明细</button>
                    {canWrite && (
                      <button
                        onClick={() => { setError(null); testM.mutate(c); setTestingId(c.id); }}
                        disabled={testingId === c.id}
                        className="text-ink-dim hover:text-ink cursor-pointer disabled:opacity-50"
                      >{testingId === c.id ? '测试中…' : '测试连通'}</button>
                    )}
                    {canWrite && (
                      <button onClick={() => { setError(null); setForm(connToForm(c)); setEditing(c); }} className="text-ink-dim hover:text-ink cursor-pointer">编辑</button>
                    )}
                    {canWrite && (
                      <button onClick={() => handleDelete(c)} className="text-sig-fail hover:opacity-75 cursor-pointer">删除</button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Create / Edit Modal：设计稿 res-create-edit 形态（徽章头 + kicker + 下划线字段 + 分段控件） */}
      {(creating || editing) && (
        <ResModal
          badge={<svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5"><circle cx="4" cy="10" r="2" fill="currentColor" stroke="none" /><circle cx="15" cy="4.5" r="2" fill="currentColor" stroke="none" /><circle cx="15" cy="15.5" r="2" fill="currentColor" stroke="none" /><path d="M6 9 L13 5.2 M6 11 L13 14.8" strokeLinecap="round" /></svg>}
          badgeCls="bg-[#F5EDDD] text-cat-mcp"
          title={editing ? `编辑连接 · ${editing.name}` : '接入 MCP 服务'}
          kicker="MCP SERVER · CONNECT"
          onClose={() => { setCreating(false); setEditing(null); setError(null); }}
          formId="mcp-conn-form"
          footer={{
            actions: (
              <>
                <button type="button" onClick={() => { setCreating(false); setEditing(null); setError(null); }} className="af-btn af-btn-ghost">取消</button>
                <button type="submit" form="mcp-conn-form" disabled={createM.isPending || updateM.isPending}
                  className="af-btn af-btn-primary disabled:opacity-60 flex items-center gap-2">
                  {(createM.isPending || updateM.isPending) && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  {editing ? '保存' : '创建'}
                </button>
              </>
            ),
          }}
        >
          <form id="mcp-conn-form" onSubmit={handleSubmit}>
            <ResField label="名称" required>
              <UInput required value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="如 工单管理-本地-jdk8" />
            </ResField>
            <ResField label="描述" optional="可选">
              <UInput value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} placeholder="这个服务提供什么能力…" />
            </ResField>
            <ResField label="传输协议" required>
              <Seg
                value={form.protocol}
                onChange={(v) => setForm({ ...form, protocol: v })}
                options={PROTOCOL_OPTIONS.map((p) => ({ value: p, label: p === 'sse' ? 'SSE 远程' : 'Streamable HTTP' }))}
              />
            </ResField>
            <ResField label="端点 URL" required hint="以 /sse 或 /mcp 结尾的服务地址">
              <UInput mono required value={form.url} onChange={(e) => setForm({ ...form, url: e.target.value })} placeholder="http://127.0.0.1:8080/mcp/sse" />
            </ResField>
            <ResField label="分组" optional="可选">
              <select
                value={form.categoryId}
                onChange={(e) => setForm({ ...form, categoryId: e.target.value })}
                className="w-full border-0 border-b border-line-strong bg-transparent px-0 py-[7px] text-[13px] text-ink outline-none transition-colors focus:border-b-brand"
              >
                <option value="">未分组</option>
                {categories.map((c) => (<option key={c.id} value={c.id}>{c.name}</option>))}
              </select>
            </ResField>
            <ResField label="认证方式" optional={form.auth_type === 'none' ? '可选' : undefined} hint={form.auth_type !== 'none' ? AUTH_HINTS[form.auth_type] : undefined}>
              <Seg
                value={form.auth_type}
                onChange={(v) => setForm({ ...form, auth_type: v })}
                options={AUTH_OPTIONS.map((a) => ({ value: a, label: AUTH_LABELS[a] }))}
              />
            </ResField>
            {form.auth_type === 'api_key' && (
              <div className="grid grid-cols-2 gap-4">
                <ResField label="API Key" required hint={editing && form.apiKey === '***' ? '已配置，保持 *** 不修改；重新输入以更新' : undefined}>
                  <UInput type="password" required value={form.apiKey} onChange={(e) => setForm({ ...form, apiKey: e.target.value })} placeholder="sk-..." autoComplete="off" />
                </ResField>
                <ResField label="请求头名称">
                  <UInput value={form.headerName} onChange={(e) => setForm({ ...form, headerName: e.target.value })} placeholder="X-API-Key" />
                </ResField>
              </div>
            )}
            {form.auth_type === 'bearer_token' && (
              <ResField label="Token" required hint={editing && form.token === '***' ? '已配置，保持 *** 不修改；重新输入以更新' : undefined}>
                <UInput type="password" required value={form.token} onChange={(e) => setForm({ ...form, token: e.target.value })} placeholder="粘贴 Bearer Token（无需加 Bearer 前缀）" autoComplete="off" />
              </ResField>
            )}
            {form.auth_type === 'basic' && (
              <div className="grid grid-cols-2 gap-4">
                <ResField label="用户名" required>
                  <UInput required value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} autoComplete="off" />
                </ResField>
                <ResField label="密码" hint={editing && form.password === '***' ? '已配置，保持 *** 不修改；重新输入以更新' : undefined}>
                  <UInput type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} autoComplete="new-password" />
                </ResField>
              </div>
            )}
            <div className="grid grid-cols-2 gap-4 items-end">
              <ResField label="超时 (秒)">
                <UInput type="number" min={1} max={300} value={form.timeout} onChange={(e) => setForm({ ...form, timeout: Number(e.target.value) })} />
              </ResField>
            </div>
            <ResField label="默认参数" optional="JSON，可选">
              <UTextarea mono rows={2} value={form.default_params} onChange={(e) => setForm({ ...form, default_params: e.target.value })} placeholder="{}" />
            </ResField>
            {error && <p className="text-sig-fail text-xs mb-3">{error}</p>}
          </form>
        </ResModal>
      )}

      {/* View-tools Modal */}
      {viewingConn && <ViewToolsModal conn={viewingConn} onClose={() => setViewingConn(null)} />}

      {/* Category manage Modal */}
      {categoryModalOpen && <McpCategoryModal onClose={() => setCategoryModalOpen(false)} />}
    </div>
  );
}

/* ─── 分组树视图：分组 → 连接 两层 ─── */

/** 树形视图的分组节点：分组（或"未分组"桶）→ 连接 两层。 */
interface TreeGroup {
  id: string;
  name: string;
  description: string;
  conns: McpConnection[];
}

/**
 * ConnectionTree — 按分组折叠的连接树（页面默认视图，默认全部折叠）。
 *
 * 分组节点行可展开/折叠（ChevronRight 旋转，风格同 PermissionTree）；
 * 连接节点行复用表格的操作语义：状态点、URL/协议/工具数、测试/查看
 * 工具/编辑/删除按钮。空分组显示「暂无连接」占位；调用方在过滤态下
 * 直接隐藏空分组。
 */
function ConnectionTree({
  groups,
  expanded,
  forceExpand,
  onToggleGroup,
  canWrite,
  testingId,
  onTest,
  onView,
  onEdit,
  onDelete,
}: {
  groups: TreeGroup[];
  expanded: Set<string>;
  /** 搜索/过滤态下强制展开，保证匹配项可见 */
  forceExpand: boolean;
  onToggleGroup: (id: string) => void;
  canWrite: boolean;
  testingId: string | null;
  onTest: (c: McpConnection) => void;
  onView: (c: McpConnection) => void;
  onEdit: (c: McpConnection) => void;
  onDelete: (c: McpConnection) => void;
}) {
  return (
    <div>
      {groups.map((g) => {
        const open = forceExpand || expanded.has(g.id);
        return (
          <div key={g.id || 'ungrouped'}>
            {/* 分组节点 */}
            <button
              type="button"
              onClick={() => onToggleGroup(g.id)}
              className="w-full flex items-center gap-2 px-4 py-3 hover:bg-panel-hover transition text-left cursor-pointer"
            >
              <ChevronRight className={`w-4 h-4 text-ink-dim shrink-0 transition-transform ${open ? 'rotate-90' : ''}`} />
              <Folder className="w-4 h-4 text-brand shrink-0" />
              <span className="text-xs font-bold text-ink shrink-0">{g.name}</span>
              <span className="px-1.5 py-0.5 rounded-full bg-brand-soft text-brand text-[11px] font-semibold font-mono shrink-0">
                {g.conns.length}
              </span>
              {g.description && <span className="text-[11px] text-ink-dim truncate">{g.description}</span>}
            </button>
            {/* 连接节点 */}
            {open && (
              g.conns.length === 0 ? (
                <p className="pl-11 pr-4 pb-3 text-[11px] text-ink-dim">暂无连接</p>
              ) : (
                <div className="pb-1">
                  {g.conns.map((c) => {
                    const st = STATUS_STYLES[c.status] ?? STATUS_STYLES.disconnected;
                    return (
                      <div key={c.id} className="flex items-center gap-3 pl-11 pr-4 py-2.5 hover:bg-panel-hover transition">
                        <div className="flex items-center gap-2 min-w-0 flex-1">
                          <st.Icon
                            className={`w-3.5 h-3.5 shrink-0 ${st.color} ${c.status === 'connecting' ? 'animate-spin' : ''}`}
                          />
                          <div className="min-w-0">
                            <div className="flex items-center gap-2">
                              <span className="text-xs font-semibold text-ink truncate">{c.name}</span>
                              <span className={`text-[11px] font-bold shrink-0 ${st.color}`}>{st.label}</span>
                            </div>
                            {c.description && <p className="text-[11px] text-ink-dim truncate">{c.description}</p>}
                          </div>
                        </div>
                        <span className="hidden lg:block text-[11px] text-ink-dim font-mono max-w-[220px] truncate shrink-0" title={c.url}>{c.url}</span>
                        <span className="hidden xl:block text-[11px] text-ink-dim shrink-0">{c.protocol ?? '—'}</span>
                        <span className="text-[11px] text-ink-dim font-mono shrink-0">{c.tool_count ?? 0} 工具</span>
                        <div className="flex items-center justify-end gap-1 shrink-0">
                          {canWrite && (
                            <button onClick={() => onTest(c)} title="测试连接 + 发现工具" disabled={testingId === c.id}
                              className="p-1.5 rounded-lg text-ink-dim hover:text-sig-wait hover:bg-raise transition cursor-pointer disabled:opacity-50">
                              {testingId === c.id ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
                            </button>
                          )}
                          <button onClick={() => onView(c)} title="查看工具"
                            className="p-1.5 rounded-lg text-ink-dim hover:text-ink hover:bg-raise transition cursor-pointer">
                            <Eye className="w-4 h-4" />
                          </button>
                          {canWrite && (
                            <button onClick={() => onEdit(c)} title="编辑"
                              className="p-1.5 rounded-lg text-ink-dim hover:text-brand hover:bg-raise transition cursor-pointer">
                              <Pencil className="w-4 h-4" />
                            </button>
                          )}
                          {canWrite && (
                            <button onClick={() => onDelete(c)} title="删除"
                              className="p-1.5 rounded-lg text-ink-dim hover:text-sig-fail hover:bg-raise transition cursor-pointer">
                              <Trash2 className="w-4 h-4" />
                            </button>
                          )}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )
            )}
          </div>
        );
      })}
    </div>
  );
}

/* ─── MCP 分组管理 Modal ─── */

function McpCategoryModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [editId, setEditId] = useState<string | null>(null);
  const [formName, setFormName] = useState('');
  const [formDescription, setFormDescription] = useState('');
  const [formSort, setFormSort] = useState(0);

  const { data, isLoading } = useQuery({
    queryKey: mcpCategoryKeys.lists(),
    queryFn: () => mcpCategoryApi.list(),
  });
  const categories = data?.items ?? [];

  const createM = useMutation({
    mutationFn: (input: McpCategoryCreateInput) => mcpCategoryApi.create(input),
    onSuccess: () => {
      toast.success('分组创建成功');
      queryClient.invalidateQueries({ queryKey: mcpCategoryKeys.all });
      resetForm();
    },
    onError: (e) => toast.error(getErrorMessage(e, '创建失败')),
  });

  const updateM = useMutation({
    mutationFn: ({ id, input }: { id: string; input: McpCategoryCreateInput }) => mcpCategoryApi.update(id, input),
    onSuccess: () => {
      toast.success('分组已更新');
      queryClient.invalidateQueries({ queryKey: mcpCategoryKeys.all });
      resetForm();
    },
    onError: (e) => toast.error(getErrorMessage(e, '更新失败')),
  });

  const deleteM = useMutation({
    mutationFn: (id: string) => mcpCategoryApi.remove(id),
    onSuccess: () => {
      toast.success('分组已删除');
      queryClient.invalidateQueries({ queryKey: mcpCategoryKeys.all });
    },
    onError: (e) => toast.error(getErrorMessage(e, '删除失败')),
  });

  function resetForm() {
    setEditId(null);
    setFormName('');
    setFormDescription('');
    setFormSort(0);
  }

  function startEdit(c: McpCategory) {
    setEditId(c.id);
    setFormName(c.name);
    setFormDescription(c.description || '');
    setFormSort(c.sort ?? 0);
  }

  function handleSubmit() {
    if (!formName.trim()) {
      toast.error('请填写分组名称');
      return;
    }
    const input: McpCategoryCreateInput = {
      name: formName.trim(),
      description: formDescription.trim(),
      sort: formSort ?? 0,
    };
    if (editId) updateM.mutate({ id: editId, input });
    else createM.mutate(input);
  }

  async function handleDelete(c: McpCategory) {
    const ok = await confirmDialog({
      title: `删除分组「${c.name}」？`,
      description: '若分组下仍有 MCP 连接将无法删除。',
      okText: '删除',
      danger: true,
    });
    if (ok) deleteM.mutate(c.id);
  }

  return (
    <div className="fixed inset-0 flex items-center justify-center p-4 z-50 animate-fade-in">
      <div className="w-full max-w-lg max-h-[85vh] overflow-y-auto bg-panel border border-line rounded-2xl shadow-[var(--shadow-pop)]">
        <div className="flex items-center justify-between px-5 py-4 border-b border-line sticky top-0 bg-panel z-10">
          <h3 className="text-sm font-bold text-ink flex items-center gap-2">
            <Folder className="w-4 h-4 text-brand" />
            MCP 分组管理
          </h3>
          <button onClick={() => { resetForm(); onClose(); }}
            className="p-1 rounded-lg text-ink-dim hover:text-ink hover:bg-line transition cursor-pointer">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="p-5 space-y-4">
          {/* 内联新增/编辑表单 */}
          <div className="space-y-2.5 rounded-lg border border-line bg-panel/40 p-3">
            <p className="text-xs font-bold text-ink">{editId ? '编辑分组' : '新增分组'}</p>
            <div className="grid grid-cols-[1fr_90px] gap-2">
              <div className="space-y-1">
                <label className="text-[11px] text-ink-dim">分组名称 *</label>
                <input value={formName} onChange={(e) => setFormName(e.target.value)} placeholder="如：飞书" maxLength={50} className={inputCls} />
              </div>
              <div className="space-y-1">
                <label className="text-[11px] text-ink-dim">排序</label>
                <input type="number" min="0" value={formSort} onChange={(e) => setFormSort(Number(e.target.value))} className={inputCls} />
              </div>
            </div>
            <div className="space-y-1">
              <label className="text-[11px] text-ink-dim">描述</label>
              <input value={formDescription} onChange={(e) => setFormDescription(e.target.value)} placeholder="分组描述（可选）" maxLength={200} className={inputCls} />
            </div>
            <div className="flex items-center justify-end gap-2">
              {editId && (
                <button type="button" onClick={resetForm}
                  className="px-3 py-1.5 border border-line hover:bg-panel text-ink-dim hover:text-ink rounded-lg text-xs font-semibold transition cursor-pointer">取消编辑</button>
              )}
              <button type="button" onClick={handleSubmit} disabled={createM.isPending || updateM.isPending}
                className="px-4 py-1.5 bg-brand hover:bg-brand-hover text-white rounded-lg text-xs font-semibold transition cursor-pointer disabled:opacity-60 flex items-center gap-1.5">
                {(createM.isPending || updateM.isPending) && <Loader2 className="w-3 h-3 animate-spin" />}
                {editId ? '保存' : '新增'}
              </button>
            </div>
          </div>

          {/* 分组列表 */}
          {isLoading ? (
            <div className="flex items-center justify-center py-8 text-ink-dim"><Loader2 className="w-4 h-4 animate-spin mr-2" />加载中…</div>
          ) : categories.length === 0 ? (
            <div className="text-center py-8 text-ink-dim text-sm">暂无分组</div>
          ) : (
            <div className="flex flex-col gap-1.5 max-h-[320px] overflow-y-auto">
              {categories.map((c) => (
                <div key={c.id} className="flex items-center gap-2 rounded-lg border border-line px-3 py-2 hover:bg-panel transition">
                  <Folder className="w-4 h-4 text-brand shrink-0" />
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-semibold text-ink truncate">{c.name}</p>
                    {c.description && <p className="text-[11px] text-ink-dim truncate">{c.description}</p>}
                  </div>
                  <span className="text-[11px] text-ink-dim shrink-0">排序 {c.sort ?? 0}</span>
                  <button onClick={() => startEdit(c)} title="编辑"
                    className="p-1.5 rounded-lg text-ink-dim hover:text-brand hover:bg-raise transition cursor-pointer">
                    <Pencil className="w-3.5 h-3.5" />
                  </button>
                  <button onClick={() => handleDelete(c)} title="删除" disabled={deleteM.isPending}
                    className="p-1.5 rounded-lg text-ink-dim hover:text-sig-fail hover:bg-raise transition cursor-pointer disabled:opacity-40">
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function ViewToolsModal({ conn, onClose }: { conn: McpConnection; onClose: () => void }) {
  const { data, isLoading } = useQuery({
    queryKey: [...toolKeys.lists(), { mcp: conn.id }],
    queryFn: () => toolsApi.list({ mcp_connection_id: conn.id, page_size: 100 }),
  });
  const tools = data?.items ?? [];
  return (
    <div className="fixed inset-0 flex items-center justify-center p-4 z-50 animate-fade-in">
      <div className="w-full max-w-2xl max-h-[85vh] flex flex-col bg-panel border border-line rounded-2xl shadow-[var(--shadow-pop)]">
        <div className="flex items-center justify-between px-5 py-4 border-b border-line">
          <h3 className="text-sm font-bold text-ink">MCP 工具列表 — {conn.name}</h3>
          <button onClick={onClose} className="p-1 rounded-lg text-ink-dim hover:text-ink hover:bg-line transition cursor-pointer">
            <X className="w-4 h-4" />
          </button>
        </div>
        <div className="p-5 overflow-y-auto flex-1 space-y-2">
          {isLoading ? (
            <div className="flex items-center justify-center py-8 text-ink-dim"><Loader2 className="w-5 h-5 animate-spin mr-2" />加载中…</div>
          ) : tools.length === 0 ? (
            <div className="text-center py-8 text-ink-dim text-sm">该连接暂无工具。请先点「测试连接」触发发现。</div>
          ) : (
            tools.map((t) => {
              const props = (t.input_schema?.properties ?? {}) as Record<string, unknown>;
              const required = (t.input_schema?.required ?? []) as string[];
              const paramNames = Object.keys(props);
              return (
                <div key={t.id} className="p-3 rounded-lg border border-line bg-panel">
                  <div className="flex items-center gap-2">
                    <span className="font-mono font-bold text-ink text-xs">{t.name}</span>
                    {paramNames.length > 0 && (
                      <div className="flex flex-wrap gap-1 ml-auto">
                        {paramNames.map((p) => (
                          <span key={p} className={`px-1.5 py-0.5 rounded text-[11px] font-mono ${required.includes(p) ? 'bg-sky-500/10 text-sky-400' : 'bg-page text-ink-dim'}`}>
                            {p}{required.includes(p) ? '*' : ''}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                  {t.description && <p className="text-[11px] text-ink-dim mt-1">{t.description}</p>}
                </div>
              );
            })
          )}
        </div>
        <div className="px-5 py-3 border-t border-line text-[11px] text-ink-dim">共 {tools.length} 个工具</div>
      </div>
    </div>
  );
}

const inputCls = 'w-full px-3 py-2 bg-page border border-line rounded-lg text-white placeholder:text-ink-dim focus:outline-none focus:border-brand transition text-xs font-sans';

function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="space-y-1">
      <label className="text-ink-dim font-medium font-sans">{label}</label>
      {children}
      {hint && <p className="text-[11px] text-ink-dim leading-relaxed">{hint}</p>}
    </div>
  );
}

/**
 * ToolMarketPage — 组织工具库（ToB 治理模型，单页卡片墙）。
 *
 * 治理流程：tool:write 创建 → submit → admin 审查 → admin 配置凭证
 * → admin 开启 →「已开启」的工具才能被 Agent 绑定 / 工作流直调。
 * 无个人工具页面：卡片标创建者；owner 就地编辑/提交发布/删除；
 * admin 就地审查/开启停用/配置凭证；单创建入口（治理流程统一）。
 */
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import {
  useQuery, useMutation, useQueryClient,
} from '@tanstack/react-query';
import {
  Wrench, Globe, Code2, ThumbsUp, ThumbsDown, Trash2, Plus,
  Send, Pencil, Eye, Crown, Copy, KeyRound, ChevronDown, Wand2,
  Maximize2, Minimize2,
} from 'lucide-react';
import hljs from 'highlight.js/lib/core';
import pythonLang from 'highlight.js/lib/languages/python';
import 'highlight.js/styles/github-dark.css';
import { getErrorMessage } from '../lib/api-client';
import { usePermission } from '../hooks/use-permission';
import { useAuthStore } from '../stores/auth-store';
import { toast } from './ui/toast';
import { confirmDialog } from './ui/confirm';
import { toolsApi, toolKeys } from '../services/tools-api';
import {
  userToolsApi, userToolKeys,
  type ToolMarketItem, type UserToolDetail,
} from '../services/user-tools-api';

hljs.registerLanguage('python', pythonLang);

type Tab = 'library';

const STATUS_LABEL: Record<string, string> = {
  private: '草稿', submitted: '审核中', published: '已过审', hidden: '已隐藏',
};

const SOURCE_META: Record<string, { label: string; icon: typeof Globe; cls: string }> = {
  openapi: { label: 'API', icon: Globe, cls: 'text-blue-400' },
  code: { label: 'Code', icon: Code2, cls: 'text-emerald-500' },
};

interface Props {
  theme?: 'dark' | 'light';
}

/** 组织工具库（单页卡片墙）：无个人工具概念——卡片标创建者，操作就地做 */
export function ToolMarketPage({ theme = 'dark' }: Props) {
  return <LibraryTab theme={theme} />;
}


/* ══════════════ 工具库（目录） ══════════════ */

function LibraryTab({ theme }: { theme: 'dark' | 'light' }) {
  const qc = useQueryClient();
  const [q, setQ] = useState('');
  const [preview, setPreview] = useState<ToolMarketItem | null>(null);
  const [argsTool, setArgsTool] = useState<{ id: string; name: string } | null>(null);
  const [editing, setEditing] = useState<UserToolDetail | null>(null);
  const [creating, setCreating] = useState(false);
  const role = useAuthStore((s) => s.user?.role);
  const isAdmin = role === 'admin';
  const canCreate = usePermission('tool:write');

  const { data: items = [], isLoading } = useQuery({
    queryKey: userToolKeys.marketplace(q),
    queryFn: () => userToolsApi.marketplace(q),
  });
  const { data: pending = [] } = useQuery({
    queryKey: userToolKeys.review('submitted'),
    queryFn: () => userToolsApi.reviewList('submitted'),
    enabled: isAdmin,
  });
  // admin 的待审置顶（own 草稿已由 marketplace 合并，去重后拼接）
  const seenIds = new Set(items.map((i) => i.id));
  const all: ToolMarketItem[] = [
    ...pending
      .filter((t) => !seenIds.has(t.id))
      .map((t) => ({
        ...t, kind: 'user' as const, author_name: '用户',
        enabled: false, is_own: false, my_vote: 0, score: 0,
        status: 'submitted' as const,
      })),
    ...items,
  ];

  const invalidate = () => void qc.invalidateQueries({ queryKey: userToolKeys.all });

  const enableM = useMutation({
    mutationFn: (v: { id: string; name: string; enabled: boolean }) =>
      userToolsApi.enable(v.id, v.enabled),
    onSuccess: (_r, v) => {
      invalidate();
      toast.success(v.enabled ? '已开启——Agent 绑定与工作流可用' : '已停用');
    },
    onError: (e, v) => {
      toast.error(getErrorMessage(e, v.enabled ? '开启失败' : '停用失败'));
      if (v.enabled) setArgsTool({ id: v.id, name: v.name });
    },
  });
  const officialStatusM = useMutation({
    mutationFn: (v: { id: string; status: 'active' | 'disabled' }) => toolsApi.setToolStatus(v.id, v.status),
    onSuccess: (_r, v) => {
      invalidate();
      toast.success(v.status === 'active' ? '已启用——Agent 绑定与工作流可用' : '已停用');
    },
    onError: (e) => toast.error(getErrorMessage(e, '操作失败')),
  });
  const forkM = useMutation({
    mutationFn: (id: string) => userToolsApi.fork(id),
    onSuccess: () => { invalidate(); toast.success('已复制为草稿'); },
    onError: (e) => toast.error(getErrorMessage(e, '复制失败')),
  });
  const voteM = useMutation({
    mutationFn: (v: { id: string; value: 1 | -1 }) => userToolsApi.vote(v.id, v.value),
    onSuccess: invalidate,
    onError: (e) => toast.error(getErrorMessage(e, '投票失败')),
  });
  const submitM = useMutation({
    mutationFn: (id: string) => userToolsApi.submit(id),
    onSuccess: () => { invalidate(); toast.success('已提交审核'); },
    onError: (e) => toast.error(getErrorMessage(e, '提交失败')),
  });
  const deleteM = useMutation({
    mutationFn: (id: string) => userToolsApi.remove(id),
    onSuccess: () => { invalidate(); toast.success('已删除'); },
    onError: (e) => toast.error(getErrorMessage(e, '删除失败')),
  });
  const handleDelete = (item: ToolMarketItem) => {
    void confirmDialog({
      title: '删除工具',
      description: `确定删除「${item.name}」？该操作不可恢复。`,
      okText: '删除',
      danger: true,
    }).then((ok) => { if (ok) deleteM.mutate(item.id); });
  };
  const handleEdit = (item: ToolMarketItem) => {
    // 拉详情作编辑初值（官方工具不支持就地编辑定义——无入口）
    void userToolsApi.get(item.id)
      .then(setEditing)
      .catch((e) => toast.error(getErrorMessage(e, '加载工具详情失败')));
  };

  const textMuted = theme === 'dark' ? 'text-[#a1a1aa]' : 'text-slate-500';

  return (
    <div className="space-y-4">
      {/* 搜索/创建工具行：滚动时固定在顶部（负边距抵消滚动容器 p-6，背景遮住滑过的卡片） */}
      <div className={`sticky top-0 z-30 -mx-6 -mt-6 px-6 py-3 flex items-center gap-2 ${
        theme === 'dark' ? 'bg-[#09090b]' : 'bg-slate-50'
      }`}>
        <input
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="搜索工具名称/描述…"
          className={`flex-1 max-w-md px-3 py-1.5 rounded-lg text-sm border outline-none ${
            theme === 'dark' ? 'bg-[#18181b] border-[#27272a] text-[#fafafa]' : 'bg-white border-slate-200'
          }`}
        />
        {canCreate && (
          <button onClick={() => setCreating(true)}
            className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs bg-blue-600 hover:bg-blue-500 text-white cursor-pointer ml-auto">
            <Plus size={14} />创建工具
          </button>
        )}
      </div>

      {isLoading && <div className="py-12 text-center text-sm opacity-60">加载中…</div>}
      {!isLoading && all.length === 0 && (
        <div className={`py-12 text-center text-sm ${textMuted}`}>
          暂无工具{canCreate ? '——点右上「创建工具」新增' : ''}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
        {all.map((it) => (
          <LibraryCard
            key={it.id}
            item={it}
            theme={theme}
            isAdmin={isAdmin}
            canCreate={canCreate}
            onPreview={() => setPreview(it)}
            onEnable={(v) => (it.kind === 'official'
              ? officialStatusM.mutate({ id: it.id, status: v ? 'active' : 'disabled' })
              : enableM.mutate({ id: it.id, name: it.name, enabled: v }))}
            onConfigArgs={() => setArgsTool({ id: it.id, name: it.name })}
            onFork={() => forkM.mutate(it.id)}
            onVote={(v) => voteM.mutate({ id: it.id, value: v })}
            onEdit={() => handleEdit(it)}
            onSubmit={() => submitM.mutate(it.id)}
            onDelete={() => handleDelete(it)}
          />
        ))}
      </div>

      {preview && <PreviewModal item={preview} theme={theme} onClose={() => setPreview(null)} />}
      {argsTool && (
        <OrgArgsModal
          key={argsTool.id}
          toolId={argsTool.id}
          fallbackName={argsTool.name}
          theme={theme}
          onClose={() => setArgsTool(null)}
        />
      )}
      {(creating || editing) && (
        <ToolEditModal
          theme={theme}
          initial={editing ?? undefined}
          onClose={() => { setCreating(false); setEditing(null); }}
          onSaved={() => { invalidate(); setCreating(false); setEditing(null); }}
        />
      )}
    </div>
  );
}

function LibraryCard({ item, theme, isAdmin, canCreate, onPreview, onEnable, onConfigArgs, onFork, onVote, onEdit, onSubmit, onDelete }: {
  item: ToolMarketItem;
  theme: 'dark' | 'light';
  isAdmin: boolean;
  canCreate: boolean;
  onPreview: () => void;
  onEnable: (v: boolean) => void;
  onConfigArgs: () => void;
  onFork: () => void;
  onVote: (v: 1 | -1) => void;
  onEdit: () => void;
  onSubmit: () => void;
  onDelete: () => void;
}) {
  const card = theme === 'dark' ? 'bg-[#18181b] border-[#27272a]' : 'bg-white border-slate-200';
  const textMuted = theme === 'dark' ? 'text-[#a1a1aa]' : 'text-slate-500';
  const chip = theme === 'dark' ? 'bg-[#27272a]' : 'bg-slate-100';
  const isPending = item.status === 'submitted';
  const isDraft = item.status === 'private';
  const isOfficial = item.kind === 'official';
  const isOwn = item.is_own;
  const srcMeta = SOURCE_META[item.source] ?? { label: item.source, icon: Wrench, cls: '' };

  const qc = useQueryClient();
  const [rejecting, setRejecting] = useState(false);
  const [reason, setReason] = useState('');
  const reviewM = useMutation({
    mutationFn: (v: { action: 'approve' | 'reject'; reason?: string }) =>
      userToolsApi.review(item.id, v.action, v.reason ?? ''),
    onSuccess: () => void qc.invalidateQueries({ queryKey: userToolKeys.all }),
    onError: (e) => toast.error(getErrorMessage(e, '审核失败')),
  });

  return (
    <div
      className={`rounded-xl border p-5 flex flex-col gap-3 transition ${
        isPending
          ? theme === 'dark'
            ? 'bg-amber-950/20 border-amber-700/50'
            : 'bg-amber-50 border-amber-300'
          : isDraft
            ? theme === 'dark'
              ? 'border-dashed border-[#3f3f46] bg-[#18181b]/60'
              : 'border-dashed border-slate-300 bg-slate-50/60'
            : isOfficial
              ? 'border-amber-500/40 border-t-2 border-t-amber-500/70 hover:border-amber-400'
              : `hover:border-[#71717a] ${card}`
      }`}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-3 min-w-0">
          <div className={`w-10 h-10 rounded-xl flex items-center justify-center shrink-0 border ${
            theme === 'dark' ? 'bg-[#121214] border-[#27272a]' : 'bg-slate-50 border-slate-200'
          }`}>
            <srcMeta.icon size={18} className={srcMeta.cls} />
          </div>
          <div className="min-w-0 space-y-1">
            <div className="flex items-center gap-1.5 min-w-0">
              <span className="text-sm font-bold truncate flex-1 min-w-0" title={item.name}>{item.name}</span>
              {isOfficial && <Crown size={13} className="shrink-0 text-amber-500" />}
            </div>
            <div className={`text-[11px] ${textMuted} truncate`}>
              {srcMeta.label} · 创建者 {item.author_name || '未知'}
            </div>
          </div>
        </div>
        <div className={`flex items-center gap-1 text-[11px] ${textMuted} shrink-0`}>
          <ThumbsUp size={12} />{item.score}
        </div>
      </div>

      <p className={`text-xs ${textMuted} line-clamp-2 min-h-[2rem]`}>{item.description || '暂无描述'}</p>

      <div className="flex items-center gap-1.5 flex-wrap text-[10px]">
        <span className={`px-1.5 py-0.5 rounded ${chip} ${
          item.enabled ? 'text-emerald-500' : 'text-[#71717a]'
        }`}>
          {item.enabled ? '已开启 · 可用' : isPending ? '待审核' : isDraft ? '草稿' : '未开启'}
        </span>
        <span className={`px-1.5 py-0.5 rounded ${chip}`}>调用 {item.stats?.load_count ?? 0}</span>
      </div>

      {isPending ? (
        <div className="space-y-2 pt-1 border-t border-current/10">
          <div className="text-[11px] text-amber-500">待审核{isAdmin ? '' : '（等待管理员处理）'}</div>
          {isOwn && (
            <div className="flex items-center gap-1 text-xs">
              <button onClick={onEdit}
                className={`flex items-center gap-1 px-2 py-1 rounded cursor-pointer hover:opacity-80 ${textMuted}`}>
                <Pencil size={12} />编辑
              </button>
              <button onClick={onDelete}
                className="flex items-center gap-1 px-2 py-1 rounded text-red-400 hover:text-red-300 cursor-pointer">
                <Trash2 size={12} />删除
              </button>
            </div>
          )}
          {isAdmin && (
            <>
              <div className="flex gap-2">
                <button onClick={() => reviewM.mutate({ action: 'approve' })}
                  className="flex-1 px-2 py-1.5 rounded-lg text-xs bg-emerald-600 hover:bg-emerald-500 text-white cursor-pointer">
                  通过
                </button>
                <button onClick={() => setRejecting(true)}
                  className="flex-1 px-2 py-1.5 rounded-lg text-xs bg-red-600/80 hover:bg-red-500 text-white cursor-pointer">
                  驳回
                </button>
              </div>
              {rejecting && (
                <div className="space-y-1.5">
                  <input value={reason} onChange={(e) => setReason(e.target.value)} placeholder="驳回理由（展示给创建者）"
                    className={`w-full px-2 py-1 rounded text-xs border outline-none ${
                      theme === 'dark' ? 'bg-[#18181b] border-[#27272a]' : 'bg-white border-slate-200'
                    }`} />
                  <button onClick={() => reviewM.mutate({ action: 'reject', reason })}
                    className="w-full px-2 py-1 rounded text-xs bg-red-600 hover:bg-red-500 text-white cursor-pointer">
                    确认驳回
                  </button>
                </div>
              )}
            </>
          )}
        </div>
      ) : isDraft ? (
        /* 草稿：owner 就地管理（提交发布 / 编辑 / 删除） */
        <div className="flex items-center gap-1 pt-1 border-t border-current/10 text-xs">
          {isOwn && (
            <>
              <button onClick={onSubmit}
                className="flex items-center gap-1 px-2 py-1 rounded text-blue-400 hover:text-blue-300 cursor-pointer">
                <Send size={12} />提交发布
              </button>
              <button onClick={onEdit}
                className={`flex items-center gap-1 px-2 py-1 rounded cursor-pointer hover:opacity-80 ${textMuted}`}>
                <Pencil size={12} />编辑
              </button>
              <div className="flex-1" />
              <button onClick={onDelete}
                className="flex items-center gap-1 px-2 py-1 rounded text-red-400 hover:text-red-300 cursor-pointer">
                <Trash2 size={12} />删除
              </button>
            </>
          )}
        </div>
      ) : (
        <div className="flex items-center gap-2 pt-1 border-t border-current/10">
          <button onClick={onPreview}
            className={`flex items-center gap-1 px-2 py-1 rounded text-xs cursor-pointer hover:opacity-80 ${textMuted}`}>
            <Eye size={13} />详情
          </button>
          {isAdmin && (
            <>
              <ToolToggle enabled={item.enabled} onChange={onEnable} />
              <button onClick={onConfigArgs}
                className={`flex items-center gap-1 px-2 py-1 rounded text-xs cursor-pointer hover:opacity-80 ${textMuted}`}
                title="配置工具级统一凭证（所有使用点共用）">
                <KeyRound size={13} />凭证
              </button>
            </>
          )}
          {isOwn && !isOfficial && (
            <>
              <button onClick={onEdit}
                className={`flex items-center gap-1 px-2 py-1 rounded text-xs cursor-pointer hover:opacity-80 ${textMuted}`}>
                <Pencil size={12} />编辑
              </button>
              <button onClick={onDelete}
                className="flex items-center gap-1 px-2 py-1 rounded text-xs text-red-400 hover:text-red-300 cursor-pointer">
                <Trash2 size={12} />删除
              </button>
            </>
          )}
          {!isOfficial && canCreate && !item.is_own && (
            <button onClick={onFork}
              className={`flex items-center gap-1 px-2 py-1 rounded text-xs cursor-pointer hover:opacity-80 ${textMuted}`}>
              <Copy size={13} />复制
            </button>
          )}
          <div className="flex-1" />
          <button onClick={() => onVote(1)}
            className={`p-1 rounded cursor-pointer hover:opacity-80 ${item.my_vote === 1 ? 'text-blue-400' : textMuted}`}
            title="赞">
            <ThumbsUp size={13} />
          </button>
          <button onClick={() => onVote(-1)}
            className={`p-1 rounded cursor-pointer hover:opacity-80 ${item.my_vote === -1 ? 'text-red-400' : textMuted}`}
            title="踩">
            <ThumbsDown size={13} />
          </button>
        </div>
      )}
    </div>
  );
}

function PreviewModal({ item, theme, onClose }: {
  item: ToolMarketItem; theme: 'dark' | 'light'; onClose: () => void;
}) {
  const { data: userDetail } = useQuery({
    queryKey: userToolKeys.detail(item.id),
    queryFn: () => userToolsApi.get(item.id),
    enabled: !!item.id && item.kind === 'user',
  });
  const { data: officialDetail } = useQuery({
    queryKey: toolKeys.detail(item.id),
    queryFn: () => toolsApi.get(item.id),
    enabled: !!item.id && item.kind === 'official',
  });
  const d = item.kind === 'user' ? userDetail : officialDetail;
  const overlay = '';
  const panel = theme === 'dark' ? 'bg-[#18181b] border-[#27272a] text-[#fafafa]' : 'bg-white border-slate-200';
  const textMuted = theme === 'dark' ? 'text-[#a1a1aa]' : 'text-slate-500';
  const chip = theme === 'dark' ? 'bg-[#27272a]' : 'bg-slate-100';

  const ep = (d?.endpoint ?? {}) as Record<string, unknown>;
  const typeLabel: Record<string, string> = { string: '文本', number: '数字', boolean: '布尔' };
  const renderParams = (schema: Record<string, unknown> | undefined) => {
    const props = ((schema as { properties?: Record<string, { type?: string; description?: string }> })?.properties ?? {});
    const keys = Object.keys(props);
    if (!keys.length) return <div className={`text-xs ${textMuted}`}>无</div>;
    return (
      <div className="space-y-1">
        {keys.map((key) => (
          <div key={key} className="flex items-start gap-2 text-xs">
            <code className={`px-1.5 py-0.5 rounded shrink-0 ${chip}`}>{key}</code>
            <span className={textMuted}>{typeLabel[props[key].type ?? 'string'] ?? props[key].type}</span>
            {props[key].description && <span className="flex-1 min-w-0">{props[key].description}</span>}
          </div>
        ))}
      </div>
    );
  };

  return (
    <div className={`fixed inset-0 z-50 flex items-center justify-center p-6 ${overlay}`} onClick={onClose}>
      <div className={`w-full max-w-2xl max-h-[80vh] flex flex-col rounded-2xl border overflow-hidden ${panel}`}
        onClick={(e) => e.stopPropagation()}>
        {/* 头部固定：滚动时标题与关闭按钮始终可见 */}
        <div className={`flex items-start justify-between shrink-0 px-6 pt-6 pb-3 border-b ${
          theme === 'dark' ? 'border-[#27272a]' : 'border-slate-200'
        }`}>
          <div>
            <h3 className="text-base font-bold">{item.name}</h3>
            <p className={`text-xs ${textMuted}`}>{item.author_name} · {SOURCE_META[item.source]?.label ?? item.source}</p>
          </div>
          <button onClick={onClose} className={`cursor-pointer hover:opacity-70 ${textMuted}`}>✕</button>
        </div>
        {/* 内容区滚动 */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        <p className="text-sm">{item.description || '暂无描述'}</p>

        {item.source === 'openapi' && (
          <div className={`flex items-center gap-2 text-xs px-3 py-2 rounded-lg ${chip} font-mono`}>
            <span className="text-blue-400 font-bold">{(ep.method as string) ?? 'GET'}</span>
            <span className="truncate">{(ep.url as string) ?? '—'}</span>
          </div>
        )}
        {item.source === 'code' && (
          <pre className={`text-xs p-3 rounded-lg overflow-x-auto ${
            theme === 'dark' ? 'bg-[#0c0c0e]' : 'bg-slate-50'
          }`}>{d?.code || '—'}</pre>
        )}
        {(ep.response_notes as string) && (
          <div className="space-y-1.5">
            <div className={`text-xs font-semibold ${textMuted}`}>返回格式</div>
            <pre className={`text-xs p-3 rounded-lg overflow-x-auto ${
              theme === 'dark' ? 'bg-[#0c0c0e]' : 'bg-slate-50'
            }`}>{ep.response_notes as string}</pre>
          </div>
        )}
        <div className="space-y-1.5">
          <div className={`text-xs font-semibold ${textMuted}`}>运行参数（调用时由 AI 填写）</div>
          {renderParams(d?.llm_args_schema)}
        </div>
        <div className="space-y-1.5">
          <div className={`text-xs font-semibold ${textMuted}`}>凭证参数（admin 配置，加密存储）</div>
          {renderParams(d?.user_args_schema)}
        </div>
        </div>
      </div>
    </div>
  );
}


/* ══════════════ 开关 / 凭证配置弹窗 ══════════════ */

/** 紧凑启停开关 */
function ToolToggle({ enabled, onChange }: { enabled: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!enabled)}
      title={enabled ? '点击停用（停用后 Agent/工作流不可用）' : '点击开启（校验定义与凭证完整性）'}
      className={`relative rounded-full transition cursor-pointer shrink-0 border ${
        enabled ? 'bg-emerald-600 border-emerald-500' : 'bg-[#27272a] border-[#3f3f46]'
      }`}
      style={{ width: '2rem', height: '1.1rem' }}
    >
      <span
        className={`absolute top-1/2 -translate-y-1/2 w-3 h-3 rounded-full bg-white transition-all ${
          enabled ? 'left-[calc(100%-0.85rem)]' : 'left-0.5'
        }`}
      />
    </button>
  );
}

/**
 * 工具级统一凭证配置（admin）——按工具 user_args_schema 渲染，
 * sensitive 后端加密存储，全使用点（Agent/工作流）共用。
 * 支持 uto_ 组织库工具与 tool_ 官方工具。
 */
function OrgArgsModal({ toolId, fallbackName, theme, onClose }: {
  toolId: string;
  fallbackName: string;
  theme: 'dark' | 'light';
  onClose: () => void;
}) {
  const qc = useQueryClient();
  const isUserTool = toolId.startsWith('uto_');
  const { data: userDetail } = useQuery({
    queryKey: userToolKeys.detail(toolId),
    queryFn: () => userToolsApi.get(toolId),
    enabled: isUserTool,
  });
  const { data: officialDetail } = useQuery({
    queryKey: toolKeys.detail(toolId),
    queryFn: () => toolsApi.get(toolId),
    enabled: !isUserTool,
  });
  const d = isUserTool ? userDetail : officialDetail;

  const dark = theme === 'dark';
  const props = (((d?.user_args_schema ?? {}) as Record<string, unknown>).properties ?? {}) as Record<
    string, { type?: string; description?: string; sensitive?: boolean }
  >;
  const propKeys = Object.keys(props);
  const savedArgs = ((d?.org_user_args ?? {}) as Record<string, unknown>);

  const [args, setArgs] = useState<Record<string, unknown>>({});

  // 回显已保存凭证：非敏感字段回明文；敏感字段不回显（后端只有密文），
  // 留空 + placeholder 标注「已配置」，输入新值才覆盖，空值不提交（后端保留旧值）
  useEffect(() => {
    if (!d) return;
    const init: Record<string, unknown> = {};
    for (const key of propKeys) {
      const saved = savedArgs[key];
      if (!props[key]?.sensitive && typeof saved === 'string' && saved) init[key] = saved;
    }
    setArgs(init);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [toolId, d !== undefined]);

  const saveM = useMutation({
    mutationFn: () => {
      const payload: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(args)) {
        // 空值不提交——后端按「缺失保留旧值」合并，避免清掉已配置的凭证
        if (String(v ?? '').trim() !== '') payload[k] = v;
      }
      return isUserTool
        ? userToolsApi.saveOrgArgs(toolId, payload)
        : toolsApi.saveOrgArgs(toolId, payload);
    },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: userToolKeys.all });
      void qc.invalidateQueries({ queryKey: toolKeys.all });
      toast.success('凭证已保存');
      onClose();
    },
    onError: (e) => toast.error(getErrorMessage(e, '保存失败')),
  });

  const inputCls = `w-full px-2 py-1 rounded text-xs font-mono border outline-none ${
    dark
      ? 'bg-[#121214] border-[#27272a] text-white placeholder:text-[#52525b] focus:border-blue-600'
      : 'bg-white border-slate-200 text-slate-900 placeholder:text-slate-400 focus:border-blue-500'
  }`;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-6" onClick={onClose}>
      <div className={`w-full max-w-md max-h-[85vh] flex flex-col rounded-2xl border overflow-hidden shadow-2xl ${
          dark ? 'border-[#27272a] bg-[#18181b] text-[#fafafa]' : 'border-slate-200 bg-white text-slate-900'
        }`}
        onClick={(e) => e.stopPropagation()}>
        {/* 头部固定：滚动时标题与关闭按钮始终可见 */}
        <div className={`flex items-start justify-between shrink-0 px-5 pt-5 pb-3 border-b ${
          dark ? 'border-[#27272a]' : 'border-slate-200'
        }`}>
          <div>
            <h3 className="text-sm font-bold">工具凭证 · {d?.name ?? fallbackName}</h3>
            <p className={`text-[11px] mt-0.5 ${dark ? 'text-[#71717a]' : 'text-slate-500'}`}>
              工具级统一配置——Agent 绑定与工作流直调共用；敏感值加密存储。
            </p>
          </div>
          <button onClick={onClose} className={`cursor-pointer hover:opacity-70 ${dark ? 'text-[#a1a1aa]' : 'text-slate-400'}`}>✕</button>
        </div>

        {/* 内容区滚动 */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
        {!d ? (
          <div className={`py-6 text-center text-xs ${dark ? 'text-[#71717a]' : 'text-slate-400'}`}>加载参数定义…</div>
        ) : propKeys.length === 0 ? (
          <p className={`text-xs ${dark ? 'text-[#52525b]' : 'text-slate-400'}`}>
            该工具无需凭证，可直接开启使用。
          </p>
        ) : (
          <div className="space-y-2">
            {propKeys.map((key) => {
              const prop = props[key];
              const configured = savedArgs[key] != null && String(savedArgs[key]) !== '';
              return (
                <div key={key} className="flex items-center gap-2">
                  <label className={`w-28 shrink-0 text-[11px] truncate ${dark ? 'text-[#a1a1aa]' : 'text-slate-500'}`} title={key}>
                    {key}{prop.sensitive ? ' 🔒' : ''}
                  </label>
                  <input
                    type={prop.sensitive ? 'password' : 'text'}
                    value={args[key] == null ? '' : String(args[key])}
                    placeholder={
                      prop.sensitive && configured
                        ? '已配置（输入新值可更换）'
                        : prop.description ?? ''
                    }
                    onChange={(e) => setArgs((prev) => {
                      const next = { ...prev };
                      if (e.target.value === '') delete next[key];
                      else next[key] = e.target.value;
                      return next;
                    })}
                    className={`flex-1 ${inputCls}`}
                  />
                  {prop.sensitive && configured && (
                    <span className={`text-[10px] shrink-0 ${dark ? 'text-emerald-500/80' : 'text-emerald-600'}`}>已配置</span>
                  )}
                </div>
              );
            })}
          </div>
        )}
        </div>

        {/* 底部按钮固定 */}
        <div className={`flex justify-end gap-2 shrink-0 px-5 py-4 border-t ${
          dark ? 'border-[#27272a]' : 'border-slate-200'
        }`}>
          <button onClick={onClose}
            className={`px-3 py-1.5 rounded-lg text-sm cursor-pointer ${dark ? 'text-[#a1a1aa] hover:text-white' : 'text-slate-500 hover:text-slate-900'}`}>
            取消
          </button>
          <button onClick={() => saveM.mutate()} disabled={!d || saveM.isPending}
            className="px-4 py-1.5 rounded-lg text-sm bg-blue-600 hover:bg-blue-500 text-white cursor-pointer disabled:opacity-50">
            {saveM.isPending ? '保存中…' : '保存凭证'}
          </button>
        </div>
      </div>
    </div>
  );
}


/* ══════════════ 创建 / 编辑表单（结构化，不暴露 JSON） ══════════════ */

/** 参数行（code 模式的运行/凭证参数）——底层转 JSON Schema */
interface ParamField {
  key: string;
  type: 'string' | 'number' | 'boolean';
  description: string;
  /** 运行参数：调用时必填 */
  required: boolean;
  /** 凭证参数：值加密存储 */
  sensitive: boolean;
}

const PARAM_KEY_RE = /^[A-Za-z_][A-Za-z0-9_]*$/;

function schemaToFields(schema?: Record<string, unknown>): ParamField[] {
  const props = (schema?.properties ?? {}) as Record<string, Record<string, unknown>>;
  const required = new Set(((schema?.required as string[]) ?? []));
  return Object.entries(props).map(([key, p]) => ({
    key,
    type: ((p.type as string) in { string: 1, number: 1, boolean: 1 } ? p.type : 'string') as ParamField['type'],
    description: (p.description as string) ?? '',
    required: required.has(key),
    sensitive: !!p.sensitive,
  }));
}

function fieldsToSchema(fields: ParamField[], mode: 'llm' | 'user'): Record<string, unknown> {
  const props: Record<string, unknown> = {};
  const required: string[] = [];
  for (const f of fields) {
    if (!f.key.trim()) continue;
    const prop: Record<string, unknown> = { type: f.type, description: f.description };
    if (mode === 'user' && f.sensitive) prop.sensitive = true;
    props[f.key.trim()] = prop;
    if (f.required) required.push(f.key.trim());
  }
  if (!Object.keys(props).length) return {};
  return { type: 'object', properties: props, required };
}

// 代码编辑区统一字体度量——textarea 与高亮回显层必须逐像素一致才不会错位
const CODE_FONT = 'font-mono text-[12.5px] leading-[1.55] tracking-normal';

/** 代码编辑器：透明文字 textarea 叠 highlight.js 高亮回显层（GitHub Dark，
 * 与页面主题无关——代码区固定深色是编辑器惯例）。Tab 插入缩进；
 * 右上角可放大为中窗口编辑（Esc / 再点恢复）。 */
function CodeEditor({ value, onChange, placeholder }: {
  value: string; onChange: (v: string) => void; placeholder: string;
}) {
  const taRef = useRef<HTMLTextAreaElement>(null);
  const preRef = useRef<HTMLPreElement>(null);
  const [focused, setFocused] = useState(false);
  const [expanded, setExpanded] = useState(false);

  const highlighted = useMemo(() => {
    try {
      return hljs.highlight(value, { language: 'python', ignoreIllegals: true }).value;
    } catch {
      return '';
    }
  }, [value]);

  const editorBody = (
    <>
      {/* 放大 / 恢复 */}
      <button onClick={() => setExpanded(!expanded)}
        title={expanded ? '恢复编辑区（Esc）' : '放大编辑'}
        className="absolute top-1.5 right-1.5 z-20 p-1 rounded text-[#8b949e] hover:text-white hover:bg-[#30363d] cursor-pointer">
        {expanded ? <Minimize2 size={13} /> : <Maximize2 size={13} />}
      </button>
      {/* 高亮回显层（不响应鼠标，仅渲染） */}
      <pre ref={preRef} aria-hidden
        className={`absolute inset-0 m-0 p-3 overflow-auto pointer-events-none whitespace-pre-wrap break-words text-[#c9d1d9] ${CODE_FONT}`}>
        <code className="hljs language-python" dangerouslySetInnerHTML={{ __html: highlighted || '&nbsp;' }} />
      </pre>
      {/* 输入层：文字透明只留光标 */}
      <textarea ref={taRef} value={value} onChange={(e) => onChange(e.target.value)}
        onFocus={() => setFocused(true)} onBlur={() => setFocused(false)}
        onScroll={() => { if (preRef.current && taRef.current) preRef.current.scrollTop = taRef.current.scrollTop; }}
        onKeyDown={(e) => {
          if (e.key === 'Escape' && expanded) {
            e.preventDefault();
            setExpanded(false);
            return;
          }
          if (e.key !== 'Tab') return;
          e.preventDefault();
          const ta = e.currentTarget;
          const { selectionStart: s, selectionEnd: en } = ta;
          const next = value.slice(0, s) + '    ' + value.slice(en);
          onChange(next);
          requestAnimationFrame(() => ta.setSelectionRange(s + 4, s + 4));
        }}
        spellCheck={false}
        placeholder={placeholder}
        className={`code-editor-input relative z-10 w-full p-3 bg-transparent text-transparent caret-white outline-none whitespace-pre-wrap break-words placeholder:text-[#484f58] ${
          expanded ? 'flex-1 min-h-0' : 'min-h-[150px] resize-y'
        } ${CODE_FONT}`} />
    </>
  );

  if (expanded) {
    // 放大态：居中大窗口（约 2/3 视口），不是全屏
    return (
      <div className="fixed inset-0 z-[60] flex items-center justify-center">
        <div className="relative flex flex-col w-[62vw] max-w-[860px] h-[62vh] rounded-xl border border-[#30363d] bg-[#0d1117] overflow-hidden shadow-2xl">
          {editorBody}
        </div>
      </div>
    );
  }
  return (
    <div className={`relative rounded-lg border overflow-hidden bg-[#0d1117] transition-colors ${
      focused ? 'border-blue-600' : 'border-[#30363d]'
    }`}>
      {editorBody}
    </div>
  );
}

/** 示例：天气查询（同一需求两种实现，一键填完全部四步表单） **/

// code 版——run 入口 + USER_ 凭证环境变量 + 返回 dict（自动 JSON 化）
const CODE_EXAMPLE = `import os
import requests


def run(city: str, unit: str = "celsius") -> dict:
    """查询城市天气。city / unit 与「运行参数」一一对应。"""
    resp = requests.get(
        "https://api.example.com/v1/weather",
        params={"city": city, "unit": unit},
        headers={"Authorization": "Bearer " + os.environ["USER_api_key"]},  # 凭证参数 api_key（敏感）
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()["data"]
    return {"city": city, "temperature": data["temperature"], "unit": unit}
`;

// openapi 版——URL + 参数表（位置定发送；凭证行由管理员配置）
const OPENAPI_EXAMPLE = {
  method: 'GET',
  url: 'https://api.example.com/v1/weather',
  params: [
    { name: 'city', in: 'query', description: '城市名，如 Beijing', required: true, credential: false },
    { name: 'unit', in: 'query', description: '温度单位：celsius（默认）或 fahrenheit', required: false, credential: false },
    { name: 'Authorization', in: 'header', description: '认证，格式 Bearer <API Key>', required: true, credential: true },
  ] as ApiParam[],
};
const OPENAPI_EXAMPLE_OUTPUT: OutputField[] = [
  { name: 'status', type: 'string', description: '处理状态：success / failed', is_list: false },
  { name: 'city', type: 'string', description: '城市名', is_list: false },
  { name: 'temperature', type: 'number', description: '温度值', is_list: false },
];

/** 代码格式说明（可展开）——入口函数 / 凭证读取 / 返回值 / 依赖 */
function CodeHelpPanel({ onInsertExample, dark }: {
  onInsertExample: () => void; dark: boolean;
}) {
  const [open, setOpen] = useState(false);
  const item = `flex gap-2 ${dark ? 'text-[#a1a1aa]' : 'text-slate-600'}`;
  return (
    <div className={`rounded-lg border text-[11px] leading-relaxed ${
      dark ? 'border-[#27272a] bg-[#121214]/60' : 'border-slate-200 bg-slate-50/70'
    }`}>
      <button onClick={() => setOpen(!open)}
        className={`flex w-full items-center gap-1 px-2.5 py-1.5 cursor-pointer font-semibold ${
          dark ? 'text-[#d4d4d8] hover:text-white' : 'text-slate-700 hover:text-slate-900'
        }`}>
        <ChevronDown size={12} className={`transition-transform ${open ? 'rotate-180' : ''}`} />
        代码怎么写？查看格式要求与可用依赖
      </button>
      {open && (
        <div className={`px-3 pb-3 pt-0.5 space-y-1.5 border-t ${dark ? 'border-[#27272a]' : 'border-slate-200'}`}>
          <div className={item}><span className="text-blue-400 shrink-0">入口</span>
            定义 <code className="font-mono text-blue-300">def run(...)</code>，参数名与「③ 运行参数」一致，调用时按名传入。</div>
          <div className={item}><span className="text-amber-400 shrink-0">凭证</span>
            「④ 凭证参数」通过环境变量读取：token → <code className="font-mono text-amber-300">os.environ["USER_token"]</code>。敏感值加密存储，管理员统一配置。</div>
          <div className={item}><span className="text-emerald-500 shrink-0">返回</span>
            return 字符串或 dict / list（自动转 JSON）；抛出异常时错误信息会返回给 AI 便于重试。</div>
          <div className={item}><span className="text-purple-400 shrink-0">依赖</span>
            可使用 Python 标准库和一些常用库（如 requests、httpx、pandas、numpy 等）；部分依赖可能被禁止安装，保存时会有提示。</div>
          <button onClick={onInsertExample}
            className="flex items-center gap-1.5 mt-1 px-2 py-1 rounded text-[11px] text-blue-400 hover:text-blue-300 hover:bg-blue-500/10 cursor-pointer">
            <Wand2 size={12} />填入完整示例（天气查询）
          </button>
        </div>
      )}
    </div>
  );
}

/** openapi 参数表行：参数名 | 位置 | 说明 | 凭证 | 必填 —— 主流 HTTP 工具模型，
 * 参数声明一次，位置决定发送到哪；凭证行的值由管理员配置（加密）。 */
interface ApiParam {
  name: string;
  in: 'query' | 'header' | 'path' | 'body';
  description: string;
  required: boolean;
  credential: boolean;
}

const PARAM_POS_LABEL: Record<ApiParam['in'], string> = {
  query: 'Query', header: '请求头', path: '路径', body: 'Body',
};

function ParamsTableEditor({ rows, onChange, inputCls, selectCls }: {
  rows: ApiParam[]; onChange: (rows: ApiParam[]) => void;
  inputCls: string; selectCls: string;
}) {
  const update = (i: number, patch: Partial<ApiParam>) =>
    onChange(rows.map((r, idx) => (idx === i ? { ...r, ...patch } : r)));
  return (
    <div className="space-y-1.5">
      <div className="grid grid-cols-[1fr_84px_1.5fr_54px_54px_28px] gap-1.5 text-[10px] text-[#71717a] px-0.5">
        <span>参数名</span><span>位置</span><span>说明（给使用者/AI 看）</span>
        <span className="text-center">凭证</span><span className="text-center">必填</span><span />
      </div>
      {rows.map((r, i) => (
        <div key={i} className="grid grid-cols-[1fr_84px_1.5fr_54px_54px_28px] gap-1.5 items-center">
          <input value={r.name} onChange={(e) => update(i, { name: e.target.value })}
            placeholder={r.in === 'header' ? 'Authorization' : 'city'}
            className={`w-full font-mono ${inputCls}`} />
          <select value={r.in} onChange={(e) => update(i, { in: e.target.value as ApiParam['in'] })}
            className={`w-full cursor-pointer ${selectCls}`}>
            {(Object.keys(PARAM_POS_LABEL) as ApiParam['in'][]).map((pos) => (
              <option key={pos} value={pos}>{PARAM_POS_LABEL[pos]}</option>
            ))}
          </select>
          <input value={r.description} onChange={(e) => update(i, { description: e.target.value })}
            placeholder={r.credential ? '认证 Key，管理员配置' : '城市名，如 Beijing'}
            className={`w-full ${inputCls}`} />
          <label className="flex items-center justify-center cursor-pointer" title="凭证：值由管理员统一配置（加密存储），调用时自动带上">
            <input type="checkbox" checked={r.credential} onChange={(e) => update(i, { credential: e.target.checked })}
              className="w-3.5 h-3.5 accent-amber-500 cursor-pointer" />
          </label>
          <label className="flex items-center justify-center cursor-pointer" title={r.credential ? '凭证必须配置后才能开启工具' : '调用时该参数必须提供'}>
            <input type="checkbox" checked={r.required} disabled={r.credential}
              onChange={(e) => update(i, { required: e.target.checked })}
              className="w-3.5 h-3.5 accent-blue-600 cursor-pointer disabled:opacity-30" />
          </label>
          <button onClick={() => onChange(rows.filter((_, idx) => idx !== i))}
            className="p-1 rounded text-red-400/70 hover:text-red-400 cursor-pointer justify-self-center" title="删除此参数">
            <Trash2 size={13} />
          </button>
        </div>
      ))}
      <button onClick={() => onChange([...rows, { name: '', in: 'query', description: '', required: false, credential: false }])}
        className="flex items-center gap-1 px-2 py-1 rounded text-xs text-blue-400 hover:text-blue-300 cursor-pointer">
        <Plus size={13} />添加参数
      </button>
    </div>
  );
}

/** 返回结构声明（与 agent response_schema 同构）——下游 {{node.result.字段}} 直接调用 */
interface OutputField {
  name: string;
  type: 'string' | 'number' | 'boolean' | 'object';
  description: string;
  is_list?: boolean;
  fields?: OutputField[];
}

/** 返回结构编辑器（递归树）：字段名/类型/列表/说明；对象类型可声明子字段 */
function OutputFieldsTree({ fields, onChange, inputCls, selectCls, depth = 0 }: {
  fields: OutputField[];
  onChange: (fields: OutputField[]) => void;
  inputCls: string;
  selectCls: string;
  depth?: number;
}) {
  const update = (i: number, patch: Partial<OutputField>) =>
    onChange(fields.map((f, idx) => (idx === i ? { ...f, ...patch } : f)));
  const row = (f: OutputField, i: number) => (
    <div key={i} className="space-y-1">
      <div className="grid grid-cols-[1fr_84px_44px_1.3fr_28px] gap-1.5 items-center">
        <input value={f.name} onChange={(e) => update(i, { name: e.target.value })}
          placeholder="status" className={`w-full font-mono ${inputCls}`} />
        <select value={f.type} onChange={(e) => {
          const type = e.target.value as OutputField['type'];
          update(i, { type, fields: type === 'object' ? (f.fields ?? [{ name: '', type: 'string', description: '' }]) : undefined });
        }}
          className={`w-full cursor-pointer ${selectCls}`}>
          <option value="string">文本</option>
          <option value="number">数字</option>
          <option value="boolean">布尔</option>
          <option value="object">对象</option>
        </select>
        <label className="flex items-center justify-center cursor-pointer" title="列表（下游 .0 下标取值）">
          <input type="checkbox" checked={!!f.is_list} onChange={(e) => update(i, { is_list: e.target.checked })}
            className="w-3.5 h-3.5 accent-blue-600 cursor-pointer" />
        </label>
        <input value={f.description} onChange={(e) => update(i, { description: e.target.value })}
          placeholder="处理状态，success / failed" className={`w-full ${inputCls}`} />
        <button onClick={() => onChange(fields.filter((_, idx) => idx !== i))}
          className="p-1 rounded text-red-400/70 hover:text-red-400 cursor-pointer justify-self-center" title="删除此字段">
          <Trash2 size={13} />
        </button>
      </div>
      {f.type === 'object' && (
        <div className="ml-5 pl-3 border-l border-[#27272a] space-y-1.5">
          <OutputFieldsTree fields={f.fields ?? []}
            onChange={(next) => update(i, { fields: next })}
            inputCls={inputCls} selectCls={selectCls} depth={depth + 1} />
        </div>
      )}
    </div>
  );
  return (
    <div className="space-y-1.5">
      {depth === 0 && fields.length > 0 && (
        <div className="grid grid-cols-[1fr_84px_44px_1.3fr_28px] gap-1.5 text-[10px] text-[#71717a] px-0.5">
          <span>字段名</span><span>类型</span><span className="text-center">列表</span><span>说明（调用方可见）</span><span />
        </div>
      )}
      {fields.map(row)}
      <button onClick={() => onChange([...fields, { name: '', type: 'string', description: '', is_list: false }])}
        className={`flex items-center gap-1 px-2 py-1 rounded text-xs text-blue-400 hover:text-blue-300 cursor-pointer ${depth > 0 ? 'pl-0' : ''}`}>
        <Plus size={13} />{depth > 0 ? '添加子字段' : '添加返回字段'}
      </button>
    </div>
  );
}

/** 参数列表编辑器（运行参数 / 凭证参数）——自动生成 JSON Schema */
function ParamListEditor({ fields, onChange, mode, inputCls, selectCls }: {  fields: ParamField[]; onChange: (fields: ParamField[]) => void;
  mode: 'llm' | 'user'; inputCls: string; selectCls: string;
}) {
  const update = (i: number, patch: Partial<ParamField>) =>
    onChange(fields.map((f, idx) => (idx === i ? { ...f, ...patch } : f)));
  const label = mode === 'llm' ? '必填' : '敏感';
  const labelTitle = mode === 'llm'
    ? '调用时该参数必须提供'
    : '值会加密存储（admin 在工具上统一配置）';
  return (
    <div className="space-y-1.5">
      <div className="grid grid-cols-[1fr_84px_1.4fr_52px_28px] gap-1.5 text-[10px] text-[#71717a] px-0.5">
        <span>参数名</span><span>类型</span><span>说明（给使用者/AI 看）</span><span className="text-center">{label}</span><span />
      </div>
      {fields.map((f, i) => (
        <div key={i} className="grid grid-cols-[1fr_84px_1.4fr_52px_28px] gap-1.5 items-center">
          <input value={f.key} onChange={(e) => update(i, { key: e.target.value })}
            placeholder={mode === 'llm' ? 'city' : 'token'}
            className={`w-full ${inputCls}`} />
          <select value={f.type} onChange={(e) => update(i, { type: e.target.value as ParamField['type'] })}
            className={`w-full cursor-pointer ${selectCls}`}>
            <option value="string">文本</option>
            <option value="number">数字</option>
            <option value="boolean">布尔</option>
          </select>
          <input value={f.description} onChange={(e) => update(i, { description: e.target.value })}
            placeholder={mode === 'llm' ? '要查询的城市名，如 Beijing' : '服务端签发的 API Key'}
            className={`w-full ${inputCls}`} />
          <label className="flex items-center justify-center cursor-pointer" title={labelTitle}>
            <input type="checkbox" checked={mode === 'llm' ? f.required : f.sensitive}
              onChange={(e) => update(i, mode === 'llm' ? { required: e.target.checked } : { sensitive: e.target.checked })}
              className="w-3.5 h-3.5 accent-blue-600 cursor-pointer" />
          </label>
          <button onClick={() => onChange(fields.filter((_, idx) => idx !== i))}
            className="p-1 rounded text-red-400/70 hover:text-red-400 cursor-pointer justify-self-center" title="删除此参数">
            <Trash2 size={13} />
          </button>
        </div>
      ))}
      <button onClick={() => onChange([...fields, { key: '', type: 'string', description: '', required: false, sensitive: false }])}
        className="flex items-center gap-1 px-2 py-1 rounded text-xs text-blue-400 hover:text-blue-300 cursor-pointer">
        <Plus size={13} />添加参数
      </button>
    </div>
  );
}

/** 分区标题（步骤式引导） */
function FormSection({ step, title, hint, dark, children }: {
  step: string; title: string; hint?: string; dark: boolean; children: ReactNode;
}) {
  return (
    <div className={`rounded-xl border p-4 space-y-3 ${
      dark ? 'border-[#27272a] bg-[#121214]/60' : 'border-slate-200 bg-slate-50/60'
    }`}>
      <div className="space-y-0.5">
        <div className="flex items-center gap-2">
          <span className="w-5 h-5 rounded-full bg-blue-600/20 text-blue-500 text-[11px] font-bold flex items-center justify-center shrink-0">{step}</span>
          <span className={`text-sm font-bold ${dark ? 'text-white' : 'text-slate-900'}`}>{title}</span>
        </div>
        {hint && <p className={`text-[11px] leading-relaxed pl-7 ${dark ? 'text-[#71717a]' : 'text-slate-500'}`}>{hint}</p>}
      </div>
      {children}
    </div>
  );
}

function ToolEditModal({ theme, initial, onClose, onSaved }: {
  theme: 'dark' | 'light';
  initial?: UserToolDetail;
  onClose: () => void;
  onSaved: () => void;
}) {
  const isEdit = !!initial;

  // ── ① 基本信息 ──
  const [name, setName] = useState(initial?.name ?? '');
  const [description, setDescription] = useState(initial?.description ?? '');
  const [source, setSource] = useState(initial?.source ?? 'openapi');

  // ── ② 调用方式 ──
  const ep = (initial?.endpoint ?? {}) as Record<string, unknown>;
  const [method, setMethod] = useState((ep.method as string) ?? 'GET');
  const [url, setUrl] = useState((ep.url as string) ?? '');
  const [apiParams, setApiParams] = useState<ApiParam[]>(
    (Array.isArray(ep.params) ? ep.params : []) as ApiParam[],
  );
  const [code, setCode] = useState(initial?.code ?? '');
  // 返回字段声明（output_schema：{type:'object', fields:[{name,type,is_list,description}]}）
  // ——给下游工作流精确引用 {{node.result.字段}}；与 agent response_schema 同构
  const initOutSchema = (initial?.output_schema ?? {}) as { type?: string; fields?: OutputField[] };
  const [outputFields, setOutputFields] = useState<OutputField[]>(
    Array.isArray(initOutSchema.fields) ? initOutSchema.fields : [],
  );

  // ── ③/④ 参数 ──
  const [llmFields, setLlmFields] = useState<ParamField[]>(schemaToFields(initial?.llm_args_schema));
  const [userFields, setUserFields] = useState<ParamField[]>(schemaToFields(initial?.user_args_schema));

  const [busy, setBusy] = useState(false);

  /** 一键填入「天气查询」完整示例（基本信息 + 调用方式 + 运行参数 + 凭证参数） */
  const applyExample = () => {
    setName('weather-query');
    setDescription('查询指定城市的实时天气');
    setOutputFields(OPENAPI_EXAMPLE_OUTPUT.map((f) => ({ ...f })));
    setLlmFields([
      { key: 'city', type: 'string', description: '城市名，如 Beijing', required: true, sensitive: false },
      { key: 'unit', type: 'string', description: '温度单位：celsius（默认）或 fahrenheit', required: false, sensitive: false },
    ]);
    if (source === 'openapi') {
      setMethod(OPENAPI_EXAMPLE.method);
      setUrl(OPENAPI_EXAMPLE.url);
      setApiParams(OPENAPI_EXAMPLE.params.map((r) => ({ ...r })));
      setCode('');
      setUserFields([]);
      setLlmFields([]);
    } else {
      setCode(CODE_EXAMPLE);
      setUserFields([
        { key: 'api_key', type: 'string', description: '服务端签发的 API Key', required: true, sensitive: true },
      ]);
    }
    toast.success('已填入示例，按需修改');
  };

  const dark = theme === 'dark';
  const inputCls = `w-full px-2 py-1 rounded text-xs border outline-none ${
    dark
      ? 'bg-[#121214] border-[#27272a] text-white placeholder:text-[#52525b] focus:border-blue-600'
      : 'bg-white border-slate-200 text-slate-900 placeholder:text-slate-400 focus:border-blue-500'
  }`;
  const monoInputCls = `${inputCls} font-mono`;
  const selectCls = `${inputCls} cursor-pointer px-1`;
  const chipCls = dark ? 'bg-[#27272a]' : 'bg-slate-100';
  const plainInputCls = dark
    ? 'w-full px-3 py-1.5 rounded-lg text-sm border outline-none bg-[#121214] border-[#27272a] text-white placeholder:text-[#52525b] focus:border-blue-600'
    : 'w-full px-3 py-1.5 rounded-lg text-sm border outline-none bg-white border-slate-200 text-slate-900 placeholder:text-slate-400 focus:border-blue-500';

  const handleSave = async () => {
    if (!name.trim()) { toast.error('请先给工具起个名字'); return; }
    if (source === 'openapi' && !url.trim()) { toast.error('请填写要调用的接口地址（URL）'); return; }
    if (source === 'code' && !code.trim()) { toast.error('请填写工具的 Python 代码'); return; }
    // 参数名校验（openapi 参数表 / code 的③④参数表共用规则）
    const fieldGroups: ReadonlyArray<readonly [string, Array<{ key?: string; name?: string }>]> = source === 'code'
      ? [['运行参数', llmFields], ['凭证参数', userFields]]
      : [['参数表', apiParams.map((r) => ({ key: r.name }))]];
    for (const [label, fields] of fieldGroups) {
      for (const f of fields) {
        if (!String(f.key ?? '').trim()) { toast.error(`${label}里有未命名的参数，请填写参数名或删除该行`); return; }
        if (!PARAM_KEY_RE.test(String(f.key).trim())) {
          toast.error(`${label}「${f.key}」的参数名只能用字母、数字、下划线，且不能以数字开头`);
          return;
        }
      }
    }

    let endpoint: Record<string, unknown> = {};
    if (source === 'openapi') {
      endpoint = {
        method: method.toUpperCase(), url: url.trim(),
        params: apiParams.map((r) => ({
          name: r.name.trim(), in: r.in,
          description: r.description.trim(),
          required: r.credential ? true : r.required,
          credential: r.credential,
        })),
      };
      // 提取响应字段已下线（返回结构声明 + {{node.result.字段}} 直接引用取代）；
      // 存量工具的 response_path / response_notes 透传保留，运行时继续生效
      if (typeof ep.response_path === 'string' && ep.response_path.trim()) {
        endpoint.response_path = ep.response_path.trim();
      }
      if (typeof ep.response_notes === 'string' && ep.response_notes.trim()) {
        endpoint.response_notes = ep.response_notes.trim();
      }
    }

    setBusy(true);
    try {
      const body = {
        name: name.trim(), description: description.trim(), source,
        endpoint,
        code: source === 'code' ? code : '',
        // openapi 的 schema 由后端按②参数表生成；code 按③④参数表定义
        llm_args_schema: source === 'code' ? fieldsToSchema(llmFields, 'llm') : {},
        user_args_schema: source === 'code' ? fieldsToSchema(userFields, 'user') : {},
        output_schema: outputFields.length
          ? { type: 'object', fields: outputFields.map((f) => ({ ...f, name: f.name.trim() })) }
          : {},
      };
      if (isEdit) await userToolsApi.update(initial!.id, body);
      else await userToolsApi.create(body);
      toast.success(isEdit ? '已保存（已过审的工具会回到草稿，需重新送审开启）' : '创建成功');
      onSaved();
    } catch (e) {
      toast.error(getErrorMessage(e, isEdit ? '保存失败' : '创建失败'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-6" onClick={busy ? undefined : onClose}>
      <div className={`w-full max-w-2xl max-h-[85vh] flex flex-col rounded-2xl border overflow-hidden ${
          dark ? 'border-[#27272a] bg-[#18181b] text-[#fafafa]' : 'border-slate-200 bg-white text-slate-900'
        }`}
        onClick={(e) => e.stopPropagation()}>
        {/* 头部固定：滚动时标题与关闭按钮始终可见 */}
        <div className={`flex items-start justify-between shrink-0 px-6 pt-6 pb-3 border-b ${
          dark ? 'border-[#27272a]' : 'border-slate-200'
        }`}>
          <div>
            <h3 className="text-base font-bold">{isEdit ? '编辑工具' : '创建工具'}</h3>
            <p className={`text-[11px] mt-0.5 ${dark ? 'text-[#71717a]' : 'text-slate-500'}`}>
              创建后提交发布，经管理员审查、开启后才能被 Agent 与工作流使用。
            </p>
          </div>
          <button onClick={onClose} className={`cursor-pointer hover:opacity-70 ${dark ? 'text-[#a1a1aa]' : 'text-slate-400'}`}>✕</button>
        </div>

        {/* 内容区滚动 */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">

        {/* ① 基本信息 */}
        <FormSection step="1" title="基本信息" dark={dark}
          hint="给工具起个名字、说清楚它做什么。">
          <div className="grid grid-cols-1 gap-3 pl-7">
            <div className="flex gap-2">
              {(['openapi', 'code'] as const).map((s) => {
                const meta = SOURCE_META[s];
                const desc = s === 'openapi' ? '封装一个 HTTP 接口' : '运行一段 Python 代码';
                return (
                  <button key={s} disabled={isEdit} onClick={() => setSource(s)}
                    className={`flex items-center gap-1.5 px-3 py-2 rounded-lg text-xs border cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed transition ${
                      source === s
                        ? 'bg-blue-600/20 border-blue-600/60 text-blue-500'
                        : dark
                          ? 'border-[#27272a] bg-transparent text-[#a1a1aa] hover:text-white'
                          : 'border-slate-200 bg-transparent text-slate-500 hover:text-slate-900'
                    }`}>
                    <meta.icon size={13} className={meta.cls} />
                    <span className="font-semibold">{meta.label}</span>
                    <span className={`text-[10px] ${dark ? 'text-[#71717a]' : 'text-slate-400'}`}>{desc}</span>
                  </button>
                );
              })}
            </div>
            <label className="space-y-1 block">
              <span className={`text-xs ${dark ? 'text-[#a1a1aa]' : 'text-slate-500'}`}>工具名称（字母数字开头，可含 - _，组织内唯一）</span>
              <input value={name} onChange={(e) => setName(e.target.value)} className={plainInputCls} placeholder="weather-query" />
            </label>
            <label className="space-y-1 block">
              <span className={`text-xs ${dark ? 'text-[#a1a1aa]' : 'text-slate-500'}`}>工具描述</span>
              <input value={description} onChange={(e) => setDescription(e.target.value)} className={plainInputCls} placeholder="查询指定城市的实时天气" />
            </label>
          </div>
        </FormSection>

        {/* ② 调用方式 */}
        {source === 'openapi' ? (
          <FormSection step="2" title="要调用的接口" dark={dark}
            hint="填一个 HTTP 接口 + 参数表。参数写在哪就发到哪（Query / 请求头 / URL 路径 / Body）：调用时 AI 填值，勾「凭证」的由管理员配置真值（加密存储）。">
            <div className="space-y-3 pl-7">
              <div className="flex gap-2">
                <select value={method} onChange={(e) => setMethod(e.target.value)}
                  className={`w-24 py-1.5 font-mono ${selectCls}`}>
                  {['GET', 'POST', 'PUT', 'DELETE'].map((m) => <option key={m} value={m}>{m}</option>)}
                </select>
                <input value={url} onChange={(e) => setUrl(e.target.value)} className={`flex-1 ${monoInputCls}`}
                  placeholder="https://api.example.com/v1/weather（路径参数写 {city}）" />
              </div>
              <button onClick={applyExample}
                className="flex items-center gap-1.5 px-2 py-1 rounded text-[11px] text-blue-400 hover:text-blue-300 hover:bg-blue-500/10 cursor-pointer">
                <Wand2 size={12} />填入完整示例（天气查询）
              </button>

              <div className="space-y-1.5">
                <span className={`text-xs ${dark ? 'text-[#a1a1aa]' : 'text-slate-500'}`}>参数表——写一次，按位置发送</span>
                <ParamsTableEditor rows={apiParams} onChange={setApiParams}
                  inputCls={inputCls} selectCls={selectCls} />
              </div>
              <div className="space-y-1.5">
                <span className={`text-xs ${dark ? 'text-[#a1a1aa]' : 'text-slate-500'}`}>返回结构（可选）——声明后下游节点可直接调用 {'{{node.result.字段}}'}（对象类型可声明子字段）</span>
                <OutputFieldsTree fields={outputFields} onChange={setOutputFields}
                  inputCls={inputCls} selectCls={selectCls} />
              </div>
            </div>
          </FormSection>
        ) : (
          <FormSection step="2" title="Python 代码" dark={dark}
            hint="在隔离环境中安全运行。定义一个 run 函数（入参即「③ 运行参数」），返回字符串或可 JSON 化的结果。">
            <div className="space-y-2 pl-7">
              <CodeHelpPanel dark={dark} onInsertExample={applyExample} />
              <CodeEditor value={code} onChange={setCode}
                placeholder={'import math\n\ndef run(radius: str) -> str:\n    """计算圆的面积"""\n    return str(math.pi * float(radius) ** 2)'} />
              <div className="space-y-1.5">
                <span className={`text-xs ${dark ? 'text-[#a1a1aa]' : 'text-slate-500'}`}>返回结构（可选）——声明后下游节点可直接调用 {'{{node.result.字段}}'}（对象类型可声明子字段）</span>
                <OutputFieldsTree fields={outputFields} onChange={setOutputFields}
                  inputCls={inputCls} selectCls={selectCls} />
              </div>
            </div>
          </FormSection>
        )}

        {/* ③ 运行参数——仅 code 模式（openapi 的参数在②参数表里） */}
        {source === 'code' && (
          <FormSection step="3" title="运行参数" dark={dark}
            hint="每次调用时动态变化的信息（如城市名、搜索词），由 AI 或工作流节点在调用时填写。">
            <div className="pl-7">
              <ParamListEditor fields={llmFields} onChange={setLlmFields} mode="llm"
                inputCls={inputCls} selectCls={selectCls} />
            </div>
          </FormSection>
        )}

        {/* ④ 凭证参数——仅 code 模式（openapi 凭证勾在②参数表里） */}
        {source === 'code' && (
          <FormSection step="4" title="凭证参数" dark={dark}
            hint="固定不变的配置或凭证（如 API Key）。发布后由管理员在工具上统一配置（勾选「敏感」的值加密存储），所有使用点共用。代码中通过 USER_ 前缀环境变量读取。">
            <div className="pl-7">
              <ParamListEditor fields={userFields} onChange={setUserFields} mode="user"
                inputCls={inputCls} selectCls={selectCls} />
            </div>
          </FormSection>
        )}
        </div>

        {/* 底部按钮固定 */}
        <div className={`flex justify-end gap-2 shrink-0 px-6 py-4 border-t ${
          dark ? 'border-[#27272a]' : 'border-slate-200'
        }`}>
          <button onClick={onClose} disabled={busy}
            className={`px-3 py-1.5 rounded-lg text-sm cursor-pointer ${dark ? 'text-[#a1a1aa] hover:text-white' : 'text-slate-500 hover:text-slate-900'}`}>取消</button>
          <button onClick={handleSave} disabled={busy}
            className="px-4 py-1.5 rounded-lg text-sm bg-blue-600 hover:bg-blue-500 text-white cursor-pointer disabled:opacity-50">
            {busy ? '保存中…' : isEdit ? '保存' : '创建'}
          </button>
        </div>
      </div>
    </div>
  );
}

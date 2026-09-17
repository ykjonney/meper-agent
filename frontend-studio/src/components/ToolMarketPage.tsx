/** ToolMarketPage — 组织工具库（ToB 治理模型，单页卡片墙）。
 *
 * 治理流程：tool:write 创建 → submit → admin 审查 → admin 配置凭证
 * → admin 开启 →「已开启」的工具才能被 Agent 绑定 / 工作流直调。
 * 对话框组件已拆分至 ./tools/（ToolEditModal / AiGenerateDialog / TestToolDialog）。
 */
import { useEffect, useState } from 'react';
import {
  useQuery, useMutation, useQueryClient,
} from '@tanstack/react-query';
import {
  Wrench, ThumbsUp, ThumbsDown, Trash2, Plus,
  Send, Pencil, Eye, Crown, KeyRound, Sparkles,
} from 'lucide-react';
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
import { ToolEditModal } from './tools/ToolEditModal';
import { AiGenerateDialog } from './tools/AiGenerateDialog';
import { SOURCE_META } from './tools/tool-form-utils';

type Tab = 'library';

const STATUS_LABEL: Record<string, string> = {
  private: '草稿', submitted: '审核中', published: '已过审', hidden: '已隐藏',
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
  /** 开启时缺凭证 → 弹配置框，保存成功后自动重试开启 */
  const [pendingEnable, setPendingEnable] = useState<{ id: string; name: string } | null>(null);
  const pendingEnableRef = pendingEnable
    ? { ...pendingEnable, enabled: true as const }
    : null;
  const [editing, setEditing] = useState<UserToolDetail | null>(null);
  const [creating, setCreating] = useState(false);
  const [genOpen, setGenOpen] = useState(false);
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
      const msg = getErrorMessage(e, v.enabled ? '开启失败' : '停用失败');
      if (v.enabled && msg.includes('凭证')) {
        // 缺凭证：直接弹配置框（保存后自动重试开启），不打错误提示
        setPendingEnable(v);
        setArgsTool({ id: v.id, name: v.name });
        return;
      }
      toast.error(msg);
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
          <div className="ml-auto flex items-center gap-2">
            <button onClick={() => setGenOpen(true)}
              title="描述需求，AI 自动生成工具定义草稿"
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium cursor-pointer transition ${
                theme === 'dark'
                  ? 'border border-blue-500/40 text-blue-400 hover:bg-blue-500/10'
                  : 'border border-blue-300 text-blue-600 hover:bg-blue-50'
              }`}>
              <Sparkles size={14} />AI 生成
            </button>
            <button onClick={() => setCreating(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs bg-blue-600 hover:bg-blue-500 text-white cursor-pointer">
              <Plus size={14} />创建工具
            </button>
          </div>
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
          onClose={() => { setArgsTool(null); setPendingEnable(null); }}
          onSaved={() => {
            const target = pendingEnableRef;
            if (target) {
              setPendingEnable(null);
              enableM.mutate(target); // 凭证配齐——自动续接开启
            }
          }}
        />
      )}
      {genOpen && (
        <AiGenerateDialog
          dark={theme === 'dark'}
          mode="create"
          // save_tool 落库后刷新列表（agent 迭代可多次触发）
          onSavedTool={() => invalidate()}
          onClose={() => setGenOpen(false)}
        />
      )}
      {(creating || editing) && (
        <ToolEditModal
          theme={theme}
          initial={editing ?? undefined}
          // AI 修改经工坊保存（save_tool=update）后刷新列表，不关表单
          onExternalSave={() => invalidate()}
          onClose={() => { setCreating(false); setEditing(null); }}
          onSaved={() => { invalidate(); setCreating(false); setEditing(null); }}
        />
      )}
    </div>
  );
}

function LibraryCard({ item, theme, isAdmin, canCreate, onPreview, onEnable, onConfigArgs, onVote, onEdit, onSubmit, onDelete }: {
  item: ToolMarketItem;
  theme: 'dark' | 'light';
  isAdmin: boolean;
  canCreate: boolean;
  onPreview: () => void;
  onEnable: (v: boolean) => void;
  onConfigArgs: () => void;
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
          {(isOwn || isAdmin) && (
            <div className="flex items-center gap-1 text-xs">
              <button onClick={onPreview}
                className={`flex items-center gap-1 px-2 py-1 rounded cursor-pointer hover:opacity-80 ${textMuted}`}>
                <Eye size={12} />详情
              </button>
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
        /* 草稿：owner 就地管理（提交发布 / 编辑 / 删除）；admin 可编辑/删除（帮忙治理） */
        <div className="flex items-center gap-1 pt-1 border-t border-current/10 text-xs">
          {(isOwn || isAdmin) && (
            <>
              <button onClick={onPreview}
                className={`flex items-center gap-1 px-2 py-1 rounded cursor-pointer hover:opacity-80 ${textMuted}`}>
                <Eye size={12} />详情
              </button>
              {isOwn && (
                <button onClick={onSubmit}
                  className="flex items-center gap-1 px-2 py-1 rounded text-blue-400 hover:text-blue-300 cursor-pointer">
                  <Send size={12} />提交发布
                </button>
              )}
              <button onClick={onEdit}
                className={`flex items-center gap-1 px-2 py-1 rounded cursor-pointer hover:opacity-80 ${textMuted}`}>
                <Pencil size={12} />编辑
              </button>
              <button onClick={onConfigArgs}
                className={`flex items-center gap-1 px-2 py-1 rounded cursor-pointer hover:opacity-80 ${textMuted}`}
                title="配置工具级统一凭证（所有使用点共用）——提交前配好，过审后管理员可直接开启">
                <KeyRound size={12} />凭证
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
          {isAdmin && <ToolToggle enabled={item.enabled} onChange={onEnable} />}
          {(isOfficial ? isAdmin : isOwn || isAdmin) && (
            <button onClick={onConfigArgs}
              className={`flex items-center gap-1 px-2 py-1 rounded text-xs cursor-pointer hover:opacity-80 ${textMuted}`}
              title="配置工具级统一凭证（所有使用点共用）">
              <KeyRound size={13} />凭证
            </button>
          )}
          {(isOwn || isAdmin) && !isOfficial && (
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
  const typeLabel: Record<string, string> = { string: '文本', number: '数字', boolean: '布尔', array: '列表' };
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
function OrgArgsModal({ toolId, fallbackName, theme, onClose, onSaved }: {
  toolId: string;
  fallbackName: string;
  theme: 'dark' | 'light';
  onClose: () => void;
  /** 保存成功后回调（先于 onClose——保存后自动续接开启等动作） */
  onSaved?: () => void;
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
      onSaved?.();
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
    /* 点遮罩不关闭（防误触丢已填配置，与其余 ui Modal 行为一致） */
    <div className="fixed inset-0 z-50 flex items-center justify-center p-6">
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


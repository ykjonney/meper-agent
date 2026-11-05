/**
 * KnowledgeBasePage — 资源库 / 知识库 tab（类型签名卡片网格）。
 *
 * 靛蓝改版（设计稿 resource-hub-page.html pane-kb）：38px 类型徽章（目录树 /
 * 向量点阵 SVG，知识库身份色）+ 名称 + 形态描述行 + 状态 pill（已就绪/索引中/
 * 构建失败）+ 文档统计 + 能力 chips（kb_search / kb_read）+ foot（日期 + 打开/删除）。
 * 顶部工具栏 = 搜索（本地过滤）+「＋ 新建知识库」CTA。
 * 创建弹窗逻辑保留（tree 类型可选编译模型），视觉用语义 token。
 */
import { useState, useMemo, type FormEvent } from 'react';
import { Plus, Search, Loader2 } from 'lucide-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { knowledgeApi, knowledgeKeys, type KnowledgeBase } from '../services/knowledge-api';
import { modelApi } from '../services/model-api';
import { usePermission } from '../hooks/use-permission';
import { confirmDialog } from './ui/confirm';
import { toast } from './ui/toast';
import { getErrorMessage } from '../lib/api-client';
import { ResModal, Field, UInput, TypeCard } from './res-modal';

type KbType = 'tree' | 'vector';

/** 形态描述行（设计稿 vendor-line）：tree=目录树精确检索 / vector=向量语义检索 */
const TYPE_DESC: Record<KbType, string> = {
  tree: '目录树 · 按路径精确检索',
  vector: '向量语义 · 检索 + 重排',
};

/** 状态 pill 映射：last_build_status 宽匹配 → 已就绪/索引中/构建失败/未索引 */
function buildPill(kb: KnowledgeBase): { label: string; tone: 'ok' | 'wait' | 'fail' | 'neutral' } {
  const s = (kb.last_build_status ?? '').toLowerCase();
  if (/fail|error/.test(s)) return { label: '构建失败', tone: 'fail' };
  if (/build|index|running|pending|progress/.test(s)) return { label: '索引中', tone: 'wait' };
  if (/ready|ok|done|success|complete/.test(s)) return { label: '已就绪', tone: 'ok' };
  return { label: '未索引', tone: 'neutral' };
}

/** 类型徽章：目录树（线条）/ 向量（点阵）——知识库身份色 soft 底 + 深色 icon */
function KbBadge({ type }: { type: KbType }) {
  return (
    <div className="w-[38px] h-[38px] rounded-[10px] flex items-center justify-center shrink-0 bg-[#F5E9E2] text-cat-kb">
      {type === 'vector' ? (
        <svg width="20" height="20" viewBox="0 0 20 20" fill="currentColor">
          <circle cx="4" cy="4" r="2" /><circle cx="10" cy="6" r="2" /><circle cx="16" cy="4" r="2" />
          <circle cx="6" cy="11" r="2" /><circle cx="12" cy="13" r="2" /><circle cx="5" cy="17" r="2" />
        </svg>
      ) : (
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6">
          <path d="M7 4h10M7 10h10M7 16h10" strokeLinecap="round" />
          <circle cx="4" cy="4" r="1.5" fill="currentColor" stroke="none" />
          <circle cx="4" cy="10" r="1.5" fill="currentColor" stroke="none" />
          <circle cx="4" cy="16" r="1.5" fill="currentColor" stroke="none" />
        </svg>
      )}
    </div>
  );
}

export function KnowledgeBasePage({
  onOpenKb,
}: {
  onOpenKb: (kb: { id: string; name: string; type: KbType }) => void;
}) {
  const queryClient = useQueryClient();
  // 写权限门控：无 knowledge:write 的用户隐藏创建/删除入口（查看详情不受影响）
  const canWrite = usePermission('knowledge:write');
  const [searchInput, setSearchInput] = useState('');
  const [isCreating, setIsCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const [newDesc, setNewDesc] = useState('');
  const [newType, setNewType] = useState<KbType>('tree');
  const [newBuilderModel, setNewBuilderModel] = useState('');
  const [error, setError] = useState<string | null>(null);

  const { data: modelsData } = useQuery({
    queryKey: ['models', 'wiki-builder'],
    queryFn: () => modelApi.list({ page_size: 100 }),
    enabled: isCreating && newType === 'tree',
  });
  const activeModels = (modelsData?.items ?? []).filter((m) => m.status === 'active');

  const { data, isLoading } = useQuery({
    queryKey: knowledgeKeys.list({}),
    queryFn: () => knowledgeApi.list({ page: 1, page_size: 50 }),
  });
  const kbs = data?.items ?? [];

  // 本地过滤：名称 / 描述 includes
  const filtered = useMemo(() => {
    const q = searchInput.trim().toLowerCase();
    if (!q) return kbs;
    return kbs.filter((kb) => `${kb.name} ${kb.description ?? ''}`.toLowerCase().includes(q));
  }, [kbs, searchInput]);

  const createM = useMutation({
    mutationFn: (input: {
      name: string;
      description?: string;
      type?: KbType;
      builder_model_id?: string;
    }) => knowledgeApi.create(input),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: knowledgeKeys.all });
      setError(null);
      setIsCreating(false);
      setNewName('');
      setNewDesc('');
      setNewType('tree');
      setNewBuilderModel('');
      onOpenKb({ id: created.id, name: created.name, type: created.type });
    },
    onError: (e: unknown) => setError(getErrorMessage(e, '创建失败')),
  });

  const deleteM = useMutation({
    mutationFn: (id: string) => knowledgeApi.remove(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: knowledgeKeys.all });
      toast.success('知识库已删除');
    },
  });

  const handleDelete = async (id: string, name: string) => {
    const ok = await confirmDialog({
      title: `删除知识库「${name}」？`,
      description: '知识库内所有文件将被清除。若被 Agent 引用将拒绝删除。',
      okText: '删除',
      danger: true,
    });
    if (ok) deleteM.mutate(id);
  };

  const handleCreateSave = (e: FormEvent) => {
    e.preventDefault();
    if (!newName.trim()) return;
    createM.mutate({
      name: newName.trim(),
      description: newDesc.trim() || undefined,
      type: newType,
      ...(newType === 'tree' ? { builder_model_id: newBuilderModel } : {}),
    });
  };

  return (
    <div className="space-y-4">
      {/* 工具栏：搜索 + 新建（设计稿 toolbar） */}
      <div className="flex items-center gap-3">
        <div className="relative w-[320px]">
          <Search className="w-3.5 h-3.5 pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-faint" />
          <input
            type="text"
            placeholder="搜索知识库名称 / 描述…"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            className="w-full pl-9 pr-3 h-8 text-xs bg-panel border border-line rounded-[10px] text-ink placeholder:text-ink-faint focus:outline-none focus:border-brand transition font-medium"
          />
        </div>
        {canWrite && (
          <button
            onClick={() => setIsCreating(true)}
            className="af-btn af-btn-primary shrink-0 ml-auto"
          >
            ＋ 新建知识库
          </button>
        )}
      </div>

      {error && (
        <div className="px-3 py-2 rounded-lg bg-sig-fail-soft border border-line text-sig-fail text-xs">{error}</div>
      )}

      {isLoading ? (
        <p className="text-xs text-ink-dim flex items-center gap-2 py-8 justify-center">
          <Loader2 className="w-4 h-4 animate-spin" /> 加载知识库…
        </p>
      ) : filtered.length === 0 ? (
        <p className="text-xs text-ink-faint py-10 text-center">
          {searchInput ? '没有匹配的知识库' : '还没有知识库，点击右上角创建。'}
        </p>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 content-start pb-4">
          {filtered.map((kb) => {
            const kbType: KbType = kb.type === 'vector' ? 'vector' : 'tree';
            const pill = buildPill(kb);
            const chips = kbType === 'tree' ? ['kb_search', 'kb_read'] : ['kb_search'];
            return (
              <div
                key={kb.id}
                onClick={() => onOpenKb({ id: kb.id, name: kb.name, type: kbType })}
                className="bg-panel border border-line rounded-xl p-4 flex flex-col transition cursor-pointer hover:shadow-[var(--shadow-card)] hover:border-line-strong"
              >
                {/* 头部：类型徽章 + 名称 + 形态描述 + 状态 pill */}
                <div className="flex items-start gap-[11px]">
                  <KbBadge type={kbType} />
                  <div className="min-w-0 flex-1">
                    <div className="text-[13px] font-semibold text-ink truncate" title={kb.name}>{kb.name}</div>
                    <div className="text-[10.5px] text-ink-dim mt-0.5 truncate">{TYPE_DESC[kbType]}</div>
                  </div>
                  <span className={`af-pill af-pill-${pill.tone} shrink-0`}>{pill.label}</span>
                </div>

                {/* 统计行 */}
                <div className="text-[11px] text-ink-dim mt-3">
                  <b className="text-ink font-semibold">{kb.file_count}</b> 文档
                  {kb.total_size > 0 && (
                    <>
                      <span className="mx-1.5 text-ink-faint">·</span>
                      {(kb.total_size / 1024).toFixed(0)} KB
                    </>
                  )}
                </div>

                {/* 能力 chips：绑定到 Agent 时暴露的检索能力 */}
                <div className="flex flex-wrap gap-1 mt-2.5">
                  {chips.map((c) => (
                    <span key={c} className="px-2 py-0.5 rounded-md bg-raise text-[10px] font-mono text-ink-dim">{c}</span>
                  ))}
                </div>

                {/* foot：日期 + 操作 */}
                <div className="flex items-center justify-between border-t border-line mt-3 pt-2.5">
                  <span className="text-[10.5px] text-ink-faint font-mono">
                    {new Date(kb.updated_at || kb.created_at).toLocaleDateString('zh-CN').replace(/\//g, '/')}
                  </span>
                  <div className="flex items-center gap-2.5 text-[11px]">
                    <button
                      onClick={(e) => { e.stopPropagation(); onOpenKb({ id: kb.id, name: kb.name, type: kbType }); }}
                      className="text-brand hover:text-brand-hover cursor-pointer"
                    >打开</button>
                    {canWrite && (
                      <button
                        onClick={(e) => { e.stopPropagation(); handleDelete(kb.id, kb.name); }}
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

      {/* create modal：设计稿 res-create-edit 形态（徽章头 + kicker + 下划线字段 + 类型卡） */}
      {isCreating && (
        <ResModal
          badge={<svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.6"><path d="M7 4h10M7 10h10M7 16h10" strokeLinecap="round" /><circle cx="4" cy="4" r="1.5" fill="currentColor" stroke="none" /><circle cx="4" cy="10" r="1.5" fill="currentColor" stroke="none" /><circle cx="4" cy="16" r="1.5" fill="currentColor" stroke="none" /></svg>}
          badgeCls="bg-[#F5E9E2] text-cat-kb"
          title="新建知识库"
          kicker="KNOWLEDGE BASE · CREATE"
          onClose={() => setIsCreating(false)}
          formId="kb-create-form"
          footer={{
            actions: (
              <>
                <button type="button" onClick={() => setIsCreating(false)} className="af-btn af-btn-ghost">取消</button>
                <button
                  type="submit"
                  form="kb-create-form"
                  disabled={createM.isPending || !newName.trim()}
                  className="af-btn af-btn-primary disabled:opacity-40 disabled:cursor-not-allowed flex items-center gap-1.5"
                >
                  {createM.isPending && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  创建
                </button>
              </>
            ),
          }}
        >
          <form id="kb-create-form" onSubmit={handleCreateSave}>
            <Field label="名称" required>
              <UInput autoFocus value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="例如：产品手册" />
            </Field>
            <Field label="检索结构" required>
              <div className="grid grid-cols-2 gap-2.5">
                <TypeCard
                  on={newType === 'tree'}
                  onClick={() => setNewType('tree')}
                  icon={<svg width="13" height="13" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.8"><path d="M7 4h10M7 10h10M7 16h10" strokeLinecap="round" /><circle cx="4" cy="4" r="1.5" fill="currentColor" stroke="none" /><circle cx="4" cy="10" r="1.5" fill="currentColor" stroke="none" /><circle cx="4" cy="16" r="1.5" fill="currentColor" stroke="none" /></svg>}
                  iconCls="bg-[#E9EDF7] text-cat-tool"
                  title="目录树 Wiki"
                  desc="上传 Markdown / 文档，按标题层级建树，AI 编译成带引用的 Wiki 页面"
                />
                <TypeCard
                  on={newType === 'vector'}
                  onClick={() => setNewType('vector')}
                  icon={<svg width="13" height="13" viewBox="0 0 20 20" fill="currentColor"><circle cx="5" cy="5" r="1.8" /><circle cx="10" cy="7" r="1.8" /><circle cx="15" cy="5" r="1.8" /><circle cx="7" cy="11" r="1.8" /><circle cx="12" cy="13" r="1.8" /><circle cx="6" cy="16" r="1.8" /></svg>}
                  iconCls="bg-[#E3F1F4] text-cat-voice"
                  title="向量语义"
                  desc="文档分块向量化，语义相似检索，适合 FAQ 与非结构化资料"
                />
              </div>
            </Field>
            {newType === 'tree' && (
              <Field label="编译模型" optional="Wiki 维护用">
                <select
                  value={newBuilderModel}
                  onChange={(e) => setNewBuilderModel(e.target.value)}
                  className="w-full border-0 border-b border-line-strong bg-transparent px-0 py-[7px] text-[13px] text-ink outline-none transition-colors focus:border-b-brand"
                >
                  <option value="">— 选择模型 —</option>
                  {activeModels.map((m) => (
                    <option key={m.id} value={m.id}>{m.name} ({m.model_id})</option>
                  ))}
                </select>
              </Field>
            )}
            <Field label="描述" optional="可选">
              <UInput value={newDesc} onChange={(e) => setNewDesc(e.target.value)} placeholder="这个知识库收录什么内容…" />
            </Field>
            {error && <p className="text-sig-fail text-xs mb-3">{error}</p>}
          </form>
        </ResModal>
      )}
    </div>
  );
}

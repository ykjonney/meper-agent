/**
 * WorkflowSpace — workflow card grid (list view).
 *
 * 规范 §6.2 列表页三段式（af-page-head → af-search/af-tabs → 卡片网格），
 * 设计语言与 AgentSpace 对齐：语义 token 明暗自适应、状态 pill、⋯ 菜单
 * （编辑/发布/归档/删除）、confirmDialog 删除确认。点击卡片进入 react-flow
 * 编辑器（onOpen）。已发布工作流可从卡片直接运行（useWorkflowExecution）。
 */
import { useState, useMemo, type FC } from 'react';
import { getErrorMessage } from '../lib/api-client';
import {
  Layers, Search, SearchX, Plus, Pencil, Trash2, Loader2, Play,
  MoreVertical, Rocket, Archive,
} from 'lucide-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  workflowsApi,
  workflowKeys,
  type WorkflowSummary,
  type WorkflowStatusValue,
} from '../services/workflows-api';
import { useWorkflowExecution } from '../hooks/useWorkflowExecution';
import { usePermission } from '../hooks/use-permission';
import { Popover } from './ui';
import { confirmDialog } from './ui/confirm';
import { toast } from './ui/toast';
import { TaskTraceModal } from '../features/workflow-editor/TaskTraceModal';
import { IconFlow } from './IndigoIcons';
import ExecuteInputDialog from '../features/workflow-editor/ExecuteInputDialog';
import { formatTimeFull } from '../lib/formatTime';

const STATUS_PILL: Record<WorkflowStatusValue, { label: string; cls: string }> = {
  draft: { label: '草稿', cls: 'af-pill af-pill-wait' },
  published: { label: '已发布', cls: 'af-pill af-pill-ok' },
  archived: { label: '已归档', cls: 'af-pill af-pill-neutral' },
};

export function WorkflowSpace({
  onOpen,
}: {
  onOpen: (id: string) => void;
  theme?: 'dark' | 'light';
}) {
  const queryClient = useQueryClient();
  // 写权限门控：无 workflow:write 的用户隐藏新建/删除入口
  const canWrite = usePermission('workflow:write');
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState<WorkflowStatusValue | 'all'>('all');
  const [menuOpenFor, setMenuOpenFor] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: workflowKeys.list({ page: 1, page_size: 100 }),
    queryFn: () => workflowsApi.list({ page: 1, page_size: 100 }),
  });
  const workflows = data?.items ?? [];

  const filtered = useMemo(() => {
    let list = workflows;
    if (statusFilter !== 'all') list = list.filter((w) => w.status === statusFilter);
    const q = search.trim().toLowerCase();
    if (q) list = list.filter((w) => w.name.toLowerCase().includes(q) || w.description?.toLowerCase().includes(q));
    return list;
  }, [workflows, statusFilter, search]);

  const tabs: { id: typeof statusFilter; label: string; count: number }[] = [
    { id: 'all', label: '全部', count: workflows.length },
    { id: 'published', label: '已发布', count: workflows.filter((w) => w.status === 'published').length },
    { id: 'draft', label: '草稿', count: workflows.filter((w) => w.status === 'draft').length },
    { id: 'archived', label: '已归档', count: workflows.filter((w) => w.status === 'archived').length },
  ];

  const invalidate = () => queryClient.invalidateQueries({ queryKey: workflowKeys.all });

  const createM = useMutation({
    mutationFn: () => workflowsApi.create({ name: `未命名工作流 ${new Date().toLocaleTimeString('zh-CN', { hour12: false })}` }),
    onSuccess: (wf) => {
      invalidate();
      setError(null);
      onOpen(wf.id); // jump straight into the editor for the new workflow
    },
    onError: (e: unknown) => setError(getErrorMessage(e, '创建失败')),
  });

  const deleteM = useMutation({
    mutationFn: (id: string) => workflowsApi.remove(id),
    onSuccess: () => {
      invalidate();
      toast.success('工作流已删除');
    },
    onError: (e: unknown) => toast.error(getErrorMessage(e, '删除失败')),
  });

  const publishM = useMutation({
    mutationFn: (id: string) => workflowsApi.publish(id),
    onSuccess: () => {
      invalidate();
      toast.success('工作流已发布');
    },
    onError: (e: unknown) => toast.error(getErrorMessage(e, '发布失败')),
  });

  const archiveM = useMutation({
    mutationFn: (id: string) => workflowsApi.archive(id),
    onSuccess: () => {
      invalidate();
      toast.success('工作流已归档');
    },
    onError: (e: unknown) => toast.error(getErrorMessage(e, '归档失败')),
  });

  const handleDelete = async (wf: WorkflowSummary) => {
    const ok = await confirmDialog({
      title: `删除工作流「${wf.name}」？`,
      description: '删除后不可恢复。',
      okText: '删除',
      danger: true,
    });
    if (ok) deleteM.mutate(wf.id);
  };

  // 工作流执行（与详情页共用 useWorkflowExecution）：列表页直接运行，
  // 不传 detail —— hook 内部按需拉取（命中详情页缓存则零请求）。
  const exec = useWorkflowExecution();
  const handleRun = (wf: WorkflowSummary) => exec.execute(wf.id);

  return (
    <div className="af-scope h-full min-h-0 flex flex-col">
      {/* 页头：标题+计数+主 CTA（规范 §6.2 列表页） */}
      <div className="af-page-head shrink-0">
        <h2 className="text-[22px] font-bold text-ink" style={{ fontFamily: 'var(--font-serif)' }}>工作流</h2>
        <span className="af-cnt">{workflows.length}</span>
        <div className="right">
          {canWrite && (
            <button
              onClick={() => createM.mutate()}
              disabled={createM.isPending}
              className="af-btn af-btn-primary"
            >
              {createM.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
              新建工作流
            </button>
          )}
        </div>
      </div>

      {error && (
        <div className="shrink-0 mb-4 px-3.5 py-2.5 rounded-lg bg-sig-fail-soft text-sig-fail text-xs">{error}</div>
      )}

      {/* 筛选行：搜索 + 状态 Tab（af-search / af-tabs 公共类） */}
      <div className="flex items-center gap-3 shrink-0 mb-4">
        <div className="af-search">
          <Search className="w-3.5 h-3.5 shrink-0" />
          <input
            className="af-search-input"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="搜索工作流名称 / 描述…"
          />
        </div>
        <div className="af-tabs">
          {tabs.map((t) => (
            <button
              key={t.id}
              onClick={() => setStatusFilter(t.id)}
              className={statusFilter === t.id ? 'on' : ''}
            >
              {t.label}
              <span className="n">{t.count}</span>
            </button>
          ))}
        </div>
      </div>

      {isLoading ? (
        <div className="flex-1 min-h-0 overflow-y-auto scrollbar-custom grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 pr-1.5 content-start pb-6">
          {[0, 1, 2].map((i) => (
            <div key={i} className="rounded-[10px] bg-panel p-4 space-y-3 animate-pulse">
              <div className="h-9 w-9 rounded-lg bg-raise" />
              <div className="h-3.5 w-2/3 rounded bg-raise" />
              <div className="h-3 w-full rounded bg-raise" />
              <div className="h-3 w-1/2 rounded bg-raise" />
            </div>
          ))}
        </div>
      ) : filtered.length === 0 ? (
        /* 空状态：区分"没有工作流"与"筛选无结果" */
        <div className="flex-1 min-h-0 overflow-y-auto scrollbar-custom flex flex-col items-center justify-center py-24 text-center">
          {workflows.length === 0 ? (
            <>
              <div className="w-14 h-14 rounded-2xl bg-brand-soft flex items-center justify-center mb-4">
                <Layers className="w-7 h-7 text-brand" />
              </div>
              <p className="text-base font-semibold text-ink">创建第一个工作流</p>
              <p className="text-[12.5px] text-ink-dim mt-1.5 max-w-[320px]">
                以节点图编排多步任务：工具调用、分支循环、子流程与人工审批
              </p>
              {canWrite && (
                <button onClick={() => createM.mutate()} className="af-btn af-btn-primary mt-5">
                  <Plus className="w-3.5 h-3.5" />
                  新建工作流
                </button>
              )}
            </>
          ) : (
            <>
              <SearchX className="w-8 h-8 text-ink-faint mb-3" />
              <p className="text-[13px] text-ink-dim">没有匹配的工作流，调整搜索或筛选条件</p>
            </>
          )}
        </div>
      ) : (
        <div className="flex-1 min-h-0 overflow-y-auto scrollbar-custom grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 pr-1.5 content-start pb-6">
          {filtered.map((wf) => (
            <WorkflowCard
              key={wf.id}
              wf={wf}
              onOpen={onOpen}
              onDelete={handleDelete}
              onRun={handleRun}
              onPublish={(id) => publishM.mutate(id)}
              onArchive={(id) => archiveM.mutate(id)}
              running={exec.executing}
              menuOpen={menuOpenFor === wf.id}
              onMenuOpen={(o) => setMenuOpenFor(o ? wf.id : null)}
              canWrite={canWrite}
              pending={publishM.isPending || archiveM.isPending}
            />
          ))}
        </div>
      )}

      {/* 执行追踪弹窗 */}
      {exec.traceOpen && (
        <TaskTraceModal task={exec.trackingTask} onClose={exec.closeTrace} />
      )}

      {/* 执行参数输入弹窗 */}
      <ExecuteInputDialog
        open={exec.execInputOpen}
        variables={exec.execInputVariables}
        onCancel={exec.cancelInput}
        onSubmit={exec.submitInput}
      />
    </div>
  );
};

const WorkflowCard: FC<CardProps> = ({
  wf, onOpen, onDelete, onRun, onPublish, onArchive,
  running, menuOpen, onMenuOpen, canWrite, pending,
}) => {
  const meta = STATUS_PILL[wf.status] ?? STATUS_PILL.draft;
  const isPublished = wf.status === 'published';
  const canRun = isPublished && !running;
  return (
    <div
      className="group bg-panel border border-line rounded-[11px] px-[13px] py-3 flex flex-col cursor-pointer transition-all duration-150 hover:border-line-strong hover:shadow-[var(--shadow-card)]"
      onClick={() => onOpen(wf.id)}
    >
      {/* 头部：类型徽章（工作流紫）+ 名称 + 节点数 + 状态 pill（签名卡） */}
      <div className="flex items-start gap-[11px]">
        <div className="w-[38px] h-[38px] rounded-[10px] bg-[#EEEBF8] text-cat-flow flex items-center justify-center shrink-0 select-none">
          <IconFlow size={19} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-[13px] font-bold text-ink truncate leading-tight pr-1">{wf.name}</div>
          <div className="text-[10.5px] text-ink-dim mt-0.5 truncate">{wf.node_count} 节点</div>
        </div>
        <span className={`${meta.cls} shrink-0`}>{meta.label}</span>
      </div>

      {/* 描述（两行截断） */}
      <p className="text-[11.5px] text-ink-dim leading-relaxed mt-2 min-h-[32px] line-clamp-2">
        {wf.description || '（无描述）'}
      </p>

      {/* 标签 */}
      {wf.tags?.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-1.5">
          {wf.tags.slice(0, 4).map((t) => (
            <span key={t} className="px-1.5 py-0.5 rounded bg-raise text-[10px] text-ink-dim">
              {t}
            </span>
          ))}
        </div>
      )}

      {/* foot：运行（主操作）+ 更多菜单（hairline 操作行） */}
      <div className="flex items-center gap-2 mt-3 pt-2.5 border-t border-line">
        <button
          onClick={(e) => {
            e.stopPropagation();
            if (canRun) onRun(wf);
          }}
          disabled={!canRun}
          title={!isPublished ? '需先发布' : running ? '正在执行…' : '运行'}
          className={`flex items-center gap-1 px-2.5 py-1 rounded-md text-[11px] font-semibold transition ${
            canRun
              ? 'bg-brand hover:bg-brand-hover text-white cursor-pointer'
              : 'bg-page border border-line text-ink-faint cursor-not-allowed'
          }`}
        >
          <Play className="w-3 h-3" /> 运行
        </button>
        <span className="flex-1" />
        <span className="font-mono text-[10px] text-ink-faint" onClick={(e) => e.stopPropagation()}>
          v{wf.version} · {formatTimeFull(wf.updated_at)}
        </span>
        <Popover
          trigger="click"
          open={menuOpen}
          onOpenChange={onMenuOpen}
          content={
            <div className="text-xs w-36">
              <button
                onClick={() => { onMenuOpen(false); onOpen(wf.id); }}
                className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-ink-soft hover:bg-panel-hover hover:text-ink transition cursor-pointer"
              >
                <Pencil className="w-3.5 h-3.5" /> 编辑
              </button>
              {wf.status === 'draft' && (
                <button
                  disabled={pending}
                  onClick={() => { onMenuOpen(false); onPublish(wf.id); }}
                  className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-ink-soft hover:bg-panel-hover hover:text-ink transition cursor-pointer disabled:opacity-50"
                >
                  <Rocket className="w-3.5 h-3.5" /> 发布
                </button>
              )}
              {isPublished && (
                <button
                  disabled={pending}
                  onClick={() => { onMenuOpen(false); onArchive(wf.id); }}
                  className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-ink-soft hover:bg-panel-hover hover:text-ink transition cursor-pointer disabled:opacity-50"
                >
                  <Archive className="w-3.5 h-3.5" /> 归档
                </button>
              )}
              {canWrite && (
                <>
                  <div className="border-t border-line my-1" />
                  <button
                    onClick={() => { onMenuOpen(false); void onDelete(wf); }}
                    className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-sig-fail hover:bg-panel-hover transition cursor-pointer"
                  >
                    <Trash2 className="w-3.5 h-3.5" /> 删除
                  </button>
                </>
              )}
            </div>
          }
        >
          <button
            onClick={(e) => { e.stopPropagation(); onMenuOpen(!menuOpen) }}
            className="shrink-0 p-1 rounded-md text-ink-faint hover:text-ink hover:bg-raise transition cursor-pointer"
            title="更多操作"
          >
            <MoreVertical className="w-3.5 h-3.5" />
          </button>
        </Popover>
      </div>
    </div>
  );
};

interface CardProps {
  wf: WorkflowSummary;
  onOpen: (id: string) => void;
  onDelete: (wf: WorkflowSummary) => void | Promise<void>;
  onRun: (wf: WorkflowSummary) => void;
  onPublish: (id: string) => void;
  onArchive: (id: string) => void;
  running: boolean;
  menuOpen: boolean;
  onMenuOpen: (open: boolean) => void;
  canWrite: boolean;
  pending: boolean;
}

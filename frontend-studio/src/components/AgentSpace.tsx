import { useState, useMemo, type FormEvent } from 'react';
import { getErrorMessage } from '../lib/api-client';
import {
  Plus, Edit, Bot, Trash2, Archive, Loader2, MoreVertical,
  Search, SearchX, Rocket,
} from 'lucide-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { agentApi, agentKeys } from '../services/agent-api';
import { modelApi, modelKeys } from '../services/model-api';
import { toStudioAgent } from '../services/adapters';
import { usePermission } from '../hooks/use-permission';
import type { Agent } from '../types';
import { Popover } from './ui';
import { toast } from './ui/toast';
import { confirmDialog } from './ui/confirm';

/**
 * AgentSpace — agent 列表 + 创建弹窗（v3.2 Workbench）。
 *
 * 重型编辑在 AgentEditorPage（onOpenEdit）；卡片保留发布/归档/删除 +
 * 详情与测试 + 编辑配置（三点菜单）。卡片交互全部保留，视觉对齐规范：
 * 无边框白卡、首字 avatar、状态 pill 双通道、mono meta 行、工具芯片人话化。
 */

/** 能力标识 → 人话名（builtin 映射动词，其余按前缀归类型）。 */
function skillLabel(skill: string): string {
  if (skill.startsWith('builtin:')) {
    const b = skill.slice(8);
    const map: Record<string, string> = {
      bash: '命令执行', read: '读取文件', write: '写入文件', edit: '编辑文件',
      glob: '查找文件', grep: '搜索内容', web_search: '联网搜索',
    };
    return map[b] ?? b;
  }
  if (skill.startsWith('mcp:')) return 'MCP 接入';
  if (skill.startsWith('workflow:')) return '工作流';
  if (skill.startsWith('kb:')) return '知识库';
  if (skill.startsWith('subagent:')) return '子 Agent';
  if (skill.startsWith('tool_')) return '自定义工具';
  return skill;
}

/** 能力芯片：人话名 + 同类合并计数（如 MCP 接入 ×3）。 */
function SkillChips({ skills }: { skills: string[] }) {
  if (skills.length === 0) {
    return <div className="text-[11px] text-ink-faint font-sans">未绑定能力</div>;
  }
  // 按 label 分组计数（同类工具合并，不刷屏）
  const counts = new Map<string, number>();
  for (const skill of skills) {
    const label = skillLabel(skill);
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  const entries = Array.from(counts.entries());
  const shown = entries.slice(0, 4);
  const rest = entries.length - shown.length;
  return (
    <div className="flex flex-wrap gap-1">
      {shown.map(([label, n]) => (
        <span key={label} className="px-2 py-0.5 rounded-md bg-raise text-[11px] text-ink-dim">
          {label}{n > 1 && <span className="font-mono text-ink-faint"> ×{n}</span>}
        </span>
      ))}
      {rest > 0 && (
        <span className="px-2 py-0.5 rounded-md text-[11px] text-ink-faint font-mono">+{rest} 类</span>
      )}
    </div>
  );
}

export function AgentSpace({
  onOpenEdit,
}: {
  onOpenEdit?: (id: string) => void;
} = {}) {
  // 实体首字彩块（DESIGN_SYSTEM §1.5）：按名称 hash 恒定取色
  const ENT_COLORS = ['#4A6CF7', '#8B5CF6', '#EC4899', '#14B8A6', '#F59E0B', '#22C55E'];
  const queryClient = useQueryClient();
  // 写操作（创建/编辑/删除/发布/归档）统一由 agent:write 权限门控，
  // 与后端 PUT/DELETE/publish 端点同一把钥匙。
  const canWrite = usePermission('agent:write');
  const [isCreating, setIsCreating] = useState(false);
  const [newName, setNewName] = useState('');
  const [newDesc, setNewDesc] = useState('');
  const [error, setError] = useState<string | null>(null);
  // 当前展开三点菜单的卡片 id。受控 Popover：菜单项点击后需手动关闭
  // （click 模式下点浮层内部不会自动收起）。
  const [menuOpenFor, setMenuOpenFor] = useState<string | null>(null);
  // 筛选与搜索（前端过滤）
  const [statusTab, setStatusTab] = useState<'all' | 'online' | 'draft'>('all');
  const [searchInput, setSearchInput] = useState('');

  const { data, isLoading } = useQuery({
    queryKey: agentKeys.list({}),
    queryFn: () => agentApi.list({ page: 1, page_size: 50, status: 'all' }),
  });
  const agents = (data?.items ?? []).map(toStudioAgent);

  // 模型 id → 友好名称（"glm-5.2 · 智谱"）；仅用于卡片 meta 行展示
  const { data: modelsData } = useQuery({
    queryKey: modelKeys.list({ page_size: 100 }),
    queryFn: () => modelApi.list({ page_size: 100 }),
  });
  const modelById = new Map((modelsData?.items ?? []).map((m) => [m.id, m]));
  const modelLabelOf = (agent: Agent) => {
    const meta = agent.model ? modelById.get(agent.model) : undefined;
    // 模型未配置或指向已删除的模型时，明确提示而非留白
    return meta ? `${meta.name} · ${meta.compatibility_type}` : '未配置模型';
  };

  const filtered = useMemo(() => {
    const q = searchInput.trim().toLowerCase();
    return agents.filter((a) => {
      if (statusTab === 'online' && a.status !== 'online') return false;
      if (statusTab === 'draft' && a.status === 'online') return false;
      if (q && !(a.name.toLowerCase().includes(q) || (a.description ?? '').toLowerCase().includes(q))) return false;
      return true;
    });
  }, [agents, statusTab, searchInput]);

  const createM = useMutation({
    mutationFn: (input: { name: string; description?: string }) => agentApi.create(input),
    onSuccess: (created) => {
      queryClient.invalidateQueries({ queryKey: agentKeys.all });
      setError(null);
      setIsCreating(false);
      setNewName('');
      setNewDesc('');
      // Jump straight into the editor to fill the full config.
      if (onOpenEdit) onOpenEdit(created.id);
    },
    onError: (e: unknown) => setError(getErrorMessage(e, '创建失败')),
  });

  const deleteM = useMutation({
    mutationFn: (id: string) => agentApi.remove(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: agentKeys.all }),
    onError: (e: unknown) => setError(getErrorMessage(e, '删除失败')),
  });

  const publishM = useMutation({
    mutationFn: (id: string) => agentApi.publish(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: agentKeys.all });
      toast.success('已发布');
    },
    onError: (e: unknown) => setError(getErrorMessage(e, '发布失败')),
  });

  const archiveM = useMutation({
    mutationFn: (id: string) => agentApi.archive(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: agentKeys.all });
      toast.success('已归档');
    },
    onError: (e: unknown) => setError(getErrorMessage(e, '归档失败')),
  });

  const handleCreateSave = (e: FormEvent) => {
    e.preventDefault();
    if (!newName.trim()) return;
    createM.mutate({ name: newName.trim(), description: newDesc.trim() || undefined });
  };

  const handleDelete = async (agent: Agent) => {
    const ok = await confirmDialog({
      title: `删除智能体「${agent.name}」？`,
      description: '删除后不可恢复。',
      okText: '删除',
      danger: true,
    });
    if (ok) deleteM.mutate(agent.id);
  };

  const statusPill = (agent: Agent) =>
    agent.status === 'online' ? (
      <span className="af-pill af-pill-ok shrink-0">已发布</span>
    ) : (
      <span className="af-pill af-pill-neutral shrink-0">未发布</span>
    );

  const tabs: { id: typeof statusTab; label: string; count: number }[] = [
    { id: 'all', label: '全部', count: agents.length },
    { id: 'online', label: '已发布', count: agents.filter((a) => a.status === 'online').length },
    { id: 'draft', label: '未发布', count: agents.filter((a) => a.status !== 'online').length },
  ];

  return (
    <div className="af-scope theme-indigo h-full min-h-0 flex flex-col">
      {/* 页头：衬线大标题 + mono 计数 + 主 CTA（列表页模板） */}
      <div className="af-page-head shrink-0">
        <h2 className="text-[22px] font-bold text-ink" style={{ fontFamily: 'var(--font-serif)' }}>智能体</h2>
        <span className="af-cnt font-mono">{agents.length} 个</span>
        <div className="right">
          {canWrite && (
            <button
              onClick={() => setIsCreating(true)}
              id="btn_add_agent"
              className="af-btn af-btn-primary"
            >
              <Plus className="w-3.5 h-3.5" />
              创建 Agent
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
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="搜索智能体名称 / 描述…"
          />
        </div>
        <div className="af-tabs">
          {tabs.map((t) => (
            <button
              key={t.id}
              onClick={() => setStatusTab(t.id)}
              className={statusTab === t.id ? 'on' : ''}
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
            <div key={i} className="rounded-[10px] bg-panel p-5 space-y-3 animate-pulse">
              <div className="h-10 w-10 rounded-xl bg-raise" />
              <div className="h-3.5 w-2/3 rounded bg-raise" />
              <div className="h-3 w-full rounded bg-raise" />
              <div className="h-3 w-1/2 rounded bg-raise" />
            </div>
          ))}
        </div>
      ) : filtered.length === 0 ? (
        /* 空状态：区分"没有 agent"与"筛选无结果" */
        <div className="flex-1 min-h-0 overflow-y-auto scrollbar-custom flex flex-col items-center justify-center py-24 text-center">
          {agents.length === 0 ? (
            <>
              <div className="w-14 h-14 rounded-2xl bg-brand-soft flex items-center justify-center mb-4">
                <Bot className="w-7 h-7 text-brand" />
              </div>
              <p className="text-base font-semibold text-ink">创建第一个智能体</p>
              <p className="text-[12.5px] text-ink-dim mt-1.5 max-w-[320px]">
                智能体是具备独立心智、专用工具与提示词的 AI 单元
              </p>
              {canWrite && (
                <button onClick={() => setIsCreating(true)} className="af-btn af-btn-primary mt-5">
                  <Plus className="w-3.5 h-3.5" />
                  创建 Agent
                </button>
              )}
            </>
          ) : (
            <>
              <SearchX className="w-8 h-8 text-ink-faint mb-3" />
              <p className="text-[13px] text-ink-dim">没有匹配的智能体，调整搜索或筛选条件</p>
            </>
          )}
        </div>
      ) : (
        <div className="flex-1 min-h-0 overflow-y-auto scrollbar-custom grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3 pr-1.5 content-start pb-6">
          {filtered.map((agent) => {
            const isPublished = agent.status === 'online';
            return (
              <div
                key={agent.id}
                onClick={() => onOpenEdit?.(agent.id)}
                className="group bg-panel rounded-[10px] shadow-[var(--shadow-card)] p-4 flex flex-col justify-between cursor-pointer hover:bg-panel-hover transition-colors duration-150"
              >
                {/* 头部：头像（配置了 avatar 用图片，否则首字色块）+ 名称 + 状态 pill + ⋯ 菜单 */}
                <div className="flex items-start justify-between gap-2">
                  <div className="flex items-center gap-2.5 min-w-0">
                    {agent.avatar ? (
                      <img
                        src={agent.avatar}
                        alt=""
                        className="w-9 h-9 rounded-[10px] object-cover shrink-0 select-none border border-line"
                        draggable={false}
                      />
                    ) : (
                      <div
                        className="w-9 h-9 rounded-[10px] flex items-center justify-center text-sm font-bold text-white shrink-0 select-none"
                        style={{ background: ENT_COLORS[agent.name.charCodeAt(0) % ENT_COLORS.length] }}
                      >
                        {agent.name.slice(0, 1).toUpperCase()}
                      </div>
                    )}
                    <div className="min-w-0">
                      <h4 className="text-[14px] font-semibold text-ink truncate leading-tight">{agent.name}</h4>
                      <div className="mt-1">{statusPill(agent)}</div>
                    </div>
                  </div>

                  {/* Card actions: 三点菜单（Popover portal 到主题根，fixed 定位，
                      不被卡片 overflow-hidden 裁剪；打开时随滚动/resize 自动重定位） */}
                  <Popover
                    trigger="click"
                    open={menuOpenFor === agent.id}
                    onOpenChange={(o) => setMenuOpenFor(o ? agent.id : null)}
                    content={
                      <div className="text-xs">
                        {canWrite && (
                          <>
                            <button
                              onClick={() => { setMenuOpenFor(null); onOpenEdit?.(agent.id); }}
                              className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-ink-soft hover:bg-panel-hover hover:text-ink transition cursor-pointer"
                            >
                              <Edit className="w-3.5 h-3.5" /> 编辑配置
                            </button>
                            <div className="border-t border-line my-1" />
                            <button
                              onClick={() => { setMenuOpenFor(null); void handleDelete(agent); }}
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
                      onClick={(e) => {
                        // stopPropagation 双重意义：不冒泡到卡片（误入编辑页），
                        // 也不冒泡到 Popover 容器（其注入的 onClick 会重复 toggle）
                        e.stopPropagation()
                        setMenuOpenFor(menuOpenFor === agent.id ? null : agent.id)
                      }}
                      className="shrink-0 p-2 -mr-1.5 -mt-1 rounded-md text-ink-faint hover:text-ink hover:bg-raise transition cursor-pointer"
                      title="更多操作"
                    >
                      <MoreVertical className="w-4 h-4" />
                    </button>
                  </Popover>
                </div>

                {/* 描述（两行截断） */}
                <p className="text-[12.5px] text-ink-dim leading-relaxed mt-2.5 mb-3 min-h-[36px] line-clamp-2">
                  {agent.description || '（无描述）'}
                </p>

                {/* 能力芯片（人话名 + 折叠） */}
                <div className="mb-3">
                  <SkillChips skills={agent.skills} />
                </div>

                {/* meta 行 + footer 操作 */}
                <div className="pt-3 border-t border-line flex items-center justify-between gap-2">
                  <span className={`text-[11px] font-mono truncate ${agent.model ? 'text-ink-faint' : 'text-sig-wait font-semibold'}`}>
                    {modelLabelOf(agent)} · {agent.lastActive}
                  </span>
                  {canWrite && (isPublished ? (
                    <button
                      onClick={(e) => { e.stopPropagation(); archiveM.mutate(agent.id); }}
                      disabled={archiveM.isPending}
                      className="shrink-0 flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-medium text-ink-dim border border-line hover:bg-raise hover:text-ink transition cursor-pointer disabled:opacity-50"
                    >
                      {archiveM.isPending ? <Loader2 className="w-3 h-3 animate-spin" /> : <Archive className="w-3 h-3" />}
                      归档
                    </button>
                  ) : (
                    <button
                      onClick={(e) => { e.stopPropagation(); publishM.mutate(agent.id); }}
                      disabled={publishM.isPending}
                      className="shrink-0 flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-semibold text-white bg-brand hover:bg-brand-hover transition cursor-pointer disabled:opacity-50"
                    >
                      {publishM.isPending ? <Loader2 className="w-3 h-3 animate-spin" /> : <Rocket className="w-3 h-3" />}
                      发布
                    </button>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* CREATE dialog (name + description only; full config on the editor page) */}
      {isCreating && (
        <div id="modal_create_agent" className="fixed inset-0 flex items-center justify-center p-4 z-50 animate-fade-in text-xs bg-page/60">
          <div className="w-full max-w-md bg-panel rounded-xl overflow-hidden shadow-[var(--shadow-pop)]">
            <div className="p-4 border-b border-line flex items-center justify-between">
              <h3 className="text-sm font-bold text-ink flex items-center gap-2 font-sans">
                <Plus className="w-4 h-4 text-brand" />
                创建 Agent
              </h3>
              <button onClick={() => setIsCreating(false)} className="text-ink-faint hover:text-ink font-bold cursor-pointer">✕</button>
            </div>

            <form onSubmit={handleCreateSave} className="p-5 space-y-4">
              <div>
                <label className="block text-[12px] text-ink-dim mb-1.5">智能体名称 *</label>
                <input
                  type="text" required autoFocus value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  placeholder="如：全局分析官…"
                  className="w-full px-3 py-2 bg-well border border-line rounded-lg text-ink text-[13px] focus:outline-none focus:border-brand focus:ring-[3px] focus:ring-brand-soft transition"
                />
              </div>
              <div>
                <label className="block text-[12px] text-ink-dim mb-1.5">描述</label>
                <input
                  type="text" value={newDesc}
                  onChange={(e) => setNewDesc(e.target.value)}
                  placeholder="这个 Agent 专门在哪些流程解决痛点…"
                  className="w-full px-3 py-2 bg-well border border-line rounded-lg text-ink text-[13px] focus:outline-none focus:border-brand focus:ring-[3px] focus:ring-brand-soft transition"
                />
              </div>
              <p className="text-[11px] text-ink-faint">创建后自动进入编辑页，可配置模型、Prompt、工具等。</p>
              <div className="pt-2 flex justify-end gap-2.5">
                <button type="button" onClick={() => setIsCreating(false)} className="af-btn af-btn-ghost border border-line">
                  取消
                </button>
                <button type="submit" disabled={createM.isPending} className="af-btn af-btn-primary">
                  {createM.isPending && <Loader2 className="w-3.5 h-3.5 animate-spin" />}
                  {createM.isPending ? '创建中…' : '立即创建'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * AgentEditorPage — full-featured Agent editor on a dedicated page.
 *
 * Replaces the cramped edit modal. Groups all fields into collapsible sections:
 * 基本信息 / Prompt 配置 / 执行参数 / 工具绑定. Loaded from a single agent
 * detail query; saves via PUT. Publish/archive actions in the header.
 *
 * Used for both editing existing agents and completing a freshly-created one
 * (backend POST only takes name+description, so the editor fills the rest).
 */
import { useState, useEffect, useMemo, type FC, type ReactNode } from 'react';
import {
  ArrowLeft, Bot, Save, Loader2, Rocket, Archive, RefreshCw, Cpu, Wrench,
  ChevronDown, ChevronRight, Sparkles, Plus, Trash2, Mic, ListPlus, Folder, X, Pencil,
} from 'lucide-react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { agentApi, agentKeys, type AgentUpdateInput } from '../services/agent-api';
import { modelApi, modelKeys } from '../services/model-api';
import { toolsApi, toolKeys, type BuiltinTool } from '../services/tools-api';
import { userToolsApi, userToolKeys } from '../services/user-tools-api';
import { mcpApi, mcpKeys } from '../services/mcp-api';
import { workflowsApi, workflowKeys } from '../services/workflows-api';
import { knowledgeApi, knowledgeKeys } from '../services/knowledge-api';
import { toStudioAgent, fromStudioAgent } from '../services/adapters';
import { Select, Modal, type SelectOptionGroup } from './ui';
import { toast } from './ui/toast';
import type { Agent } from '../types';
import AvatarField from './AvatarField';

const inputCls =
  'w-full px-3 py-2 bg-[#121214] border border-[#27272a] rounded-lg text-white placeholder:text-[#52525b] focus:outline-none focus:border-indigo-600 transition font-sans';

export function AgentEditorPage({
  agentId,
  onBack,
  onSaved,
}: {
  agentId: string;
  onBack: () => void;
  /** Called after a successful save; parent typically navigates to detail/chat. */
  onSaved?: (id: string) => void;
}) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<Agent | null>(null);

  const { data, isLoading, refetch } = useQuery({
    queryKey: agentKeys.detail(agentId),
    queryFn: () => agentApi.get(agentId),
  });

  // Sync remote data into the local form once loaded.
  useEffect(() => {
    if (data) setForm(toStudioAgent(data));
  }, [data]);

  // Tool-binding + model data sources.
  const { data: modelsData } = useQuery({
    queryKey: modelKeys.list({ status: 'active', page_size: 100 }),
    queryFn: () => modelApi.list({ status: 'active', page_size: 100 }),
  });
  const activeModels = modelsData?.items ?? [];
  // Group active models by compatibility_type (provider) for the model selector.
  const modelGroups: SelectOptionGroup[] = useMemo(() => {
    const buckets = new Map<string, SelectOptionGroup>();
    for (const m of activeModels) {
      const provider = (m.compatibility_type ?? 'other') as string;
      if (!buckets.has(provider)) buckets.set(provider, { label: provider, options: [] });
      // value = Model record _id (e.g. "model_01..."); backend get_llm_client
      // only resolves references with the "model_" prefix. Using model_id
      // (e.g. "glm-5.2") here would fall through to the env-var fallback
      // path and fail with "Missing credentials".
      buckets.get(provider)!.options.push({
        value: m.id,
        label: `${m.name} (${m.model_id})`,
      });
    }
    return Array.from(buckets.values());
  }, [activeModels]);
  const { data: builtinsData } = useQuery({
    queryKey: ['builtin-tools'],
    queryFn: () => toolsApi.listBuiltins(),
  });
  const builtinTools: BuiltinTool[] = builtinsData ?? [];
  const { data: skillsData } = useQuery({
    queryKey: toolKeys.list({ source: 'markdown', page_size: 100 }),
    queryFn: () => toolsApi.list({ source: 'markdown', page_size: 100 }),
  });
  const skillTools = skillsData?.items ?? [];
  const { data: mcpData } = useQuery({
    queryKey: mcpKeys.list({ page: 1, page_size: 100 }),
    queryFn: () => mcpApi.list({ page: 1, page_size: 100 }),
  });
  const mcpConnections = mcpData?.items ?? [];
  const { data: workflowsData } = useQuery({
    queryKey: workflowKeys.list({ page: 1, page_size: 100 }),
    queryFn: () => workflowsApi.list({ page: 1, page_size: 100 }),
  });
  const workflows = workflowsData?.items ?? [];
  const { data: kbData } = useQuery({
    queryKey: knowledgeKeys.list({ page: 1, page_size: 100 }),
    queryFn: () => knowledgeApi.list({ page: 1, page_size: 100 }),
  });
  const knowledgeBases = kbData?.items ?? [];

  // 自定义工具候选：组织库「已开启」工具全集（官方 active + uto_ published&enabled）。
  // 凭证为工具级统一配置（admin 维护），绑定只需选工具——勾选即绑。
  const { data: enabledToolsData } = useQuery({
    queryKey: userToolKeys.enabled(),
    queryFn: () => userToolsApi.listEnabled(),
  });
  const customToolCandidates: CustomToolCandidate[] = useMemo(
    () => (enabledToolsData ?? []).map((t) => ({ id: t.id, name: t.name, source: t.source })),
    [enabledToolsData],
  );

  /** 勾选/移除自定义工具（凭证工具级统一，无需绑定时填写） */
  const handleCustomToggle = (toolId: string) => {
    setForm((prev) => {
      if (!prev) return prev;
      const bindings = prev.customTools ?? [];
      const next = bindings.some((b) => b.tool_id === toolId)
        ? bindings.filter((b) => b.tool_id !== toolId)
        : [...bindings, { tool_id: toolId, user_args: {} }];
      return { ...prev, customTools: next };
    });
  };

  const updateM = useMutation({
    mutationFn: (input: AgentUpdateInput) => agentApi.update(agentId, input),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: agentKeys.all });
      refetch();
      // 统一 Toast 反馈（替代旧的 savedMsg 临时横幅），然后交回父级跳转。
      toast.success('配置已保存');
      if (onSaved) onSaved(agentId);
    },
  });

  const publishM = useMutation({
    mutationFn: () => agentApi.publish(agentId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: agentKeys.all }),
  });

  const archiveM = useMutation({
    mutationFn: () => agentApi.archive(agentId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: agentKeys.all }),
  });

  // 批量添加推荐项弹窗 + 紧凑列表的展开索引（hooks 必须位于 isLoading 早退之前）。
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkText, setBulkText] = useState('');
  const [expandedItems, setExpandedItems] = useState<Set<number>>(new Set());
  // 批量落位目标：UNGROUPED_VALUE=未分组，否则为分组名（弹窗内选择，默认未分组）
  const [bulkDest, setBulkDest] = useState(UNGROUPED_VALUE);
  // 分区标题行内编辑：重命名某分组（Enter/失焦提交，Esc 取消）
  const [renamingGroup, setRenamingGroup] = useState<number | null>(null);
  const [renameText, setRenameText] = useState('');
  // 新建分组弹窗（底部按钮触发，弹窗内输入名称）
  const [createGroupOpen, setCreateGroupOpen] = useState(false);
  const [createGroupText, setCreateGroupText] = useState('');
  // 组内条目展开索引（key `${gIdx}:${itemIdx}`，避免删除后的平移运算）
  const [expandedGroupItems, setExpandedGroupItems] = useState<Set<string>>(new Set());
  // 分区折叠状态（默认全收起，点击分组头展开）：key = UNGROUPED_SECTION_KEY / groupSectionKey(title)
  const [openSections, setOpenSections] = useState<Set<string>>(new Set());
  const bulkParsed = useMemo(() => parseBulkRecommendedItems(bulkText), [bulkText]);

  const handleSave = () => {
    if (!form) return;
    if (!form.rolePrompt?.trim() || !form.taskPrompt?.trim()) {
      toast.error('「角色定义」和「任务描述」为必填项（对话执行校验）');
      return;
    }
    updateM.mutate(fromStudioAgent(form));
  };

  if (isLoading || !form) {
    return (
      <div className="flex items-center justify-center py-16 text-[#71717a]">
        <Loader2 className="w-5 h-5 animate-spin mr-2" /> 载入 Agent 配置…
      </div>
    );
  }

  const isPublished = form.status === 'online';
  const set = (patch: Partial<Agent>) => setForm({ ...form, ...patch });

  // ── 推荐项（快捷输入）操作 ──
  const recommendedItems = form.recommendedItems ?? [];

  const updateItem = (idx: number, patch: Partial<{ label: string; prompt: string }>) =>
    set({ recommendedItems: recommendedItems.map((it, i) => (i === idx ? { ...it, ...patch } : it)) });

  // 删除后数组塌缩，需同步平移展开索引（删除项之前的保留，之后的减一）。
  const removeItem = (idx: number) => {
    set({ recommendedItems: recommendedItems.filter((_, i) => i !== idx) });
    const next = new Set<number>();
    for (const i of expandedItems) {
      if (i < idx) next.add(i);
      else if (i > idx) next.add(i - 1);
    }
    setExpandedItems(next);
  };

  const addItem = () => {
    set({ recommendedItems: [...recommendedItems, { label: '', prompt: '' }] });
    setExpandedItems((prev) => new Set(prev).add(recommendedItems.length)); // 新项自动展开便于填写
    openSection(UNGROUPED_SECTION_KEY); // 新项落未分组，分区同步展开才能看到
  };

  const toggleItemExpanded = (idx: number) =>
    setExpandedItems((prev) => {
      const next = new Set(prev);
      if (next.has(idx)) next.delete(idx);
      else next.add(idx);
      return next;
    });

  // ── 推荐项分组（recommendedGroups）操作：分组即分区，默认收起、点击头部展开，条目通过「所属分组」选择器归类 ──
  const recommendedGroups = form.recommendedGroups ?? [];

  const openSection = (key: string) => setOpenSections((prev) => new Set(prev).add(key));

  const toggleSection = (key: string) =>
    setOpenSections((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const beginRenameGroup = (gIdx: number) => {
    setRenamingGroup(gIdx);
    setRenameText(recommendedGroups[gIdx]?.title ?? '');
  };

  /** 分区标题重命名提交（重名/超长/保留字校验）。 */
  const commitRenameGroup = () => {
    if (renamingGroup === null) return;
    const title = renameText.trim();
    if (!title) {
      setRenamingGroup(null);
      return;
    }
    if (title.length > GROUP_TITLE_MAX) {
      toast.error(`分组名不能超过 ${GROUP_TITLE_MAX} 字符`);
      return;
    }
    if (title === UNGROUPED_VALUE) {
      toast.error('该名称为保留字，请换一个分组名');
      return;
    }
    if (recommendedGroups.some((g, i) => i !== renamingGroup && g.title === title)) {
      toast.error(`分组「${title}」已存在`);
      return;
    }
    set({ recommendedGroups: recommendedGroups.map((g, i) => (i === renamingGroup ? { ...g, title } : g)) });
    // 分区折叠状态以标题为 key，重命名后原样带过去
    setOpenSections((prev) => {
      const oldKey = groupSectionKey(recommendedGroups[renamingGroup].title);
      if (!prev.has(oldKey)) return prev;
      const next = new Set(prev);
      next.delete(oldKey);
      next.add(groupSectionKey(title));
      return next;
    });
    setRenamingGroup(null);
  };

  const openCreateGroup = () => {
    setCreateGroupText('');
    setCreateGroupOpen(true);
  };

  /** 新建空分组（弹窗确认；重名/超长/保留字/数量上限校验）。 */
  const handleCreateGroup = () => {
    const title = createGroupText.trim();
    if (!title) return;
    if (title.length > GROUP_TITLE_MAX) {
      toast.error(`分组名不能超过 ${GROUP_TITLE_MAX} 字符`);
      return;
    }
    if (title === UNGROUPED_VALUE) {
      toast.error('该名称为保留字，请换一个分组名');
      return;
    }
    if (recommendedGroups.length >= MAX_RECOMMENDED_GROUPS) {
      toast.error(`最多 ${MAX_RECOMMENDED_GROUPS} 个分组`);
      return;
    }
    if (recommendedGroups.some((g) => g.title === title)) {
      toast.error(`分组「${title}」已存在`);
      return;
    }
    set({ recommendedGroups: [...recommendedGroups, { title, items: [] }] });
    setCreateGroupOpen(false);
    openSection(groupSectionKey(title));
  };

  /** 删除分组：组内条目回落到未分组（超上限则拒绝），展开 key 与重命名索引平移。 */
  const removeGroup = (gIdx: number) => {
    const group = recommendedGroups[gIdx];
    if (!group) return;
    if (recommendedItems.length + group.items.length > MAX_RECOMMENDED_ITEMS) {
      toast.error(`删除后未分组将超过 ${MAX_RECOMMENDED_ITEMS} 条上限，请先清理该分组内条目`);
      return;
    }
    set({
      recommendedItems: [...recommendedItems, ...group.items.map((it) => ({ ...it }))],
      recommendedGroups: recommendedGroups.filter((_, i) => i !== gIdx),
    });
    setExpandedGroupItems((prev) => {
      const next = new Set<string>();
      for (const key of prev) {
        const sep = key.indexOf(':');
        const gi = Number(key.slice(0, sep));
        if (gi < gIdx) next.add(key);
        else if (gi > gIdx) next.add(`${gi - 1}:${key.slice(sep + 1)}`);
      }
      return next;
    });
    // 正在重命名的分区索引随之平移；被删分区的重命名取消
    setRenamingGroup((prev) =>
      prev === null ? null : prev === gIdx ? null : prev > gIdx ? prev - 1 : prev,
    );
    if (group.items.length > 0) toast.info(`分组「${group.title}」已删除，${group.items.length} 条移入未分组`);
  };

  const updateGroupItem = (gIdx: number, itemIdx: number, patch: Partial<{ label: string; prompt: string }>) =>
    set({
      recommendedGroups: recommendedGroups.map((g, i) =>
        i === gIdx ? { ...g, items: g.items.map((it, j) => (j === itemIdx ? { ...it, ...patch } : it)) } : g,
      ),
    });

  // 组内条目 key 前缀保留、同组后段索引减一，其余组原样保留
  const removeGroupItem = (gIdx: number, itemIdx: number) => {
    set({
      recommendedGroups: recommendedGroups.map((g, i) =>
        i === gIdx ? { ...g, items: g.items.filter((_, j) => j !== itemIdx) } : g,
      ),
    });
    setExpandedGroupItems((prev) => {
      const prefix = `${gIdx}:`;
      const next = new Set<string>();
      for (const key of prev) {
        if (!key.startsWith(prefix)) {
          next.add(key);
          continue;
        }
        const ii = Number(key.slice(prefix.length));
        if (ii < itemIdx) next.add(key);
        else if (ii > itemIdx) next.add(`${gIdx}:${ii - 1}`);
      }
      return next;
    });
  };

  const toggleGroupItemExpanded = (key: string) =>
    setExpandedGroupItems((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  /** 条目改所属分组：gIdx=-1 未分组；target=-1 移入未分组、>=0 移入对应分组（满员选项已禁用，此处兜底）。 */
  const assignItemGroup = (gIdx: number, itemIdx: number, target: number) => {
    if (target === gIdx) return;
    const source = gIdx >= 0 ? recommendedGroups[gIdx]?.items[itemIdx] : recommendedItems[itemIdx];
    if (!source) return;
    if (target >= 0 && (recommendedGroups[target]?.items.length ?? 0) >= MAX_GROUP_ITEMS) return;
    if (target < 0 && recommendedItems.length >= MAX_RECOMMENDED_ITEMS) return;

    const nextItems = [...recommendedItems];
    const nextGroups = recommendedGroups.map((g) => ({ title: g.title, items: g.items.map((it) => ({ ...it })) }));
    // 从源位置移除并平移展开索引
    if (gIdx >= 0) {
      nextGroups[gIdx] = { ...nextGroups[gIdx], items: nextGroups[gIdx].items.filter((_, j) => j !== itemIdx) };
      setExpandedGroupItems((prev) => {
        const prefix = `${gIdx}:`;
        const next = new Set<string>();
        for (const key of prev) {
          if (!key.startsWith(prefix)) {
            next.add(key);
            continue;
          }
          const ii = Number(key.slice(prefix.length));
          if (ii < itemIdx) next.add(key);
          else if (ii > itemIdx) next.add(`${gIdx}:${ii - 1}`);
        }
        return next;
      });
    } else {
      nextItems.splice(itemIdx, 1);
      setExpandedItems((prev) => {
        const next = new Set<number>();
        for (const i of prev) {
          if (i < itemIdx) next.add(i);
          else if (i > itemIdx) next.add(i - 1);
        }
        return next;
      });
    }
    // 追加到目标末尾并自动展开，便于继续编辑；目标分区同步展开
    const moved = { ...source };
    if (target >= 0) {
      nextGroups[target] = { ...nextGroups[target], items: [...nextGroups[target].items, moved] };
      setExpandedGroupItems((prev) => new Set(prev).add(`${target}:${nextGroups[target].items.length - 1}`));
      openSection(groupSectionKey(nextGroups[target].title));
    } else {
      nextItems.push(moved);
      setExpandedItems((prev) => new Set(prev).add(nextItems.length - 1));
      openSection(UNGROUPED_SECTION_KEY);
    }
    set({ recommendedItems: nextItems, recommendedGroups: nextGroups });
  };

  const openBulk = () => {
    setBulkDest(UNGROUPED_VALUE);
    setBulkText('');
    setBulkOpen(true);
  };

  const handleBulkAdd = () => {
    const parsed = bulkParsed;
    if (parsed.items.length === 0 && parsed.groups.length === 0) return;

    const destGroupIdx = bulkDest === UNGROUPED_VALUE
      ? -1
      : recommendedGroups.findIndex((g) => g.title === bulkDest);
    if (bulkDest !== UNGROUPED_VALUE && destGroupIdx < 0) return; // 目标分组已被删除

    const nextItems = [...recommendedItems];
    const nextGroups = recommendedGroups.map((g) => ({ title: g.title, items: g.items.map((it) => ({ ...it })) }));
    const notes: string[] = [];

    // 分组 JSON：同名分组直接并入，否则新建（受组数/组内条数上限截断）；有落位的分区记录下来待展开
    let addedGroups = 0;
    const touchedGroupTitles: string[] = [];
    for (const group of parsed.groups) {
      const existIdx = nextGroups.findIndex((g) => g.title === group.title);
      if (existIdx >= 0) {
        const room = Math.max(0, MAX_GROUP_ITEMS - nextGroups[existIdx].items.length);
        const adding = group.items.slice(0, room);
        nextGroups[existIdx] = {
          ...nextGroups[existIdx],
          items: [...nextGroups[existIdx].items, ...adding.map((it) => ({ ...it }))],
        };
        if (adding.length > 0) touchedGroupTitles.push(group.title);
        if (group.items.length > room) notes.push(`分组「${group.title}」已达上限：仅并入 ${room} 条`);
      } else if (nextGroups.length < MAX_RECOMMENDED_GROUPS) {
        const adding = group.items.slice(0, MAX_GROUP_ITEMS);
        nextGroups.push({ title: group.title, items: adding.map((it) => ({ ...it })) });
        addedGroups++;
        touchedGroupTitles.push(group.title);
        if (group.items.length > MAX_GROUP_ITEMS) notes.push(`分组「${group.title}」超过 ${MAX_GROUP_ITEMS} 条：仅保留前 ${MAX_GROUP_ITEMS} 条`);
      } else {
        notes.push(`分组已达上限 ${MAX_RECOMMENDED_GROUPS} 个：「${group.title}」未添加`);
      }
    }

    // 普通条目按弹窗选择的目标落位
    let addedItems = 0;
    if (parsed.items.length > 0) {
      if (destGroupIdx >= 0) {
        const room = Math.max(0, MAX_GROUP_ITEMS - nextGroups[destGroupIdx].items.length);
        addedItems = Math.min(parsed.items.length, room);
        if (parsed.items.length > room) notes.push(`分组「${bulkDest}」已达上限 ${MAX_GROUP_ITEMS} 条：仅添加 ${room} 条，其余忽略`);
        if (addedItems > 0) {
          nextGroups[destGroupIdx] = {
            ...nextGroups[destGroupIdx],
            items: [...nextGroups[destGroupIdx].items, ...parsed.items.slice(0, addedItems).map((it) => ({ ...it }))],
          };
        }
      } else {
        const room = Math.max(0, MAX_RECOMMENDED_ITEMS - nextItems.length);
        addedItems = Math.min(parsed.items.length, room);
        if (parsed.items.length > room) notes.push(`已达上限 ${MAX_RECOMMENDED_ITEMS} 条：仅添加 ${room} 条，其余忽略`);
        nextItems.push(...parsed.items.slice(0, addedItems).map((it) => ({ ...it })));
      }
    }

    set({ recommendedItems: nextItems, recommendedGroups: nextGroups });
    // 有新内容的分区自动展开，用户能立即看到落位结果
    if (addedItems > 0) openSection(destGroupIdx >= 0 ? groupSectionKey(nextGroups[destGroupIdx].title) : UNGROUPED_SECTION_KEY);
    for (const title of touchedGroupTitles) openSection(groupSectionKey(title));
    if (notes.length) {
      toast.warning(notes.join('；'));
    } else {
      const parts: string[] = [];
      if (addedItems > 0) parts.push(`${addedItems} 条推荐项`);
      if (addedGroups > 0) parts.push(`${addedGroups} 个分组`);
      if (parts.length > 0) toast.success(`已添加 ${parts.join(' + ')}`);
    }
    setBulkOpen(false);
    setBulkText('');
  };

  // 批量弹窗容量预览：普通条目按目标容量、分组按同名并入/新建名额粗估
  const bulkDestGroupIdx = bulkDest === UNGROUPED_VALUE
    ? -1
    : recommendedGroups.findIndex((g) => g.title === bulkDest);
  const bulkItemRoom = bulkDestGroupIdx >= 0
    ? Math.max(0, MAX_GROUP_ITEMS - (recommendedGroups[bulkDestGroupIdx]?.items.length ?? 0))
    : Math.max(0, MAX_RECOMMENDED_ITEMS - recommendedItems.length);
  const bulkGroupRoom = Math.max(0, MAX_RECOMMENDED_GROUPS - recommendedGroups.length);
  const bulkNewGroupCount = bulkParsed.groups.filter((g) => !recommendedGroups.some((x) => x.title === g.title)).length;

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      {/* Scrollable form column — owns its own padding because content_stage
          renders p-0/overflow-hidden when the editor is open (see App.tsx). */}
      <div className="flex-1 min-h-0 overflow-y-auto max-w-3xl w-full mx-auto px-6 py-6 space-y-4">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button onClick={onBack} className="p-1.5 rounded-lg text-[#a1a1aa] hover:text-white hover:bg-[#27272a] transition cursor-pointer">
              <ArrowLeft className="w-4 h-4" />
            </button>
            <div>
              <div className="flex items-center gap-2 text-xs text-[#71717a]">
                <Bot className="w-3.5 h-3.5" />
                <span>智能体</span><span>/</span>
                <span className="text-white font-semibold">{form.name || '未命名'}</span>
              </div>
              <h2 className="text-sm font-bold text-white mt-0.5">编辑 Agent 配置</h2>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {isPublished ? (
              <button
                onClick={() => archiveM.mutate()}
                disabled={archiveM.isPending}
                className="flex items-center gap-1.5 px-3 py-1.5 border border-[#27272a] hover:bg-[#27272a] text-[#a1a1aa] hover:text-white rounded-lg text-xs font-semibold transition cursor-pointer disabled:opacity-60"
              >
                {archiveM.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Archive className="w-3.5 h-3.5" />}
                归档
              </button>
            ) : (
              <button
                onClick={() => publishM.mutate()}
                disabled={publishM.isPending}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 text-white rounded-lg text-xs font-semibold transition cursor-pointer disabled:opacity-60"
              >
                {publishM.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Rocket className="w-3.5 h-3.5" />}
                发布
              </button>
            )}
          </div>
        </div>

        {/* ── Section: 基本信息 ── */}
        <Section title="基本信息" icon={<Bot className="w-3.5 h-3.5" />} defaultOpen>
          <Field label="智能体名称 *">
            <input className={inputCls} value={form.name} onChange={(e) => set({ name: e.target.value })} />
          </Field>
          <Field label="头像">
            <AvatarField value={form.avatar} entityId={agentId} onChange={(url) => set({ avatar: url })} />
          </Field>
          <Field label="职责描述">
            <input className={inputCls} value={form.description} onChange={(e) => set({ description: e.target.value })} placeholder="这个 Agent 专门解决什么问题…" />
          </Field>
          <button
            type="button"
            role="switch"
            aria-checked={form.voiceEnabled}
            onClick={() => set({ voiceEnabled: !form.voiceEnabled })}
            className="flex min-h-11 w-full items-center justify-between gap-4 rounded-lg border border-[#27272a] bg-[#121214] px-3 py-2 text-left transition-colors duration-200 hover:border-[#3f3f46] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 cursor-pointer"
          >
            <span className="flex min-w-0 items-center gap-2.5">
              <Mic className={`h-4 w-4 shrink-0 ${form.voiceEnabled ? 'text-sky-400' : 'text-[#71717a]'}`} />
              <span>
                <span className="block text-xs font-semibold text-[#f4f4f5]">允许语音对话</span>
                <span className="mt-0.5 block text-[11px] leading-relaxed text-[#71717a]">
                  还需配置全局语音凭证，两个条件满足后才显示麦克风入口。
                </span>
              </span>
            </span>
            <span
              className={`relative h-6 w-11 shrink-0 rounded-full border transition-colors duration-200 ${
                form.voiceEnabled
                  ? 'border-sky-400 bg-sky-500'
                  : 'border-[#52525b] bg-[#27272a]'
              }`}
              aria-hidden="true"
            >
              <span
                className={`absolute top-0.5 h-4.5 w-4.5 rounded-full bg-white shadow-sm transition-transform duration-200 ${
                  form.voiceEnabled ? 'translate-x-5' : 'translate-x-0.5'
                }`}
              />
            </span>
          </button>
        </Section>

        {/* ── Section: Prompt 配置 ── */}
        <Section title="Prompt 配置" icon={<Cpu className="w-3.5 h-3.5" />} defaultOpen>
          <Field label="角色定义 *（Role — 必填）">
            <textarea rows={2} className={`${inputCls} font-mono text-xs placeholder-[#52525b]`} placeholder="如：你是一位资深产品经理…" value={form.rolePrompt ?? ''} onChange={(e) => set({ rolePrompt: e.target.value })} />
          </Field>
          <Field label="任务描述 *（Task — 必填）">
            <textarea rows={3} className={`${inputCls} font-mono text-xs placeholder-[#52525b]`} placeholder="如：根据用户需求，输出功能拆解与优先级。" value={form.taskPrompt ?? ''} onChange={(e) => set({ taskPrompt: e.target.value })} />
          </Field>
          <div className="grid grid-cols-1 gap-4">
            <Field label="约束规则（Constraints · 可选）">
              <textarea rows={2} className={`${inputCls} font-mono text-xs placeholder-[#52525b]`} placeholder="如：回答必须用中文；不臆测。" value={form.constraintsPrompt ?? ''} onChange={(e) => set({ constraintsPrompt: e.target.value })} />
            </Field>
            <Field label="上下文信息（Context · 可选）">
              <textarea rows={2} className={`${inputCls} font-mono text-xs placeholder-[#52525b]`} placeholder="如：当前项目 meper-agent，技术栈 React+FastAPI。" value={form.contextPrompt ?? ''} onChange={(e) => set({ contextPrompt: e.target.value })} />
            </Field>
            <Field label="输出格式（Output Format · 可选）">
              <textarea rows={2} className={`${inputCls} font-mono text-xs placeholder-[#52525b]`} placeholder="如：用 Markdown 表格输出。" value={form.outputFormatPrompt ?? ''} onChange={(e) => set({ outputFormatPrompt: e.target.value })} />
            </Field>
            <Field label="补充说明（System Prompt · 可选）">
              <textarea rows={3} className={`${inputCls} font-mono text-xs`} value={form.systemPrompt} onChange={(e) => set({ systemPrompt: e.target.value })} />
            </Field>
          </div>
        </Section>

        {/* ── Section: 欢迎与引导（终端用户首屏） ── */}
        <Section title="欢迎与引导" icon={<Sparkles className="w-3.5 h-3.5" />} defaultOpen={false}>
          <Field label="欢迎词（Markdown，展示在终端用户首屏）">
            <textarea rows={3} className={`${inputCls} text-xs`} placeholder="如：你好！我是销售助理，可以问我业绩、客户、订单等相关问题。" value={form.welcomeMessage ?? ''} onChange={(e) => set({ welcomeMessage: e.target.value })} />
            <div className="text-[11px] text-slate-500 mt-1">留空则使用默认欢迎语。支持 Markdown 语法（加粗、列表等）。</div>
          </Field>
          <Field label="推荐问题 / 操作（终端用户可一键点击发送）">
            <div className="space-y-3">
              {/* ── 分区列表：未分组（终端独立展示）+ 各分组；条目展开后在「所属分组」归类 ── */}
              <div className="max-h-[520px] overflow-y-auto space-y-3 pr-1">
                <div className="space-y-1.5">
                  <button
                    type="button"
                    className="flex w-full items-center gap-2 text-left cursor-pointer"
                    onClick={() => toggleSection(UNGROUPED_SECTION_KEY)}
                    title={openSections.has(UNGROUPED_SECTION_KEY) ? '收起' : '展开'}
                  >
                    {openSections.has(UNGROUPED_SECTION_KEY)
                      ? <ChevronDown className="w-3 h-3 text-[#71717a] shrink-0" />
                      : <ChevronRight className="w-3 h-3 text-[#71717a] shrink-0" />}
                    <Folder className="w-3 h-3 text-amber-400/80 shrink-0" />
                    <span className="text-[11px] font-semibold text-[#a1a1aa]">未分组</span>
                    <span className="text-[10px] text-[#71717a] font-mono ml-auto shrink-0">{recommendedItems.length} / {MAX_RECOMMENDED_ITEMS}</span>
                  </button>
                  {openSections.has(UNGROUPED_SECTION_KEY) && recommendedItems.map((item, idx) => (
                      <RecommendedItemCard
                        key={idx}
                        index={idx}
                        item={item}
                        expanded={expandedItems.has(idx)}
                        onToggle={() => toggleItemExpanded(idx)}
                        onRemove={() => removeItem(idx)}
                        onUpdate={(patch) => updateItem(idx, patch)}
                        groupValue={UNGROUPED_VALUE}
                        groupOptions={[
                          { value: UNGROUPED_VALUE, label: '未分组（独立展示）' },
                          ...recommendedGroups.map((g) => ({
                            value: g.title,
                            label: g.title,
                            disabled: g.items.length >= MAX_GROUP_ITEMS,
                          })),
                        ]}
                        onAssignGroup={(v) =>
                          assignItemGroup(-1, idx, v === UNGROUPED_VALUE ? -1 : recommendedGroups.findIndex((g) => g.title === v))
                        }
                      />
                    ))}
                </div>
                {recommendedGroups.map((group, gIdx) => {
                  const sectionKey = groupSectionKey(group.title);
                  const sectionOpen = openSections.has(sectionKey);
                  return (
                    <div key={`section:${gIdx}`} className="space-y-1.5">
                      <div className="flex items-center gap-1.5">
                        {renamingGroup === gIdx ? (
                          <>
                            <Folder className="w-3 h-3 text-amber-400/80 shrink-0" />
                            <input
                              autoFocus
                              className="h-6 flex-1 min-w-0 px-2 rounded border border-amber-500/50 bg-[#121214] text-amber-200 text-[11px] focus:outline-none focus:border-amber-400"
                              value={renameText}
                              maxLength={GROUP_TITLE_MAX}
                              onChange={(e) => setRenameText(e.target.value)}
                              onBlur={commitRenameGroup}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') commitRenameGroup();
                                if (e.key === 'Escape') setRenamingGroup(null);
                              }}
                            />
                          </>
                        ) : (
                          <button
                            type="button"
                            className="flex flex-1 min-w-0 items-center gap-2 text-left cursor-pointer"
                            onClick={() => toggleSection(sectionKey)}
                            title={sectionOpen ? '收起' : '展开'}
                          >
                            {sectionOpen
                              ? <ChevronDown className="w-3 h-3 text-[#71717a] shrink-0" />
                              : <ChevronRight className="w-3 h-3 text-[#71717a] shrink-0" />}
                            <Folder className="w-3 h-3 text-amber-400/80 shrink-0" />
                            <span className="text-[11px] font-semibold text-[#a1a1aa] truncate">{group.title}</span>
                            <span className="text-[10px] text-[#71717a] font-mono ml-auto shrink-0">{group.items.length} / {MAX_GROUP_ITEMS}</span>
                          </button>
                        )}
                        {renamingGroup !== gIdx && (
                          <>
                            <button
                              type="button"
                              className="flex items-center justify-center w-5 h-5 rounded-full text-[#a1a1aa] hover:text-white hover:bg-[#27272a] cursor-pointer shrink-0"
                              title="重命名"
                              onClick={() => beginRenameGroup(gIdx)}
                            >
                              <Pencil className="w-2.5 h-2.5" />
                            </button>
                            <button
                              type="button"
                              className="flex items-center justify-center w-5 h-5 rounded-full text-[#a1a1aa] hover:text-rose-400 hover:bg-rose-500/10 cursor-pointer shrink-0"
                              title={`删除分组（${group.items.length} 条移入未分组）`}
                              onClick={() => removeGroup(gIdx)}
                            >
                              <X className="w-3 h-3" />
                            </button>
                          </>
                        )}
                      </div>
                      {sectionOpen && group.items.map((item, iIdx) => (
                      <RecommendedItemCard
                        key={`${gIdx}:${iIdx}`}
                        index={iIdx}
                        item={item}
                        expanded={expandedGroupItems.has(`${gIdx}:${iIdx}`)}
                        onToggle={() => toggleGroupItemExpanded(`${gIdx}:${iIdx}`)}
                        onRemove={() => removeGroupItem(gIdx, iIdx)}
                        onUpdate={(patch) => updateGroupItem(gIdx, iIdx, patch)}
                        groupValue={group.title}
                        groupOptions={[
                          {
                            value: UNGROUPED_VALUE,
                            label: '未分组（独立展示）',
                            disabled: recommendedItems.length >= MAX_RECOMMENDED_ITEMS,
                          },
                          ...recommendedGroups.map((g) => ({
                            value: g.title,
                            label: g.title,
                            disabled: g.title !== group.title && g.items.length >= MAX_GROUP_ITEMS,
                          })),
                        ]}
                        onAssignGroup={(v) =>
                          assignItemGroup(gIdx, iIdx, v === UNGROUPED_VALUE ? -1 : recommendedGroups.findIndex((g) => g.title === v))
                        }
                      />
                      ))}
                    </div>
                  );
                })}
              </div>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={addItem}
                  disabled={recommendedItems.length >= MAX_RECOMMENDED_ITEMS}
                  className="flex items-center gap-1.5 px-3 py-1.5 border border-[#27272a] hover:bg-[#27272a] text-[#a1a1aa] hover:text-white rounded-lg text-xs font-semibold transition cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <Plus className="w-3.5 h-3.5" /> 添加推荐项
                </button>
                <button
                  type="button"
                  onClick={openBulk}
                  className="flex items-center gap-1.5 px-3 py-1.5 border border-[#27272a] hover:bg-[#27272a] text-[#a1a1aa] hover:text-white rounded-lg text-xs font-semibold transition cursor-pointer"
                >
                  <ListPlus className="w-3.5 h-3.5" /> 批量添加
                </button>
                <button
                  type="button"
                  onClick={openCreateGroup}
                  disabled={recommendedGroups.length >= MAX_RECOMMENDED_GROUPS}
                  className="flex items-center gap-1.5 px-3 py-1.5 border border-[#27272a] hover:bg-[#27272a] text-[#a1a1aa] hover:text-white rounded-lg text-xs font-semibold transition cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <Plus className="w-3.5 h-3.5" /> 新建分组
                </button>
                <span className="text-[10px] text-[#71717a] font-mono ml-auto">{recommendedGroups.length} / {MAX_RECOMMENDED_GROUPS} 组</span>
              </div>
              <div className="text-[11px] text-slate-500">
                分组：最多 {MAX_RECOMMENDED_GROUPS} 组、每组 {MAX_GROUP_ITEMS} 条；未分组：最多 {MAX_RECOMMENDED_ITEMS} 条。点击分区头展开/收起，条目展开后在「所属分组」归类；✏ 重命名、× 删除分组。未分组条目在终端独立展示，分组在终端收进组按钮按需展开。
              </div>
            </div>
          </Field>
        </Section>

        {/* ── Section: 执行参数 ── */}
        <Section title="执行参数" icon={<RefreshCw className="w-3.5 h-3.5" />} defaultOpen>
          <Field label="推理模型">
            <Select
              value={form.model || null}
              onChange={(v) => set({ model: v ?? '' })}
              placeholder={activeModels.length === 0 ? '暂无可用模型，请先在模型配置页添加' : '— 未选择 —'}
              groups={modelGroups}
            />
          </Field>
          <Field label={`思维活性 Temperature: ${form.temperature}`}>
            <input type="range" min="0" max="1.0" step="0.1" value={form.temperature} onChange={(e) => set({ temperature: parseFloat(e.target.value) })} className="w-full accent-indigo-500 cursor-pointer" />
          </Field>
          <Field label="最大重试次数（0-10）">
            <input type="number" min="0" max="10" className={`${inputCls} font-mono`} value={form.maxRetry ?? 3} onChange={(e) => set({ maxRetry: Math.max(0, Math.min(10, Number(e.target.value) || 0)) })} />
          </Field>
          <Field label="会话 Token 上限（0 = 全局默认）">
            <input type="number" min="0" max="10000000" step="10000" className={`${inputCls} font-mono`} value={form.maxTokens ?? 0} onChange={(e) => set({ maxTokens: Math.max(0, Number(e.target.value) || 0) })} placeholder="0 = 使用全局默认" />
            <div className="text-[11px] text-slate-500 mt-1">单次会话累计 Token 上限，超出后 Agent 自动停止。0 表示使用全局默认值（200000）。</div>
          </Field>
        </Section>

        {/* ── Section: 工具绑定 ── */}
        <Section title="工具绑定" icon={<Wrench className="w-3.5 h-3.5" />} defaultOpen>
          <ToolGroup title="内置工具 (Built-in)" hint={builtinTools.length === 0 ? '后端无内置工具' : undefined}>
            {builtinTools.map((t) => (
              <ToolChip key={`builtin:${t.name}`} label={t.name} checked={form.skills.includes(`builtin:${t.name}`)} onToggle={() => set({ skills: toggleSkill(form.skills, `builtin:${t.name}`) })} />
            ))}
          </ToolGroup>
          <ToolGroup title="技能 (Skills)" hint={skillTools.length === 0 ? '无已上传技能' : undefined}>
            {skillTools.map((t) => (
              <ToolChip key={t.id} label={t.name} checked={form.skills.includes(t.id)} onToggle={() => set({ skills: toggleSkill(form.skills, t.id) })} />
            ))}
          </ToolGroup>
          <ToolGroup title="MCP 连接" hint={mcpConnections.length === 0 ? '无 MCP 连接' : undefined}>
            {mcpConnections.map((c) => (
              <ToolChip key={`mcp:${c.id}`} label={c.name} checked={form.skills.includes(`mcp:${c.id}`)} onToggle={() => set({ skills: toggleSkill(form.skills, `mcp:${c.id}`) })} />
            ))}
          </ToolGroup>
          <ToolGroup title="工作流 (Workflows)" hint={workflows.length === 0 ? '无工作流' : undefined}>
            {workflows.map((w) => (
              <ToolChip key={w.id} label={w.name} checked={form.skills.includes(`workflow:${w.id}`)} onToggle={() => set({ skills: toggleSkill(form.skills, `workflow:${w.id}`) })} />
            ))}
          </ToolGroup>
          <ToolGroup title="知识库 (Knowledge Base)" hint={knowledgeBases.length === 0 ? '无知识库' : undefined}>
            {knowledgeBases.map((kb) => (
              <ToolChip key={`kb:${kb.id}`} label={kb.name} checked={form.skills.includes(`kb:${kb.id}`)} onToggle={() => set({ skills: toggleSkill(form.skills, `kb:${kb.id}`) })} />
            ))}
          </ToolGroup>
          <ToolGroup title="自定义工具 (OpenAPI / Code)" hint={customToolCandidates.length === 0 ? '暂无已开启的工具——需在工具库中开启' : undefined}>
            {customToolCandidates.map((c) => (
              <ToolChip
                key={c.id}
                label={c.name}
                checked={(form.customTools ?? []).some((b) => b.tool_id === c.id)}
                onToggle={() => handleCustomToggle(c.id)}
              />
            ))}
          </ToolGroup>
        </Section>

      </div>

      {/* Footer save bar — a flex sibling of the scroll area, so it is pinned
          flush to the bottom of the main column with no gap. bg-[#09090b] and
          border-[#27272a] are theme-aware via the index.css overrides. */}
      <div className="shrink-0 border-t border-[#27272a] bg-[#09090b] px-6 py-3">
        <div className="max-w-3xl mx-auto flex justify-end gap-3">
          <button onClick={onBack} className="px-4 py-2 border border-[#27272a] hover:bg-[#18181b] text-[#a1a1aa] hover:text-white rounded-lg cursor-pointer font-semibold text-xs">
            取消
          </button>
          <button
            onClick={handleSave}
            disabled={updateM.isPending}
            className="flex items-center gap-2 px-5 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg cursor-pointer font-semibold text-xs disabled:opacity-60"
          >
            {updateM.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
            保存配置
          </button>
        </div>
      </div>

      {/* 批量添加推荐项弹窗（目标在弹窗内选择；分组 JSON 同名并入、异名新建） */}
      <Modal
        open={bulkOpen}
        title="批量添加推荐项"
        onOk={handleBulkAdd}
        onCancel={() => setBulkOpen(false)}
        okText={`添加${bulkParsed.items.length > 0 ? ` ${bulkParsed.items.length} 条` : ''}${bulkParsed.groups.length > 0 ? ` ${bulkParsed.groups.length} 组` : ''}`}
        okButtonProps={{ disabled: bulkParsed.items.length === 0 && bulkParsed.groups.length === 0 }}
        width={560}
      >
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <span className="text-[11px] text-[#71717a] shrink-0">添加到</span>
            <Select
              value={bulkDest}
              onChange={(v) => setBulkDest(v ?? UNGROUPED_VALUE)}
              options={[
                { value: UNGROUPED_VALUE, label: '未分组（独立展示）', disabled: recommendedItems.length >= MAX_RECOMMENDED_ITEMS },
                ...recommendedGroups.map((g) => ({
                  value: g.title,
                  label: g.title,
                  disabled: g.items.length >= MAX_GROUP_ITEMS,
                })),
              ]}
              size="small"
              className="flex-1"
              showSearch={false}
            />
          </div>
          <div className="text-[11px] text-[#71717a] leading-relaxed">
            自动识别格式，直接粘贴即可：
            <br />① 纯文本 — 每行一条 <code className="text-indigo-300">{'显示文案 | 实际发送内容'}</code>，不需要 []，不含 | 时整行即显示文案；
            <br />② JSON — 整段数组，或每行一个 <code className="text-indigo-300">{'{"label":"…","prompt":"…"}'}</code> 对象（[] 可省略，prompt 可省略）；
            <br />③ 分组 — 对象形如 <code className="text-indigo-300">{'{"title":"分组名","items":[…]}'}</code>（title 必填 ≤{GROUP_TITLE_MAX} 字符），同名分组直接并入、否则新建；普通条目按上方「添加到」落位。
          </div>
          <textarea
            rows={8}
            className={`${inputCls} font-mono text-xs`}
            placeholder={'导出本月报表 | 帮我导出 2026 年 8 月的销售报表\n写一份周报\n\n也可粘贴 JSON：{"label": "导出本月报表", "prompt": "帮我导出 2026 年 8 月的销售报表"}\n或分组：{"title": "销售查询", "items": [{"label": "查业绩"}]}'}
            value={bulkText}
            onChange={(e) => setBulkText(e.target.value)}
          />
          {bulkText.trim() && (
            <div className="text-[11px] leading-relaxed">
              {(bulkParsed.items.length > 0 || bulkParsed.groups.length > 0) ? (
                <span className="text-emerald-400">
                  解析出 {bulkParsed.items.length} 条{bulkParsed.groups.length > 0 ? ` + ${bulkParsed.groups.length} 个分组` : ''}（{bulkParsed.mode === 'json' ? 'JSON 格式' : '逐行文本格式'}）
                  {(bulkParsed.items.length > bulkItemRoom || bulkNewGroupCount > bulkGroupRoom) && (
                    <span className="text-amber-400">，超出上限部分将忽略</span>
                  )}
                </span>
              ) : (
                <span className="text-rose-400">未解析出有效条目，请检查格式</span>
              )}
              {bulkParsed.invalidCount > 0 && (
                <span className="text-amber-400">
                  {' '}{bulkParsed.invalidCount} 条格式无效已跳过（label 必填 ≤{RECOMMENDED_LABEL_MAX} 字符，prompt ≤{RECOMMENDED_PROMPT_MAX} 字符，分组名 ≤{GROUP_TITLE_MAX} 字符）
                </span>
              )}
            </div>
          )}
        </div>
      </Modal>

      {/* 新建分组弹窗 */}
      <Modal
        open={createGroupOpen}
        title="新建分组"
        onOk={handleCreateGroup}
        onCancel={() => setCreateGroupOpen(false)}
        okText="创建"
        okButtonProps={{ disabled: !createGroupText.trim() || recommendedGroups.length >= MAX_RECOMMENDED_GROUPS }}
        width={420}
      >
        <div className="space-y-3">
          <input
            autoFocus
            className={inputCls}
            placeholder={`分组名（≤${GROUP_TITLE_MAX} 字符），如：销售查询`}
            value={createGroupText}
            maxLength={GROUP_TITLE_MAX}
            onChange={(e) => setCreateGroupText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') handleCreateGroup();
            }}
          />
          <div className="text-[11px] text-[#71717a]">
            新建后可在推荐项的「所属分组」中选用，或用批量添加按分组导入。当前 {recommendedGroups.length} / {MAX_RECOMMENDED_GROUPS} 组。
          </div>
        </div>
      </Modal>
    </div>
  );
}

// ── Sub-components ──

type BulkItem = { label: string; prompt: string };

// 推荐项约束 — 与后端 RecommendedItem / recommended_items max_length 保持一致
const RECOMMENDED_LABEL_MAX = 100;
const RECOMMENDED_PROMPT_MAX = 500;
const MAX_RECOMMENDED_ITEMS = 200;
// 分组约束 — 与后端 RecommendedGroup / recommended_groups max_length 保持一致
const GROUP_TITLE_MAX = 50;
const MAX_GROUP_ITEMS = 50;
const MAX_RECOMMENDED_GROUPS = 20;

/** 「所属分组」选项中「未分组」的哨兵值；分组名禁止取该值（创建/重命名/批量解析均已拦截）。 */
const UNGROUPED_VALUE = '__none__';

/** 分区折叠状态 key：未分组固定 key，分组用标题（全局唯一，删除/移动无需平移索引）。 */
const UNGROUPED_SECTION_KEY = '__ungrouped__';
const groupSectionKey = (title: string) => `g:${title}`;

/** 推荐项编辑卡片：折叠显示摘要，展开编辑 label/prompt/所属分组（未分组与组内共用）。 */
function RecommendedItemCard({
  index, item, expanded, onToggle, onRemove, onUpdate, groupValue, groupOptions, onAssignGroup,
}: {
  index: number;
  item: BulkItem;
  expanded: boolean;
  onToggle: () => void;
  onRemove: () => void;
  onUpdate: (patch: Partial<BulkItem>) => void;
  /** 当前所属分组名，未分组为 UNGROUPED_VALUE */
  groupValue: string;
  /** 所属分组选项（含未分组），满员目标由调用方置 disabled */
  groupOptions: { value: string; label: string; disabled?: boolean }[];
  onAssignGroup: (value: string) => void;
}) {
  return (
    <div className="rounded-lg border border-[#27272a] bg-[#121214]">
      <div className="flex items-center gap-2 px-2.5 py-2">
        <button
          type="button"
          onClick={onToggle}
          className="flex flex-1 min-w-0 items-center gap-2 text-left cursor-pointer"
          title={expanded ? '收起' : '展开编辑'}
        >
          {expanded
            ? <ChevronDown className="w-3.5 h-3.5 text-[#71717a] shrink-0" />
            : <ChevronRight className="w-3.5 h-3.5 text-[#71717a] shrink-0" />}
          <span className="text-[10px] text-[#71717a] font-mono shrink-0">#{index + 1}</span>
          <span className={`text-xs truncate shrink-0 max-w-[240px] ${item.label ? 'text-white' : 'text-[#52525b] italic'}`}>
            {item.label || '（未填写）'}
          </span>
          <span className="text-[11px] text-[#71717a] truncate">
            {item.prompt ? `· ${item.prompt}` : '· 点击直接发送显示文案'}
          </span>
        </button>
        <button type="button" onClick={onRemove} className="flex items-center gap-1 text-[#ef4444] text-[10px] hover:underline cursor-pointer shrink-0">
          <Trash2 className="w-3 h-3" /> 删除
        </button>
      </div>
      {expanded && (
        <div className="px-3 pb-3 space-y-2">
          <input className={inputCls} placeholder="显示文案（必填），如：导出本月报表" value={item.label} onChange={(e) => onUpdate({ label: e.target.value })} />
          <input className={inputCls} placeholder="实际发送内容（留空则同显示文案）" value={item.prompt} onChange={(e) => onUpdate({ prompt: e.target.value })} />
          <div className="flex items-center gap-2">
            <span className="text-[11px] text-[#71717a] shrink-0">所属分组</span>
            <Select
              value={groupValue}
              onChange={(v) => onAssignGroup(v ?? UNGROUPED_VALUE)}
              options={groupOptions}
              size="small"
              className="flex-1"
              showSearch={false}
            />
          </div>
        </div>
      )}
    </div>
  );
}

/**
 * 解析批量输入的推荐项，自动识别格式：
 * ① 整段 JSON 数组（以 [ 开头）；
 * ② 每行一个 JSON 对象（可省略外层 []）；
 * ③ 每行一条纯文本（label | prompt，无 | 则整行为 label）。
 * JSON 对象含 {title, items} 时识别为分组（始终新建，由调用方落位）。
 * 返回普通条目 + 分组 + 被跳过的无效条数，供弹窗实时预览。
 */
function parseBulkRecommendedItems(text: string): {
  items: BulkItem[];
  groups: { title: string; items: BulkItem[] }[];
  invalidCount: number;
  mode: 'json' | 'lines' | 'none';
} {
  const trimmed = text.trim();
  if (!trimmed) return { items: [], groups: [], invalidCount: 0, mode: 'none' };

  const validate = (label: unknown, prompt: unknown): BulkItem | null => {
    if (typeof label !== 'string') return null;
    const l = label.trim();
    const p = typeof prompt === 'string' ? prompt.trim() : '';
    if (!l || l.length > RECOMMENDED_LABEL_MAX || p.length > RECOMMENDED_PROMPT_MAX) return null;
    return { label: l, prompt: p };
  };

  // {title, items} 对象 → 分组：title 必填 ≤GROUP_TITLE_MAX 且非保留字，组内条目逐条校验（无效计入 invalidCount）
  const validateGroup = (row: Record<string, unknown>): { group: { title: string; items: BulkItem[] }; invalidCount: number } | null => {
    if (typeof row.title !== 'string' || !Array.isArray(row.items)) return null;
    const title = row.title.trim();
    if (!title || title.length > GROUP_TITLE_MAX || title === UNGROUPED_VALUE) return null;
    const items: BulkItem[] = [];
    let invalidCount = 0;
    for (const entry of row.items) {
      const rec = (entry ?? {}) as Record<string, unknown>;
      const item = validate(rec.label, rec.prompt);
      if (item) items.push(item);
      else invalidCount++;
    }
    return { group: { title, items }, invalidCount };
  };

  // ① 整段 JSON 数组
  if (trimmed.startsWith('[')) {
    try {
      const parsed: unknown = JSON.parse(trimmed);
      if (Array.isArray(parsed)) {
        const items: BulkItem[] = [];
        const groups: { title: string; items: BulkItem[] }[] = [];
        let invalidCount = 0;
        for (const row of parsed) {
          const rec = (row ?? {}) as Record<string, unknown>;
          const groupResult = validateGroup(rec);
          if (groupResult) {
            groups.push(groupResult.group);
            invalidCount += groupResult.invalidCount;
            continue;
          }
          const item = validate(rec.label, rec.prompt);
          if (item) items.push(item);
          else invalidCount++;
        }
        return { items, groups, invalidCount, mode: 'json' };
      }
      // 合法 JSON 但不是数组 — 整体无效
      return { items: [], groups: [], invalidCount: 1, mode: 'json' };
    } catch {
      // 非法 JSON → 回退逐行解析
    }
  }

  // ②/③ 逐行解析：{ 开头尝试单行 JSON 对象（含分组对象），否则按 label | prompt 文本
  const items: BulkItem[] = [];
  const groups: { title: string; items: BulkItem[] }[] = [];
  let invalidCount = 0;
  let jsonLines = 0;
  for (const line of trimmed.split('\n')) {
    const l = line.trim();
    if (!l) continue;
    if (l.startsWith('{')) {
      try {
        const row = JSON.parse(l) as Record<string, unknown>;
        const groupResult = validateGroup(row);
        if (groupResult) {
          groups.push(groupResult.group);
          invalidCount += groupResult.invalidCount;
          jsonLines++;
          continue;
        }
        const item = validate(row?.label, row?.prompt);
        if (item) {
          items.push(item);
          jsonLines++;
          continue;
        }
        invalidCount++; // JSON 对象但字段无效（缺 label 等）
        continue;
      } catch {
        invalidCount++; // 以 { 开头但不是合法 JSON — 视为无效而非怪异文本
        continue;
      }
    }
    const sep = l.indexOf('|');
    const item = validate(sep >= 0 ? l.slice(0, sep) : l, sep >= 0 ? l.slice(sep + 1) : '');
    if (item) items.push(item);
    else invalidCount++;
  }
  return {
    items,
    groups,
    invalidCount,
    mode: jsonLines > 0 && jsonLines === items.length + groups.length ? 'json' : 'lines',
  };
}

/** Collapsible section with a title bar. */
const Section: FC<{ title: string; icon?: ReactNode; defaultOpen?: boolean; children: ReactNode }> = ({
  title, icon, defaultOpen = false, children,
}) => {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-xl border border-[#27272a] bg-[#18181b] overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2 px-4 py-3 text-left cursor-pointer hover:bg-[#1c1c1f] transition"
      >
        {open ? <ChevronDown className="w-4 h-4 text-[#71717a]" /> : <ChevronRight className="w-4 h-4 text-[#71717a]" />}
        {icon && <span className="text-indigo-400">{icon}</span>}
        <span className="text-sm font-bold text-white">{title}</span>
      </button>
      {open && <div className="px-4 pb-4 space-y-4">{children}</div>}
    </div>
  );
};

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="space-y-1">
      <label className="text-slate-400 font-semibold text-xs font-sans">{label}</label>
      {children}
    </div>
  );
}

/** Toggle a prefixed skill token in/out of the skills array. */
function toggleSkill(skills: string[], token: string): string[] {
  return skills.includes(token) ? skills.filter((s) => s !== token) : [...skills, token];
}

const ToolGroup: FC<{ title: string; hint?: string; children: ReactNode }> = ({ title, hint, children }) => (
  <div className="p-3 rounded-lg bg-[#121214] border border-[#27272a]">
    <p className="text-[10px] text-[#71717a] uppercase tracking-wider font-bold mb-2">{title}</p>
    {hint ? <p className="text-[11px] text-[#52525b] italic">{hint}</p> : <div className="flex flex-wrap gap-1.5">{children}</div>}
  </div>
);
const ToolChip: FC<{ label: string; checked: boolean; onToggle: () => void }> = ({ label, checked, onToggle }) => (
  <button
    type="button"
    onClick={onToggle}
    className={`px-2.5 py-1 rounded-lg text-[11px] font-semibold border transition cursor-pointer select-none ${
      checked ? 'bg-indigo-600 border-indigo-500 text-white' : 'bg-[#18181b] border-[#27272a] text-[#a1a1aa] hover:text-white hover:border-[#52525b]'
    }`}
  >
    {checked ? '✓ ' : ''}{label}
  </button>
);

/* ── 自定义工具绑定 ── */

interface CustomToolCandidate {
  id: string;
  name: string;
  source: string;
}

/**
 * 单个已绑定自定义工具的 user_args 表单——按 user_args_schema 渲染。
 *
 * 回显脱敏：已加密值（enc: 前缀）显示空 + placeholder「已设置」，未改动
 * 则保留原值提交（后端不重复加密）；输入新值即覆盖。
 * 用户工具（uto_）的 schema 在详情里，按需查询。
 */

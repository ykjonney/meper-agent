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
import { useState, useEffect, useMemo, useRef, type FC, type ReactNode } from 'react';
import {
  ArrowLeft, Bot, Save, Loader2, Rocket, Archive, RefreshCw, Cpu, Wrench,
  ChevronDown, ChevronRight, Sparkles, Plus, Trash2, Mic, ListPlus, Folder, X, Pencil,
  Search, Check,
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
import { IconAgent, IconWrench, IconSkill, IconPlug, IconBook, IconSubAgent, IconChip, IconVoice } from './IndigoIcons';
import type { Agent } from '../types';
import AvatarField, { type AvatarFieldHandle } from './AvatarField';

/* 输入框统一定稿 inline-field 修订线语言：透明无边框就地编辑，聚焦时品牌淡底
   + 右侧圆角（左缘修订线由字段容器 border-l-2 承担）——禁用 SaaS 白底边框矩形 */
const inputCls =
  'w-full px-0 py-1.5 bg-transparent border-0 outline-none text-ink placeholder:text-ink-faint focus:bg-brand-soft/40 rounded-r-lg transition font-sans resize-none';

/** 节标：靛蓝衬线章节符 § + 衬线斜体标题——纸墨文书的分节语言，
    替代修订线（border-l-2）与幽灵小字标签，节与节靠留白呼吸。 */
function SectionMark({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="flex items-baseline gap-2.5 mb-3.5">
      <span aria-hidden className="font-serif italic text-brand text-[17px] leading-none select-none">§</span>
      <span className="font-serif italic text-[15px] font-semibold text-ink leading-none">{title}</span>
      {hint && <span className="text-[10px] text-ink-faint">{hint}</span>}
    </div>
  );
}

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

  // 可委派子 Agent 候选：published Agents（排除自身——委派池只信任已发布
  // 定义，运行时 load_subagent_bundles 同口径过滤）。
  const { data: subagentsData } = useQuery({
    queryKey: agentKeys.list({ page: 1, page_size: 100, status: 'published' }),
    queryFn: () => agentApi.list({ page: 1, page_size: 100, status: 'published' }),
  });
  const subagentCandidates = (subagentsData?.items ?? []).filter(
    (a) => a.id !== agentId,
  );

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

  const deleteM = useMutation({
    mutationFn: () => agentApi.remove(agentId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: agentKeys.all });
      onBack();
    },
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
  // 纸墨工作台：高级参数展开 / 能力浮层开关
  const [advOpen, setAdvOpen] = useState(false);
  const [advParamsOpen, setAdvParamsOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  // 能力浮层搜索词：按名称/描述过滤当前 tab 分组
  const [paletteQ, setPaletteQ] = useState('');
  // 能力浮层类别 tab（技能 / MCP / 知识库 / 子 Agent）与锚定位置（触发按钮下方）
  const [paletteTab, setPaletteTab] = useState<'skill' | 'mcp' | 'kb' | 'sub'>('skill');
  const [palettePos, setPalettePos] = useState<{ top: number; right: number }>({ top: 0, right: 0 });
  // 从触发按钮打开浮层：锚定按钮右缘正下方（380px 浮层向左展开）；
  // 底部越界时上收（视口高 - 浮层最大高 390）。
  const openPalette = (e: { currentTarget: EventTarget & HTMLElement }) => {
    const r = e.currentTarget.getBoundingClientRect();
    setPalettePos({
      top: Math.min(r.bottom + 8, window.innerHeight - 396),
      right: window.innerWidth - r.right,
    });
    setPaletteTab('skill');
    setPaletteQ('');
    setPaletteOpen(true);
  };
  // 开场卡管理区折叠（推荐项卡片/分组管理/批量入口收纳于此）
  const [guideMgrOpen, setGuideMgrOpen] = useState(false);
  // 分区折叠状态（默认全收起，点击分组头展开）：key = UNGROUPED_SECTION_KEY / groupSectionKey(title)
  const [openSections, setOpenSections] = useState<Set<string>>(new Set());
  const bulkParsed = useMemo(() => parseBulkRecommendedItems(bulkText), [bulkText]);
  // 分类导航当前高亮项（hook 必须在下方 early return 之前声明）
  const [activeSec, setActiveSec] = useState('sec-basic');
  // 点击导航后的程序滚动锁：滚动期间 onScroll 不抢高亮，scrollend 解锁
  const scrollLockRef = useRef<string | null>(null);
  // 顶栏头像快捷入口 → AvatarField 的同一套选图/裁剪/上传流程
  const avatarFieldRef = useRef<AvatarFieldHandle>(null);

  const handleSave = () => {
    if (!form) return;
    if (!form.systemPrompt?.trim()) {
      toast.error('「系统提示词」为必填项');
      return;
    }
    updateM.mutate(fromStudioAgent(form));
  };

  if (isLoading || !form) {
    return (
      <div className="flex items-center justify-center py-16 text-ink-dim">
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

  // 分类导航：滚动联动高亮（滚动列 onScroll 更新，点击平滑锚定）

  const FORM_SECTIONS = [
    { id: 'sec-basic', label: '基本信息' },
    { id: 'sec-prompt', label: 'Prompt 配置' },
    { id: 'sec-home', label: '欢迎与引导' },
    { id: 'sec-params', label: '执行参数' },
    { id: 'sec-tools', label: '工具绑定' },
  ];
  const handleFormScroll = (e: React.UIEvent<HTMLDivElement>) => {
    if (scrollLockRef.current) return;
    const el = e.currentTarget;
    let current = FORM_SECTIONS[0].id;
    for (const sec of FORM_SECTIONS) {
      const node = document.getElementById(sec.id);
      if (node && node.getBoundingClientRect().top - el.getBoundingClientRect().top < 120) {
        current = sec.id;
      }
    }
    setActiveSec(current);
  };
  const scrollToSection = (id: string) => {
    // 仅支持 scrollend 的浏览器加锁，否则退化为滚动联动高亮（锁会永久卡住）
    if (typeof document.createElement('div').onscrollend !== 'undefined') scrollLockRef.current = id;
    setActiveSec(id);
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };
  const unlockScroll = () => { scrollLockRef.current = null; };

  // 能力浮层三分组：token 与 form.skills 前缀约定一致（技能=裸 id、mcp:/kb:），
  // 勾选即 toggle，保存链路由 adapters 的 skills↔skill_ids/mcp_connection_ids/
  // knowledge_base_ids 双向映射承担。组恒在（tab 切分），搜索只过滤当前组条目。
  const paletteGroups = ([
    { key: 'skill', label: '技能', Icon: IconSkill, color: 'text-cat-skill', chip: 'bg-[#E7F2EA]',
      items: skillTools.map((t) => ({ token: t.id, name: t.name, desc: t.description })) },
    { key: 'mcp', label: 'MCP 连接', Icon: IconPlug, color: 'text-cat-mcp', chip: 'bg-[#F5EDDD]',
      items: mcpConnections.map((c) => ({ token: `mcp:${c.id}`, name: c.name, desc: c.description })) },
    { key: 'kb', label: '知识库', Icon: IconBook, color: 'text-cat-kb', chip: 'bg-[#F5E9E2]',
      items: knowledgeBases.map((k) => ({ token: `kb:${k.id}`, name: k.name, desc: k.description })) },
    { key: 'sub', label: '子 Agent', Icon: IconSubAgent, color: 'text-cat-sub', chip: 'bg-[#ECEFF2]',
      // 仅已发布 Agent 可入委派池（运行时 load_subagent_bundles 同口径过滤），排除自身
      items: subagentCandidates.map((a) => ({ token: `subagent:${a.id}`, name: a.name, desc: a.description })) },
  ] as { key: 'skill' | 'mcp' | 'kb' | 'sub'; label: string; Icon: (p: { size?: number; className?: string }) => ReactNode; color: string; chip: string; items: { token: string; name: string; desc: string }[] }[])
    .map((g) => ({
      ...g,
      items: g.items.filter((it) =>
        (it.name + ' ' + it.desc).toLowerCase().includes(paletteQ.trim().toLowerCase())),
    }));
  const paletteCur = paletteGroups.find((g) => g.key === paletteTab) ?? paletteGroups[0];

  return (
    <div className="af-scope theme-indigo flex-1 min-h-0 flex flex-col">
      {/* 顶栏：sticky（返回/头像/名称就地编辑/状态/删除保存发布） */}
      <div className="shrink-0 sticky top-0 z-10 bg-page px-5 py-3 border-b border-line flex items-center gap-3">
        <button onClick={onBack} className="w-8 h-8 rounded-lg text-ink-dim hover:text-ink hover:bg-raise transition cursor-pointer shrink-0 flex items-center justify-center">
          <ArrowLeft className="w-4 h-4" />
        </button>
        {/* 头像：点击换——经 AvatarField（inputOnly）触发同一套选图/裁剪/上传 */}
        <div
          title="点击更换头像"
          onClick={() => avatarFieldRef.current?.open()}
          className="relative w-10 h-10 shrink-0 cursor-pointer group"
        >
          <div className="w-full h-full rounded-[11px] overflow-hidden relative border border-line" style={{ background: form?.iconColor || 'var(--color-brand)' }}>
            {form?.avatar ? (
              <img src={form.avatar} alt="" className="w-full h-full object-cover select-none" draggable={false} />
            ) : (
              <span className="w-full h-full flex items-center justify-center text-white font-bold text-sm">
                {(form?.name ?? '?')[0]}
              </span>
            )}
            <span className="absolute inset-0 bg-ink/60 text-white flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity">
              <Pencil className="w-4 h-4" strokeWidth={1.8} />
            </span>
          </div>
          {/* 常驻编辑角标：不依赖 hover 即可见 */}
          <span className="absolute -bottom-1 -right-1 w-4 h-4 rounded-full bg-brand text-white flex items-center justify-center ring-2 ring-page">
            <Pencil className="w-2.5 h-2.5" strokeWidth={2.5} />
          </span>
        </div>
        {/* 头像上传全流程（隐藏 UI，仅 input + 裁剪弹层；预览即顶栏头像） */}
        <AvatarField
          inputOnly
          ref={avatarFieldRef}
          value={form?.avatar ?? ''}
          entityId={agentId}
          onChange={(url) => set({ avatar: url })}
        />
        <div className="name-edit flex items-center gap-1.5 min-w-0" title="点击编辑名称">
          <input
            value={form?.name ?? ''}
            onChange={(e) => form && set({ name: e.target.value })}
            className="bg-transparent border-0 outline-none font-bold text-ink min-w-0 max-w-[280px] px-0"
            style={{ fontFamily: 'var(--font-serif)', fontStyle: 'italic', fontSize: 17 }}
          />
        </div>
        {isPublished && (
          <span className="af-pill af-pill-ok shrink-0">已发布</span>
        )}
        {!isPublished && form?.name && (
          <span className="af-pill af-pill-wait shrink-0">未发布</span>
        )}
        <span className="t-sp flex-1" />
        <button
          onClick={() => { if (confirm(`确认删除「${form?.name}」？此操作不可恢复。`)) { deleteM.mutate(); } }}
          disabled={deleteM?.isPending}
          className="af-btn af-btn-ghost border border-line !text-sig-fail hover:!border-sig-fail disabled:opacity-60"
          title="删除该 Agent"
        >
          {deleteM?.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />}
        </button>
        <button onClick={handleSave} disabled={updateM.isPending} className="af-btn af-btn-secondary">
          {updateM.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : '保存'}
        </button>
        {isPublished ? (
          <button
            onClick={() => archiveM.mutate()}
            disabled={archiveM.isPending}
            className="af-btn af-btn-ghost border border-line disabled:opacity-60"
          >
            {archiveM.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Archive className="w-3.5 h-3.5" />}
            归档
          </button>
        ) : (
          <button
            onClick={() => publishM.mutate()}
            disabled={publishM.isPending}
            className="af-btn af-btn-primary disabled:opacity-60"
          >
            {publishM.isPending ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Rocket className="w-3.5 h-3.5" />}
            发布
          </button>
        )}
      </div>

      {/* ═══ 双栏工作台：左人设大纸 × 右能力架 ═══ */}
      <div className="flex-1 min-h-0 flex">
        {/* ── 左：人设大纸（章节手稿——§ 分节，无修订线）── */}
        <div className="flex-[1.45] min-w-0 overflow-y-auto scrollbar-custom pl-10 pr-12 py-8">

          {/* § 人设基调 */}
          <section className="mb-9">
            <SectionMark title="人设基调" hint="一句话描述智能体" />
            <input className="w-full bg-transparent outline-none text-[14.5px] text-ink placeholder:text-ink-faint" value={form.description} onChange={(e) => set({ description: e.target.value })} placeholder="如：帮你查询工单、工艺路线并处理设备告警的 MES 助手（展示在列表卡，不进提示词）" />
          </section>

          {/* § 系统提示词——稿纸卡（全页唯一强调处） */}
          <section className="mb-9">
            <SectionMark title="系统提示词" hint="支持 Markdown 小节与 {{变量}}（工作流调用时解析）" />
            <div className="relative bg-page rounded-xl border border-line focus-within:border-brand/60 transition-colors">
              <textarea
                rows={14}
                className="w-full bg-transparent outline-none text-[13.5px] leading-[1.85] text-ink placeholder:text-ink-faint resize-y p-4 pb-8 rounded-xl"
                placeholder={'如：\n# 角色\n你是一位资深产品经理…\n\n# 任务\n…\n\n# 约束\n…'}
                value={form.systemPrompt ?? ''}
                onChange={(e) => set({ systemPrompt: e.target.value })}
              />
              <span className="absolute right-3 bottom-2.5 text-[10px] font-mono tabular-nums text-ink-faint select-none pointer-events-none">
                {(form.systemPrompt ?? '').length} 字
              </span>
            </div>
          </section>


          {/* § 开场卡：所见即所得 */}
          <section className="mb-9">
            <SectionMark title="开场" hint="用户看到的第一眼" />
            <div className="bg-page rounded-xl p-4">
              <div className="flex gap-2.5 items-start">
                <span className="w-6 h-6 rounded-lg bg-brand text-white flex items-center justify-center text-[10px] font-bold shrink-0">
                  {(form.name ?? '?')[0]}
                </span>
                <textarea
                  rows={2}
                  className="flex-1 bg-transparent outline-none text-[12.5px] leading-[1.7] text-ink-soft placeholder:text-ink-faint resize-none border-0"
                  placeholder="如：你好！我是销售助理，可以问我业绩、客户、订单等相关问题。"
                  value={form.welcomeMessage ?? ''}
                  onChange={(e) => set({ welcomeMessage: e.target.value })}
                />
              </div>
              <div className="af-label mt-3 mb-2" style={{ fontSize: 9 }}>推荐问题 / 操作</div>
              <div className="flex flex-wrap gap-1.5">
                {recommendedItems.map((item, idx) => (
                  <span key={idx} className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full border border-line bg-paper text-[10.5px] text-ink-dim">
                    {item.label}
                    <button type="button" onClick={() => removeItem(idx)} className="text-ink-faint hover:text-sig-fail px-0.5 cursor-pointer">✕</button>
                  </span>
                ))}
                <button
                  type="button"
                  onClick={addItem}
                  disabled={recommendedItems.length >= MAX_RECOMMENDED_ITEMS}
                  className="px-2.5 py-1 rounded-full border border-dashed border-line2 text-[10.5px] text-ink-faint hover:text-acc hover:border-brand cursor-pointer disabled:opacity-40"
                >
                  ＋ 推荐
                </button>
              </div>
            </div>
            {/* 推荐项/分组管理：完整功能折叠区（RecommendedItemCard/分组/批量 原样保留） */}
            <div className="mt-3 pt-1">
              <button
                type="button"
                className="flex items-center gap-2 text-[10.5px] text-ink-dim hover:text-ink cursor-pointer py-1"
                onClick={() => setGuideMgrOpen(v => !v)}
              >
                {guideMgrOpen ? <ChevronDown className="w-3 h-3" /> : <ChevronRight className="w-3 h-3" />}
                推荐项与分组管理
                <span className="font-mono text-[8.5px] text-ink-faint">{recommendedItems.length + recommendedGroups.reduce((n, g) => n + g.items.length, 0)} 项</span>
              </button>
              {guideMgrOpen && (
              <div className="space-y-3 max-h-[420px] overflow-y-auto scrollbar-custom pr-1">
                <div className="space-y-1.5">
                  <button
                    type="button"
                    className="flex w-full items-center gap-2 text-left cursor-pointer"
                    onClick={() => toggleSection(UNGROUPED_SECTION_KEY)}
                    title={openSections.has(UNGROUPED_SECTION_KEY) ? '收起' : '展开'}
                  >
                    {openSections.has(UNGROUPED_SECTION_KEY)
                      ? <ChevronDown className="w-3 h-3 text-ink-dim shrink-0" />
                      : <ChevronRight className="w-3 h-3 text-ink-dim shrink-0" />}
                    <Folder className="w-3 h-3 text-sig-wait shrink-0" />
                    <span className="text-[11px] font-semibold text-ink-dim">未分组</span>
                    <span className="text-[11px] text-ink-dim font-mono ml-auto shrink-0">{recommendedItems.length} / {MAX_RECOMMENDED_ITEMS}</span>
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
                            <Folder className="w-3 h-3 text-sig-wait shrink-0" />
                            <input
                              autoFocus
                              className="h-6 flex-1 min-w-0 px-2 rounded border border-line bg-page text-ink text-[11px] focus:outline-none focus:border-brand"
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
                              ? <ChevronDown className="w-3 h-3 text-ink-dim shrink-0" />
                              : <ChevronRight className="w-3 h-3 text-ink-dim shrink-0" />}
                            <Folder className="w-3 h-3 text-sig-wait shrink-0" />
                            <span className="text-[11px] font-semibold text-ink-dim truncate">{group.title}</span>
                            <span className="text-[11px] text-ink-dim font-mono ml-auto shrink-0">{group.items.length} / {MAX_GROUP_ITEMS}</span>
                          </button>
                        )}
                        {renamingGroup !== gIdx && (
                          <>
                            <button
                              type="button"
                              className="flex items-center justify-center w-5 h-5 rounded-full text-ink-dim hover:text-ink hover:bg-line cursor-pointer shrink-0"
                              title="重命名"
                              onClick={() => beginRenameGroup(gIdx)}
                            >
                              <Pencil className="w-2.5 h-2.5" />
                            </button>
                            <button
                              type="button"
                              className="flex items-center justify-center w-5 h-5 rounded-full text-ink-dim hover:text-sig-fail hover:bg-sig-fail-soft cursor-pointer shrink-0"
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
              )}

              <div className="flex items-center gap-2 mt-3">
                <button
                  type="button"
                  onClick={addItem}
                  disabled={recommendedItems.length >= MAX_RECOMMENDED_ITEMS}
                  className="flex items-center gap-1.5 px-3 py-1.5 border border-line hover:bg-line text-ink-dim hover:text-ink rounded-lg text-xs font-semibold transition cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <Plus className="w-3.5 h-3.5" /> 添加推荐项
                </button>
                <button
                  type="button"
                  onClick={openBulk}
                  className="flex items-center gap-1.5 px-3 py-1.5 border border-line hover:bg-line text-ink-dim hover:text-ink rounded-lg text-xs font-semibold transition cursor-pointer"
                >
                  <ListPlus className="w-3.5 h-3.5" /> 批量添加
                </button>
              </div>
            </div>
          </section>
        </div>

        {/* ── 右：能力架 ── */}
        <div className="w-[360px] shrink-0 border-l border-line bg-panel overflow-y-auto scrollbar-custom px-5 py-6">
          <div className="flex items-baseline gap-2 mb-4">
            <span aria-hidden className="font-serif italic text-brand text-[17px] leading-none select-none">§</span>
            <span className="font-serif italic text-[15px] font-semibold text-ink leading-none">能力</span>
            <span className="text-[10px] text-ink-faint">搜索技能、MCP、知识库并装配</span>
          </div>
          <button
            type="button"
            onClick={(e) => openPalette(e)}
            className="w-full flex items-center gap-2.5 px-3.5 py-3 border border-dashed border-line-strong rounded-xl text-[11.5px] text-ink-dim hover:text-brand hover:border-brand transition-colors cursor-pointer mb-5"
          >
            <Plus className="w-3.5 h-3.5" /> 添加能力 — 搜索技能、MCP、知识库…
          </button>

          {/* 内置工具 */}
          <div className="mb-4">
            <div className="flex items-center gap-1.5 mb-2">
              <IconWrench size={12} className="text-cat-tool" />
              <span className="text-[11px] font-bold text-ink-soft">内置工具</span>
              <span className="font-mono text-[8.5px] text-ink-faint ml-auto">8 默认 · +11 隐藏</span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {builtinTools.filter((t) => form.skills.includes(`builtin:${t.name}`)).map((t) => (
                <span key={`builtin:${t.name}`} className="inline-flex items-center gap-1 text-[10.5px] text-ink-soft bg-paper border border-line rounded-md px-2 py-0.5">
                  {t.name}
                  <button type="button" onClick={() => set({ skills: toggleSkill(form.skills, `builtin:${t.name}`) })} className="text-ink-faint hover:text-sig-fail cursor-pointer">✕</button>
                </span>
              ))}
              <button type="button" onClick={(e) => openPalette(e)} className="text-[10px] text-ink-faint border border-dashed border-line2 rounded-md px-2 py-0.5 hover:text-brand hover:border-brand cursor-pointer">＋ 添加</button>
            </div>
          </div>

          {/* 技能 */}
          <div className="mb-4">
            <div className="flex items-center gap-1.5 mb-2">
              <IconSkill size={12} className="text-cat-skill" />
              <span className="text-[11px] font-bold text-ink-soft">技能</span>
              <span className="font-mono text-[8.5px] text-ink-faint ml-auto">{form.skills.filter((s) => !s.includes(':')).length}</span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {form.skills.filter((s) => !s.includes(':')).map((sid) => (
                <span key={sid} className="inline-flex items-center gap-1 text-[10.5px] text-ink-soft bg-paper border border-line rounded-md px-2 py-0.5">
                  {skillTools.find((t) => t.id === sid)?.name ?? sid}
                  <button type="button" onClick={() => set({ skills: toggleSkill(form.skills, sid) })} className="text-ink-faint hover:text-sig-fail cursor-pointer">✕</button>
                </span>
              ))}
              {form.skills.filter((s) => !s.includes(':')).length === 0 && (
                <button type="button" onClick={(e) => openPalette(e)} className="text-[10px] text-ink-faint border border-dashed border-line2 rounded-md px-2 py-0.5 hover:text-brand hover:border-brand cursor-pointer">＋ 从浮层添加</button>
              )}
            </div>
          </div>

          {/* MCP 连接 */}
          <div className="mb-4">
            <div className="flex items-center gap-1.5 mb-2">
              <IconPlug size={12} className="text-cat-mcp" />
              <span className="text-[11px] font-bold text-ink-soft">MCP 连接</span>
              <span className="font-mono text-[8.5px] text-ink-faint ml-auto">{form.skills.filter((s) => s.startsWith('mcp:')).length}</span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {mcpConnections.filter((c) => form.skills.includes(`mcp:${c.id}`)).map((c) => (
                <span key={`mcp:${c.id}`} className="inline-flex items-center gap-1 text-[10.5px] text-ink-soft bg-paper border border-line rounded-md px-2 py-0.5">
                  {c.name}
                  <button type="button" onClick={() => set({ skills: toggleSkill(form.skills, `mcp:${c.id}`) })} className="text-ink-faint hover:text-sig-fail cursor-pointer">✕</button>
                </span>
              ))}
              <button type="button" onClick={(e) => openPalette(e)} className="text-[10px] text-ink-faint border border-dashed border-line2 rounded-md px-2 py-0.5 hover:text-brand hover:border-brand cursor-pointer">＋ 添加</button>
            </div>
          </div>

          {/* 知识库 */}
          <div className="mb-4">
            <div className="flex items-center gap-1.5 mb-2">
              <IconBook size={12} className="text-cat-kb" />
              <span className="text-[11px] font-bold text-ink-soft">知识库</span>
              <span className="font-mono text-[8.5px] text-ink-faint ml-auto">{form.skills.filter((s) => s.startsWith('kb:')).length}</span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {knowledgeBases.filter((k) => form.skills.includes(`kb:${k.id}`)).map((k) => (
                <span key={`kb:${k.id}`} className="inline-flex items-center gap-1 text-[10.5px] text-ink-soft bg-paper border border-line rounded-md px-2 py-0.5">
                  {k.name}
                  <button type="button" onClick={() => set({ skills: toggleSkill(form.skills, `kb:${k.id}`) })} className="text-ink-faint hover:text-sig-fail cursor-pointer">✕</button>
                </span>
              ))}
              <button type="button" onClick={(e) => openPalette(e)} className="text-[10px] text-ink-faint border border-dashed border-line2 rounded-md px-2 py-0.5 hover:text-brand hover:border-brand cursor-pointer">＋ 添加</button>
            </div>
          </div>

          {/* 可委派子 Agent */}
          <div className="mb-4">
            <div className="flex items-center gap-1.5 mb-2">
              <IconSubAgent size={12} className="text-cat-sub" />
              <span className="text-[11px] font-bold text-ink-soft">可委派子 Agent</span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {subagentCandidates.filter((a) => form.skills.includes(`subagent:${a.id}`)).map((a) => (
                <span key={`subagent:${a.id}`} className="inline-flex items-center gap-1 text-[10.5px] text-ink-soft bg-paper border border-line rounded-md px-2 py-0.5">
                  {a.name}
                  <button type="button" onClick={() => set({ skills: toggleSkill(form.skills, `subagent:${a.id}`) })} className="text-ink-faint hover:text-sig-fail cursor-pointer">✕</button>
                </span>
              ))}
              <button type="button" onClick={(e) => openPalette(e)} className="text-[10px] text-ink-faint border border-dashed border-line2 rounded-md px-2 py-0.5 hover:text-brand hover:border-brand cursor-pointer">＋ 添加</button>
            </div>
          </div>

          {/* ── 模型 ── */}
          <div className="rk-h flex items-center gap-1.5 mb-2">
            <IconChip size={12} className="text-brand" />
            <span className="text-[11px] font-bold text-ink-soft">模型</span>
          </div>
          <Select
            value={form.model || null}
            onChange={(v) => set({ model: v ?? '' })}
            placeholder={activeModels.length === 0 ? '暂无可用模型，请先在模型配置页添加' : '— 未选择 —'}
            groups={modelGroups}
          />

          {/* ── 高级参数（行展开编辑）── */}
          <div className="mt-5">
            <button type="button" onClick={() => setAdvParamsOpen(v => !v)} className="w-full flex items-center justify-between text-[11.5px] text-ink-dim hover:text-ink cursor-pointer py-1.5">
              <span>▸ 高级参数</span>
              <span className="font-mono text-[9px] text-ink-faint">温度 {form.temperature} · 重试 {form.maxRetry ?? 3} · {form.maxTokens ? `${Math.round(form.maxTokens / 1000)}k` : '默认'}</span>
            </button>
            {advParamsOpen && (
              <div className="border border-dashed border-line2 rounded-md p-3 space-y-3 mt-1">
                <div>
                  <div className="text-[10px] text-ink-faint mb-1.5">思维活性 Temperature: {form.temperature}</div>
                  <input type="range" min="0" max="1.0" step="0.1" value={form.temperature} onChange={(e) => set({ temperature: parseFloat(e.target.value) })} className="w-full accent-indigo-500 cursor-pointer" />
                </div>
                <div>
                  <div className="text-[10px] text-ink-faint mb-1.5">最大重试次数（0-10）</div>
                  <input type="number" min="0" max="10" className={`${inputCls} font-mono`} value={form.maxRetry ?? 3} onChange={(e) => set({ maxRetry: Math.max(0, Math.min(10, Number(e.target.value) || 0)) })} />
                </div>
                <div>
                  <div className="text-[10px] text-ink-faint mb-1.5">会话 Token 上限（0 = 全局默认）</div>
                  <input type="number" min="0" max="10000000" step="10000" className={`${inputCls} font-mono`} value={form.maxTokens ?? 0} onChange={(e) => set({ maxTokens: Math.max(0, Number(e.target.value) || 0) })} placeholder="0 = 使用全局默认" />
                  <div className="text-[10px] text-ink-faint mt-1">单次会话累计 Token 上限，超出后自动停止。0 = 全局默认值（200000）。</div>
                </div>
              </div>
            )}
          </div>

          {/* ── 开关行：语音 / 允许创建 Agent ── */}
          <div className="mt-4">
            <div className="sw-row flex items-center justify-between py-2.5 border-b border-line">
              <div className="flex items-center gap-2">
                <IconVoice size={14} className="text-cat-voice" />
                <span className="text-[11.5px] text-ink">语音对话<span className="block text-[9px] text-ink-faint mt-0.5">需全局语音凭证</span></span>
              </div>
              <button
                type="button"
                role="switch"
                aria-checked={form.voiceEnabled}
                onClick={() => set({ voiceEnabled: !form.voiceEnabled })}
                className={`w-8 h-[18px] rounded-full relative transition-colors cursor-pointer ${form.voiceEnabled ? 'bg-brand' : 'bg-line-strong'}`}
              >
                <span className={`absolute top-[2px] w-[15px] h-[15px] rounded-full bg-white shadow transition-all ${form.voiceEnabled ? 'left-[15px]' : 'left-[2px]'}`} />
              </button>
            </div>
            <div className="sw-row flex items-center justify-between py-2.5 border-b border-line">
              <div className="flex items-center gap-2">
                <IconSubAgent size={14} className="text-cat-sub" />
                <span className="text-[11.5px] text-ink">允许创建 Agent<span className="block text-[9px] text-ink-faint mt-0.5">创建物为草稿，需人工审核</span></span>
              </div>
              <button
                type="button"
                role="switch"
                aria-checked={form.canSpawnAgents}
                onClick={() => set({ canSpawnAgents: !form.canSpawnAgents })}
                className={`w-8 h-[18px] rounded-full relative transition-colors cursor-pointer ${form.canSpawnAgents ? 'bg-brand' : 'bg-line-strong'}`}
              >
                <span className={`absolute top-[2px] w-[15px] h-[15px] rounded-full bg-white shadow transition-all ${form.canSpawnAgents ? 'left-[15px]' : 'left-[2px]'}`} />
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* ── 能力添加浮层：锚定触发按钮下方（向左展开），类别 tab 快速切分 ── */}
      {paletteOpen && (
        <>
          <div className="fixed inset-0 z-40" onClick={() => setPaletteOpen(false)} />
          <div
            className="fixed w-[380px] bg-panel border border-line rounded-2xl shadow-[var(--shadow-pop)] overflow-hidden z-50 animate-fade-in"
            style={{ top: palettePos.top, right: palettePos.right }}
          >
            <div className="flex items-center gap-2.5 px-4 py-3 border-b border-line">
              <Search className="w-3.5 h-3.5 text-ink-faint shrink-0" />
              <input
                autoFocus
                value={paletteQ}
                onChange={(e) => setPaletteQ(e.target.value)}
                placeholder={`搜索${paletteCur.label}…`}
                className="flex-1 bg-transparent border-0 outline-none text-[12.5px] text-ink placeholder:text-ink-faint"
              />
              <button
                type="button"
                onClick={() => setPaletteOpen(false)}
                className="text-ink-faint hover:text-ink cursor-pointer shrink-0"
                title="关闭"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            </div>
            {/* 类别 tab：选中 = 靛蓝下划线；计数随搜索过滤实时变化 */}
            <div className="flex items-center gap-1 px-3 border-b border-line">
              {paletteGroups.map((g) => (
                <button
                  key={g.key}
                  type="button"
                  onClick={() => setPaletteTab(g.key)}
                  className={`flex items-center gap-1.5 px-3 py-2 text-[11.5px] -mb-px border-b-2 transition-colors cursor-pointer ${
                    paletteTab === g.key ? 'text-brand border-brand font-semibold' : 'text-ink-dim border-transparent hover:text-ink'
                  }`}
                >
                  {g.label}
                  <span className="font-mono text-[9px] text-ink-faint">{g.items.length}</span>
                </button>
              ))}
            </div>
            <div className="max-h-[300px] overflow-y-auto scrollbar-custom p-1.5">
              {paletteCur.items.length === 0 ? (
                <div className="px-3 py-6 text-center text-[11.5px] text-ink-faint">
                  {paletteQ.trim() ? `没有匹配「${paletteQ.trim()}」的${paletteCur.label}` : `暂无可添加的${paletteCur.label}`}
                </div>
              ) : (
                paletteCur.items.map((it) => {
                  const added = form.skills.includes(it.token);
                  return (
                    <button
                      key={it.token}
                      type="button"
                      onClick={() => set({ skills: toggleSkill(form.skills, it.token) })}
                      className={`w-full flex items-center gap-2.5 px-2.5 py-2 rounded-[9px] text-left transition-colors cursor-pointer hover:bg-raise ${added ? 'bg-brand-soft/50' : ''}`}
                    >
                      <span className={`w-6 h-6 rounded-[7px] flex items-center justify-center shrink-0 ${paletteCur.chip}`}>
                        <paletteCur.Icon size={12} className={paletteCur.color} />
                      </span>
                      <span className={`min-w-0 flex-1 text-[12.5px] truncate ${added ? 'text-brand font-medium' : 'text-ink'}`}>{it.name}</span>
                      <span className="min-w-0 w-[130px] text-[10.5px] text-ink-faint truncate text-right">{it.desc}</span>
                      {added && <Check className="w-3.5 h-3.5 text-brand shrink-0" />}
                    </button>
                  );
                })
              )}
            </div>
          </div>
        </>
      )}

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
            <span className="text-[11px] text-ink-dim shrink-0">添加到</span>
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
          <div className="text-[11px] text-ink-dim leading-relaxed">
            自动识别格式，直接粘贴即可：
            <br />① 纯文本 — 每行一条 <code className="text-brand">{'显示文案 | 实际发送内容'}</code>，不需要 []，不含 | 时整行即显示文案；
            <br />② JSON — 整段数组，或每行一个 <code className="text-brand">{'{"label":"…","prompt":"…"}'}</code> 对象（[] 可省略，prompt 可省略）；
            <br />③ 分组 — 对象形如 <code className="text-brand">{'{"title":"分组名","items":[…]}'}</code>（title 必填 ≤{GROUP_TITLE_MAX} 字符），同名分组直接并入、否则新建；普通条目按上方「添加到」落位。
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
                <span className="text-sig-ok">
                  解析出 {bulkParsed.items.length} 条{bulkParsed.groups.length > 0 ? ` + ${bulkParsed.groups.length} 个分组` : ''}（{bulkParsed.mode === 'json' ? 'JSON 格式' : '逐行文本格式'}）
                  {(bulkParsed.items.length > bulkItemRoom || bulkNewGroupCount > bulkGroupRoom) && (
                    <span className="text-sig-wait">，超出上限部分将忽略</span>
                  )}
                </span>
              ) : (
                <span className="text-sig-fail">未解析出有效条目，请检查格式</span>
              )}
              {bulkParsed.invalidCount > 0 && (
                <span className="text-sig-wait">
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
          <div className="text-[11px] text-ink-dim">
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
    <div className="rounded-lg border border-line bg-page">
      <div className="flex items-center gap-2 px-2.5 py-2">
        <button
          type="button"
          onClick={onToggle}
          className="flex flex-1 min-w-0 items-center gap-2 text-left cursor-pointer"
          title={expanded ? '收起' : '展开编辑'}
        >
          {expanded
            ? <ChevronDown className="w-3.5 h-3.5 text-ink-dim shrink-0" />
            : <ChevronRight className="w-3.5 h-3.5 text-ink-dim shrink-0" />}
          <span className="text-[11px] text-ink-dim font-mono shrink-0">#{index + 1}</span>
          <span className={`text-xs truncate shrink-0 max-w-[240px] ${item.label ? 'text-ink' : 'text-ink-dim italic'}`}>
            {item.label || '（未填写）'}
          </span>
          <span className="text-[11px] text-ink-dim truncate">
            {item.prompt ? `· ${item.prompt}` : '· 点击直接发送显示文案'}
          </span>
        </button>
        <button type="button" onClick={onRemove} className="flex items-center gap-1 text-danger-text text-[11px] hover:underline cursor-pointer shrink-0">
          <Trash2 className="w-3 h-3" /> 删除
        </button>
      </div>
      {expanded && (
        <div className="px-3 pb-3 space-y-2">
          <input className={inputCls} placeholder="显示文案（必填），如：导出本月报表" value={item.label} onChange={(e) => onUpdate({ label: e.target.value })} />
          <input className={inputCls} placeholder="实际发送内容（留空则同显示文案）" value={item.prompt} onChange={(e) => onUpdate({ prompt: e.target.value })} />
          <div className="flex items-center gap-2">
            <span className="text-[11px] text-ink-dim shrink-0">所属分组</span>
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
const Section: FC<{ id?: string; title: string; icon?: ReactNode; defaultOpen?: boolean; children: ReactNode }> = ({
  id, title, icon, defaultOpen = false, children,
}) => {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div id={id} style={{ scrollMarginTop: 88 }} className="rounded-[10px] bg-panel shadow-[var(--shadow-card)] overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center gap-2 px-4 py-3 text-left cursor-pointer hover:bg-panel-hover transition"
      >
        {open ? <ChevronDown className="w-4 h-4 text-ink-dim" /> : <ChevronRight className="w-4 h-4 text-ink-dim" />}
        {icon && <span className="text-brand">{icon}</span>}
        <span className="text-sm font-bold text-ink">{title}</span>
      </button>
      {open && <div className="px-4 pb-4 space-y-4">{children}</div>}
    </div>
  );
};

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="space-y-1">
      <label className="text-ink-dim font-semibold text-xs font-sans">{label}</label>
      {children}
    </div>
  );
}

/** Toggle a prefixed skill token in/out of the skills array. */
function toggleSkill(skills: string[], token: string): string[] {
  return skills.includes(token) ? skills.filter((s) => s !== token) : [...skills, token];
}

const ToolGroup: FC<{ title: string; hint?: string; children: ReactNode }> = ({ title, hint, children }) => (
  <div className="p-3 rounded-lg bg-page border border-line">
    <p className="text-[11px] text-ink-dim uppercase tracking-wider font-bold mb-2">{title}</p>
    {hint ? <p className="text-[11px] text-ink-dim italic">{hint}</p> : <div className="flex flex-wrap gap-1.5">{children}</div>}
  </div>
);
const ToolChip: FC<{ label: string; checked: boolean; onToggle: () => void }> = ({ label, checked, onToggle }) => (
  <button
    type="button"
    onClick={onToggle}
    className={`px-2.5 py-1 rounded-lg text-[11px] font-semibold border transition cursor-pointer select-none ${
      checked ? 'bg-brand border-brand text-ink' : 'bg-panel border-line text-ink-dim hover:text-ink hover:border-line-strong'
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

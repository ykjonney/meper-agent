/**
 * AgentEditorPage — 智能体编辑器（预览稿 agents-workspace ② 视觉 + v1 全字段）。
 * 布局：顶栏（保存）+ 左 8 分区锚点 + 中表单 + 右试运行占位。
 * 数据：agentApi.get → toStudioAgent 表单模型；保存 = fromStudioAgent → agentApi.update。
 * 试运行完整聊天 P4.5（当前提供跳转对话页）。
 * TODO-API: 发布（publish 端点）、快照（快照端点）— P4.5。
 */
import { useMemo, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useNavigate, useParams } from 'react-router-dom';
import { agentApi } from '../services/agent-api';
import { modelApi } from '../services/model-api';
import { mcpApi } from '../services/mcp-api';
import { knowledgeApi } from '../services/knowledge-api';
import { userSkillsApi } from '../services/user-skills-api';
import { toStudioAgent, fromStudioAgent } from '../services/adapters';
import type { Agent as StudioAgent } from '../types';

const CSS = `
.ed { height:100%; display:flex; background:var(--color-canvas); font-family:-apple-system,'PingFang SC','Segoe UI',sans-serif; font-size:14px; color:#1E1B2E; }
.ed * { box-sizing:border-box; }
.ed-top { height:52px; background:#fff; border-bottom:1px solid #EFEDF7; display:flex; align-items:center; gap:10px; padding:0 16px; flex:none; }
.ed-anchors { width:186px; background:#FBFAFE; border-right:1px solid #EFEDF7; padding:14px 10px; display:flex; flex-direction:column; gap:2px; flex:none; }
.ed-an { padding:8px 12px; border-radius:8px; font-size:13.5px; color:#8A85A3; cursor:pointer; display:flex; align-items:center; gap:8px; }
.ed-an:hover { background:#F6F4FC; }
.ed-an.on { background:#EFEAFD; color:#6D4AE0; font-weight:700; }
.ed-an .n { width:19px; height:19px; border-radius:5px; background:#F1EFF8; color:#8A85A3; font-size:10px; display:flex; align-items:center; justify-content:center; flex:none; }
.ed-an.on .n { background:#6D4AE0; color:#fff; }
.ed-form { flex:1; padding:16px 20px; overflow-y:auto; display:flex; flex-direction:column; gap:12px; min-width:0; align-items:center; }
.ed-form-inner { width:100%; max-width:760px; display:flex; flex-direction:column; gap:12px; }
.ed-sec { background:#fff; border:1px solid #EFEDF7; border-radius:13px; padding:14px 16px; }
.ed-sec-h { display:flex; align-items:center; gap:8px; margin-bottom:10px; }
.ed-sec-h b { font-size:13.5px; }
.ed-sec-h .hint { font-size:11px; color:#B6B1C9; }
.ed-f { margin-bottom:9px; }
.ed-f label { font-size:11.5px; color:#9A95B0; display:block; margin-bottom:4px; }
.ed-f label .req { color:#DC2626; }
.ed-in, .ed-ta, .ed-sel { width:100%; background:#FBFAFE; border:1px solid #EBE8F5; border-radius:8px; padding:8px 12px; font-size:13px; color:#1E1B2E; outline:none; font-family:inherit; }
.ed-in:focus, .ed-ta:focus, .ed-sel:focus { border-color:#C9BEF0; background:#fff; }
.ed-ta { resize:vertical; line-height:1.6; }
.ed-chips { display:flex; flex-wrap:wrap; gap:7px; }
.ed-chip { display:flex; align-items:center; gap:5px; background:#F6F4FC; border:1px solid #EBE8F5; border-radius:8px; padding:5px 11px; font-size:12px; color:#55506E; cursor:pointer; user-select:none; }
.ed-chip.on { background:#EFEAFD; border-color:#C9BEF0; color:#6D4AE0; font-weight:600; }
.ed-chip .x { color:#C6C2D6; font-weight:700; }
.ed-bp { background:linear-gradient(135deg,#8B5CF6,#6D4AE0); color:#fff; border-radius:8px; padding:6px 18px; font-size:12px; font-weight:700; cursor:pointer; border:none; }
.ed-bp:disabled { opacity:.5; cursor:default; }
.ed-bg { border:1px solid #DDD3F8; color:#6D4AE0; border-radius:8px; padding:6px 18px; font-size:12px; font-weight:700; background:#fff; cursor:pointer; }
.ed-range { width:100%; accent-color:#6D4AE0; }
.ed-fold { display:flex; align-items:center; gap:6px; width:100%; text-align:left; cursor:pointer; border:none; background:none; padding:3px 2px; font-family:inherit; }
.ed-fold:hover { opacity:.8; }
.ed-gitem { background:#FBFAFE; border:1px solid #F0EDF9; border-radius:9px; padding:9px 11px; margin-bottom:6px; }
.ed-ginput { width:100%; background:#fff; border:1px solid #EBE8F5; border-radius:7px; padding:6px 10px; font-size:12px; color:#1E1B2E; outline:none; }
.ed-ginput:focus { border-color:#C9BEF0; }
.ed-mini { border:1px solid #DDD3F8; color:#6D4AE0; background:#fff; border-radius:6px; padding:3px 10px; font-size:11px; font-weight:600; cursor:pointer; }
.ed-mini:hover { background:#EFEAFD; }
.ed-mini.danger { color:var(--color-danger); border-color:var(--color-danger); }
.ed-bulk-mask { position:fixed; inset:0; background:rgba(30,27,46,.45); z-index:110; display:flex; align-items:center; justify-content:center; }
.ed-bulk { width:560px; max-width:92vw; background:#fff; border-radius:16px; box-shadow:0 20px 60px rgba(42,38,64,.25); padding:20px 24px; }
.ed-bulk-ta { width:100%; min-height:180px; background:#FBFAFE; border:1px solid #EBE8F5; border-radius:9px; padding:10px 12px; font-size:12px; font-family:var(--font-mono); color:#1E1B2E; outline:none; resize:vertical; }
.ed-bulk-ta:focus { border-color:#C9BEF0; }
`;

const MAX_RECOMMENDED_ITEMS = 200;
const MAX_GROUP_ITEMS = 20;
const MAX_RECOMMENDED_GROUPS = 10;
const UNGROUPED = -1;

const SECTIONS = [
  { n: '1', key: 'basic', label: '基础信息' },
  { n: '2', key: 'model', label: '模型与推理' },
  { n: '3', key: 'prompt', label: '提示词' },
  { n: '4', key: 'guide', label: '欢迎与引导' },
  { n: '5', key: 'tools', label: '工具与技能' },
  { n: '6', key: 'kb', label: '知识库' },
  { n: '7', key: 'exec', label: '执行与委派' },
];

function Chips({ options, selected, onToggle }: {
  options: { id: string; label: string }[];
  selected: string[];
  onToggle: (id: string) => void;
}) {
  if (options.length === 0) return <div style={{ fontSize: 12, color: '#B6B1C9', fontStyle: 'italic' }}>暂无可选项</div>;
  return (
    <div className="ed-chips">
      {options.map((o) => {
        const on = selected.includes(o.id);
        return (
          <span key={o.id} className={`ed-chip ${on ? 'on' : ''}`} onClick={() => onToggle(o.id)}>
            {on ? <span className="x">✓</span> : <span style={{ color: '#C6C2D6' }}>＋</span>}
            {o.label}
          </span>
        );
      })}
    </div>
  );
}

export function AgentEditorPage() {
  const { agentId = '' } = useParams();
  const nav = useNavigate();
  const qc = useQueryClient();
  const isNew = agentId === 'new';

  const { data: backendAgent, isLoading } = useQuery({
    queryKey: ['agent-edit', agentId],
    queryFn: () => agentApi.get(agentId),
    enabled: !isNew,
  });
  void isLoading;
  const { data: modelList } = useQuery({
    queryKey: ['models', 'editor'], queryFn: () => modelApi.list({ page_size: 50 }),
  });
  const { data: mcpList } = useQuery({
    queryKey: ['mcp', 'editor'], queryFn: () => mcpApi.list({ page_size: 50 }),
  });
  const { data: kbList } = useQuery({
    queryKey: ['knowledge-bases', 'editor'], queryFn: () => knowledgeApi.list({ page_size: 50 }),
  });
  const { data: skillList } = useQuery({
    queryKey: ['skills', 'editor'], queryFn: () => userSkillsApi.list(),
  });
  const { data: subagentList } = useQuery({
    queryKey: ['agents', 'subagent-candidates'], queryFn: () => agentApi.list({ status: 'published', page_size: 50 }),
  });

  // 表单模型（Studio Agent）
  const [form, setForm] = useState<StudioAgent | null>(null);
  const [initialized, setInitialized] = useState(false);
  const [activeSection, setActiveSection] = useState('basic');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // 欢迎与引导：折叠/重命名/新建分组状态
  const [guideOpen, setGuideOpen] = useState(true);
  const [renaming, setRenaming] = useState<number | null>(null);
  const [renameText, setRenameText] = useState('');
  const [createGroupOpen, setCreateGroupOpen] = useState(false);
  const [createGroupText, setCreateGroupText] = useState('');
  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkText, setBulkText] = useState('');

  // 后端数据到达 → toStudioAgent 初始化表单
  if (!isNew && backendAgent && !initialized) {
    setForm(toStudioAgent(backendAgent));
    setInitialized(true);
  }
  if (isNew && !form) {
    setForm({
      id: '', name: '', avatar: '', description: '',
      model: modelList?.items?.[0]?.id ?? '',
      voiceEnabled: false, canSpawnAgents: false,
      temperature: 0.5, systemPrompt: '', rolePrompt: '', taskPrompt: '',
      constraintsPrompt: '', contextPrompt: '', outputFormatPrompt: '',
      status: 'idle', iconColor: 'bg-indigo-500', skills: [], lastActive: '',
      welcomeMessage: '', recommendedItems: [], recommendedGroups: [],
      customTools: [], maxRetry: 3, maxTokens: 0,
    });
  }

  const set = (patch: Partial<StudioAgent>) => setForm((f) => (f ? { ...f, ...patch } : f));

  // 前缀化 skills 视图模型（编辑 chips 用）
  const toggleSkill = (prefix: string, id: string) => {
    if (!form) return;
    const tag = `${prefix}:${id}`;
    const next = form.skills.includes(tag)
      ? form.skills.filter((s) => s !== tag)
      : [...form.skills, tag];
    set({ skills: next });
  };

  // ── 欢迎与引导分组操作（v1 同款语义）──
  const commitCreateGroup = () => {
    const title = createGroupText.trim();
    if (!title) return;
    if (title.length > 20) { setError('分组名不能超过 20 字符'); return; }
    if (title === '未分组') { setError('该名称为保留字，请换一个分组名'); return; }
    const groups = form?.recommendedGroups ?? [];
    if (groups.length >= MAX_RECOMMENDED_GROUPS) { setError(`最多 ${MAX_RECOMMENDED_GROUPS} 个分组`); return; }
    if (groups.some((g) => g.title === title)) { setError(`分组「${title}」已存在`); return; }
    setForm((f) => (f ? { ...f, recommendedGroups: [...(f.recommendedGroups ?? []), { title, items: [] }] } : f));
    setCreateGroupOpen(false);
    setCreateGroupText('');
  };
  const removeGroup = (gIdx: number) => {
    if (!form) return;
    const groups = [...(form.recommendedGroups ?? [])];
    const group = groups[gIdx];
    if (!group) return;
    const ungrouped = form.recommendedItems ?? [];
    if (ungrouped.length + group.items.length > MAX_RECOMMENDED_ITEMS) {
      setError(`删除后未分组将超过 ${MAX_RECOMMENDED_ITEMS} 条上限，请先清理该分组内条目`.replace('MAX_RECOMMENDED_ITEMS', String(MAX_RECOMMENDED_ITEMS)));
      return;
    }
    set({
      recommendedItems: [...ungrouped, ...group.items.map((it) => ({ ...it }))],
      recommendedGroups: groups.filter((_, i) => i !== gIdx),
    });
  };
  const removeGroupItem = (gIdx: number, itemIdx: number) => {
    set({ recommendedGroups: (form?.recommendedGroups ?? []).map((g, i) =>
      i === gIdx ? { ...g, items: g.items.filter((_, j) => j !== itemIdx) } : g) });
  };
  const updateGroupItem = (gIdx: number, itemIdx: number, patch: Partial<{ label: string; prompt: string }>) => {
    set({ recommendedGroups: (form?.recommendedGroups ?? []).map((g, i) =>
      i === gIdx ? { ...g, items: g.items.map((it, j) => (j === itemIdx ? { ...it, ...patch } : it)) } : g) });
  };
  const addGroupItem = (gIdx: number) => {
    set({ recommendedGroups: (form?.recommendedGroups ?? []).map((g, i) =>
      i === gIdx ? { ...g, items: [...g.items, { label: '', prompt: '' }] } : g) });
  };
  /** 条目归类迁移：source=-1 未分组；target=-1 未分组（v1 assignItemGroup 同款语义） */
  const assignItem = (source: number, itemIdx: number, target: number) => {
    if (!form || source === target) return;
    const ungrouped = form.recommendedItems ?? [];
    const groups = (form.recommendedGroups ?? []).map((g) => ({ title: g.title, items: [...g.items] }));
    let moved: { label: string; prompt: string } | undefined;
    if (source === UNGROUPED) {
      moved = ungrouped[itemIdx];
      if (!moved) return;
      ungrouped.splice(itemIdx, 1);
    } else {
      moved = groups[source]?.items[itemIdx];
      if (!moved) return;
      groups[source].items.splice(itemIdx, 1);
    }
    if (target === UNGROUPED) ungrouped.push(moved);
    else groups[target]?.items.push(moved);
    set({ recommendedItems: ungrouped, recommendedGroups: groups });
  };
  const commitRename = (gIdx: number) => {
    const title = renameText.trim();
    if (!title || !form) return;
    set({ recommendedGroups: (form.recommendedGroups ?? []).map((g, i) => (i === gIdx ? { ...g, title } : g)) });
    setRenaming(null);
  };

  // ── 批量添加（行模式：`显示文案 | 提示词`；JSON 模式：[{"label","prompt"}]）──
  const bulkParsed = useMemo(() => {
    const trimmed = bulkText.trim();
    if (!trimmed) return { items: [] as { label: string; prompt: string }[], invalid: 0 };
    const items: { label: string; prompt: string }[] = [];
    let invalid = 0;
    const validate = (label: unknown, prompt: unknown) => {
      const l = typeof label === 'string' ? label.trim() : '';
      const pp = typeof prompt === 'string' ? prompt.trim() : '';
      if (!l || l.length > 50) { invalid++; return; }
      items.push({ label: l, prompt: pp.slice(0, 200) });
    };
    if (trimmed.startsWith('[')) {
      try {
        const arr = JSON.parse(trimmed);
        if (Array.isArray(arr)) {
          for (const row of arr) {
            const rec = (row ?? {}) as Record<string, unknown>;
            validate(rec.label, rec.prompt);
          }
          return { items, invalid };
        }
      } catch { /* 不是 JSON，回落行模式 */ }
    }
    for (const line of trimmed.split('\n')) {
      const l = line.trim();
      if (!l) continue;
      const sep = l.includes('|') ? '|' : '\t';
      const parts = l.split(sep);
      validate(parts[0], parts[1] ?? parts[0]);
    }
    return { items, invalid };
  }, [bulkText]);

  const handleSave = async () => {
    if (!form) return;
    if (!form.name.trim()) { setError('名称为必填项'); setActiveSection('basic'); return; }
    if (!form.rolePrompt?.trim() || !form.taskPrompt?.trim()) {
      setError('「角色定义」和「任务描述」为必填项（对话执行校验）');
      setActiveSection('prompt');
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const payload = fromStudioAgent(form);
      if (isNew) {
        await agentApi.create({
          name: payload.name ?? '未命名智能体',
          description: payload.description ?? '',
          avatar: payload.avatar ?? '🤖',
          prompt_slots: payload.prompt_slots ?? {},
          default_model: payload.default_model ?? '',
          skill_ids: payload.skill_ids ?? [],
          mcp_connection_ids: payload.mcp_connection_ids ?? [],
          builtin_config: payload.builtin_config ?? [],
          knowledge_base_ids: payload.knowledge_base_ids ?? [],
          subagent_ids: payload.subagent_ids ?? [],
          max_retry: payload.max_retry ?? 3,
          max_tokens: payload.max_tokens ?? 0,
          voice_enabled: payload.voice_enabled ?? false,
          can_spawn_agents: payload.can_spawn_agents ?? false,
        } as never);
      } else {
        await agentApi.update(agentId, payload);
      }
      qc.invalidateQueries({ queryKey: ['agents'] });
      nav('/agents');
    } catch (e) {
      setError((e as Error).message || '保存失败');
    } finally {
      setSaving(false);
    }
  };

  const scrollTo = (key: string) => {
    setActiveSection(key);
    document.getElementById(`ed-sec-${key}`)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };

  const form_ = form;
  const skillOptions = (skillList ?? []).map((k) => ({ id: String(k.id), label: String(k.name ?? k.id) }));
  const kbOptions = (kbList?.items ?? []).map((k) => ({ id: k.id, label: k.name }));
  const mcpOptions = (mcpList?.items ?? []).map((m) => ({ id: m.id, label: m.name }));
  const subOptions = (subagentList?.items ?? [])
    .filter((a) => a.id !== agentId)
    .map((a) => ({ id: a.id, label: a.name }));
  const builtinOptions = [
    { id: 'bash', label: '⌨ 沙盒 Bash' },
    { id: 'read', label: '📄 文件读取' },
    { id: 'write', label: '✍ 文件写入' },
  ];

  return (
    <div className="ed">
      <style>{CSS}</style>
      <div style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
        {/* 顶栏 */}
        <div className="ed-top">
          <span onClick={() => nav('/agents')} style={{ cursor: 'pointer', color: '#8A85A3', fontSize: 16 }} title="返回">‹</span>
          <div className="ag-av" style={{ width: 32, height: 32, borderRadius: 9, background: 'linear-gradient(135deg,#8B5CF6,#6D4AE0)', color: '#fff', fontSize: 15 }}>
            {form_?.avatar || '✦'}
          </div>
          <input
            className="ed-in" style={{ width: 220, padding: '5px 10px', fontSize: 15, fontWeight: 800, background: 'transparent', border: 'none' }}
            value={form_?.name ?? ''} onChange={(e) => set({ name: e.target.value })} placeholder="智能体名称"
          />
          {form_ && <span className={`K-pill ${isNew ? 'K-pd' : 'K-pg'}`}>{isNew ? '草稿' : '编辑中'}</span>}
          {error && <span style={{ fontSize: 11.5, color: 'var(--color-danger)' }}>✗ {error}</span>}
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
            <span className="ed-bg" title="P4.5 快照端点">存为快照</span>
            <span className="ed-bg" onClick={() => nav('/chat')} title="保存后在对话页试运行">试运行 →</span>
            <button className="ed-bp" onClick={handleSave} disabled={saving}>
              {saving ? '保存中…' : '保存配置'}
            </button>
          </div>
        </div>

        {/* 三栏 */}
        <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
          {/* 锚点 */}
          <div className="ed-anchors">
            <div style={{ fontSize: 10, color: '#B6B1C9', fontWeight: 700, padding: '0 8px 6px' }}>CONFIG / 配置分区</div>
            {SECTIONS.map((sec) => (
              <div key={sec.key} className={`ed-an ${activeSection === sec.key ? 'on' : ''}`} onClick={() => scrollTo(sec.key)}>
                <span className="n">{sec.n}</span> {sec.label}
              </div>
            ))}
          </div>

          {/* 表单 */}
          <div className="ed-form"><div className="ed-form-inner">
            {/* 1 基础信息 */}
            <div id="ed-sec-basic" className="ed-sec">
              <div className="ed-sec-h"><b>① 基础信息</b></div>
              <div style={{ display: 'flex', gap: 12 }}>
                <div className="ed-f" style={{ width: 90 }}>
                  <label>头像 Emoji</label>
                  <input className="ed-in" style={{ textAlign: 'center', fontSize: 20 }} value={form_?.avatar ?? ''} onChange={(e) => set({ avatar: e.target.value.slice(0, 2) })} />
                </div>
                <div className="ed-f" style={{ flex: 1 }}>
                  <label>智能体名称 <span className="req">*</span></label>
                  <input className="ed-in" value={form_?.name ?? ''} onChange={(e) => set({ name: e.target.value })} placeholder="例如：数据分析员" />
                </div>
              </div>
              <div className="ed-f">
                <label>职责描述</label>
                <input className="ed-in" value={form_?.description ?? ''} onChange={(e) => set({ description: e.target.value })} placeholder="一句话描述这个智能体的职责" />
              </div>
            </div>

            {/* 2 模型与推理 */}
            <div id="ed-sec-model" className="ed-sec">
              <div className="ed-sec-h"><b>② 模型与推理</b><span className="hint">模型来自「管理 → 模型配置」</span></div>
              <div className="ed-f">
                <label>推理模型</label>
                <select className="ed-sel" value={form_?.model ?? ''} onChange={(e) => set({ model: e.target.value })}>
                  <option value="">— 未选择 —</option>
                  {(modelList?.items ?? []).map((m) => (
                    <option key={m.id} value={m.id}>{m.name} ({m.model_id})</option>
                  ))}
                </select>
              </div>
              <div className="ed-f">
                <label>思维活性 Temperature：{form_?.temperature ?? 0.5}</label>
                <input className="ed-range" type="range" min={0} max={1} step={0.1}
                       value={form_?.temperature ?? 0.5} onChange={(e) => set({ temperature: Number(e.target.value) })} />
              </div>
              <div style={{ display: 'flex', gap: 12 }}>
                <div className="ed-f" style={{ flex: 1 }}>
                  <label>最大重试次数（0-10）</label>
                  <input className="ed-in" type="number" min={0} max={10} value={form_?.maxRetry ?? 3} onChange={(e) => set({ maxRetry: Number(e.target.value) })} />
                </div>
                <div className="ed-f" style={{ flex: 1 }}>
                  <label>会话 Token 上限（0 = 全局默认）</label>
                  <input className="ed-in" type="number" min={0} value={form_?.maxTokens ?? 0} onChange={(e) => set({ maxTokens: Number(e.target.value) })} />
                </div>
              </div>
            </div>

            {/* 3 提示词 */}
            <div id="ed-sec-prompt" className="ed-sec">
              <div className="ed-sec-h"><b>③ 提示词</b><span className="hint">Role/Task 为对话执行必填</span></div>
              <div className="ed-f">
                <label>角色定义 <span className="req">*</span>（Role）</label>
                <textarea className="ed-ta" rows={3} value={form_?.rolePrompt ?? ''} onChange={(e) => set({ rolePrompt: e.target.value })} placeholder="你是…（身份与专业领域）" />
              </div>
              <div className="ed-f">
                <label>任务描述 <span className="req">*</span>（Task）</label>
                <textarea className="ed-ta" rows={3} value={form_?.taskPrompt ?? ''} onChange={(e) => set({ taskPrompt: e.target.value })} placeholder="你的任务是…（目标与边界）" />
              </div>
              <div className="ed-f">
                <label>约束规则（Constraints · 可选）</label>
                <textarea className="ed-ta" rows={2} value={form_?.constraintsPrompt ?? ''} onChange={(e) => set({ constraintsPrompt: e.target.value })} />
              </div>
              <div className="ed-f">
                <label>上下文信息（Context · 可选）</label>
                <textarea className="ed-ta" rows={2} value={form_?.contextPrompt ?? ''} onChange={(e) => set({ contextPrompt: e.target.value })} />
              </div>
              <div className="ed-f">
                <label>输出格式（Output Format · 可选）</label>
                <textarea className="ed-ta" rows={2} value={form_?.outputFormatPrompt ?? ''} onChange={(e) => set({ outputFormatPrompt: e.target.value })} />
              </div>
              <div className="ed-f">
                <label>补充说明（System Prompt · 可选）</label>
                <textarea className="ed-ta" rows={3} value={form_?.systemPrompt ?? ''} onChange={(e) => set({ systemPrompt: e.target.value })} />
              </div>
            </div>

            {/* 4 欢迎与引导（v1 分组管理对齐：未分组 + 分组折叠/重命名/删除/条目归类） */}
            <div id="ed-sec-guide" className="ed-sec">
              <div className="ed-sec-h"><b>④ 欢迎与引导</b><span className="hint">展示在终端用户首屏 · 上限 {MAX_RECOMMENDED_ITEMS} 条</span></div>
              <div className="ed-f">
                <label>欢迎词（Markdown，展示在终端用户首屏）</label>
                <textarea className="ed-ta" rows={3} value={form_?.welcomeMessage ?? ''} onChange={(e) => set({ welcomeMessage: e.target.value })}
                          placeholder="如：你好！我是销售助理，可以问我业绩、客户、订单等相关问题。" />
                <div style={{ fontSize: 11, color: '#B6B1C9', marginTop: 4 }}>留空则使用默认欢迎语。支持 Markdown 语法（加粗、列表等）。</div>
              </div>
              <div className="ed-f">
                <label>推荐问题 / 操作（终端用户可一键点击发送）</label>
                {/* 未分组 */}
                <div style={{ marginBottom: 8 }}>
                  <button type="button" className="ed-fold" onClick={() => setGuideOpen((v) => !v)}>
                    <span style={{ color: '#B6B1C9', fontSize: 10 }}>{guideOpen ? '▾' : '▸'}</span>
                    <span style={{ color: '#B97A0F' }}>📁</span>
                    <span style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--color-ink-dim)' }}>未分组</span>
                    <span style={{ marginLeft: 'auto', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--color-ink-dim)' }}>
                      {(form_?.recommendedItems ?? []).length} / {MAX_RECOMMENDED_ITEMS}
                    </span>
                  </button>
                  {guideOpen && (
                    <div style={{ paddingLeft: 8, paddingTop: 4 }}>
                      {(form_?.recommendedItems ?? []).length < MAX_RECOMMENDED_ITEMS && (
                        <div style={{ marginBottom: 6 }}>
                          <span className="ed-mini" onClick={() => setForm((f) => f ? { ...f, recommendedItems: [...(f.recommendedItems ?? []), { label: '', prompt: '' }] } : f)}>＋ 添加推荐项</span>
                        </div>
                      )}
                      {(form_?.recommendedItems ?? []).map((it, idx) => {
                        return (
                          <div key={idx} className="ed-gitem">
                            <div style={{ display: 'flex', gap: 8, marginBottom: 6 }}>
                              <input className="ed-ginput" style={{ flex: 1 }} value={it.label}
                                     onChange={(e) => setForm((f) => f ? { ...f, recommendedItems: (f.recommendedItems ?? []).map((x, i) => i === idx ? { ...x, label: e.target.value } : x) } : f)}
                                     placeholder="显示文案（必填），如：导出本月报表" />
                              <span className="ed-mini" onClick={() => setForm((f) => f ? { ...f, recommendedItems: (f.recommendedItems ?? []).filter((_, i) => i !== idx) } : f)}
                                    title="删除">🗑</span>
                            </div>
                            <div style={{ display: 'flex', gap: 8 }}>
                              <input className="ed-ginput" style={{ flex: 1.4 }} value={it.prompt}
                                     onChange={(e) => setForm((f) => f ? { ...f, recommendedItems: (f.recommendedItems ?? []).map((x, i) => i === idx ? { ...x, prompt: e.target.value } : x) } : f)}
                                     placeholder="实际发送内容（留空则同显示文案）" />
                              <select className="ed-ginput" style={{ flex: 1 }} value={UNGROUPED}
                                      onChange={(e) => assignItem(UNGROUPED, idx, Number(e.target.value))}>
                                <option value={UNGROUPED}>未分组（独立展示）</option>
                                {(form_?.recommendedGroups ?? []).map((g, gi) => (
                                  <option key={gi} value={gi} disabled={g.items.length >= MAX_GROUP_ITEMS}>{g.title}</option>
                                ))}
                              </select>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  )}
                </div>
                {/* 分组列表 */}
                {(form_?.recommendedGroups ?? []).map((g, gi) => (
                  <div key={g.title} style={{ marginBottom: 8 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 4 }}>
                      {renaming === gi ? (
                        <input autoFocus className="ed-ginput" style={{ flex: 1, maxWidth: 200 }} value={renameText} maxLength={20}
                               onChange={(e) => setRenameText(e.target.value)}
                               onBlur={() => commitRename(gi)}
                               onKeyDown={(e) => { if (e.key === 'Enter') commitRename(gi); if (e.key === 'Escape') setRenaming(null); }} />
                      ) : (
                        <span style={{ fontSize: 11.5, fontWeight: 600, color: 'var(--color-ink-dim)' }}>📁 {g.title}
                          <span style={{ fontFamily: 'var(--font-mono)', marginLeft: 6 }}>{g.items.length} / {MAX_GROUP_ITEMS}</span>
                        </span>
                      )}
                      {renaming !== gi && (
                        <>
                          <span className="ed-mini" onClick={() => { setRenaming(gi); setRenameText(g.title); }}>✎ 重命名</span>
                          <span className="ed-mini danger" title={`删除分组（${g.items.length} 条移入未分组）`}
                                onClick={() => removeGroup(gi)}>🗑 删除</span>
                        </>
                      )}
                    </div>
                    <div style={{ paddingLeft: 8 }}>
                      {g.items.map((it, ii) => (
                        <div key={ii} className="ed-gitem">
                          <div style={{ display: 'flex', gap: 8, marginBottom: 6 }}>
                            <input className="ed-ginput" style={{ flex: 1 }} value={it.label}
                                   onChange={(e) => updateGroupItem(gi, ii, { label: e.target.value })} placeholder="显示文案" />
                            <span className="ed-mini danger" onClick={() => removeGroupItem(gi, ii)}>🗑</span>
                          </div>
                          <input className="ed-ginput" value={it.prompt}
                                 onChange={(e) => updateGroupItem(gi, ii, { prompt: e.target.value })} placeholder="实际发送内容" />
                        </div>
                      ))}
                      {g.items.length < MAX_GROUP_ITEMS && (
                        <span className="ed-mini" onClick={() => addGroupItem(gi)}>＋ 添加条目</span>
                      )}
                    </div>
                  </div>
                ))}
                {/* 底部操作组（v1 同款：添加/批量/新建分组 + 分组计数） */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 8, paddingTop: 8, borderTop: '1px solid #F4F2FA' }}>
                  <span className="ed-mini" onClick={() => setForm((f) => f ? { ...f, recommendedItems: [...(f.recommendedItems ?? []), { label: '', prompt: '' }] } : f)}>＋ 添加推荐项</span>
                  <span className="ed-mini" onClick={() => setBulkOpen(true)}>📋 批量添加</span>
                  <span className="ed-mini" onClick={() => setCreateGroupOpen(true)}>＋ 新建分组</span>
                  <span style={{ marginLeft: 'auto', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--color-ink-dim)' }}>
                    {(form_?.recommendedGroups ?? []).length} / {MAX_RECOMMENDED_GROUPS} 组
                  </span>
                </div>
                {/* 新建分组 */}
                {createGroupOpen ? (
                  <div style={{ display: 'flex', gap: 8, marginTop: 4 }}>
                    <input autoFocus className="ed-ginput" style={{ maxWidth: 220 }} value={createGroupText} maxLength={20}
                           onChange={(e) => setCreateGroupText(e.target.value)}
                           onKeyDown={(e) => { if (e.key === 'Enter') commitCreateGroup(); }} placeholder="分组名（如：数据分析）" />
                    <span className="ed-mini" onClick={commitCreateGroup}>创建</span>
                    <span className="ed-mini" onClick={() => { setCreateGroupOpen(false); setCreateGroupText(''); }}>取消</span>
                  </div>
                ) : (
                  <span className="ed-mini" onClick={() => setCreateGroupOpen(true)}>＋ 新建分组</span>
                )}
              </div>
            </div>

            {/* 5 工具与技能 */}
            <div id="ed-sec-tools" className="ed-sec">
              <div className="ed-sec-h"><b>⑤ 工具与技能</b><span className="hint">点击挂载 / 卸载</span></div>
              <div className="ed-f">
                <label>内置工具</label>
                <div className="ed-chips">
                  {builtinOptions.map((o) => {
                    const on = (form_?.skills ?? []).includes(`builtin:${o.id}`);
                    return (
                      <span key={o.id} className={`ed-chip ${on ? 'on' : ''}`} onClick={() => toggleSkill('builtin', o.id)}>
                        {on ? <span className="x">✓</span> : '＋'}{o.label}
                      </span>
                    );
                  })}
                </div>
              </div>
              <div className="ed-f">
                <label>技能</label>
                <Chips options={skillOptions} selected={(form_?.skills ?? []).filter((s) => !s.includes(':'))}
                       onToggle={(id) => toggleSkill('', id)} />
              </div>
              <div className="ed-f">
                <label>MCP 接入</label>
                <Chips options={mcpOptions} selected={(form_?.skills ?? []).filter((s) => s.startsWith('mcp:')).map((s) => s.slice(4))}
                       onToggle={(id) => toggleSkill('mcp', id)} />
              </div>
            </div>

            {/* 6 知识库 */}
            <div id="ed-sec-kb" className="ed-sec">
              <div className="ed-sec-h"><b>⑥ 知识库</b></div>
              <Chips options={kbOptions} selected={(form_?.skills ?? []).filter((s) => s.startsWith('kb:')).map((s) => s.slice(3))}
                     onToggle={(id) => toggleSkill('kb', id)} />
            </div>

            {/* 7 执行与委派 */}
            <div id="ed-sec-exec" className="ed-sec">
              <div className="ed-sec-h"><b>⑦ 执行与委派</b></div>
              <div className="ed-f">
                <label>可委派子 Agent 池（仅已发布）</label>
                <Chips options={subOptions} selected={(form_?.skills ?? []).filter((s) => s.startsWith('subagent:')).map((s) => s.slice(9))}
                       onToggle={(id) => toggleSkill('subagent', id)} />
              </div>
              <div style={{ display: 'flex', gap: 24, marginTop: 4 }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12.5, cursor: 'pointer' }}>
                  <input type="checkbox" checked={form_?.canSpawnAgents ?? false} onChange={(e) => set({ canSpawnAgents: e.target.checked })} />
                  允许自繁殖（创建新 Agent）
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 12.5, cursor: 'pointer' }}>
                  <input type="checkbox" checked={form_?.voiceEnabled ?? false} onChange={(e) => set({ voiceEnabled: e.target.checked })} />
                  启用语音对话
                </label>
              </div>
            </div>

          </div>
          </div>

        </div>
      </div>
      {bulkOpen && (
          <div className="ed-bulk-mask" onClick={() => setBulkOpen(false)}>
            <div className="ed-bulk" onClick={(e) => e.stopPropagation()}>
              <b style={{ fontSize: 15 }}>批量添加推荐项</b>
              <div style={{ fontSize: 11.5, color: '#9A95B0', margin: '6px 0 10px', lineHeight: 1.6 }}>
                每行一条：<code>显示文案 | 实际发送提示词</code>（提示词可省略则同显示文案）。
                也支持粘贴 JSON 数组：[{'{'}"label": "…", "prompt": "…"{'}'}]
              </div>
              <textarea className="ed-bulk-ta" value={bulkText} onChange={(e) => setBulkText(e.target.value)}
                        placeholder={'导出本月报表 | 查询并导出本月数据报表\n分析 Q3 销售数据'} />
              <div style={{ display: 'flex', alignItems: 'center', marginTop: 10, gap: 8 }}>
                <span style={{ fontSize: 11.5, color: bulkParsed.invalid > 0 ? 'var(--color-danger)' : '#9A95B0' }}>
                  解析到 {bulkParsed.items.length} 条{bulkParsed.invalid > 0 ? ` · ${bulkParsed.invalid} 条无效` : ''}
                </span>
                <span style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
                  <span className="ed-bg" onClick={() => { setBulkOpen(false); setBulkText(''); }}>取消</span>
                  <button className="ed-bp" disabled={bulkParsed.items.length === 0}
                          onClick={() => { setForm((f) => f ? { ...f, recommendedItems: [...(f.recommendedItems ?? []), ...bulkParsed.items] } : f); setBulkOpen(false); setBulkText(''); }}>
                    导入 {bulkParsed.items.length} 条
                  </button>
                </span>
              </div>
            </div>
          </div>
        )}
    </div>
  );
}

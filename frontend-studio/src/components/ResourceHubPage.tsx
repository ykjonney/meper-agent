/**
 * ResourceHubPage — 资源库：知识库 / 模型配置 / 技能 / 工具库 / MCP 接入 的合并入口。
 *
 * 靛蓝改版（设计稿 resource-hub-page.html）：衬线页头「资源库 · N 类 · N 项」
 * + 下划线 tab（带实时计数，选中 = 靛蓝 + 底线）——MCP 接入从独立导航并入为
 * 第 5 个 tab。各 pane 复用现有子页组件（功能完整），签名卡视觉按子页逐个改造。
 *
 * tab 计数：hub 层以与子页相同的 queryKey 拉各类列表（react-query 缓存共享，
 * 子页不重复请求）。
 */
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useAuthStore } from '../stores/auth-store';
import { knowledgeApi, knowledgeKeys } from '../services/knowledge-api';
import { modelApi } from '../services/model-api';
import { toolsApi } from '../services/tools-api';
import { mcpApi, mcpKeys } from '../services/mcp-api';
import { KnowledgeBasePage } from './KnowledgeBasePage';
import { ModelsPage } from './ModelsPage';
import { UserSkillsPage } from './UserSkillsPage';
import { ToolMarketPage } from './ToolMarketPage';
import { McpManagePage } from './McpManagePage';
import { KbDetailPage } from './KbDetailPage';
import { KbVectorDetailPage } from './KbVectorDetailPage';
import { SkillDetailPage } from './SkillDetailPage';

interface ResourceTab {
  id: 'knowledge' | 'models' | 'skills' | 'tool-market' | 'mcp';
  label: string;
  /** 单键精确匹配；undefined = 所有登录用户可见。 */
  perm?: string;
}

const TABS: ResourceTab[] = [
  { id: 'knowledge', label: '知识库', perm: 'knowledge:read' },
  { id: 'models', label: '模型配置', perm: 'model:read' },
  { id: 'skills', label: '技能' },
  { id: 'tool-market', label: '工具库' },
  { id: 'mcp', label: 'MCP 接入', perm: 'tool:read' },
];

export function ResourceHubPage({ theme }: { theme: 'dark' | 'light' }) {
  const permissions = useAuthStore((s) => s.user?.permissions ?? []);
  const visibleTabs = TABS.filter((t) => !t.perm || permissions.includes(t.perm));
  const [tab, setTab] = useState<ResourceTab['id']>(visibleTabs[0]?.id ?? 'skills');
  const [openKb, setOpenKb] = useState<{ id: string; name: string; type: 'tree' | 'vector' } | null>(null);
  const [openSkill, setOpenSkill] = useState<{ id: string; name: string } | null>(null);

  // ── tab 实时计数（与子页同 queryKey，缓存共享零额外请求成本） ──
  const { data: kbCountData } = useQuery({
    queryKey: knowledgeKeys.list({}),
    queryFn: () => knowledgeApi.list({ page: 1, page_size: 50 }),
    enabled: visibleTabs.some((t) => t.id === 'knowledge'),
  });
  const { data: modelsData } = useQuery({
    queryKey: ['models', 'list', { page_size: 100 }],
    queryFn: () => modelApi.list({ page_size: 100 }),
    enabled: visibleTabs.some((t) => t.id === 'models'),
  });
  const { data: skillsData } = useQuery({
    queryKey: ['builtin-tools', 'skills-count'],
    queryFn: () => toolsApi.list({ source: 'markdown', page_size: 100 }),
    enabled: visibleTabs.some((t) => t.id === 'skills'),
  });
  const { data: toolsData } = useQuery({
    queryKey: ['tools', 'hub-count'],
    queryFn: () => toolsApi.list({ page_size: 100 }),
    enabled: visibleTabs.some((t) => t.id === 'tool-market'),
  });
  const { data: mcpData } = useQuery({
    queryKey: mcpKeys.list({ page: 1, page_size: 100 }),
    queryFn: () => mcpApi.list({ page: 1, page_size: 100 }),
    enabled: visibleTabs.some((t) => t.id === 'mcp'),
  });

  const mdToolCount = skillsData?.items?.length ?? 0;
  const tabCounts: Record<ResourceTab['id'], number> = {
    knowledge: kbCountData?.items?.length ?? 0,
    models: modelsData?.items?.length ?? 0,
    skills: mdToolCount,
    'tool-market': (toolsData?.items?.length ?? 0) - mdToolCount,
    mcp: mcpData?.items?.length ?? 0,
  };
  const totalItems = visibleTabs.reduce((sum, t) => sum + (tabCounts[t.id] ?? 0), 0);

  return (
    <div className="af-scope theme-indigo h-full min-h-0 flex flex-col">
      {/* 页头：衬线大标题 + mono 计数（列表页模板） */}
      <div className="af-page-head shrink-0">
        <h2 className="text-[22px] font-bold text-ink" style={{ fontFamily: 'var(--font-serif)' }}>资源库</h2>
        <span className="af-cnt font-mono">{visibleTabs.length} 类 · {totalItems} 项</span>
      </div>

      {/* 下划线 tab：选中 = 靛蓝 + 底线 + mono 计数 */}
      <div className="shrink-0 flex items-center gap-[26px] border-b border-line mt-3" style={{ marginTop: 14 }}>
        {visibleTabs.map((t) => (
          <button
            key={t.id}
            onClick={() => { setTab(t.id); setOpenKb(null); setOpenSkill(null); }}
            className={`flex items-center gap-1.5 px-0.5 pt-2 pb-[9px] text-[13px] -mb-px border-b-2 transition-colors cursor-pointer ${
              tab === t.id
                ? 'text-brand border-brand font-bold'
                : 'text-ink-dim border-transparent hover:text-ink'
            }`}
          >
            {t.label}
            <span className={`font-mono text-[11px] ${tab === t.id ? 'text-brand opacity-70' : 'text-ink-faint'}`}>
              {tabCounts[t.id] ?? 0}
            </span>
          </button>
        ))}
      </div>

      {/* 子页面区：内容区限宽居中（卡片宽度由设计元素决定——徽章 38 + 标题区 +
          pill ≈ 380-400px/卡最舒展，全屏拉伸会导致卡片虚胖）。
          overflow-hidden：列表类子页（模型/技能/工具库/MCP）自带内滚容器，
          工具栏结构固定不滚；详情页（无内滚）内容溢出时仍由本容器滚动。 */}
      <div className="flex-1 min-h-0 overflow-hidden pt-4">
        <div className="w-full max-w-[1200px] h-full min-h-0">
        {tab === 'knowledge' && (
          openKb ? (
            openKb.type === 'vector' ? (
              <KbVectorDetailPage
                kbId={openKb.id}
                kbName={openKb.name}
                onBack={() => setOpenKb(null)}
              />
            ) : (
              <KbDetailPage
                kbId={openKb.id}
                kbName={openKb.name}
                onBack={() => setOpenKb(null)}
              />
            )
          ) : (
            <KnowledgeBasePage onOpenKb={(kb) => setOpenKb({ id: kb.id, name: kb.name, type: kb.type })} />
          )
        )}

        {tab === 'models' && <ModelsPage />}

        {tab === 'skills' && (
          openSkill ? (
            <SkillDetailPage
              toolId={openSkill.id}
              toolName={openSkill.name}
              onBack={() => setOpenSkill(null)}
            />
          ) : (
            <UserSkillsPage
              theme={theme}
              onOpenOfficial={(id, name) => setOpenSkill({ id, name })}
            />
          )
        )}

        {tab === 'tool-market' && <ToolMarketPage theme={theme} />}

        {tab === 'mcp' && <McpManagePage />}
        </div>
      </div>
    </div>
  );
}

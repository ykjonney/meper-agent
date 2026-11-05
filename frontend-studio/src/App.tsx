import { useState, useEffect, useMemo, useRef } from 'react';
import {
  Bot, LayoutDashboard, Layers, Key,
  ListTodo, Shield,
  Clock, Mic,
  Link2, ArrowLeftRight, Store,
} from 'lucide-react';
import { useAuthStore, REFRESH_TOKEN_KEY } from './stores/auth-store';
import { useQuery, useQueries, useQueryClient } from '@tanstack/react-query';
import { agentApi, agentKeys, type Agent as BackendAgent } from './services/agent-api';
import { toStudioAgent } from './services/adapters';
import { authApi } from './services/auth-api';
import { tasksApi, taskKeys, type TaskStatusValue } from './services/tasks-api';
import { workflowsApi, workflowKeys } from './services/workflows-api';
import Login from './components/Login';
import { AuthInitializer } from './components/AuthInitializer';
import { Toaster } from './components/ui/toast';
import { ConfirmHost } from './components/ui/confirm';
import { ChatHomepage } from './components/ChatHomepage';
import { VoiceHomepage } from './components/voice/VoiceHomepage';
import { TaskBoard } from './components/TaskBoard';
import { TaskDetailPage } from './components/task/TaskDetailPage';
import { Dashboard } from './components/Dashboard';
import { AgentSpace } from './components/AgentSpace';
import { AgentEditorPage } from './components/AgentEditorPage';
import { WorkflowDesigner } from './components/WorkflowDesigner';
import { WorkflowSpace } from './components/WorkflowSpace';
import { ResourceHubPage } from './components/ResourceHubPage';
import { UserManagement } from './components/UserManagement';
import { TransferManagementPage } from './components/transfer/TransferManagementPage';
import { ExternalAuthPage } from './components/ExternalAuthPage';
import { SettingsPage } from './components/SettingsPage';
import { ProfilePage } from './components/ProfilePage';
import { NotificationCenter } from './components/notification-center';
import { ActivationWizard } from './components/ActivationWizard';
import { licenseApi, licenseKeys } from './services/license-api';
import { useTaskRealtime } from './hooks/use-task-realtime';
import { wsClient } from './lib/ws-client';
import { useNotificationStore } from './stores/notification-store';
import type { Agent } from './types';

/**
 * Navigation items, each mapping to a backend permission key. Items whose
 * permission the current user lacks are filtered out (mirrors the umi/Max
 * AppLayout NAV_GROUPS permission gating in frontend/src/layouts/AppLayout.tsx).
 *
 * `permission: undefined` means "always visible" (e.g. the home board).
 *
 * v3.2 Workbench：侧栏按「工作台 / 资产 / 管理」三组分区渲染（NAV_GROUPS）；
 * 知识库/模型配置/技能/工具库四个"创建配置资源"性质的功能合并为「资源库」
 * 单一入口（ResourceHubPage 页内 Tab 切换）。
 */
interface NavItem {
  id: string;
  label: string;
  icon: typeof Bot;
  badge?: string;
  /** 权限门控：单键精确匹配；数组 = 任一满足（多权限域页面的入口并集）。 */
  permission?: string | string[];
  /** 仅 admin 角色可见（如导入导出中心），与 permission 点过滤叠加。 */
  adminOnly?: boolean;
}

const NAV_ITEMS: NavItem[] = [
  { id: 'voice', label: '语音对话', icon: Mic },
  // 任务看板 badge 由下方 activeTaskCount 实时注入（执行中 + 等待人工）。
  { id: 'board', label: '任务看板', icon: ListTodo },
  { id: 'dashboard', label: '仪表盘', icon: LayoutDashboard, permission: 'execution:read:own' },
  { id: 'agents', label: '智能体', icon: Bot, permission: 'agent:read' },
  { id: 'workflows', label: '工作流', icon: Layers, permission: 'workflow:read' },
  // 资源库 = 知识库/模型配置/技能/工具库/MCP 接入 合并入口（ResourceHubPage 页内
  // Tab 各自沿用原权限门控）。入口恒可见，无权限的 Tab 在页内隐藏。
  // MCP 接入并入资源库第 5 个 tab（设计稿 resource-hub-page.html），不再单独导航。
  { id: 'resource', label: '资源库', icon: Store },
  // 外部授权：所有登录用户可见；应用管理操作按 application:write 权限在卡片上显示。
  { id: 'external-auth', label: '外部授权', icon: Link2 },
  { id: 'users', label: '用户权限', icon: Shield, permission: 'user:read' },
  // 数据导入导出中心：资源包（afpkg）迁移入口，仅管理员可见（后端 admin/developer 双角色放行）。
  { id: 'transfer', label: '导入导出', icon: ArrowLeftRight, adminOnly: true },
  // 系统设置 = 多权限域容器（SettingsPage 内 Tab 各自门控）：语音/通用走
  // settings:manage，消息渠道走 channel:read。入口 permission 为数组——任一满足即可见。
  { id: 'settings', label: '系统设置', icon: Key, permission: ['settings:manage', 'channel:read'] },
];

export default function App() {
  const [activeTab, setActiveTab] = useState<string>('chat');
  // Theme persists across reloads via localStorage (key mirrors the existing
  // `agentflow_` prefix used by auth-store.ts). Falls back to 'light'
  // (v3.2 Workbench: 亮色为默认主题).
  const [theme, setTheme] = useState<'dark' | 'light'>(
    () => (localStorage.getItem('agentflow_theme') as 'dark' | 'light') || 'light',
  );
  // 主题 class 同步到 <html>：portal 到 body 的浮层（Modal/Confirm 等）
  // 在下方根 div 的 .theme-* 作用域之外，token 变量会回落暗色默认值
  // （亮色模式下弹窗发黑）。挂到 documentElement 让所有层共享主题。
  useEffect(() => {
    const root = document.documentElement
    root.classList.remove('theme-dark', 'theme-light')
    root.classList.add(`theme-${theme}`)
  }, [theme])

  // Sub-state for the workflow editor (list → click card → editor).
  const [openWorkflow, setOpenWorkflow] = useState<string | null>(null);
  // Sub-state for the Agent detail / live-test split view + editor.
  const [openAgent, setOpenAgent] = useState<{ id: string; mode: 'edit' } | null>(null);

  // ── Auth gate ──────────────────────────────────────────────
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const clearAuth = useAuthStore((s) => s.clearAuth);
  const authUser = useAuthStore((s) => s.user);

  // ── License gate（激活向导闸门，优先于登录）────────────────────
  // 任意页面加载都会拉一次状态；api-client 拦到 403 LIC_E_* 时派发
  // agentflow-license-blocked 事件 → 此处 invalidate → 闸门即时生效。
  const queryClient = useQueryClient();
  const { data: license } = useQuery({
    queryKey: licenseKeys.status,
    queryFn: () => licenseApi.status().then((res) => res.data),
    staleTime: 60_000,
    retry: 1,
  });
  useEffect(() => {
    const handler = () => queryClient.invalidateQueries({ queryKey: licenseKeys.status });
    window.addEventListener('agentflow-license-blocked', handler);
    return () => window.removeEventListener('agentflow-license-blocked', handler);
  }, [queryClient]);

  // 任务详情全屏 view（看板卡片=full 操作模式；通知中心/Dashboard/Triggers=仅查看）。
  // 由 TaskDetailPage 内部 useQuery 拉取 GET /tasks/{id}，刷新由 WS invalidate 驱动。
  const [activeTaskDetail, setActiveTaskDetail] = useState<{ id: string; mode: 'full' | 'view' } | null>(null);

  // Live agent list for the ChatHomepage agent picker + count badge.
  const { data: agentsData } = useQuery({
    queryKey: agentKeys.list({ page: 1, page_size: 50, status: 'all' }),
    queryFn: () => agentApi.list({ page: 1, page_size: 50, status: 'all' }),
    enabled: isAuthenticated,
    staleTime: 60_000,
  });
  const agentCount = agentsData?.total ?? 0;
  const studioAgents: Agent[] = useMemo(
    () => (agentsData?.items ?? []).map(toStudioAgent),
    [agentsData],
  );

  // 图算工作流 badge：动态获取工作流总数（与 WorkflowSpace 列表共用缓存键，
  // 新建/删除后数字自动同步）。
  const { data: workflowsData } = useQuery({
    queryKey: workflowKeys.list({ page: 1, page_size: 100 }),
    queryFn: () => workflowsApi.list({ page: 1, page_size: 100 }),
    enabled: isAuthenticated,
    staleTime: 60_000,
  });
  const workflowCount = workflowsData?.total ?? 0;

  // 任务协作看板 badge：聚合“活跃”状态（待执行 + 执行中 + 等待人工）的任务数。
  // 复用与 TaskBoard 相同的 taskKeys.list({status}) 缓存键，列表打开后两侧共享缓存、
  // 数字始终一致；刷新由 WebSocket 的 task_status 事件 invalidate 驱动（见
  // use-task-realtime），不做定时轮询。
  const BOARD_BADGE_STATUSES: TaskStatusValue[] = ['running', 'waiting_human'];
  const boardBadgeQueries = useQueries({
    queries: BOARD_BADGE_STATUSES.map((status) => ({
      queryKey: taskKeys.list({ status, page: 1, page_size: 50 }),
      queryFn: () => tasksApi.list({ status, page: 1, page_size: 50 }),
      enabled: isAuthenticated,
      // 用列表 total 作为该状态计数（任务量不大时 page_size=50 足够准确）。
      select: (res: { total: number }) => res.total,
      staleTime: 30_000,
    })),
  });
  const activeTaskCount = useMemo(
    () => boardBadgeQueries.reduce((sum, q) => sum + (q.data ?? 0), 0),
    [boardBadgeQueries],
  );

  // ── Realtime: WS task_status → react-query invalidate; WS notification → store ──
  // Mounted once at the App root; safe to call every render (it no-ops internally
  // until wsClient.connect() is driven by the isAuthenticated effect below).
  useTaskRealtime();

  // WS lifecycle follows auth state — connect on login, disconnect on logout.
  // Initial unread count is loaded once the user enters the main UI.
  const loadUnreadCount = useNotificationStore((s) => s.loadUnreadCount);
  useEffect(() => {
    if (!isAuthenticated) {
      wsClient.disconnect();
      return;
    }
    wsClient.resume();
    wsClient.connect();
    loadUnreadCount();
  }, [isAuthenticated, loadUnreadCount]);

  // Keep the WS connection in sync with access-token refreshes.
  //
  // Background: axios refreshes the access token lazily (only when an HTTP
  // request hits 401). The WS client reconnecting blindly after a 4401 close
  // would re-use the still-stale token in the store and loop connect→reject
  // until some unrelated HTTP request happened to refresh it. By subscribing
  // to the store's accessToken here, the moment a refresh lands we hand the
  // fresh token straight to the WS client and it reconnects immediately.
  useEffect(() => {
    let lastToken = useAuthStore.getState().accessToken;
    return useAuthStore.subscribe((state) => {
      const nextToken = state.accessToken;
      if (nextToken && nextToken !== lastToken) {
        lastToken = nextToken;
        // Only act when authenticated — disconnect/logout clears the token and
        // the isAuthenticated effect above handles teardown.
        wsClient.reconnectWithFreshToken(nextToken);
      }
    });
  }, []);

  const permissions = authUser?.permissions ?? [];
  // 数组 = 任一满足（多权限域页面的入口并集，如系统设置）
  const has = (perm?: string | string[]) =>
    !perm ||
    (Array.isArray(perm) ? perm.some((p) => permissions.includes(p)) : permissions.includes(perm));

  const visibleNav = useMemo(() => {
    const items = NAV_ITEMS.filter(
      (n) => has(n.permission) && (!n.adminOnly || authUser?.role === 'admin'),
    );
    // Inject live counts into the badges (agents total / board active tasks / workflows total).
    return items.map((n) => {
      if (n.id === 'agents') return { ...n, badge: String(agentCount) };
      if (n.id === 'board') return { ...n, badge: String(activeTaskCount) };
      if (n.id === 'workflows') return { ...n, badge: String(workflowCount) };
      return n;
    });
  }, [permissions, authUser, agentCount, activeTaskCount, workflowCount]);

  // If the active tab got filtered out, fall back to the first visible tab.
  // chat（默认主页）与 profile 是非导航项的合法页面，不参与回退判断。
  useEffect(() => {
    if (activeTab === 'chat' || activeTab === 'profile') return;
    if (!visibleNav.some((n) => n.id === activeTab)) {
      setActiveTab('chat');
    }
  }, [visibleNav, activeTab]);

  // Auth gate: AuthInitializer (mounted in main.tsx) drives the refresh-check
  // window and the initializing spinner; here we only branch on the resolved
  // auth state. All hooks above must run unconditionally on every render
  // (Rules of Hooks). Return only after the last hook has been called.
  // License gate：强制模式下未激活/失效 → 全屏激活向导（在登录之前——
  // 未激活时可能还没有任何账号）。dev_mode（源码轨）不拦截。
  if (license && license.enforced && !license.activated) {
    return (
      <ActivationWizard
        status={license}
        onActivated={() => queryClient.invalidateQueries({ queryKey: licenseKeys.status })}
      />
    );
  }

  if (!isAuthenticated) return <Login />;
  // ───────────────────────────────────────────────────────────

  const displayName = authUser?.username ?? '用户';
  const displayEmail = authUser?.username ? `${authUser.username}@agentflow` : '';

  // 登出：调 /auth/logout 吊销 refresh token，清本地登录态，跳登录页
  const handleLogout = async () => {
    const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY);
    try {
      if (refreshToken) await authApi.logout(refreshToken);
    } catch {
      // 登出接口幂等，失败也继续清除本地态
    } finally {
      clearAuth();
      window.location.href = '/login';
    }
  };

  // 非聊天路由的右侧内容：license 条 + 页面 stage。组装后交给全局壳层
  // （ChatHomepage 的融合侧栏在所有页面保持不变，仅右侧区域切换）。
  const stageClass =
    activeTab === 'voice' ? 'h-full flex flex-col p-0 overflow-hidden' :
    activeTab === 'board' ? 'h-full flex flex-col p-6 pb-0 overflow-hidden' :
    activeTab === 'workflows' && openWorkflow ? 'h-full flex flex-col p-6 overflow-hidden' :
    // Agent 编辑器自带贴底 footer 与内部滚动，stage 去 padding 由页面控制留白
    activeTab === 'agents' && openAgent ? 'h-full flex flex-col p-0 overflow-hidden' :
    activeTab === 'agents' ? 'h-full flex flex-col px-6 pt-6 overflow-hidden' :
    activeTab === 'users' ? 'h-full flex flex-col p-6 overflow-hidden' :
    'overflow-y-auto p-6';
  // 聊天态（默认主页）传 null → 壳层渲染聊天面板；任务详情覆盖所有页面。
  const showChat = activeTab === 'chat' && !activeTaskDetail;
  const activePage = showChat ? null : (
    <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
      {activeTaskDetail ? (
        <TaskDetailPage
          taskId={activeTaskDetail.id}
          mode={activeTaskDetail.mode}
          onBack={() => setActiveTaskDetail(null)}
          theme={theme}
        />
      ) : (
        <>
          {/* 到期警告条：≤30 天（含永久授权为 null 的豁免） */}
          {license?.activated && license.days_left != null && license.days_left <= 30 && (
            <div className="h-9 shrink-0 flex items-center justify-center gap-2 bg-sig-wait-soft border-b border-line text-sig-wait text-xs">
              <Clock className="w-3.5 h-3.5" />
              授权将于 {license.expires_at ? new Date(license.expires_at).toLocaleDateString() : '—'} 到期（剩 {license.days_left} 天），请联系供应商续费
            </div>
          )}
          <div id="content_stage" className={stageClass}>
            {activeTab === 'voice' && (
              <VoiceHomepage agents={studioAgents} theme={theme} />
            )}

            {activeTab === 'board' && (
              <TaskBoard theme={theme} onOpenTaskDetail={(id) => setActiveTaskDetail({ id, mode: 'full' })} />
            )}

            {activeTab === 'dashboard' && (
              <Dashboard
                onSelectTab={setActiveTab}
                onViewTask={(task) => setActiveTaskDetail({ id: task.id, mode: 'view' })}
              />
            )}

            {activeTab === 'agents' && (
              openAgent ? (
                /* 配置页即详情页：全字段可编辑（侧栏保留，编辑器渲染在右侧区域
                   ——所有功能的操作都在右侧完成）。保存后留在编辑器（Toast 反馈），
                   返回列表由用户点左上返回。 */
                <AgentEditorPage
                  agentId={openAgent.id}
                  onBack={() => setOpenAgent(null)}
                />
              ) : (
                <AgentSpace onOpenEdit={(id) => setOpenAgent({ id, mode: 'edit' })} />
              )
            )}

            {activeTab === 'workflows' && (
              openWorkflow ? (
                <WorkflowDesigner
                  theme={theme}
                  workflowId={openWorkflow}
                  onBack={() => setOpenWorkflow(null)}
                  onCreated={(id) => setOpenWorkflow(id)}
                />
              ) : (
                <WorkflowSpace theme={theme} onOpen={(id) => setOpenWorkflow(id)} />
              )
            )}

            {/* 资源库 = 知识库/模型配置/技能/工具库/MCP 接入 合并入口（页内 Tab） */}
            {activeTab === 'resource' && <ResourceHubPage theme={theme} />}

            {activeTab === 'users' && <UserManagement />}
            {activeTab === 'transfer' && <TransferManagementPage theme={theme} />}
            {activeTab === 'external-auth' && <ExternalAuthPage />}
            {activeTab === 'settings' && <SettingsPage theme={theme} />}

            {activeTab === 'profile' && (
              <ProfilePage theme={theme} />
            )}
          </div>
        </>
      )}
    </div>
  );

  return (
    <div className="h-dvh flex overflow-hidden theme-indigo bg-page text-ink transition-colors duration-200">
      {/* 全局壳层：融合侧栏常驻（功能导航 + 会话历史），右侧按 activePage 切换——
          点功能/点会话都不再整条更换左侧目录，编辑器等操作全部在右侧区域完成 */}
      <ChatHomepage
        agents={studioAgents}
        theme={theme}
        userInitial={displayName[0]}
        navItems={visibleNav}
        activeId={activeTab}
        onNavigate={(tab) => { setActiveTab(tab); setActiveTaskDetail(null); setOpenAgent(null); }}
        onLogout={handleLogout}
        activePage={activePage}
      />

      {/* 全局消息提醒：Toast + 统一确认弹窗（内联渲染，继承 theme-${theme} 主题） */}
      <Toaster />
      <ConfirmHost />

    </div>
  );
}


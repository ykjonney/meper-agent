/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React from 'react';
import { Layout, Menu, Badge } from 'antd';
import {
  Bot,
  Terminal,
  Cpu,
  CheckSquare,
  MessageSquare,
  Activity,
  Layers,
  Workflow,
  Users,
  Shield,
  Key
} from 'lucide-react';
import { useAppState, Tab } from '../AppContext';
import { useTranslation } from '../LocaleContext';

const { Sider } = Layout;

/** Map lucide icon components to React nodes for Menu items */
const iconMap: Record<string, React.ReactNode> = {
  agents: <Bot className="h-4 w-4" />,
  chat: <MessageSquare className="h-4 w-4" />,
  skills: <Terminal className="h-4 w-4" />,
  mcp: <Cpu className="h-4 w-4" />,
  nodes: <Layers className="h-4 w-4" />,
  flows: <Workflow className="h-4 w-4" />,
  tasks: <CheckSquare className="h-4 w-4" />,
  users: <Users className="h-4 w-4" />,
  roles: <Shield className="h-4 w-4" />,
  permissions: <Key className="h-4 w-4" />,
};

interface MenuItemDef {
  key: Tab;
  label: string;
  badge?: number;
  badgeHighlight?: boolean;
  category: string;
}

export const Navigation: React.FC = () => {
  const {
    activeTab,
    setActiveTab,
    agents,
    mcpServers,
    tasks,
    chats,
    flows,
    presetNodes,
    users,
    notifications,
    dismissNotification
  } = useAppState();
  const { t } = useTranslation();

  const activeMcpCount = mcpServers.filter(s => s.status === 'connected').length;
  const runningTasksCount = tasks.filter(t => t.status === 'running').length;

  const menuItems: MenuItemDef[] = [
    {
      key: 'agents',
      label: 'Agent',
      badge: agents.length,
      category: t('nav.aiFoundation'),
    },
    {
      key: 'chat',
      label: 'Chat List',
      badge: chats.length,
      category: t('nav.aiFoundation'),
    },
    {
      key: 'skills',
      label: 'Skills',
      category: t('nav.extensions'),
    },
    {
      key: 'mcp',
      label: 'MCP',
      category: t('nav.extensions'),
    },
    {
      key: 'nodes',
      label: 'Task Node',
      badge: presetNodes.length,
      category: t('nav.workflowEngine'),
    },
    {
      key: 'flows',
      label: 'Work Flow',
      badge: flows.length,
      category: t('nav.workflowEngine'),
    },
    {
      key: 'tasks',
      label: 'Task Board',
      badge: runningTasksCount > 0 ? runningTasksCount : undefined,
      badgeHighlight: runningTasksCount > 0,
      category: t('nav.workflowEngine'),
    },
    {
      key: 'users',
      label: t('nav.users'),
      badge: users.length,
      category: t('nav.systemAdmin'),
    },
    {
      key: 'roles',
      label: t('nav.roles'),
      category: t('nav.systemAdmin'),
    },
    {
      key: 'permissions',
      label: t('nav.permissions'),
      category: t('nav.systemAdmin'),
    },
  ];

  // Build antd Menu items with groups
  const categories = Array.from(new Set(menuItems.map(item => item.category)));

  const antdMenuItems = categories.map(cat => ({
    key: `group-${cat}`,
    type: 'group' as const,
    label: (
      <span className="text-[11px] font-medium uppercase tracking-wider">
        {cat}
      </span>
    ),
    children: menuItems
      .filter(item => item.category === cat)
      .map(item => ({
        key: item.key,
        icon: iconMap[item.key],
        label: (
          <div className="flex items-center justify-between w-full">
            <span className="tracking-tight">{item.label}</span>
            {item.badge !== undefined && (
              item.badgeHighlight ? (
                <Badge count={item.badge} size="small" color="#1677ff" />
              ) : (
                <Badge
                  count={item.badge}
                  size="small"
                  style={{ backgroundColor: 'var(--antd-border, #f0f0f0)', color: 'var(--antd-text-muted, #8c8c8c)' }}
                />
              )
            )}
          </div>
        ),
      })),
  }));

  return (
    <>
      {/* Notifications overlay - global floating */}
      <div className="fixed right-6 top-6 z-50 flex flex-col gap-3 max-w-sm w-full pointer-events-none">
        {notifications.map(n => (
          <div
            key={n.id}
            onClick={() => dismissNotification(n.id)}
            className={`pointer-events-auto flex items-start gap-3 rounded border p-4 shadow-sm transition-all duration-200 hover:translate-y-[-1px] cursor-pointer`}
            style={{
              contentVisibility: 'auto',
              backgroundColor: 'var(--antd-card, #ffffff)',
              borderColor: n.type === 'success' ? '#b7eb8f' : n.type === 'warning' ? '#ffe58f' : '#ffccc7',
            }}
          >
            <div className={`h-2 w-2 rounded-full mt-1.5 ${
              n.type === 'success' ? 'bg-[#52c41a]' : n.type === 'warning' ? 'bg-[#faad14]' : 'bg-[#f5222d]'
            }`} />
            <div className="flex-1">
              <div className="text-xs font-semibold mb-0.5" style={{ color: 'var(--antd-text-muted, #8c8c8c)' }}>
                {n.type === 'success' ? t('common.success') : n.type === 'warning' ? t('common.warning') : t('common.error')}
              </div>
              <div className="text-sm font-normal leading-relaxed" style={{ color: 'var(--antd-text-primary, #262626)' }}>
                {n.message}
              </div>
            </div>
          </div>
        ))}
      </div>

      <Sider
        width={256}
        className="h-screen sticky top-0 shrink-0 !border-r !border-solid select-none"
        style={{ borderColor: 'var(--antd-border, #f0f0f0)', backgroundColor: 'var(--antd-card, #ffffff)' }}
      >
        <div className="flex flex-col h-full">
          {/* Logo area */}
          <div className="h-16 px-6 border-b border-solid flex items-center gap-2.5" style={{ borderColor: 'var(--antd-border, #f0f0f0)' }}>
            <div className="flex h-8 w-8 items-center justify-center rounded bg-[#1677ff] text-white font-bold shadow-sm shadow-[#1677ff]/20">
              <Cpu className="h-4 w-4" />
            </div>
            <div>
              <span className="font-sans font-bold tracking-tight text-base" style={{ color: 'var(--antd-text-primary, #262626)' }}>
                AgentPlat Console
              </span>
              <div className="text-[10px] font-mono leading-none" style={{ color: 'var(--antd-text-muted, #8c8c8c)' }}>
                v1.1.0 · Web Portal
              </div>
            </div>
          </div>

          {/* Menu area */}
          <div className="flex-1 overflow-y-auto py-4 px-3">
            <Menu
              mode="inline"
              selectedKeys={[activeTab]}
              onClick={({ key }) => setActiveTab(key as Tab)}
              items={antdMenuItems}
              className="!border-none"
            />
          </div>

          {/* Bottom stats */}
          <div className="p-4 border-t border-solid" style={{ borderColor: 'var(--antd-border, #f0f0f0)', backgroundColor: 'var(--antd-bg, #fafafa)' }}>
            <div className="flex flex-col gap-1.5 text-xs" style={{ color: 'var(--antd-text-muted, #8c8c8c)' }}>
              <div className="flex justify-between items-center">
                <span>{t('nav.onlineMcp')}</span>
                <span className="font-mono text-[#52c41a] font-medium">{activeMcpCount} / {mcpServers.length}</span>
              </div>
              <div className="flex justify-between items-center">
                <span>{t('nav.runningTasks')}</span>
                <span className="font-mono text-[#faad14] font-medium">{runningTasksCount} {t('nav.items')}</span>
              </div>
            </div>
          </div>
        </div>
      </Sider>
    </>
  );
};

export const StatusBar: React.FC = () => {
  const { agents, mcpServers, tasks, flows } = useAppState();
  const { t } = useTranslation();

  const totalAgents = agents.length;
  const publishedAgents = agents.filter(a => a.status === 'published').length;
  const connectedMcp = mcpServers.filter(s => s.status === 'connected');
  const totalTasks = tasks.length;

  return (
    <footer
      className="w-full border-t border-solid py-2.5 text-xs px-6 select-none shrink-0"
      style={{
        borderColor: 'var(--antd-border, #f0f0f0)',
        backgroundColor: 'var(--antd-card, #ffffff)',
        color: 'var(--antd-text-muted, #8c8c8c)',
      }}
    >
      <div className="flex flex-col sm:flex-row items-center justify-between gap-2.5">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <div className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full bg-[#1677ff]" />
            <span>{t('statusBar.agents')}: {totalAgents} {t('statusBar.unit')} ({t('statusBar.published')} {publishedAgents})</span>
          </div>
          <span className="hidden sm:inline" style={{ color: 'var(--antd-border, #f0f0f0)' }}>|</span>
          <div className="flex items-center gap-1.5">
            <span className={`h-2 w-2 rounded-full ${connectedMcp.length > 0 ? 'bg-[#52c41a]' : 'bg-[#ff4d4f]'}`} />
            <span>{t('statusBar.workflowSchemes')}: {flows.length} {t('statusBar.schemes')}</span>
          </div>
        </div>
        <div className="flex items-center gap-3 font-mono text-[11px]">
          <div className="flex items-center gap-1.5">
            <Activity className="h-3.5 w-3.5 text-[#1677ff] animate-spin" style={{ animationDuration: '6s' }} />
            <span>{t('statusBar.taskGatewayOnline')} · {t('statusBar.registeredJobs')} {totalTasks} {t('statusBar.jobs')}</span>
          </div>
          <span style={{ color: 'var(--antd-border, #f0f0f0)' }}>|</span>
          <span>{t('statusBar.systemTimezone')}</span>
        </div>
      </div>
    </footer>
  );
};

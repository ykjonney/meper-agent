/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React from 'react';
import { Dropdown, Avatar, Tooltip, Switch } from 'antd';
import type { MenuProps } from 'antd';
import {
  Sun,
  Moon,
  User,
  Bell,
  Settings,
  LogOut,
  Shield,
  Globe,
  Check,
} from 'lucide-react';
import { useAppState } from '../AppContext';
import { useTheme } from '../ThemeContext';
import { useTranslation, LocaleType } from '../LocaleContext';

/** Language option definitions - label shown in its own language */
const languageOptions: { key: LocaleType; label: string }[] = [
  { key: 'zh-CN', label: '中文简体' },
  { key: 'en', label: 'English' },
  { key: 'zh-TW', label: '繁體中文' },
];

/**
 * AppHeader — Global top bar with user info, status, theme switching, and language switcher.
 * Uses antd Dropdown, Avatar, Tooltip, and Switch components.
 */
export function AppHeader() {
  const { activeTab, currentUser, logout, setActiveTab } = useAppState();
  const { themeMode, toggleTheme, isDark } = useTheme();
  const { locale, setLocale, t } = useTranslation();

  // Active tab display name
  const tabLabels: Record<string, string> = {
    agents: t('header.agentManagement'),
    chat: t('header.chatDebug'),
    skills: t('header.skillConfig'),
    mcp: t('header.mcpService'),
    nodes: t('header.presetNodes'),
    flows: t('header.workflow'),
    tasks: t('header.taskQueue'),
    users: t('header.userManagement'),
    roles: t('header.roleManagement'),
    permissions: t('header.permissionConfig'),
    profile: t('header.profilePage'),
  };

  const displayName = currentUser?.username || t('header.notLoggedIn');
  const displayEmail = currentUser?.email || '';
  const initials = displayName.slice(0, 1).toUpperCase();

  // Dropdown menu items using antd
  const userMenuItems: MenuProps['items'] = [
    {
      key: 'user-info',
      label: (
        <div className="py-1">
          <p className="text-sm font-medium" style={{ color: 'var(--antd-text-primary, #262626)' }}>{displayName}</p>
          <p className="text-[11px]" style={{ color: 'var(--antd-text-muted, #8c8c8c)' }}>{displayEmail}</p>
        </div>
      ),
      disabled: true,
    },
    { type: 'divider' },
    {
      key: 'profile',
      icon: <User className="h-3.5 w-3.5" />,
      label: t('header.profile'),
      onClick: () => setActiveTab('profile'),
    },
    {
      key: 'roles',
      icon: <Shield className="h-3.5 w-3.5" />,
      label: t('header.permissionMgmt'),
      onClick: () => setActiveTab('roles'),
    },
    { type: 'divider' },
    {
      key: 'logout',
      icon: <LogOut className="h-3.5 w-3.5" />,
      label: t('header.logout'),
      danger: true,
      onClick: () => logout(),
    },
  ];

  // Language dropdown menu items
  const languageMenuItems: MenuProps['items'] = languageOptions.map((opt) => ({
    key: opt.key,
    label: (
      <div className="flex items-center justify-between gap-4 min-w-[120px]">
        <span>{opt.label}</span>
        {locale === opt.key && <Check className="h-3.5 w-3.5 text-[#1677ff]" />}
      </div>
    ),
    onClick: () => setLocale(opt.key),
  }));

  return (
    <header
      className="sticky top-0 z-30 flex items-center justify-between h-16 px-6 border-b border-solid select-none"
      style={{
        backgroundColor: 'var(--antd-card, #ffffff)',
        borderColor: 'var(--antd-border, #f0f0f0)',
      }}
    >
      {/* Left: page title */}
      <div className="flex items-center gap-2 text-sm" style={{ color: 'var(--antd-text-secondary, #595959)' }}>
        <span className="font-medium" style={{ color: 'var(--antd-text-primary, #262626)' }}>
          {tabLabels[activeTab] ?? t('header.agentManagement')}
        </span>
      </div>

      {/* Right: actions */}
      <div className="flex items-center gap-1">

        {/* Notification bell */}
        <Tooltip title={t('header.notifications')}>
          <button
            className="relative flex items-center justify-center w-8 h-8 rounded transition-colors duration-150 hover:opacity-80"
            style={{ backgroundColor: 'transparent' }}
          >
            <Bell className="h-4 w-4" style={{ color: 'var(--antd-text-muted, #8c8c8c)' }} />
          </button>
        </Tooltip>

        {/* Settings */}
        <Tooltip title={t('header.settings')}>
          <button
            className="flex items-center justify-center w-8 h-8 rounded transition-colors duration-150 hover:opacity-80"
            style={{ backgroundColor: 'transparent' }}
          >
            <Settings className="h-4 w-4" style={{ color: 'var(--antd-text-muted, #8c8c8c)' }} />
          </button>
        </Tooltip>

        {/* Theme toggle using antd Switch */}
        <Tooltip title={isDark ? t('header.switchLight') : t('header.switchDark')}>
          <div className="flex items-center gap-1.5 px-1">
            <Sun className="h-3.5 w-3.5" style={{ color: isDark ? 'var(--antd-text-dark, #595959)' : '#faad14' }} />
            <Switch
              size="small"
              checked={isDark}
              onChange={toggleTheme}
            />
            <Moon className="h-3.5 w-3.5" style={{ color: isDark ? '#1677ff' : 'var(--antd-text-dark, #595959)' }} />
          </div>
        </Tooltip>

        {/* Language switcher */}
        <Dropdown
          menu={{ items: languageMenuItems }}
          trigger={['click']}
          placement="bottomRight"
        >
          <Tooltip title={t('language.switcher')}>
            <button
              className="flex items-center justify-center w-8 h-8 rounded transition-colors duration-150 hover:opacity-80"
              style={{ backgroundColor: 'transparent' }}
            >
              <Globe className="h-4 w-4" style={{ color: 'var(--antd-text-muted, #8c8c8c)' }} />
            </button>
          </Tooltip>
        </Dropdown>

        {/* Divider */}
        <div className="w-px h-4 mx-1" style={{ backgroundColor: 'var(--antd-border, #f0f0f0)' }} />

        {/* User avatar & dropdown */}
        <Dropdown
          menu={{ items: userMenuItems }}
          trigger={['click']}
          placement="bottomRight"
        >
          <button className="flex items-center gap-2 h-8 pl-1 pr-2 rounded transition-colors duration-150 hover:opacity-80">
            <Avatar
              size={24}
              style={{ backgroundColor: '#1677ff', fontSize: 12, fontWeight: 600 }}
            >
              {initials}
            </Avatar>
            <span className="text-sm hidden sm:inline max-w-[100px] truncate" style={{ color: 'var(--antd-text-primary, #262626)' }}>
              {displayName}
            </span>
          </button>
        </Dropdown>
      </div>
    </header>
  );
}

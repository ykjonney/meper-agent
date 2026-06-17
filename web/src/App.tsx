/**
 * @license
 * SPDX-License-Identifier: Apache-2.0
 */

import React from 'react';
import { ConfigProvider, theme as antdTheme } from 'antd';
import { AppStateProvider, useAppState } from './AppContext';
import { ThemeProvider, useTheme } from './ThemeContext';
import { LocaleProvider, useAntdLocale } from './LocaleContext';
import { lightTheme, darkTheme } from './theme';
import { Navigation, StatusBar } from './components/Navigation';
import { AgentsPage } from './components/AgentsPage';
import { ChatPage } from './components/ChatPage';
import { SkillsPage } from './components/SkillsPage';
import { MCPServersPage } from './components/MCPServersPage';
import { TasksPage } from './components/TasksPage';
import { PresetNodesPage } from './components/PresetNodesPage';
import { FlowsPage } from './components/FlowsPage';
import { AppHeader } from './components/AppHeader';
import { LoginPage } from './components/LoginPage';
import { RegisterPage } from './components/RegisterPage';
import { UsersPage } from './components/UsersPage';
import { RolesPage } from './components/RolesPage';
import { PermissionsPage } from './components/PermissionsPage';
import { ProfilePage } from './components/ProfilePage';

function AuthGate() {
  const { authView } = useAppState();

  if (authView === 'login') return <LoginPage />;
  if (authView === 'register') return <RegisterPage />;
  return <AppShell />;
}

function AppShell() {
  const { activeTab } = useAppState();

  const renderActiveTab = () => {
    switch (activeTab) {
      case 'agents':
        return <AgentsPage />;
      case 'chat':
        return <ChatPage />;
      case 'skills':
        return <SkillsPage />;
      case 'mcp':
        return <MCPServersPage />;
      case 'nodes':
        return <PresetNodesPage />;
      case 'flows':
        return <FlowsPage />;
      case 'tasks':
        return <TasksPage />;
      case 'users':
        return <UsersPage />;
      case 'roles':
        return <RolesPage />;
      case 'permissions':
        return <PermissionsPage />;
      case 'profile':
        return <ProfilePage />;
      default:
        return <AgentsPage />;
    }
  };

  return (
    <div className="min-h-screen flex selection:bg-[#1677ff]/10 selection:text-[#1677ff]"
         style={{ backgroundColor: 'var(--antd-bg, #f5f5f5)', color: 'var(--antd-text-primary, #262626)' }}>
      {/* Left sidebar navigation */}
      <Navigation />

      {/* Right content area */}
      <div className="flex-1 min-w-0 h-screen flex flex-col">
        {/* Global header bar */}
        <AppHeader />

        <main className="flex-1 min-h-0 overflow-y-auto">
          {renderActiveTab()}
        </main>

        {/* Persistent bottom status bar */}
        <StatusBar />
      </div>
    </div>
  );
}

/** Wraps children with antd ConfigProvider bound to the current theme mode and locale */
function AntdConfigWrapper({ children }: { children?: React.ReactNode }) {
  const { themeMode } = useTheme();
  const antdLocale = useAntdLocale();

  const currentTheme = themeMode === 'dark'
    ? { ...darkTheme, algorithm: antdTheme.darkAlgorithm }
    : lightTheme;

  return (
    <ConfigProvider theme={currentTheme} locale={antdLocale}>
      {children}
    </ConfigProvider>
  );
}

export default function App() {
  return (
    <AppStateProvider>
      <ThemeProvider>
        <LocaleProvider>
          <AntdConfigWrapper>
            <AuthGate />
          </AntdConfigWrapper>
        </LocaleProvider>
      </ThemeProvider>
    </AppStateProvider>
  );
}

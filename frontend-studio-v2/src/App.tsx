import { Navigate, Route, Routes } from 'react-router-dom';
import { useAuthStore } from './stores/auth-store';
import { AuthInitializer } from './components/AuthInitializer';
import Login from './components/Login';
import { IconRail } from './components/shell/IconRail';
import { HomePage } from './pages/HomePage';
import { ChatPage } from './pages/ChatPage';
import { TasksPage } from './pages/TasksPage';
import { TaskDetailPage } from './pages/TaskDetailPage';
import { ErrorBoundary } from './components/ErrorBoundary';
import { AgentsPage } from './pages/AgentsPage';
import { AgentEditorPage } from './pages/AgentEditorPage';
import { KnowledgePage } from './pages/KnowledgePage';
import { ToolsPage } from './pages/ToolsPage';
import { AdminPage } from './pages/AdminPage';
import { ProfilePage } from './pages/ProfilePage';

/**
 * v2 App shell：图标栏 + 路由出口。
 * 认证门复用 v1 的 AuthInitializer（refresh-token 自举）。
 */
export default function App() {
  // TEMP-DEV-VIEW: ?demo=1 不挂 AuthInitializer（避免 refresh 401 重定向吃掉 demo 参数）
  const demo = new URLSearchParams(window.location.search).has('demo');
  return demo ? <Inner /> : <AuthInitializer><Inner /></AuthInitializer>;
}

function Inner() {
  const isAuthenticated = useAuthStore((s) => s.isAuthenticated);
  const isInitializing = useAuthStore((s) => s.isInitializing);

  const demoSkip = new URLSearchParams(window.location.search).has('demo');

  if (!isAuthenticated && !demoSkip) {
    if (isInitializing) {
      return (
        <div className="flex h-full items-center justify-center bg-page text-ink-dim">
          加载中…
        </div>
      );
    }
    return <Login />;
  }

  return (
    <div className="flex h-full bg-page">
      <IconRail />
      <main className="min-w-0 flex-1 overflow-hidden">
        <Routes>
          <Route path="/" element={<Navigate to="/home" replace />} />
          <Route path="/home" element={<HomePage />} />
          <Route path="/chat" element={<ChatPage />} />
          <Route path="/tasks" element={<TasksPage />} />
          <Route path="/tasks/:taskId" element={<ErrorBoundary><TaskDetailPage /></ErrorBoundary>} />
          <Route path="/agents" element={<AgentsPage />} />
          <Route path="/agents/:agentId/edit" element={<AgentEditorPage />} />
          <Route path="/agents/new" element={<AgentEditorPage />} />
          <Route path="/knowledge" element={<KnowledgePage />} />
          <Route path="/tools" element={<ToolsPage />} />
          <Route path="/admin" element={<AdminPage />} />
          <Route path="/profile" element={<ProfilePage />} />
          <Route path="*" element={<Navigate to="/home" replace />} />
        </Routes>
      </main>
    </div>
  );
}

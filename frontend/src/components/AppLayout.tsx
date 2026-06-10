/**
 * AppLayout — Dify-inspired two-tier navigation layout.
 *
 * Top bar: group-level tabs (仪表盘 / Agent / 工作流 / 工具 / 用户管理 / 系统信息).
 * Secondary bar: sub-page tabs (left-aligned, small font), only visible for
 * groups with multiple children. Single-page groups navigate directly.
 */
import { useLocation, useNavigate, Outlet } from 'react-router-dom'
import {
  NodeIndexOutlined,
  DashboardOutlined,
  RobotOutlined,
  BranchesOutlined,
  ToolOutlined,
  TeamOutlined,
  SettingOutlined,
  SearchOutlined,
  BellOutlined,
  QuestionCircleOutlined,
  UserOutlined,
} from '@ant-design/icons'
import { Avatar, Badge, Dropdown } from 'antd'
import type { MenuProps } from 'antd'
import { useTheme } from '../contexts/ThemeContext'
import { useAuthStore } from '../stores/auth-store'
import { authApi } from '../services/auth-api'
import { LogoutOutlined } from '@ant-design/icons'
import type { ReactNode } from 'react'

/* ─── Group nav items ─── */
interface SubPage {
  label: string
  path: string
  key: string
}

interface NavGroup {
  key: string
  label: string
  icon: ReactNode
  single?: boolean       // single-page group, no sub-tabs
  path?: string           // path for single groups
  children?: SubPage[]    // sub-pages for grouped groups
}

const GROUPS: NavGroup[] = [
  { key: 'dashboard', label: '仪表盘', icon: <DashboardOutlined />, single: true, path: '/dashboard' },
  {
    key: 'agent', label: 'Agent', icon: <RobotOutlined />,
    children: [
      { label: 'Agent 管理', path: '/agents', key: 'agents' },
      { label: '模型', path: '/models', key: 'models' },
    ],
  },
  {
    key: 'workflow', label: '工作流', icon: <BranchesOutlined />,
    children: [
      { label: '工作流', path: '/workflows', key: 'workflows' },
      { label: '任务管理', path: '/tasks', key: 'tasks' },
    ],
  },
  {
    key: 'tools', label: '工具', icon: <ToolOutlined />,
    children: [
      { label: '工具', path: '/tools', key: 'tools' },
      { label: 'MCP', path: '/mcp', key: 'mcp' },
      { label: 'Skill', path: '/skills', key: 'skills' },
    ],
  },
  { key: 'users', label: '用户管理', icon: <TeamOutlined />, single: true, path: '/users' },
  {
    key: 'system', label: '系统信息', icon: <SettingOutlined />,
    children: [
      { label: 'API 密钥', path: '/api-keys', key: 'api-keys' },
      { label: '执行日志', path: '/execution-logs', key: 'execution-logs' },
      { label: '设置', path: '/settings', key: 'settings' },
    ],
  },
]

/* ─── Path → group lookup ─── */
const PATH_TO_GROUP: Record<string, string> = {
  '/dashboard': 'dashboard',
  '/agents': 'agent',
  '/models': 'agent',
  '/workflows': 'workflow',
  '/tasks': 'workflow',
  '/tools': 'tools',
  '/mcp': 'tools',
  '/skills': 'tools',
  '/users': 'users',
  '/api-keys': 'system',
  '/execution-logs': 'system',
  '/settings': 'system',
}

export default function AppLayout() {
  const { t } = useTheme()
  const location = useLocation()
  const navigate = useNavigate()
  const currentPath = location.pathname
  const { clearAuth } = useAuthStore()

  /* ─── Resolve active group & child ─── */
  // Support dynamic routes like /agents/:id → group "agent"
  const basePath = currentPath.startsWith('/agents/') ? '/agents' : currentPath
  const activeGroupKey = PATH_TO_GROUP[basePath] || 'dashboard'
  const activeGroup = GROUPS.find((g) => g.key === activeGroupKey)
  const activeChild = activeGroup?.children?.find((c) => c.path === basePath)
  const pageTitle = activeChild?.label || activeGroup?.label || '仪表盘'

  const handleGroupClick = (group: NavGroup) => {
    if (group.single && group.path) {
      navigate(group.path)
    } else if (group.children && group.children.length > 0) {
      // If already in this group, stay; otherwise navigate to first child
      if (activeGroupKey !== group.key) {
        navigate(group.children[0].path)
      }
    }
  }

  const handleLogout = async () => {
    try {
      await authApi.logout()
    } catch {
      // 即使 API 失败也要本地清除登录态
    }
    clearAuth()
    navigate('/login', { replace: true })
  }

  const userMenuItems: MenuProps['items'] = [
    {
      key: 'logout',
      icon: <LogoutOutlined />,
      label: '退出登录',
      danger: true,
      onClick: handleLogout,
    },
  ]

  return (
    <div className="flex flex-col h-screen overflow-hidden bg-white text-[#0F172A]">
      {/* ════════════ Top navigation bar ════════════ */}
      <header className="h-14 shrink-0 flex items-center px-6 border-b border-gray-200 bg-white">
        {/* Logo */}
        <div className="flex items-center gap-2 mr-8 shrink-0">
          <div className="w-7 h-7 rounded-lg flex items-center justify-center text-white shrink-0" style={{ background: t.primary }}>
            <NodeIndexOutlined className="text-[11px]" />
          </div>
          <span className="font-semibold text-sm text-[#0F172A] tracking-tight">Agent Flow</span>
        </div>

        {/* Group tabs */}
        <nav className="flex items-center gap-0.5">
          {GROUPS.map((group) => {
            const isActive = activeGroupKey === group.key
            return (
              <button
                key={group.key}
                onClick={() => handleGroupClick(group)}
                className={`flex items-center gap-1.5 px-3.5 py-[6px] text-sm rounded-lg transition-all duration-150 cursor-pointer border-0 bg-transparent ${
                  isActive
                    ? 'font-medium shadow-sm'
                    : 'text-[#64748B] hover:text-[#334155] hover:bg-gray-50'
                }`}
                style={isActive ? { color: t.primary, background: t.bg } : undefined}
                onFocus={(e) => (e.currentTarget.style.outline = 'none')}
              >
                <span className="text-sm leading-none">{group.icon}</span>
                <span>{group.label}</span>
              </button>
            )
          })}
        </nav>

        {/* Spacer */}
        <div className="flex-1" />

        {/* User controls */}
        <div className="flex items-center gap-1">
          <button className="border-0 bg-transparent w-8 h-8 flex items-center justify-center rounded-md text-[#64748B] hover:text-[#0F172A] hover:bg-gray-50 transition-colors duration-150">
            <SearchOutlined />
          </button>
          <button className="border-0 bg-transparent w-8 h-8 flex items-center justify-center rounded-md text-[#64748B] hover:text-[#0F172A] hover:bg-gray-50 transition-colors duration-150">
            <QuestionCircleOutlined />
          </button>
          <Badge count={3} size="small" color={t.primary} offset={[-2, 2]}>
            <button className="border-0 bg-transparent w-8 h-8 flex items-center justify-center rounded-md text-[#64748B] hover:text-[#0F172A] hover:bg-gray-50 transition-colors duration-150">
              <BellOutlined />
            </button>
          </Badge>
          <div className="w-px h-6 mx-2 bg-gray-200" />
          <Dropdown menu={{ items: userMenuItems }} placement="bottomRight" trigger={['click']}>
            <div className="flex items-center gap-2 px-2 py-1 rounded-md hover:bg-gray-50 transition-colors duration-150 cursor-pointer">
              <Avatar size={28} icon={<UserOutlined />} style={{ background: t.primary }} />
              <div className="hidden sm:block text-left leading-tight">
                <div className="text-sm font-medium text-[#0F172A]">Admin</div>
                <div className="text-[11px] text-[#94A3B8]">管理员</div>
              </div>
            </div>
          </Dropdown>
        </div>
      </header>

      {/* ════════ Sub-page tabs (grouped groups only) ════════ */}
      {activeGroup?.children && activeGroup.children.length > 0 && (
        <div className="flex items-center h-10 bg-[#F8FAFC] border-b border-gray-100 px-6 gap-0.5">
          {activeGroup.children.map((child) => {
            const isChildActive = currentPath === child.path || (child.path === '/agents' && currentPath.startsWith('/agents/'))
            return (
              <button
                key={child.key}
                onClick={() => navigate(child.path)}
                className={`px-3 py-1 text-xs rounded-md transition-all duration-150 cursor-pointer border-0 ${
                  isChildActive
                    ? 'text-white font-medium shadow-sm'
                    : 'text-[#64748B] hover:text-[#334155] hover:bg-gray-100'
                }`}
                style={isChildActive ? { background: t.primary } : undefined}
                onFocus={(e) => (e.currentTarget.style.outline = 'none')}
              >
                {child.label}
              </button>
            )
          })}
        </div>
      )}

      {/* ════════ Page header (optional title + right actions) ════════ */}
      {activeGroup?.children && activeGroup.children.length > 0 && (
        <div className="flex items-center justify-between px-6 h-12 border-b border-gray-100 bg-white shrink-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium text-[#0F172A]">{pageTitle}</span>
          </div>
          <div className="flex items-center gap-2">
            {/* Page-level actions can be injected here */}
          </div>
        </div>
      )}

      {/* ════════ Content area ════════ */}
      <main className="flex-1 p-6 bg-[#F8FAFC] overflow-auto flex flex-col min-h-0">
        <Outlet />
      </main>
    </div>
  )
}

/**
 * Sidebar — clean white navigation, minimal style.
 *
 * Design principles (referenced from Linear/Vercel/CRM):
 *   - Transparent background (no heavy color blocks)
 *   - Left 2px indicator for active state
 *   - Icon + label unified color (slate-600 / primary when active)
 *   - Generous spacing (py-2.5 + space-y-1)
 *   - No rounded corners on nav items (flat, editorial feel)
 */
import { useNavigate, useLocation } from 'react-router-dom'
import {
  DashboardOutlined,
  RobotOutlined,
  BranchesOutlined,
  ToolOutlined,
  DatabaseOutlined,
  WechatOutlined,
  FileTextOutlined,
  KeyOutlined,
  TeamOutlined,
  SettingOutlined,
  MenuFoldOutlined,
  MenuUnfoldOutlined,
  NodeIndexOutlined,
} from '@ant-design/icons'
import type { ReactNode } from 'react'
import { useState } from 'react'
import { MENU_ITEMS } from '../../config/menu'

const ICON_MAP: Record<string, ReactNode> = {
  DashboardOutlined: <DashboardOutlined />,
  RobotOutlined: <RobotOutlined />,
  BranchesOutlined: <BranchesOutlined />,
  ToolOutlined: <ToolOutlined />,
  DatabaseOutlined: <DatabaseOutlined />,
  WechatOutlined: <WechatOutlined />,
  FileTextOutlined: <FileTextOutlined />,
  KeyOutlined: <KeyOutlined />,
  TeamOutlined: <TeamOutlined />,
  SettingOutlined: <SettingOutlined />,
}

export default function Sidebar() {
  const navigate = useNavigate()
  const location = useLocation()
  const [collapsed, setCollapsed] = useState(false)

  const currentPath = location.pathname

  return (
    <aside
      className={`shrink-0 flex flex-col h-screen bg-white border-r border-gray-200 transition-all duration-300 ${
        collapsed ? 'w-[64px]' : 'w-[248px]'
      }`}
    >
      {/* ─── Logo ─── */}
      <div className="flex items-center gap-2.5 px-5 h-16 border-b border-gray-100 shrink-0">
        <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center text-white shrink-0">
          <NodeIndexOutlined className="text-sm" />
        </div>
        {!collapsed && (
          <span className="font-semibold text-[15px] text-[#0F172A] tracking-tight truncate">
            Agent Flow
          </span>
        )}
      </div>

      {/* ─── Navigation ─── */}
      <nav className="flex-1 overflow-y-auto px-3 py-4">
        <ul className="space-y-0.5">
          {MENU_ITEMS.map((item) => {
            const isActive = currentPath === item.path || currentPath.startsWith(item.path + '/')
            return (
              <li key={item.key}>
                <button
                  onClick={() => navigate(item.path)}
                  className={`group w-full flex items-center gap-3 px-3 py-2 rounded-md text-[13px] transition-colors duration-150 cursor-pointer relative ${
                    isActive
                      ? 'text-[#0F172A] font-semibold bg-gray-50'
                      : 'text-[#64748B] font-medium hover:text-[#0F172A] hover:bg-gray-50'
                  }`}
                  title={collapsed ? item.label : undefined}
                >
                  {/* Left active indicator */}
                  {isActive && (
                    <span className="absolute left-0 top-1/2 -translate-y-1/2 w-[2px] h-5 bg-primary rounded-r-full" />
                  )}
                  <span
                    className={`text-[15px] shrink-0 leading-none ${
                      isActive ? 'text-primary' : 'text-[#94A3B8] group-hover:text-[#475569]'
                    }`}
                  >
                    {ICON_MAP[item.icon] ?? <ToolOutlined />}
                  </span>
                  {!collapsed && <span className="truncate">{item.label}</span>}
                </button>
              </li>
            )
          })}
        </ul>
      </nav>

      {/* ─── Collapse toggle ─── */}
      <div className="px-3 pb-4 shrink-0 border-t border-gray-100 pt-3">
        <button
          onClick={() => setCollapsed(!collapsed)}
          className="group w-full flex items-center gap-3 px-3 py-2 rounded-md text-[13px] font-medium text-[#64748B] hover:text-[#0F172A] hover:bg-gray-50 transition-colors duration-150 cursor-pointer"
          title={collapsed ? '展开' : undefined}
        >
          <span className="text-[15px] shrink-0 leading-none text-[#94A3B8] group-hover:text-[#475569]">
            {collapsed ? <MenuUnfoldOutlined /> : <MenuFoldOutlined />}
          </span>
          {!collapsed && <span>收起菜单</span>}
        </button>
      </div>
    </aside>
  )
}

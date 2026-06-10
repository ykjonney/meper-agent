/**
 * Users page — user management with RBAC roles & lifecycle status.
 *
 * Data model aligned with Story 1.4 (User Management & RBAC):
 *   id: user_xxx, username, email, role (admin/developer/operator/viewer),
 *   status (active/disabled), created_at, updated_at, last_login_at
 *
 * Role colors (from UX DESIGN.md): admin=red, developer=blue, operator=green, viewer=gray
 */
import { useState } from 'react'
import { Button, Tag, Avatar, Select, Tooltip } from 'antd'
import { SearchOutlined, PlusOutlined, UserOutlined, MoreOutlined, FilterOutlined, MailOutlined, ClockCircleOutlined, SafetyCertificateOutlined } from '@ant-design/icons'
import { useTheme } from '../contexts/ThemeContext'

const USERS = [
  { id: 'user_01HXYZ', name: '张明', email: 'zhangming@company.com', role: 'admin', roleLabel: '管理员', status: 'active', agents: 8, created_at: '2026-01-15', lastLogin: '2 分钟前' },
  { id: 'user_02HABC', name: '李华', email: 'lihua@company.com', role: 'developer', roleLabel: '开发者', status: 'active', agents: 5, created_at: '2026-02-01', lastLogin: '1 小时前' },
  { id: 'user_03HDEF', name: '王芳', email: 'wangfang@company.com', role: 'developer', roleLabel: '开发者', status: 'active', agents: 3, created_at: '2026-03-10', lastLogin: '3 小时前' },
  { id: 'user_04HGHI', name: '赵磊', email: 'zhaolei@company.com', role: 'viewer', roleLabel: '观察者', status: 'disabled', agents: 0, created_at: '2026-04-05', lastLogin: '7 天前' },
  { id: 'user_05HJKL', name: '陈静', email: 'chenjing@company.com', role: 'developer', roleLabel: '开发者', status: 'active', agents: 6, created_at: '2026-02-20', lastLogin: '30 分钟前' },
  { id: 'user_06HMNO', name: '刘洋', email: 'liuyang@company.com', role: 'admin', roleLabel: '管理员', status: 'active', agents: 12, created_at: '2026-01-01', lastLogin: '5 分钟前' },
  { id: 'user_07HPQR', name: '孙丽', email: 'sunli@company.com', role: 'operator', roleLabel: '操作员', status: 'active', agents: 2, created_at: '2026-05-01', lastLogin: '1 天前' },
  { id: 'user_08HSTU', name: '周伟', email: 'zhouwei@company.com', role: 'viewer', roleLabel: '观察者', status: 'active', agents: 0, created_at: '2026-05-15', lastLogin: '2 天前' },
]

/* Role colors from UX DESIGN.md: admin=red, developer=blue, operator=green, viewer=gray */
const ROLE_COLORS: Record<string, string> = {
  admin: '#EF4444',
  developer: '#2563EB',
  operator: '#10B981',
  viewer: '#94A3B8',
}

const ROLE_OPTIONS = [
  { value: 'all', label: '全部角色' },
  { value: 'admin', label: '管理员' },
  { value: 'developer', label: '开发者' },
  { value: 'operator', label: '操作员' },
  { value: 'viewer', label: '观察者' },
]

export default function UsersPage() {
  const { t } = useTheme()
  const [roleFilter, setRoleFilter] = useState('all')

  const filtered = roleFilter === 'all' ? USERS : USERS.filter((u) => u.role === roleFilter)

  return (
    <div className="animate-[fadeIn_0.3s_ease-out]">
      {/* Stats */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        {[
          { label: '总用户', value: USERS.length.toString() },
          { label: '活跃用户', value: USERS.filter(u => u.status === 'active').length.toString() },
          { label: '管理员', value: USERS.filter(u => u.role === 'admin').length.toString() },
          { label: '开发者', value: USERS.filter(u => u.role === 'developer').length.toString() },
        ].map((s) => (
          <div key={s.label} className="rounded-xl border border-gray-200 bg-white p-4">
            <div className="text-2xl font-semibold text-[#0F172A] mb-0.5">{s.value}</div>
            <div className="text-xs text-[#64748B]">{s.label}</div>
          </div>
        ))}
      </div>

      {/* Actions */}
      <div className="flex items-center justify-between gap-4 mb-6">
        <div className="flex items-center gap-3">
          <div className="relative">
            <SearchOutlined className="absolute left-3 top-1/2 -translate-y-1/2 text-[#94A3B8] text-sm" />
            <input type="text" placeholder="搜索用户..." className="pl-9 pr-4 py-2 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 w-64" style={{ '--tw-ring-color': t.bg } as React.CSSProperties} />
          </div>
          <Select value={roleFilter} onChange={setRoleFilter} className="w-32" options={ROLE_OPTIONS} />
        </div>
        <Button type="primary" icon={<PlusOutlined />}>邀请用户</Button>
      </div>

      {/* User table */}
      <div className="rounded-xl border border-gray-200 bg-white overflow-hidden">
        {/* Header */}
        <div className="grid grid-cols-[1fr_100px_80px_80px_120px_40px] gap-4 px-5 py-3 bg-[#F8FAFC] border-b border-gray-100 text-xs font-medium text-[#64748B]">
          <span>用户</span>
          <span>角色</span>
          <span>Agent 数</span>
          <span>状态</span>
          <span>上次登录</span>
          <span></span>
        </div>

        {/* Rows */}
        {filtered.map((user, i) => (
          <div key={user.id} className={`grid grid-cols-[1fr_100px_80px_80px_120px_40px] gap-4 px-5 py-3.5 items-center hover:bg-[#F8FAFC] transition-colors duration-150 cursor-pointer ${i > 0 ? 'border-t border-gray-50' : ''}`}>
            <div className="flex items-center gap-3 min-w-0">
              <Avatar size={32} icon={<UserOutlined />} style={{ background: t.bg, color: t.primary }} />
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <span className="text-sm font-medium text-[#0F172A]">{user.name}</span>
                  <Tooltip title={`ID: ${user.id} · 创建于 ${user.created_at}`}>
                    <SafetyCertificateOutlined className="text-[10px] text-[#94A3B8] cursor-help" />
                  </Tooltip>
                </div>
                <div className="text-xs text-[#64748B] truncate flex items-center gap-1">
                  <MailOutlined className="text-[10px]" />
                  {user.email}
                </div>
              </div>
            </div>
            <Tag className="!m-0 !w-fit !px-2 !py-0.5 !text-xs !rounded" style={{ color: ROLE_COLORS[user.role], background: `${ROLE_COLORS[user.role]}15`, borderColor: 'transparent' }}>
              {user.roleLabel}
            </Tag>
            <span className="text-sm text-[#0F172A]">{user.agents}</span>
            <Tag className="!m-0 !w-fit !px-2 !py-0.5 !text-xs !rounded" style={{
              color: user.status === 'active' ? '#10B981' : '#94A3B8',
              background: user.status === 'active' ? '#D1FAE5' : '#F1F5F9',
              borderColor: 'transparent',
            }}>
              {user.status === 'active' ? '活跃' : '已禁用'}
            </Tag>
            <span className="text-xs text-[#64748B] flex items-center gap-1">
              <ClockCircleOutlined className="text-[10px]" />
              {user.lastLogin}
            </span>
            <button className="border-0 bg-transparent w-8 h-8 flex items-center justify-center rounded-md text-[#64748B] hover:text-[#0F172A] hover:bg-gray-50 transition-colors duration-150"><MoreOutlined /></button>
          </div>
        ))}
      </div>
    </div>
  )
}

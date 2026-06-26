/**
 * Header — clean white top bar.
 */
import { useLocation } from 'react-router-dom'
import { Button, Avatar, Dropdown } from 'antd'
import {
  SearchOutlined,
  QuestionCircleOutlined,
  UserOutlined,
  SettingOutlined,
  LogoutOutlined,
} from '@ant-design/icons'
import { MENU_ITEMS } from '../../config/menu'
import NotificationCenter from '../../components/notification-center'

export default function Header() {
  const location = useLocation()

  const currentItem = MENU_ITEMS.find(
    (item) => item.path === location.pathname || location.pathname.startsWith(item.path + '/'),
  )
  const pageTitle = currentItem?.label ?? '仪表盘'

  return (
    <header className="h-16 shrink-0 flex items-center justify-between px-6 border-b border-gray-100 bg-white">
      {/* Left: Page title */}
      <h2 className="font-semibold text-lg text-[#0F172A] m-0">
        {pageTitle}
      </h2>

      {/* Right: Actions */}
      <div className="flex items-center gap-1">
        <Button
          type="text"
          icon={<SearchOutlined />}
          className="!text-[#64748B] hover:!text-[#0F172A]"
        />
        <Button
          type="text"
          icon={<QuestionCircleOutlined />}
          className="!text-[#64748B] hover:!text-[#0F172A]"
        />
        <NotificationCenter />

        <div className="w-px h-6 mx-3 bg-gray-200" />

        <Dropdown
          menu={{
            items: [
              { key: 'profile', icon: <UserOutlined />, label: '个人信息' },
              { key: 'settings', icon: <SettingOutlined />, label: '偏好设置' },
              { type: 'divider' },
              { key: 'logout', icon: <LogoutOutlined />, label: '退出登录', danger: true },
            ],
          }}
          placement="bottomRight"
          trigger={['click']}
        >
          <div className="flex items-center gap-2.5 px-2 py-1 rounded-lg hover:bg-gray-50 transition-colors duration-150 cursor-pointer">
            <Avatar
              size={32}
              icon={<UserOutlined />}
              className="!bg-primary"
            />
            <div className="hidden sm:block text-left leading-tight">
              <div className="text-sm font-medium text-[#0F172A]">Admin</div>
              <div className="text-[11px] text-[#94A3B8]">管理员</div>
            </div>
          </div>
        </Dropdown>
      </div>
    </header>
  )
}

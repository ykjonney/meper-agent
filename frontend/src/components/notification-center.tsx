// frontend/src/components/notification-center.tsx
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Badge, Popover, Button, Typography, Empty } from 'antd'
import { BellOutlined, CheckOutlined } from '@ant-design/icons'
import { useNotificationStore } from '../stores/notification-store'
import type { NotificationItem } from '../services/notifications-api'

const { Text } = Typography

const KIND_COLORS: Record<string, string> = {
  task_failed: '#EF4444',
  task_waiting_human: '#F59E0B',
  task_completed: '#22C55E',
}

const KIND_LABELS: Record<string, string> = {
  task_failed: '失败',
  task_waiting_human: '待审批',
  task_completed: '已完成',
}

function NotificationItemRow({ item }: { item: NotificationItem }) {
  const navigate = useNavigate()
  const markAsRead = useNotificationStore((s) => s.markAsRead)

  const handleClick = () => {
    if (!item.read) {
      markAsRead(item.id)
    }
    if (item.related_task_id) {
      navigate(`/tasks?highlight=${item.related_task_id}`)
    }
  }

  return (
    <div
      className="px-3 py-2.5 cursor-pointer hover:bg-gray-50 transition-colors border-b border-gray-50 last:border-b-0"
      onClick={handleClick}
    >
      <div className="flex items-start gap-2">
        <span
          className="mt-1.5 w-2 h-2 rounded-full shrink-0"
          style={{ backgroundColor: KIND_COLORS[item.kind] ?? '#94A3B8' }}
        />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <Text strong className="text-sm leading-tight">{item.title}</Text>
            <Text type="secondary" className="text-xs shrink-0">
              {KIND_LABELS[item.kind]}
            </Text>
          </div>
          <Text type="secondary" className="text-xs block truncate mt-0.5">
            {item.body}
          </Text>
          <Text type="secondary" className="text-[11px] mt-1">
            {new Date(item.created_at).toLocaleString()}
          </Text>
        </div>
        {!item.read && (
          <span className="mt-1 w-2 h-2 rounded-full bg-blue-500 shrink-0" />
        )}
      </div>
    </div>
  )
}

export default function NotificationCenter() {
  const [open, setOpen] = useState(false)
  const { notifications, unreadCount, loadFromApi, markAllAsRead } = useNotificationStore()

  useEffect(() => {
    if (open) {
      loadFromApi()
    }
  }, [open, loadFromApi])

  const content = (
    <div className="w-80">
      <div className="flex items-center justify-between px-3 py-2 border-b border-gray-100">
        <Text strong className="text-sm">通知中心</Text>
        {unreadCount > 0 && (
          <Button type="link" size="small" icon={<CheckOutlined />} onClick={() => markAllAsRead()}>
            全部已读
          </Button>
        )}
      </div>
      <div className="max-h-80 overflow-y-auto">
        {notifications.length === 0 ? (
          <Empty description="暂无通知" image={Empty.PRESENTED_IMAGE_SIMPLE} className="py-6" />
        ) : (
          notifications.map((item) => (
            <NotificationItemRow key={item.id} item={item} />
          ))
        )}
      </div>
    </div>
  )

  return (
    <Popover
      content={content}
      trigger="click"
      open={open}
      onOpenChange={setOpen}
      placement="bottomRight"
      arrow={false}
      overlayInnerStyle={{ padding: 0 }}
    >
      <Badge count={unreadCount} size="small" color="#F97316" offset={[-2, 2]}>
        <Button
          type="text"
          icon={<BellOutlined />}
          className="!text-[#64748B] hover:!text-[#0F172A]"
        />
      </Badge>
    </Popover>
  )
}

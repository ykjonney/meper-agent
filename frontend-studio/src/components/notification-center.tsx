/**
 * NotificationCenter — header bell with unread badge + dropdown panel.
 *
 * Rewrite of frontend/src/components/notification-center.tsx (antd version) to
 * the studio's self-built UI primitives:
 *   - antd Badge           → ui/Badge (count + orange style)
 *   - antd Button(text/link) → ui/Button(text/link)
 *   - antd Typography.Text → native <span> + tailwind (dark-native + .theme-light)
 *   - antd Empty           → native empty state (mirrors ui/Table empty style)
 *   - @ant-design/icons    → lucide-react (Bell / Check)
 *   - react-router navigate → controlled `onNavigateTask(taskId)` callback
 *   - createPortal(panel)  → ui/Popover (trigger=click, controlled, click-outside auto-close)
 */
import { useEffect, useState } from 'react'
import { Bell, Check } from 'lucide-react'
import { Badge, Button, Popover } from './ui'
import { useNotificationStore } from '../stores/notification-store'
import type { NotificationItem } from '../services/notifications-api'

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

interface NotificationCenterProps {
  /** Called when a notification with a related task is clicked. App injects
   * setActiveTab('board') + the highlight mechanism. */
  onNavigateTask?: (taskId: string) => void
}

function NotificationItemRow({
  item,
  onNavigateTask,
}: {
  item: NotificationItem
  onNavigateTask?: (taskId: string) => void
}) {
  const markAsRead = useNotificationStore((s) => s.markAsRead)

  const handleClick = () => {
    if (!item.read) {
      markAsRead(item.id)
    }
    if (item.related_task_id) {
      onNavigateTask?.(item.related_task_id)
    }
  }

  return (
    <div
      className={`px-3 py-2.5 cursor-pointer transition-colors border-b border-[#27272a]/60 last:border-b-0 ${
        !item.read ? 'bg-[#1E5EFF]/10 hover:bg-[#1E5EFF]/20' : 'hover:bg-[#121214]/60'
      }`}
      onClick={handleClick}
    >
      <div className="flex items-start gap-2">
        <span
          className="mt-1.5 w-2 h-2 rounded-full shrink-0"
          style={{ backgroundColor: KIND_COLORS[item.kind] ?? '#94A3B8' }}
        />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium leading-tight text-[#fafafa] truncate">
              {item.title}
            </span>
            <span
              className="text-[10px] shrink-0 px-1 py-0 rounded leading-tight"
              style={{
                backgroundColor: `${KIND_COLORS[item.kind] ?? '#94A3B8'}1A`,
                color: KIND_COLORS[item.kind] ?? '#94A3B8',
              }}
            >
              {KIND_LABELS[item.kind] ?? item.kind}
            </span>
          </div>
          <span className="text-xs block truncate mt-0.5 text-slate-400">{item.body}</span>
          <span className="text-[11px] mt-1 block text-[#71717a]">
            {new Date(item.created_at).toLocaleString()}
          </span>
        </div>
        {!item.read && <span className="mt-1.5 w-2 h-2 rounded-full bg-[#1E5EFF] shrink-0" />}
      </div>
    </div>
  )
}

export function NotificationCenter({ onNavigateTask }: NotificationCenterProps) {
  const [open, setOpen] = useState(false)
  const { notifications, unreadCount, loadFromApi, markAllAsRead } = useNotificationStore()

  useEffect(() => {
    if (open) {
      loadFromApi()
    }
  }, [open, loadFromApi])

  const title = (
    <div className="flex items-center justify-between w-full">
      <span>通知中心</span>
      {unreadCount > 0 && (
        <Button type="link" size="small" icon={<Check className="w-3 h-3" />} onClick={() => markAllAsRead()}>
          全部已读
        </Button>
      )}
    </div>
  )

  const content = (
    <div className="-m-2.5 max-h-80 overflow-y-auto w-72">
      {notifications.length === 0 ? (
        <div className="py-8 text-center text-xs text-[#71717a]">暂无通知</div>
      ) : (
        notifications.map((item) => (
          <NotificationItemRow key={item.id} item={item} onNavigateTask={onNavigateTask} />
        ))
      )}
    </div>
  )

  return (
    <Popover
      trigger="click"
      open={open}
      onOpenChange={setOpen}
      title={title}
      content={content}
    >
      <Badge count={unreadCount} size="small" style={{ backgroundColor: '#F97316' }}>
        <Button type="text" size="small" icon={<Bell className="w-4 h-4" />} />
      </Badge>
    </Popover>
  )
}

export default NotificationCenter

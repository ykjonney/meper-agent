import { apiClient } from './api-client'

export interface NotificationItem {
  id: string
  user_id: string
  kind: 'task_failed' | 'task_waiting_human' | 'task_completed'
  title: string
  body: string
  related_task_id: string | null
  related_workflow_id: string | null
  read: boolean
  created_at: string
}

export interface NotificationListResponse {
  total: number
  page: number
  page_size: number
  items: NotificationItem[]
}

export const notificationsApi = {
  list(params?: { page?: number; page_size?: number; read?: boolean; kind?: string }) {
    return apiClient.get<NotificationListResponse>('/api/v1/notifications', { params }).then((r) => r.data)
  },

  unreadCount() {
    return apiClient.get<{ count: number }>('/api/v1/notifications/unread-count').then((r) => r.data)
  },

  markRead(id: string) {
    return apiClient.patch(`/api/v1/notifications/${id}/read`).then((r) => r.data)
  },

  markAllRead() {
    return apiClient.patch('/api/v1/notifications/read-all').then((r) => r.data)
  },
}

export const notificationKeys = {
  all: ['notifications'] as const,
  list: (filters?: Record<string, unknown>) => [...notificationKeys.all, 'list', filters] as const,
  unreadCount: () => [...notificationKeys.all, 'unread-count'] as const,
}

import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { wsClient } from '../lib/ws-client'
import { useNotificationStore } from '../stores/notification-store'
import { taskKeys } from '../services/tasks-api'
import type { NotificationItem } from '../services/notifications-api'

/**
 * Global hook that bridges WebSocket events to TanStack Query and Notification Store.
 * Call once in App root.
 */
export function useTaskRealtime() {
  const queryClient = useQueryClient()

  useEffect(() => {
    // Task status changes → invalidate related queries
    const unsubStatus = wsClient.on('task_status', (data: unknown) => {
      const d = data as { task_id: string; status: string; from_status?: string }
      // Invalidate the list for the new status
      queryClient.invalidateQueries({
        queryKey: taskKeys.list({ status: d.status }),
      })
      // Invalidate the specific task detail
      queryClient.invalidateQueries({
        queryKey: taskKeys.detail(d.task_id),
      })
      // Also invalidate the old status list (task moved out of it)
      if (d.from_status && d.from_status !== d.status) {
        queryClient.invalidateQueries({
          queryKey: taskKeys.list({ status: d.from_status }),
        })
      }
    })

    // Notification → add to store
    const unsubNotif = wsClient.on('notification', (data: unknown) => {
      useNotificationStore.getState().addNotification(data as NotificationItem)
    })

    return () => {
      unsubStatus()
      unsubNotif()
    }
  }, [queryClient])
}

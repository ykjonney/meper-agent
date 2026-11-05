/**
 * Notification store — in-memory notification list + unread count (Zustand).
 *
 * Deduplicates by id so WS push + REST list overlap never double-counts.
 * Optimistic mark-read with rollback to full reload on API failure.
 *
 * Mirrors frontend/src/stores/notification-store.ts.
 */
import { create } from 'zustand'
import { notificationsApi, type NotificationItem } from '../services/notifications-api'

interface NotificationState {
  notifications: NotificationItem[]
  unreadCount: number
  loading: boolean
  loadFromApi: () => Promise<void>
  loadUnreadCount: () => Promise<void>
  addNotification: (notification: NotificationItem) => void
  markAsRead: (id: string) => Promise<void>
  markAllAsRead: () => Promise<void>
}

export const useNotificationStore = create<NotificationState>((set, get) => ({
  notifications: [],
  unreadCount: 0,
  loading: false,

  loadFromApi: async () => {
    set({ loading: true })
    try {
      const [listResult, countResult] = await Promise.all([
        notificationsApi.list({ page_size: 20 }),
        notificationsApi.unreadCount(),
      ])
      set({
        notifications: listResult.items,
        unreadCount: countResult.count,
        loading: false,
      })
    } catch {
      set({ loading: false })
    }
  },

  loadUnreadCount: async () => {
    try {
      const result = await notificationsApi.unreadCount()
      set({ unreadCount: result.count })
    } catch {
      // Silently ignore
    }
  },

  addNotification: (notification: NotificationItem) => {
    set((state) => {
      // Deduplicate by ID — prevents duplicates from WS push + API list overlap
      if (state.notifications.some((n) => n.id === notification.id)) {
        return { unreadCount: state.unreadCount }
      }
      return {
        notifications: [notification, ...state.notifications].slice(0, 50),
        unreadCount: state.unreadCount + 1,
      }
    })
  },

  markAsRead: async (id: string) => {
    set((state) => ({
      notifications: state.notifications.map((n) =>
        n.id === id ? { ...n, read: true } : n,
      ),
      unreadCount: Math.max(
        0,
        state.unreadCount - (state.notifications.find((n) => n.id === id && !n.read) ? 1 : 0),
      ),
    }))
    try {
      await notificationsApi.markRead(id)
    } catch {
      await get().loadFromApi()
    }
  },

  markAllAsRead: async () => {
    set((state) => ({
      notifications: state.notifications.map((n) => ({ ...n, read: true })),
      unreadCount: 0,
    }))
    try {
      await notificationsApi.markAllRead()
    } catch {
      await get().loadFromApi()
    }
  },
}))

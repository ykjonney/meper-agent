/**
 * WebSocket client — manages persistent connection for real-time notifications
 * and task status updates. Supports auto-reconnect with exponential backoff.
 */
import { useAuthStore } from '../stores/auth-store'
import { ENV } from '../config/env'

type MessageHandler = (data: unknown) => void

const MAX_RECONNECT_DELAY = 30_000
const BASE_RECONNECT_DELAY = 1_000

export class WsClient {
  private ws: WebSocket | null = null
  private reconnectDelay = BASE_RECONNECT_DELAY
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private listeners = new Map<string, Set<MessageHandler>>()
  private disposed = false

  connect(): void {
    if (this.disposed) return
    if (this.ws?.readyState === WebSocket.OPEN) return

    const token = useAuthStore.getState().accessToken
    if (!token) return

    const url = `${ENV.WS_BASE_URL}/api/v1/ws?token=${token}`
    this.ws = new WebSocket(url)

    this.ws.onopen = () => {
      this.reconnectDelay = BASE_RECONNECT_DELAY
    }

    this.ws.onmessage = (event: MessageEvent) => {
      try {
        const msg = JSON.parse(event.data)
        if (msg.type === 'ping') {
          this.ws?.send(JSON.stringify({ type: 'pong' }))
          return
        }
        if (msg.type === 'auth_expired') {
          this.disconnect()
          return
        }
        this.emit(msg.type, msg.data)
      } catch {
        // Ignore malformed messages
      }
    }

    this.ws.onclose = () => {
      this.ws = null
      this.scheduleReconnect()
    }

    this.ws.onerror = () => {
      // onclose will fire after onerror
    }
  }

  on(type: string, handler: MessageHandler): () => void {
    if (!this.listeners.has(type)) {
      this.listeners.set(type, new Set())
    }
    this.listeners.get(type)!.add(handler)
    return () => {
      this.listeners.get(type)?.delete(handler)
    }
  }

  disconnect(): void {
    this.disposed = true
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }
    this.ws?.close()
    this.ws = null
  }

  /** Resume the client after disconnect — resets disposed flag. */
  resume(): void {
    this.disposed = false
  }

  get connected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN
  }

  private emit(type: string, data: unknown): void {
    const handlers = this.listeners.get(type)
    if (handlers) {
      for (const handler of handlers) {
        try {
          handler(data)
        } catch {
          // Don't let handler errors break the client
        }
      }
    }
  }

  private scheduleReconnect(): void {
    if (this.disposed) return
    if (this.reconnectTimer) return

    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      this.connect()
    }, this.reconnectDelay)

    this.reconnectDelay = Math.min(this.reconnectDelay * 2, MAX_RECONNECT_DELAY)
  }
}

export const wsClient = new WsClient()

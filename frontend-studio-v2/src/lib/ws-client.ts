/**
 * WebSocket client — manages persistent connection for real-time notifications
 * and task status updates. Supports auto-reconnect with exponential backoff.
 *
 * Token refresh integration:
 * The old design read the access token only at connect() time and reconnected
 * blindly on close — if the token had expired, this created a tight loop of
 * connect → rejected (4401) → reconnect → rejected, because nothing refreshed
 * the token. Now:
 *   - On close code 4401 (auth failed), we mark `authFailed=true` and DON'T
 *     schedule an immediate reconnect. We wait for a fresh token.
 *   - `reconnectWithFreshToken(token)` is called by App.tsx whenever the auth
 *     store gets a new access token, so the WS reconnects with a valid token
 *     immediately after a refresh — no waiting for an unrelated HTTP request.
 *
 * Mirrors frontend/src/lib/ws-client.ts.
 */
import { useAuthStore } from '../stores/auth-store'
import { ENV } from '../config/env'

type MessageHandler = (data: unknown) => void

const MAX_RECONNECT_DELAY = 30_000
const BASE_RECONNECT_DELAY = 1_000
/** WebSocket close code used by the backend when the token is invalid. */
const WS_AUTH_FAILED_CODE = 4401

export class WsClient {
  private ws: WebSocket | null = null
  private reconnectDelay = BASE_RECONNECT_DELAY
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null
  private listeners = new Map<string, Set<MessageHandler>>()
  private disposed = false
  /** Set when the backend rejected the connection (4401). Pauses auto-reconnect
   * until a fresh token arrives via reconnectWithFreshToken(). */
  private authFailed = false

  connect(): void {
    if (this.disposed) return
    if (this.ws?.readyState === WebSocket.OPEN) return

    const token = useAuthStore.getState().accessToken
    if (!token) return

    this.openWithToken(token)
  }

  /**
   * Reconnect using a freshly-refreshed access token.
   *
   * Called by App.tsx when the auth store's token changes (after a refresh).
   * Closes any existing connection (which was likely rejected with 4401) and
   * opens a new one with the valid token, bypassing the reconnect backoff.
   */
  reconnectWithFreshToken(token: string): void {
    if (this.disposed) return
    if (!token) return

    this.authFailed = false
    this.reconnectDelay = BASE_RECONNECT_DELAY

    // If a reconnect was pending, cancel it — we're connecting now.
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer)
      this.reconnectTimer = null
    }

    // Close the old (rejected) connection if still hanging around.
    if (this.ws && this.ws.readyState <= WebSocket.OPEN) {
      this.ws.onclose = null
      try {
        this.ws.close()
      } catch {
        // ignore
      }
      this.ws = null
    }

    this.openWithToken(token)
  }

  private openWithToken(token: string): void {
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
          this.authFailed = true
          this.disconnect()
          return
        }
        this.emit(msg.type, msg.data)
      } catch {
        // Ignore malformed messages
      }
    }

    this.ws.onclose = (event: CloseEvent) => {
      this.ws = null
      // If the backend rejected our token, DON'T auto-reconnect with the same
      // (expired) token — that loops. Wait for reconnectWithFreshToken().
      if (event.code === WS_AUTH_FAILED_CODE) {
        this.authFailed = true
        return
      }
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
    this.authFailed = false
  }

  get connected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN
  }

  /** Whether the connection is currently blocked waiting for a fresh token. */
  get waitingForAuth(): boolean {
    return this.authFailed
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
    if (this.authFailed) return
    if (this.reconnectTimer) return

    this.reconnectTimer = setTimeout(() => {
      this.reconnectTimer = null
      this.connect()
    }, this.reconnectDelay)

    this.reconnectDelay = Math.min(this.reconnectDelay * 2, MAX_RECONNECT_DELAY)
  }
}

export const wsClient = new WsClient()

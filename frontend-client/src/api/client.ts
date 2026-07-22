import { REFRESH_TOKEN_KEY, useAuthStore } from '../store/auth'
import type { TokenResponse } from '../types'

const API_BASE = import.meta.env.VITE_API_BASE ?? '/api'
const API_KEY = import.meta.env.VITE_PUBLIC_API_KEY ?? ''
export const AUTH_MODE: 'jwt' | 'apikey' = API_KEY ? 'apikey' : 'jwt'
const VISITOR_ID_KEY = 'meper_client_visitor_id'

// Callback 模式的终端用户 token（X-User-Token），由宿主页通过 postMessage
// 注入。仅存内存，不落 localStorage。
let userToken: string | null = null
export function setUserToken(token: string | null): void {
  userToken = token
}
export function getUserToken(): string | null {
  return userToken
}

let refreshPromise: Promise<string | null> | null = null

export class ApiError extends Error {
  constructor(
    message: string,
    public readonly status: number,
    public readonly code?: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

function apiUrl(path: string): string {
  return `${API_BASE}${path}`
}

/** 生成 UUID（兼容非安全上下文，与 use-chat.genId 同策略）。 */
function genId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0
    const v = c === 'x' ? r : (r & 0x3) | 0x8
    return v.toString(16)
  })
}

export function getVisitorId(): string {
  let id = localStorage.getItem(VISITOR_ID_KEY)
  if (!id) {
    id = genId()
    localStorage.setItem(VISITOR_ID_KEY, id)
  }
  return id
}

async function readError(response: Response): Promise<ApiError> {
  let payload: unknown
  try {
    payload = await response.json()
  } catch {
    payload = null
  }
  const data = payload as
    | {
      detail?: unknown
      message?: string
      code?: string
      error?: { message?: string; code?: string }
    }
    | null
  const detail = data?.detail
  const nestedDetail =
    detail && typeof detail === 'object'
      ? (detail as { message?: unknown; code?: unknown })
      : null
  const message =
    typeof detail === 'string'
      ? detail
      : typeof nestedDetail?.message === 'string'
        ? nestedDetail.message
      : typeof data?.error?.message === 'string'
        ? data.error.message
      : typeof data?.message === 'string'
        ? data.message
        : `请求失败（${response.status}）`
  const code =
    data?.code ??
    data?.error?.code ??
    (typeof nestedDetail?.code === 'string' ? nestedDetail.code : undefined)
  return new ApiError(message, response.status, code)
}

async function refreshAccessToken(): Promise<string | null> {
  if (refreshPromise) return refreshPromise
  refreshPromise = (async () => {
    const refreshToken = localStorage.getItem(REFRESH_TOKEN_KEY)
    if (!refreshToken) return null
    const response = await fetch(apiUrl('/v1/auth/refresh'), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
    if (!response.ok) {
      useAuthStore.getState().clear()
      return null
    }
    const bundle = (await response.json()) as TokenResponse
    useAuthStore.getState().setSession(bundle)
    return bundle.access_token
  })().finally(() => {
    refreshPromise = null
  })
  return refreshPromise
}

export async function ensureAccessToken(): Promise<string | null> {
  if (AUTH_MODE === 'apikey') return null
  return useAuthStore.getState().accessToken ?? refreshAccessToken()
}

/** apikey 模式：附加 API Key +（若有）用户 token（X-User-Token header）。
 * 访客 ID（visitor_id）由调用方按后端约定放进 query 或 body。
 * 后端按 API Key 的 user_info_url 自动选用 legacy(visitor_id) / callback(user_token)。 */
export function applyApiKeyHeaders(headers: Headers): void {
  headers.set('Authorization', `Bearer ${API_KEY}`)
  const token = getUserToken()
  if (token) headers.set('X-User-Token', token)
}

export async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
  retry = true,
): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  if (AUTH_MODE === 'apikey') {
    applyApiKeyHeaders(headers)
  } else {
    const token = useAuthStore.getState().accessToken
    if (token) headers.set('Authorization', `Bearer ${token}`)
  }
  const response = await fetch(apiUrl(path), { ...init, headers })
  if (response.status === 401 && retry && AUTH_MODE === 'jwt') {
    const nextToken = await refreshAccessToken()
    if (nextToken) return apiRequest<T>(path, init, false)
  }
  if (!response.ok) throw await readError(response)
  if (response.status === 204) return undefined as T
  const contentType = response.headers.get('content-type') ?? ''
  if (contentType.includes('application/json')) return response.json() as Promise<T>
  return response.blob() as Promise<T>
}

export async function bootstrapAuth(): Promise<void> {
  if (AUTH_MODE === 'apikey') {
    useAuthStore.getState().setInitialized(true)
    return
  }
  try {
    await refreshAccessToken()
  } finally {
    useAuthStore.getState().setInitialized(true)
  }
}

export function streamUrl(path: string): string {
  const base = import.meta.env.VITE_STREAM_BASE ?? API_BASE
  return `${base}${path}`
}

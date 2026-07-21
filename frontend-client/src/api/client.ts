import { REFRESH_TOKEN_KEY, useAuthStore } from '../store/auth'
import type { TokenResponse } from '../types'

const API_BASE = import.meta.env.VITE_API_BASE ?? '/api'
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
  return useAuthStore.getState().accessToken ?? refreshAccessToken()
}

export async function apiRequest<T>(
  path: string,
  init: RequestInit = {},
  retry = true,
): Promise<T> {
  const token = useAuthStore.getState().accessToken
  const headers = new Headers(init.headers)
  if (init.body && !(init.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const response = await fetch(apiUrl(path), { ...init, headers })
  if (response.status === 401 && retry) {
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

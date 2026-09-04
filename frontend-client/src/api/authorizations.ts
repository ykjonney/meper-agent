/**
 * 应用授权 API —— client 自助授权（绑定/更新/解绑外部应用账密）。
 *
 * 双模式路径切换（apiRequest 已统一处理两种鉴权头）：
 * - jwt 模式：`/v1/my-app-authorizations*`（平台用户自服务，后端现有端点）
 * - apikey 模式：`/v1/ext/my-app-authorizations*`（ext 端点，首绑两步
 *   bootstrap/PUT 为 relaxed 鉴权——未绑定用户可访问）
 */
import { AUTH_MODE, apiRequest } from './client'
import type { AuthBootstrap, AvailableApp, MyAuthorizations } from '../types'

/** 绑定请求。claim 字段二选一填写：认领已有平台账号（仅首绑时可用）。 */
export interface AuthorizeAppPayload {
  username: string
  password: string
  claimPlatformUsername?: string
  claimPlatformPassword?: string
}

/** 查询我的应用授权（脱敏）。 */
export function fetchMyAuthorizations(): Promise<MyAuthorizations> {
  const path = AUTH_MODE === 'apikey'
    ? '/v1/ext/my-app-authorizations'
    : '/v1/my-app-authorizations'
  return apiRequest<MyAuthorizations>(path)
}

/** 首绑门页引导信息（仅 apikey 模式；relaxed 鉴权，未绑定可访问）。 */
export function fetchAuthBootstrap(): Promise<AuthBootstrap> {
  return apiRequest<AuthBootstrap>('/v1/ext/my-app-authorizations/bootstrap')
}

/** 可授权应用列表。返回 keyAppId（apikey 模式下 username 需锁定的应用）。 */
export async function fetchAvailableApps(): Promise<{
  keyAppId?: string
  items: AvailableApp[]
}> {
  if (AUTH_MODE === 'apikey') {
    const data = await apiRequest<{ key_app_id: string; items: AvailableApp[] }>(
      '/v1/ext/my-app-authorizations/available-apps',
    )
    return { keyAppId: data.key_app_id || undefined, items: data.items }
  }
  const data = await apiRequest<{ items: AvailableApp[] }>(
    '/v1/my-app-authorizations/available-apps',
  )
  return { items: data.items }
}

/** 授权应用（绑定/更新账密）。认领字段仅首绑场景使用。 */
export function authorizeApp(
  appId: string,
  payload: AuthorizeAppPayload,
): Promise<MyAuthorizations> {
  const path = AUTH_MODE === 'apikey'
    ? `/v1/ext/my-app-authorizations/${encodeURIComponent(appId)}`
    : `/v1/my-app-authorizations/${encodeURIComponent(appId)}`
  return apiRequest<MyAuthorizations>(path, {
    method: 'PUT',
    body: JSON.stringify({
      username: payload.username,
      password: payload.password,
      ...(payload.claimPlatformUsername
        ? { claim_platform_username: payload.claimPlatformUsername }
        : {}),
      ...(payload.claimPlatformPassword
        ? { claim_platform_password: payload.claimPlatformPassword }
        : {}),
    }),
  })
}

/** 取消授权（解绑凭证 + 删身份映射）。 */
export function revokeApp(appId: string): Promise<MyAuthorizations> {
  const path = AUTH_MODE === 'apikey'
    ? `/v1/ext/my-app-authorizations/${encodeURIComponent(appId)}`
    : `/v1/my-app-authorizations/${encodeURIComponent(appId)}`
  return apiRequest<MyAuthorizations>(path, { method: 'DELETE' })
}

/** MCP 工具错误标记：UNBOUND=未授权；INVALID=已授权但凭证失效（密码/用户名被修改）。 */
export type McpCredentialErrorKind = 'UNBOUND' | 'INVALID'

/** 从 MCP 工具错误文本解析凭证错误标记（运行时授权卡片用）。
 * 标记格式见后端 mcp/loader.py：首行 JSON
 * `{"mcp_credential_error":"UNBOUND"|"INVALID","app_id":"...","app_name":"..."}` */
export function parseUnboundMarker(
  content: string | undefined | null,
): { appId: string; appName: string; errorKind: McpCredentialErrorKind } | null {
  if (!content || !content.includes('mcp_credential_error')) return null
  const firstLine = content.split('\n')[0].trim()
  try {
    const parsed = JSON.parse(firstLine) as {
      mcp_credential_error?: string
      app_id?: string
      app_name?: string
    }
    if (
      (parsed.mcp_credential_error === 'UNBOUND' ||
        parsed.mcp_credential_error === 'INVALID') &&
      parsed.app_id
    ) {
      return {
        appId: parsed.app_id,
        appName: parsed.app_name || parsed.app_id,
        errorKind: parsed.mcp_credential_error,
      }
    }
  } catch {
    // 非 JSON 首行（后端格式变化等）——安静降级
  }
  return null
}

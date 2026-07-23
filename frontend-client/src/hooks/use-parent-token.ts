import { useEffect } from 'react'

import { applyEmbedConfig, setUserToken } from '../api/client'

const CONFIG_TYPE = 'agentflow:config'
const TOKEN_TYPE = 'agentflow:user_token'

function getAllowedOrigins(): string[] {
  const raw = import.meta.env.VITE_ALLOWED_PARENT_ORIGINS ?? ''
  return raw
    .split(',')
    .map((s: string) => s.trim())
    .filter(Boolean)
}

function isInIframe(): boolean {
  try {
    return window.self !== window.top
  } catch {
    // 跨域访问 window.top 抛 SecurityError → 必然在 iframe 内
    return true
  }
}

/**
 * iframe 嵌入时接收宿主页（chat-widget.js）注入的配置：
 *   agentflow:config  { apiKey, userToken? } → applyEmbedConfig（data-api-key 模式）
 *   agentflow:user_token { token }           → setUserToken（旧 callback 协议兼容）
 * 仅 iframe 内生效。bootstrapAuth 会主动发 agentflow:request_config 请求配置。
 *
 * 安全：
 * - 两类消息都只接受来自直接父页（event.source === window.parent），防其他 iframe 注入。
 * - apiKey 属公开凭据（本就写在第三方 HTML），source 校验足够。
 * - user_token 是终端用户身份凭据（敏感），额外校验 VITE_ALLOWED_PARENT_ORIGINS 白名单，
 *   白名单未配置时拒绝（fail-safe），防恶意父页注入伪造 token 冒充任意 sub。
 */
export function useParentToken(): void {
  useEffect(() => {
    if (!isInIframe()) return

    const allowed = getAllowedOrigins()

    const onMessage = (event: MessageEvent) => {
      // 只信任直接父页（嵌入方），忽略来自其他 iframe/window 的消息
      if (event.source !== window.parent) return
      const data = event.data as
        | { type?: string; apiKey?: string; userToken?: string; token?: string }
        | null
      if (!data) return

      if (data.type === CONFIG_TYPE && typeof data.apiKey === 'string' && data.apiKey) {
        applyEmbedConfig(data.apiKey, data.userToken)
      } else if (data.type === TOKEN_TYPE && typeof data.token === 'string') {
        // 终端 token 敏感：白名单未配置或非白名单 origin → 拒绝
        if (allowed.length === 0 || !allowed.includes(event.origin)) return
        setUserToken(data.token)
      }
    }

    window.addEventListener('message', onMessage)
    return () => window.removeEventListener('message', onMessage)
  }, [])
}

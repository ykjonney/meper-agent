import { useEffect } from 'react'

import { AUTH_MODE, setUserToken } from '../api/client'

const REQUEST_MSG = { type: 'agentflow:request_token' }
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
 * iframe 嵌入时，向宿主页请求并接收终端用户 token（X-User-Token）。
 * 仅 apikey 模式且在 iframe 内生效。token 到达后存入内存
 *（client.setUserToken），后续请求自动带上。不阻塞首屏：legacy Key
 * 无需 token 即可用。
 *
 * 安全：只接受 VITE_ALLOWED_PARENT_ORIGINS 白名单内 origin 的消息；
 * 白名单未配置时拒绝接收（fail-safe），防止恶意父页注入伪造 token
 * 冒充任意终端用户。
 */
export function useParentToken(): void {
  useEffect(() => {
    if (AUTH_MODE !== 'apikey' || !isInIframe()) return

    const allowed = getAllowedOrigins()

    const onMessage = (event: MessageEvent) => {
      // 白名单未配置 → 拒绝（callback 模式必须显式配置允许的父页 origin）
      if (allowed.length === 0 || !allowed.includes(event.origin)) return
      const data = event.data as { type?: string; token?: string } | null
      if (data?.type === TOKEN_TYPE && typeof data.token === 'string') {
        setUserToken(data.token)
      }
    }

    window.addEventListener('message', onMessage)
    // 主动向父页请求 token（父页收到后注入；也可能由父页主动注入）
    window.parent.postMessage(REQUEST_MSG, '*')

    return () => window.removeEventListener('message', onMessage)
  }, [])
}

/**
 * Login — 严格照抄 all-pages-review ⑨ 翻译（左品牌右表单）。
 * 登录逻辑保留 v1（authApi.login + ACCOUNT_LOCKED 错误码 + ?reason= 消费）。
 */
import { useEffect, useState, type FormEvent } from 'react'
import { useAuthStore, REFRESH_TOKEN_KEY, type AuthUser } from '../stores/auth-store'
import { authApi } from '../services/auth-api'

const REASON_MESSAGES: Record<string, string> = {
  AUTH_EXPIRED: '登录已过期，请重新登录',
  ACCOUNT_LOCKED: '账号已被锁定，请在 15 分钟后重试',
  TOKEN_INVALID: '登录凭证已失效，请重新登录',
  TOKEN_REVOKED: '登录已注销，请重新登录',
}

const CSS = `
.lg { height:100%; display:flex; align-items:center; justify-content:center; background:var(--color-canvas); font-family:-apple-system,'PingFang SC','Segoe UI',sans-serif; }
.lg-card { width:920px; max-width:92vw; background:#F0EDFA; border-radius:16px; overflow:hidden; display:flex; height:400px; box-shadow:0 20px 60px rgba(76,58,158,.2); }
.lg * { box-sizing:border-box; }
.lg-brand { flex:1; background:linear-gradient(160deg,#8B5CF6,#6D4AE0); color:#fff; padding:34px; display:flex; flex-direction:column; }
.lg-form { width:356px; background:#fff; padding:32px; display:flex; flex-direction:column; justify-content:center; gap:11px; }
.lg-in { border:1px solid #EBE8F5; border-radius:10px; padding:10px 14px; font-size:13px; color:#1E1B2E; outline:none; width:100%; }
.lg-in::placeholder { color:#B6B1C9; }
.lg-in:focus { border-color:#C9BEF0; }
.lg-btn { background:linear-gradient(135deg,#8B5CF6,#6D4AE0); color:#fff; border:none; border-radius:10px; padding:10px; text-align:center; font-size:13.5px; font-weight:700; cursor:pointer; }
.lg-btn:disabled { opacity:.6; cursor:default; }
.lg-err { background:#FEF2F2; color:#DC2626; border-radius:8px; padding:8px 12px; font-size:12px; }
.lg-ssobtn { flex:1; border:1px solid #EBE8F5; border-radius:10px; padding:8px; text-align:center; font-size:12px; color:#55506E; cursor:default; }
`;

export default function Login() {
  const setAuth = useAuthStore((s) => s.setAuth)
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(() => {
    const reason = new URLSearchParams(window.location.search).get('reason')
    if (!reason) return null
    return REASON_MESSAGES[reason] ?? '登录已失效，请重新登录'
  })

  // 消费 ?reason=（防止刷新重复提示；保留 ?redirect=）
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    if (params.has('reason')) {
      params.delete('reason')
      const qs = params.toString()
      window.history.replaceState(null, '', qs ? `?${qs}` : window.location.pathname)
    }
  }, [])

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    if (loading) return
    setLoading(true)
    setError(null)
    try {
      const res = await authApi.login(username.trim(), password)
      const { access_token, refresh_token, user } = res.data
      localStorage.setItem(REFRESH_TOKEN_KEY, refresh_token)
      const authUser: AuthUser = user
        ? {
            id: user.id,
            username: user.username,
            role: user.role,
            permissions: user.permissions ?? [],
            isSuperAdmin: Boolean(user.is_super_admin),
          }
        : { id: '', username: username.trim(), role: '', permissions: [] }
      setAuth(access_token, authUser)
    } catch (err) {
      // 后端统一 envelope 错误（NormalizedApiError：{code, message}）
      const e = err as { code?: string; message?: string }
      const code = e?.code
      const msg = e?.message ?? '登录失败，请检查网络或凭据'
      setError(code === 'ACCOUNT_LOCKED' ? '账号已被锁定，请在 15 分钟后重试' : msg)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="lg">
      <style>{CSS}</style>
      <div className="lg-card">
        {/* 左品牌 */}
        <div className="lg-brand">
          <div style={{ fontSize: 19, fontWeight: 800 }}>✦ Agent Flow</div>
          <div style={{ marginTop: 'auto', fontSize: 18, fontWeight: 800, lineHeight: 1.5 }}>
            让每个团队<br />拥有自己的 AI 数字员工
          </div>
          <div style={{ fontSize: 12, opacity: 0.85, marginTop: 10, lineHeight: 1.8 }}>
            计划模式 · 先规划后人审再执行<br />
            沙盒隔离 · 执行全程可回溯
          </div>
        </div>
        {/* 右表单 */}
        <form className="lg-form" onSubmit={handleSubmit}>
          <b style={{ fontSize: 17 }}>欢迎回来</b>
          {error && <div className="lg-err">{error}</div>}
          <input
            className="lg-in"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            placeholder="账号 / 邮箱"
            autoComplete="username"
          />
          <input
            className="lg-in"
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="密码"
            autoComplete="current-password"
          />
          <button className="lg-btn" type="submit" disabled={loading}>
            {loading ? '登录中…' : '登 录'}
          </button>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 11, color: '#B6B1C9' }}>
            <span style={{ flex: 1, height: 1, background: '#EFEDF7' }} />或<span style={{ flex: 1, height: 1, background: '#EFEDF7' }} />
          </div>
          <div style={{ display: 'flex', gap: 10 }}>
            <span className="lg-ssobtn" title="即将上线">飞书</span>
            <span className="lg-ssobtn" title="即将上线">钉钉</span>
          </div>
        </form>
      </div>
    </div>
  )
}

import { test, expect, type Page } from '@playwright/test'

/**
 * E2E tests for feat-studio-infra — studio 工程基建 + API 层 + 鉴权.
 *
 * Maps Gherkin acceptance scenarios from spec.md:
 *   1. dev proxy 调通后端        → GET /api/v1/health via proxy returns {status:ok}
 *   2. 登录成功                  → fill login form, submit, App gate放行
 *   3. token 过期自动刷新        → /auth/refresh returns new token (single-flight parity)
 *   4. 刷新失败回登录            → invalid refresh token → 401 (clearAuth+redirect parity)
 *
 * Backend (admin/admin123) + vite dev proxy (:3000 → :8000) must be running.
 */
const BASE = 'http://localhost:3000'

test.describe('feat-studio-infra — studio 工程基建 + API 层 + 鉴权', () => {

  test('Scenario 1: dev proxy 调通后端', async ({ page }) => {
    // GET /api/v1/health through the vite proxy must return {status:ok}
    const res = await page.request.get(`${BASE}/api/v1/health`)
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body.status).toBe('ok')
  })

  test('Scenario 2: 登录成功', async ({ page }) => {
    await page.goto(BASE)
    // App gate renders Login when unauthenticated
    await expect(page.locator('h1')).toContainText('AgentForge')
    await page.getByPlaceholder('admin').fill('admin')
    await page.getByPlaceholder('••••••••').fill('admin123')
    await page.getByRole('button', { name: /登录/ }).click()
    // access_token 入 auth-store → App gate 放行进入主界面.
    // Wait for the app shell's nav rail (<aside>) — it only renders after the
    // auth gate opens, so the token is guaranteed persisted by the time it's
    // visible. (Waiting on the "AgentForge" text is unreliable: that heading
    // also appears on the Login page itself.)
    await expect(page.locator('aside')).toBeVisible({ timeout: 10_000 })
    // refresh_token persisted to localStorage
    const rt = await page.evaluate(() => localStorage.getItem('agentflow_refresh_token'))
    expect(rt).toBeTruthy()
  })

  test('Scenario 3: token 过期自动刷新 (API parity)', async ({ page }) => {
    // Login to obtain a refresh token
    const loginRes = await page.request.post(`${BASE}/api/v1/auth/login`, {
      data: { username: 'admin', password: 'admin123' },
    })
    expect(loginRes.status()).toBe(200)
    const loginBody = await loginRes.json()
    expect(loginBody.access_token).toBeTruthy()
    expect(loginBody.refresh_token).toBeTruthy()

    // Single-flight refresh: /auth/refresh returns a NEW access+refresh token pair
    const refreshRes = await page.request.post(`${BASE}/api/v1/auth/refresh`, {
      data: { refresh_token: loginBody.refresh_token },
    })
    expect(refreshRes.status()).toBe(200)
    const refreshBody = await refreshRes.json()
    expect(refreshBody.access_token).toBeTruthy()
    expect(refreshBody.refresh_token).toBeTruthy()
    // New access token differs from the original (rotated)
    expect(refreshBody.access_token).not.toBe(loginBody.access_token)
  })

  test('Scenario 4: 刷新失败回登录 (API parity)', async ({ page }) => {
    // An invalid/expired refresh token must yield 401 — the api-client
    // interceptor then calls clearAuth() and redirects to /login.
    const res = await page.request.post(`${BASE}/api/v1/auth/refresh`, {
      data: { refresh_token: 'invalid-expired-token' },
    })
    expect(res.status()).toBe(401)
  })

  test('authenticated request uses Bearer injection', async ({ page }) => {
    // Login → use access_token on a protected endpoint through the proxy
    const loginRes = await page.request.post(`${BASE}/api/v1/auth/login`, {
      data: { username: 'admin', password: 'admin123' },
    })
    const { access_token } = await loginRes.json()
    const res = await page.request.get(`${BASE}/api/v1/agents`, {
      headers: { Authorization: `Bearer ${access_token}` },
    })
    expect(res.status()).toBe(200)
    const body = await res.json()
    expect(body).toHaveProperty('items')
    expect(body).toHaveProperty('total')
  })
})

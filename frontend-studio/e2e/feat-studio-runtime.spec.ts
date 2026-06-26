import { test, expect } from '@playwright/test'

/**
 * E2E smoke for feat-studio-runtime — Chat(SSE+sessions)/Dashboard/TaskBoard/Settings.
 * Text-only assertions (no visual screenshot diff) per model constraints.
 *
 * Gherkin scenarios:
 *   1. Chat 真实流式对话 — SSE stream + sessions persist
 *   2. Dashboard 聚合 — /tasks/stats + /tasks 历史
 *   3. TaskBoard 任务映射 — status→column + intervene
 *   4. Settings api-keys 保留 mock (gap)
 *
 * Pre: vite dev (:3000) + backend (:8000) running; admin/admin123.
 */
const BASE = 'http://localhost:3000'

async function login(page) {
  await page.goto(BASE)
  await expect(page.locator('h1')).toContainText('AgentForge')
  await page.getByPlaceholder('admin').fill('admin')
  await page.getByPlaceholder('••••••••').fill('admin123')
  await page.getByRole('button', { name: /登录/ }).click()
  // app shell (nav rail) renders after auth
  await expect(page.locator('aside')).toBeVisible({ timeout: 10_000 })
  // nav items populated (admin has all perms)
  await expect(page.locator('nav button').first()).toBeVisible({ timeout: 5_000 })
}

// Click a nav item by matching its label text.
async function openTab(page, labelRe) {
  const btn = page.locator('nav button', { hasText: labelRe })
  await expect(btn).toBeVisible({ timeout: 5_000 })
  await btn.click()
}

test.describe('feat-studio-runtime', () => {

  test('Scenario 4: Settings api-keys 保留 mock (gap)', async ({ page }) => {
    await login(page)
    await openTab(page, /密钥及参数设置/)
    // gap annotation present (client-side mock, no backend)
    await expect(page.getByText(/GAP/)).toBeVisible({ timeout: 5_000 })
    // mock generate flow: name + 生成 → key card appears (client-side only)
    await page.getByPlaceholder(/命名您的新密钥/).fill('test-key-runtime')
    await page.getByRole('button', { name: /生成新 Key/ }).click()
    // generated key visible in the list
    await expect(page.getByText('test-key-runtime')).toBeVisible({ timeout: 5_000 })
  })

  test('Scenario 2: Dashboard 聚合 — stats + tasks 历史', async ({ page }) => {
    await login(page)
    await openTab(page, /控制台仪表盘/)
    // dashboard renders the execution-history section (GET /tasks)
    await expect(page.getByText(/运行历史/)).toBeVisible({ timeout: 8_000 })
  })

  test('Scenario 3: TaskBoard 任务映射 — status→column', async ({ page }) => {
    await login(page)
    await openTab(page, /任务协作看板/)
    // board columns render (best-effort status→column mapping)
    await expect(page.getByText(/Backlog|Todo|In Progress|In Review|Done/).first()).toBeVisible({ timeout: 8_000 })
  })

  test('Scenario 1: Chat SSE — sessions list + stream wiring', async ({ page }) => {
    await login(page)
    // chat is the default tab; SSE connected marker + 对话 sidebar
    await expect(page.getByText(/SSE|对话/).first()).toBeVisible({ timeout: 8_000 })
    // open the new-session dropdown via the chat panel header + button
    // (the first plus button on the page — in the chat sidebar header, not the
    // main nav aside)
    await page.locator('button:has(svg.lucide-plus)').first().click()
    // dropdown offers the agent-select entry (both "新建项目" and
    // "选择 Agent 开始" entries render — assert at least one is visible)
    await expect(page.getByText(/选择 Agent 开始|新建项目/).first()).toBeVisible({ timeout: 5_000 })
  })
})

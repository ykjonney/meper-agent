---
baseline_commit: NO_VCS
title: 'Frontend API Integration — Auth, Users & Agents'
type: 'feature'
created: '2026-06-09'
status: 'done'
context:
  - 'frontend/src/services/api-client.ts'
  - 'frontend/src/stores/auth-store.ts'
  - 'frontend/src/config/env.ts'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** 登录认证虽已实现基础流程，但缺少页面刷新恢复和登出功能，路由也未经认证保护。

**Approach:** 完善认证基础设施（AuthInitializer、登出、路由守卫），页面功能先用 mock 数据正常运行。

## Boundaries & Constraints

**Always:**
- Auth 功能必须真实工作（登录、刷新、登出、路由守卫）
- 所有 API 请求通过 `src/services/api-client.ts` 共享实例（自动处理 auth header + 401 refresh）
- API 响应使用 snake_case 字段名（后端契约）
- UI 组件和样式必须与设计系统页面展示的一致
- auth store 的 accessToken 仅存内存（不存 localStorage）

**Ask First:**
- 如果 backend API 返回的数据结构不符合预期，是否调整前端适配层

**Never:**
- 不创建新的全局状态管理（仅用 Zustand + TanStack Query）
- 不修改 backend API 的响应格式
- 不将 access_token 存入 localStorage（XSS 安全）
- 不修改已有的设计系统令牌和组件样式

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| 页面刷新恢复 | localStorage 有 refresh_token | 自动刷新 access_token → 恢复登录态 | 刷新失败 → clearAuth → 跳转 /login |
| 用户登出 | header 头像菜单点击"退出登录" | POST /api/v1/auth/logout → clearAuth → 跳转 /login | API 失败仍执行本地 clearAuth |
| 未登录访问受保护路由 | 未认证用户访问 /dashboard | 重定向到 /login?redirect=/dashboard | N/A |
| 已登录访问 /login | 已认证用户访问 /login | 自动跳转 /dashboard（已在 LoginPage 实现） | N/A |

</frozen-after-approval>

## Code Map

- `frontend/src/App.tsx` — 根组件，添加 AuthInitializer
- `frontend/src/components/AppLayout.tsx` — header 添加退出登录按钮 + 用户菜单
- `frontend/src/routes/index.tsx` — 添加 ProtectedRoute 包裹子路由
- `frontend/src/routes/protected-routes.tsx` — 无需修改（已实现）
- `frontend/src/pages/login-page.tsx` — 无需修改（已完成）
- `frontend/src/pages/users-page.tsx` — 保持现有 mock 数据（已增强）
- `frontend/src/pages/agents-page.tsx` — 保持现有 mock 数据（已增强）

## Tasks

**Execution:**
- [x] `frontend/src/App.tsx` — 创建 AuthInitializer 组件并包裹全局，实现页面刷新恢复登录态
- [x] `frontend/src/components/AppLayout.tsx` — header 头像菜单添加"退出登录"选项
- [x] `frontend/src/routes/index.tsx` — 将 AppLayout 子路由包裹在 ProtectedRoute 中

**Acceptance Criteria:**
- Given 用户刷新页面（有 refresh_token），当 App 初始化，then 自动恢复登录态，页面无闪烁
- Given 已登录用户，当点击 header 头像菜单"退出登录"，then 清除 auth 状态并跳转 /login
- Given 未登录用户，当访问 /dashboard，then 重定向到 /login?redirect=/dashboard
- Given 已登录用户访问 /login，then 自动跳转 /dashboard

## Verification

**Commands:**
- `cd /Users/huyuekai/company/agent-flow/frontend && npx tsc --noEmit` — 零 TS 错误
- `npm run build` — 构建成功
- Playwright 导航所有页面 — 零 runtime error

**Manual checks:**
- 登录后刷新页面 → 自动恢复登录态
- 访问 /login（已登录）→ 自动跳转 /dashboard
- 退出登录 → 跳转 /login，无法访问 /dashboard（手动 URL 输入）

## Suggested Review Order

**Auth initialization**

- 入口点：AuthInitializer 挂载时检查 refresh_token，静默恢复会话；App.tsx 注入全局
  [`AuthInitializer.tsx:14`](../../frontend/src/components/AuthInitializer.tsx#L14)
  [`App.tsx:98`](../../frontend/src/App.tsx#L98)

**Logout**

- Header 头像 dropdown 菜单，退出登录时调用 API 并本地清除状态
  [`AppLayout.tsx:57`](../../frontend/src/components/AppLayout.tsx#L57)

**Route protection**

- ProtectedRoute 通过 Outlet 模式包裹所有 AppLayout 子路由，未登录重定向到 /login
  [`routes/index.tsx:19`](../../frontend/src/routes/index.tsx#L19)

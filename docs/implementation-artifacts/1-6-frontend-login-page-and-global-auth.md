---
baseline_commit: NO_VCS
---

# Story 1.6: 前端登录页与全局认证

Status: ready-for-dev

## Story

**As a** 平台用户，
**I want** 通过 Web 登录页面安全登录，并在登录后自动跳转到工作台，在 Token 过期后自动无感续期，
**So that** 我可以安全地使用平台的所有功能，而无需关心 Token 过期等细节。

## Acceptance Criteria (BDD)

### AC1: 登录页面 UI

**Given** 用户未登录
**When** 访问任何需要认证的路由
**Then** 重定向到 `/login` 页面
**And** 登录页居中展示，包含：产品 Logo + 名称 "Agent Flow"、用户名输入框、密码输入框（含显示/隐藏切换）、"登录" 按钮
**And** 登录页 URL 保留原始目标路径（如 `/login?redirect=/agents`），以便登录后跳转回原页面
**And** 登录页无侧边栏和顶部导航栏（全屏独立布局）

### AC2: 登录成功流程

**Given** 用户在登录页输入用户名和密码
**When** 点击"登录"按钮
**Then** 调用 `POST /api/v1/auth/login`（请求体 `{username, password}`）
**And** 成功后：后端返回 `TokenResponse {access_token, refresh_token, token_type, expires_in}`
**And** 前端将 `access_token` 存入 Zustand auth store（内存态，不持久化到 localStorage）
**And** 前端将 `refresh_token` 存入 `localStorage`（key: `agentflow_refresh_token`）
**And** 同时从 JWT access_token 解析 `role` 和 `username` 存入 auth store
**And** 跳转到 `redirect` 参数指定的路径，默认 `/dashboard`
**And** 登录按钮在请求期间显示 loading 状态（Spinner + "登录中..."），禁止重复提交

### AC3: 登录失败处理

**Given** 用户提交登录表单
**When** 后端返回 401 错误
**Then** 表单上方显示红色错误提示条：
  - `INVALID_CREDENTIALS` → "用户名或密码错误"
  - `ACCOUNT_LOCKED` → "账户已锁定，请稍后再试"
  - `ACCOUNT_DISABLED` → "账户已禁用"
  - 其他 401 → "登录失败，请检查用户名和密码"
**And** 输入框和按钮恢复可交互状态
**And** 密码输入框清空，焦点回到用户名输入框

### AC4: 表单校验

**Given** 用户在登录页
**When** 用户名或密码为空时点击"登录"
**Then** 对应输入框显示红色边框和错误提示"请输入用户名"/"请输入密码"
**And** 不发送 API 请求
**And** 焦点定位到第一个错误字段

### AC5: 全局请求拦截器（Auth Header 注入）

**Given** 用户已登录（auth store 有 access_token）
**When** 前端发起任何 API 请求
**Then** axios request interceptor 自动添加 `Authorization: Bearer {access_token}` 请求头
**And** 同时添加 `X-Request-ID` 请求头（复用现有 `request-id.ts`）

### AC6: Token 自动刷新（Silent Refresh）

**Given** 用户已登录
**When** API 请求返回 401 且错误码为 `TOKEN_EXPIRED`
**Then** 拦截器自动使用 localStorage 中的 `refresh_token` 调用 `POST /api/v1/auth/refresh`
**And** 刷新成功后用新 `access_token` 更新 auth store，并重发原始请求
**And** 刷新失败时（refresh_token 也过期/无效），清除 auth store + localStorage，跳转 `/login`
**And** 多个请求同时遇到 401 时，只触发一次 refresh 请求，其余请求排队等待刷新完成后重发（防并发刷新）

### AC7: 路由守卫（ProtectedRoute）

**Given** 路由配置中标记为需要认证的页面
**When** 未登录用户尝试访问
**Then** 重定向到 `/login?redirect={当前路径}`
**And** 已登录用户访问 `/login` 时，自动重定向到 `/dashboard`
**And** 路由守卫检查 auth store 的 `isAuthenticated` 状态（基于 access_token 是否存在）

### AC8: 登出流程

**Given** 用户已登录
**When** 用户点击顶栏用户菜单中的"退出登录"
**Then** 调用 `POST /api/v1/auth/logout`（携带 refresh_token）
**And** 无论 API 调用成功与否，清除 auth store + localStorage 中的 token
**And** 跳转到 `/login`

### AC9: 页面刷新后恢复登录态

**Given** 用户已登录并刷新页面
**When** 应用重新初始化
**Then** 检查 localStorage 中是否有 `refresh_token`
**And** 如果有，调用 `POST /api/v1/auth/refresh` 获取新 access_token
**And** 刷新成功 → 恢复登录态，正常显示页面
**And** 刷新失败 → 清除 token，跳转 `/login`（用户需重新登录）
**And** 刷新期间显示全局 Spin loading（防止页面闪烁）

---

## Tasks / Subtasks

### 阶段 1：Auth Store 完善

- [ ] **T1** 实现完整的 auth store（AC: #2, #7, #8, #9）
  - [ ] T1.1 在 `src/stores/auth-store.ts` 实现完整 `AuthState`：
    ```ts
    interface AuthState {
      accessToken: string | null
      refreshToken: string | null
      user: { id: string; username: string; role: string } | null
      isAuthenticated: boolean
      isInitializing: boolean
      setAuth: (accessToken: string, refreshToken: string, user: AuthUser) => void
      clearAuth: () => void
      setAccessToken: (token: string) => void
      setInitializing: (v: boolean) => void
    }
    ```
  - [ ] T1.2 `setAuth` 方法：设置 accessToken + user + isAuthenticated=true
  - [ ] T1.3 `clearAuth` 方法：清空所有状态 + 移除 localStorage `agentflow_refresh_token`
  - [ ] T1.4 导出 `AuthUser` 类型（`{id, username, role}`）

### 阶段 2：API Client Auth 拦截器

- [ ] **T2** 实现 axios interceptors（AC: #5, #6）
  - [ ] T2.1 Request interceptor：从 auth store 读取 `accessToken`，注入 `Authorization: Bearer {token}` + `X-Request-ID`
  - [ ] T2.2 Response interceptor — 401 自动刷新：
    - 检测 `TOKEN_EXPIRED` 错误码
    - 实现单例 refresh promise（防并发刷新）
    - 刷新成功：更新 store + 重发原请求
    - 刷新失败：调用 `clearAuth` + `window.location.href = '/login'`
  - [ ] T2.3 Response interceptor — 错误码映射：保留原始错误码信息，方便上层使用

### 阶段 3：登录页面

- [ ] **T3** 创建登录页面组件（AC: #1, #2, #3, #4）
  - [ ] T3.1 创建 `src/pages/login-page.tsx`
    - 全屏居中布局（无 AppLayout 外壳）
    - 产品 Logo + "Agent Flow" 标题（使用设计令牌：colorPrimary #7C3AED）
    - AntD Form 组件：
      - 用户名 Input（`<Input prefix={<UserOutlined />} placeholder="用户名" />`）
      - 密码 Input.Password（`<Input.Password prefix={<LockOutlined />} placeholder="密码" />`）
      - "登录" Button（type="primary" htmlType="submit" block loading={isSubmitting}）
    - 错误提示 Alert（type="error" showIcon closable）
  - [ ] T3.2 表单校验规则：
    - username: `required: true, message: "请输入用户名"`
    - password: `required: true, message: "请输入密码"`
    - blur 时校验
  - [ ] T3.3 提交逻辑（使用 TanStack Query mutation）：
    - 调用 `authApi.login(username, password)`
    - 成功：`setAuth(accessToken, refreshToken, user)` → `navigate(redirect || '/dashboard')`
    - 失败：根据 error code 显示中文提示
  - [ ] T3.4 登录页样式：使用 Tailwind + AntD token，白色卡片居中 + 底色 `colorBgLayout`

### 阶段 4：Auth API Service

- [ ] **T4** 创建 auth API service（AC: #2, #6, #8）
  - [ ] T4.1 创建 `src/services/auth-api.ts`：
    ```ts
    export const authApi = {
      login: (username: string, password: string) => apiClient.post('/api/v1/auth/login', { username, password }),
      refresh: (refreshToken: string) => apiClient.post('/api/v1/auth/refresh', { refresh_token: refreshToken }),
      logout: (refreshToken: string) => apiClient.post('/api/v1/auth/logout', { refresh_token: refreshToken }),
    }
    ```
  - [ ] T4.2 JWT decode 工具函数：`decodeAccessToken(token)` → 提取 `{sub, role, username, exp}`（轻量解析，不用校验签名——后端已校验）

### 阶段 5：路由守卫

- [ ] **T5** 实现 ProtectedRoute 和路由配置更新（AC: #7）
  - [ ] T5.1 更新 `src/routes/protected-routes.tsx`：
    - 检查 `useAuthStore.isAuthenticated`
    - 未认证 → `<Navigate to="/login" state={{ from: location }} replace />`
    - 已认证 → `<Outlet />`
  - [ ] T5.2 更新 `src/routes/index.tsx`：
    - `/login` 路由渲染 `<LoginPage />`（独立布局，无 AppLayout）
    - 已登录用户访问 `/login` → 重定向到 `/dashboard`（在 LoginPage 组件内处理）
    - 所有需要认证的路由包裹在 `<ProtectedRoute>` 中
  - [ ] T5.3 将 AppLayout 子路由包裹在 ProtectedRoute 中

### 阶段 6：页面刷新恢复登录态

- [ ] **T6** 实现 Auth 初始化逻辑（AC: #9）
  - [ ] T6.1 创建 `src/features/auth/auth-initializer.tsx` 组件：
    - 挂载时检查 localStorage 是否有 `refresh_token`
    - 如果有：调用 `authApi.refresh(token)` → 成功则 `setAuth()`，失败则 `clearAuth()`
    - `isInitializing` 期间显示全局 `<Spin size="large" fullscreen />`
  - [ ] T6.2 在 App.tsx 中包裹 `<AuthInitializer>` 作为顶层组件

### 阶段 7：登出流程

- [ ] **T7** 在顶栏用户菜单中实现登出（AC: #8）
  - [ ] T7.1 更新 `src/features/layout/header.tsx`：
    - 用户头像下拉菜单添加"退出登录"选项
    - 点击后调用 `authApi.logout(refreshToken)` → `clearAuth()` → `navigate('/login')`
    - API 调用失败也执行 clearAuth（保证本地清除）

### 阶段 8：测试

- [ ] **T8** 编写前端测试
  - [ ] T8.1 `src/stores/auth-store.test.ts`：
    - setAuth / clearAuth / setAccessToken 状态正确更新
    - clearAuth 清除 localStorage
  - [ ] T8.2 `src/services/auth-api.test.ts`（使用 msw 或 vitest mock）：
    - login 成功返回 TokenResponse
    - login 失败返回 401 错误码
    - refresh 成功/失败
  - [ ] T8.3 `src/pages/login-page.test.tsx`：
    - 渲染登录表单（用户名 + 密码 + 登录按钮）
    - 空字段校验显示错误
    - 登录成功跳转
    - 登录失败显示错误提示
    - 已登录用户自动跳转 /dashboard
  - [ ] T8.4 `src/routes/protected-routes.test.tsx`：
    - 未认证访问受保护路由 → 重定向 /login
    - 已认证访问受保护路由 → 正常渲染

### 阶段 9：端到端验证

- [ ] **T9** 端到端验证（AC: #1-#9）
  - [ ] T9.1 `npm run type-check` — 零 TS 错误
  - [ ] T9.2 `npm run lint` — 零 lint 错误
  - [ ] T9.3 `npm run test` — 所有测试通过
  - [ ] T9.4 `npm run build` — 构建成功
  - [ ] T9.5 手动验证：登录 → 查看仪表盘 → 刷新页面保持登录 → 退出登录

---

## Dev Notes

### 1. 架构对齐（关键决策）

- **Decision 2.1**: JWT access (15min) + refresh (7d)。前端 access_token 仅存内存（Zustand），refresh_token 存 localStorage。
- **Decision 4.1**: 三层状态管理 — 本 Story 使用 Zustand（auth 状态）+ TanStack Query（API 请求）。
- **Decision 4.3**: React Router v7 路由守卫。
- **Authentication Flow**（architecture.md §Communication Patterns）：
  - 登录：POST `/api/v1/auth/login` → 后端验证 → 返回 access_token + refresh_token
  - 请求拦截：axios interceptor 自动加 `Authorization: Bearer {access_token}`
  - Token 刷新：401 → 自动 refresh → 重发原请求
  - 登出：POST `/api/v1/auth/logout` → 清除前端 store + 后端注销 refresh_token

### 2. 后端 Auth API 契约（已实现，不可修改）

**Login API：**
```
POST /api/v1/auth/login
Body: { username: string, password: string }
Success 200: { access_token: string, refresh_token: string, token_type: "bearer", expires_in: 900 }
Error 401: { error: { code: "INVALID_CREDENTIALS"|"ACCOUNT_LOCKED"|"ACCOUNT_DISABLED", message: "..." } }
```

**Refresh API：**
```
POST /api/v1/auth/refresh
Body: { refresh_token: string }
Success 200: { access_token: string, refresh_token: string, token_type: "bearer", expires_in: 900 }
Error 401: { error: { code: "TOKEN_REVOKED"|"TOKEN_EXPIRED"|"TOKEN_INVALID", message: "..." } }
```

**Logout API：**
```
POST /api/v1/auth/logout
Body: { refresh_token: string }
Success 200: { message: "已注销" }  (幂等)
```

**JWT Access Token Payload：**
```json
{
  "sub": "user_01HXYZ...",
  "type": "access",
  "iat": 1749...,
  "exp": 1749...,
  "role": "admin",
  "username": "zhangsan"
}
```

### 3. 前端现有代码基础（Story 1-1 脚手架产物）

以下文件已存在且为 **placeholder**，需要在此 Story 中实现真实逻辑：

| 文件 | 当前状态 | 本 Story 需做的事 |
|------|----------|-------------------|
| `src/stores/auth-store.ts` | 仅 `token + setToken` | 扩展为完整 AuthState |
| `src/services/api-client.ts` | request interceptor 无 auth | 注入 Bearer token + 401 刷新逻辑 |
| `src/routes/protected-routes.tsx` | 直接返回 children | 实现 auth 检查 + 重定向 |
| `src/routes/role-routes.tsx` | 返回全部路由 | 保持 placeholder（Story 1-7 实现） |
| `src/routes/index.tsx` | 无 /login 路由、无 auth guard | 添加 login 路由 + 包裹 ProtectedRoute |
| `src/hooks/use-permission.ts` | 返回 false | 保持 placeholder（后续 Story 实现） |

### 4. Zustand Auth Store 设计

```ts
// src/stores/auth-store.ts
import { create } from 'zustand'

const REFRESH_TOKEN_KEY = 'agentflow_refresh_token'

export interface AuthUser {
  id: string
  username: string
  role: string
}

interface AuthState {
  accessToken: string | null
  user: AuthUser | null
  isAuthenticated: boolean
  isInitializing: boolean

  setAuth: (accessToken: string, user: AuthUser) => void
  setAccessToken: (token: string) => void
  clearAuth: () => void
  setInitializing: (v: boolean) => void
}

export const useAuthStore = create<AuthState>((set) => ({
  accessToken: null,
  user: null,
  isAuthenticated: false,
  isInitializing: true, // 初始为 true，等待 refresh 检查完成

  setAuth: (accessToken, user) => {
    set({ accessToken, user, isAuthenticated: true })
  },

  setAccessToken: (token) => {
    set({ accessToken: token })
  },

  clearAuth: () => {
    localStorage.removeItem(REFRESH_TOKEN_KEY)
    set({ accessToken: null, user: null, isAuthenticated: false })
  },

  setInitializing: (v) => {
    set({ isInitializing: v })
  },
}))
```

**关键设计决策：**
- `accessToken` 仅存内存 — 页面关闭即丢失（安全）
- `refreshToken` 存 localStorage — 支持页面刷新恢复
- `isInitializing` 防止页面闪烁（刷新恢复期间显示 loading）
- `clearAuth` 自动清理 localStorage

### 5. Token 自动刷新（防并发）设计

```ts
// src/services/api-client.ts — response interceptor 核心逻辑
let isRefreshing = false
let refreshPromise: Promise<string> | null = null

async function refreshAccessToken(): Promise<string> {
  if (isRefreshing && refreshPromise) {
    return refreshPromise // 复用正在进行的 refresh
  }

  isRefreshing = true
  const refreshToken = localStorage.getItem('agentflow_refresh_token')
  if (!refreshToken) {
    throw new Error('No refresh token')
  }

  refreshPromise = authApi.refresh(refreshToken)
    .then((res) => {
      const { access_token, refresh_token } = res.data
      // 更新 localStorage 和 store
      localStorage.setItem('agentflow_refresh_token', refresh_token)
      useAuthStore.getState().setAccessToken(access_token)
      return access_token
    })
    .finally(() => {
      isRefreshing = false
      refreshPromise = null
    })

  return refreshPromise
}
```

### 6. 登录页设计令牌

遵循 `DESIGN.md` + `EXPERIENCE.md`：
- 背景：`colorBgLayout` (#FAFAFA) — 整页背景
- 登录卡片：`colorBgContainer` (#FFFFFF) + `borderRadius: 12px` + `shadow: 0 1px 3px rgba(0,0,0,0.1)`
- 产品标题：`fontFamily` primary + `fontSize: 24px` + `fontWeight: 600` + `colorPrimary` (#7C3AED)
- 输入框：AntD Input + Input.Password，高度 40px
- 登录按钮：AntD Button type="primary" block，高度 40px
- 错误提示：AntD Alert type="error" showIcon
- 卡片宽度：400px，居中（Tailwind: `flex items-center justify-center min-h-screen`）

### 7. 路由配置变更

```tsx
// src/routes/index.tsx — 更新后结构
export const routes = [
  // 独立页面（无布局）
  { path: PATHS.DESIGN_SYSTEM, element: <DesignSystemPage /> },
  { path: PATHS.LOGIN, element: <LoginPage /> },

  // 认证保护的应用路由
  {
    element: <ProtectedRoute />,  // 使用 Outlet 模式
    children: [
      {
        path: PATHS.HOME,
        element: <AppLayout />,
        children: [
          { index: true, element: <DashboardPage /> },
          // ...其他子路由
        ],
      },
    ],
  },
]
```

### 8. Auth 初始化流程（App 启动时）

```tsx
// src/features/auth/auth-initializer.tsx
export function AuthInitializer({ children }: { children: ReactNode }) {
  const { isInitializing, setInitializing, setAuth, clearAuth } = useAuthStore()

  useEffect(() => {
    const refreshToken = localStorage.getItem('agentflow_refresh_token')
    if (!refreshToken) {
      setInitializing(false)
      return
    }

    authApi.refresh(refreshToken)
      .then((res) => {
        const { access_token } = res.data
        const user = decodeAccessToken(access_token)
        setAuth(access_token, user)
        localStorage.setItem('agentflow_refresh_token', res.data.refresh_token)
      })
      .catch(() => {
        clearAuth()
      })
      .finally(() => {
        setInitializing(false)
      })
  }, [])

  if (isInitializing) {
    return <Spin size="large" fullscreen />
  }

  return <>{children}</>
}
```

### 9. refresh_token localStorage 策略

- 存储时机：登录成功后、refresh 成功后（双 token 轮换）
- 读取时机：页面刷新初始化
- 清除时机：登出、refresh 失败
- Key：`agentflow_refresh_token`
- **注意**：后端 refresh API 返回新的 refresh_token（轮换机制），前端必须同时更新 localStorage

### 10. 文件清单（NEW / UPDATE）

| 操作 | 文件路径 | 说明 |
|------|----------|------|
| UPDATE | `frontend/src/stores/auth-store.ts` | 扩展为完整 AuthState + AuthUser 类型 |
| UPDATE | `frontend/src/services/api-client.ts` | Auth header 注入 + 401 自动刷新拦截器 |
| NEW | `frontend/src/services/auth-api.ts` | Auth API 调用封装（login/refresh/logout） |
| NEW | `frontend/src/pages/login-page.tsx` | 登录页面组件 |
| UPDATE | `frontend/src/routes/index.tsx` | 添加 /login 路由 + ProtectedRoute 包裹 |
| UPDATE | `frontend/src/routes/protected-routes.tsx` | 实现 auth 检查 + 未认证重定向 |
| UPDATE | `frontend/src/features/layout/header.tsx` | 用户菜单添加"退出登录" |
| NEW | `frontend/src/features/auth/auth-initializer.tsx` | 页面刷新恢复登录态 |
| UPDATE | `frontend/src/App.tsx` | 包裹 AuthInitializer |
| NEW | `frontend/src/lib/jwt.ts` | JWT decode 工具函数 |
| NEW | `frontend/src/stores/auth-store.test.ts` | Auth store 测试 |
| NEW | `frontend/src/pages/login-page.test.tsx` | 登录页测试 |
| NEW | `frontend/src/routes/protected-routes.test.tsx` | 路由守卫测试 |

### 11. 依赖方向

```
pages/login-page → services/auth-api + stores/auth-store
                      ↓
                 services/api-client (axios interceptors)
                      ↓
                 lib/jwt (JWT decode)

routes/protected-routes → stores/auth-store
features/auth/auth-initializer → services/auth-api + stores/auth-store
features/layout/header → services/auth-api + stores/auth-store
```

### 12. 来自前序 Story 的可复用资产

- `src/services/api-client.ts` ✅ 基础 axios 实例（需扩展 interceptors）
- `src/stores/auth-store.ts` ✅ 占位（需扩展）
- `src/routes/protected-routes.tsx` ✅ 占位（需实现）
- `src/routes/paths.ts` ✅ 已有 `LOGIN: '/login'` 路径常量
- `src/config/env.ts` ✅ `API_BASE_URL` 配置
- `src/lib/request-id.ts` ✅ X-Request-ID 生成
- `src/components/error-boundary.tsx` ✅ 错误边界
- `src/features/layout/app-layout.tsx` ✅ App Shell 布局
- `src/features/layout/header.tsx` ✅ 顶栏组件（需添加退出登录菜单）
- `src/features/layout/sidebar.tsx` ✅ 侧栏组件

### 13. 后端已实现的认证相关代码

- `backend/app/api/v1/auth.py` ✅ Login / Refresh / Logout / ChangePassword 路由
- `backend/app/schemas/auth.py` ✅ LoginRequest / RefreshRequest / TokenResponse / LogoutRequest
- `backend/app/services/auth_service.py` ✅ AuthService.login / refresh_token / logout / change_password
- `backend/app/core/security.py` ✅ JWT 创建/解码 + get_current_user + require_role
- `backend/app/models/user.py` ✅ UserRole (admin/developer/operator/viewer) + UserStatus (active/disabled)

### 14. AntD 6.x 注意事项

- 本项目使用 **AntD 6.x**（非 5.x），API 可能有细微差异
- `Input.Password` 组件：AntD 6.x 中从 `antd` 直接导入
- `Spin` fullscreen：AntD 6.x 支持 `<Spin fullscreen />` prop
- Form.validateTrigger：默认 `onChange`，登录表单建议改为 `onBlur`
- `message.error()` / `notification.error()` 通过 `App.useApp()` hook 获取（AntD 6.x 推荐方式）

### 15. 注意事项与防坑指南

- **禁止将 access_token 存入 localStorage 或 sessionStorage** — 安全风险（XSS 可窃取）
- **refresh API 返回新的 refresh_token** — 后端是轮换机制，前端必须更新 localStorage
- **并发刷新防护** — 多个 401 只触发一次 refresh，否则会导致第一个 refresh 成功后旧 refresh_token 失效
- **Login 页面不需要 ProtectedRoute** — 它是公开页面，已登录用户访问时自动跳转
- **JWT decode 不校验签名** — 前端只是读取 payload，签名验证由后端完成
- **表单校验用 AntD Form 内置** — 不自建校验逻辑（Architecture Decision）
- **snake_case JSON 字段** — 后端返回 `access_token` 非 `accessToken`，前端 service 层直接使用 snake_case
- **API 响应格式** — 后端返回裸 `TokenResponse`（非 `{data: {...}}` 包裹），与架构统一格式说明有差异。**以后端实际行为为准**

### References

- [Source: docs/planning-artifacts/architecture.md#Decision-2.1] — JWT 认证（access + refresh）
- [Source: docs/planning-artifacts/architecture.md#Authentication-Flow] — 前端认证流程
- [Source: docs/planning-artifacts/architecture.md#Decision-4.1] — 三层状态管理
- [Source: docs/planning-artifacts/architecture.md#Decision-4.3] — React Router v7 数据路由
- [Source: docs/planning-artifacts/architecture.md#Frontend-Architecture] — 前端架构
- [Source: docs/planning-artifacts/architecture.md#State-Management-Patterns] — Zustand 使用规范
- [Source: docs/planning-artifacts/architecture.md#Loading-State-Patterns] — Loading 状态规范
- [Source: docs/planning-artifacts/ux-designs/ux-agent-flow-2026-06-08/EXPERIENCE.md#IA] — 信息架构导航
- [Source: docs/planning-artifacts/ux-designs/ux-agent-flow-2026-06-08/EXPERIENCE.md#Component-Patterns] — 按钮和输入框行为
- [Source: docs/planning-artifacts/ux-designs/ux-agent-flow-2026-06-08/EXPERIENCE.md#State-Patterns] — 状态矩阵
- [Source: docs/planning-artifacts/ux-designs/ux-agent-flow-2026-06-08/DESIGN.md#Colors] — 颜色令牌
- [Source: docs/planning-artifacts/ux-designs/ux-agent-flow-2026-06-08/DESIGN.md#Typography] — 字体令牌
- [Source: docs/planning-artifacts/epics.md#Epic-1] — 平台基础建设
- [Source: docs/implementation-artifacts/1-5-password-change-and-logout.md] — 前序 Story（密码修改/登出后端）
- [Source: docs/implementation-artifacts/1-4-user-management-and-rbac.md] — RBAC 实现
- [Source: docs/implementation-artifacts/1-3-user-login-jwt-auth.md] — JWT 认证后端实现

---

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

### Completion Notes List

### File List

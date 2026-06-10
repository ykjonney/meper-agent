---
baseline_commit: NO_VCS
title: 'Frontend Agent API Integration — Replace Mock with Real API'
type: 'feature'
created: '2026-06-09'
status: 'done'
context:
  - 'frontend/src/services/api-client.ts'
  - 'frontend/src/services/auth-api.ts'
  - 'frontend/src/pages/agents-page.tsx'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Agent 管理页面使用硬编码 mock 数据，无法与后端 Agent CRUD API 交互。

**Approach:** 创建 Agent API 服务层（`agent-api.ts`），用 TanStack Query 替换 mock 数据驱动 agents-page 的列表、搜索、筛选、创建和删除功能。

## Boundaries & Constraints

**Always:**
- 所有请求通过共享 `apiClient` 实例（自动 auth header + 401 refresh）
- API 响应使用 snake_case（后端契约），前端直接使用不做 camelCase 转换
- 使用 TanStack Query（`@tanstack/react-query`）管理服务端状态
- 保持现有页面 UI 布局和交互模式不变
- 错误处理使用 `message.error()` 展示后端返回的错误消息

**Ask First:**
- 是否需要安装 TanStack Query（检查是否已有依赖）

**Never:**
- 不修改后端 API 响应格式
- 不创建新的全局 Zustand store（用 TanStack Query 缓存即可）
- 不实现 invoke/stream 调用端点（仅 CRUD）
- 不实现 Agent 创建向导/编辑表单（仅列表页集成，创建/编辑按钮保留但暂为 placeholder）

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| 列表加载 | 进入 /agents 页面 | GET /agents → 渲染卡片列表，按 updated_at 降序 | 网络错误 → message.error + 空状态提示 |
| 分页加载 | 滚动或切换页码 | GET /agents?page=N&page_size=20 | 超出范围 → 返回空列表 |
| 名称搜索 | 输入搜索关键词 | GET /agents?name=xxx（debounce 300ms） | 无结果 → 显示空状态 |
| 状态筛选 | 切换筛选下拉框 | GET /agents?status=draft/published/archived | N/A |
| 创建 Agent | 点击新建按钮 | 暂为 placeholder（message.info 提示） | N/A |
| 删除 Agent | 点击删除按钮 | DELETE /agents/{id} → 刷新列表 | 404 → 提示已不存在；其他 → message.error |
| 空列表 | 后端返回 items=[] | 显示空状态占位（"暂无 Agent"） | N/A |

</frozen-after-approval>

## Code Map

- `frontend/src/services/agent-api.ts` — Agent API 服务层（新建）
- `frontend/src/pages/agents-page.tsx` — Agent 管理页面（替换 mock → TanStack Query）
- `frontend/src/services/api-client.ts` — 共享 HTTP 客户端（无需修改）
- `backend/app/schemas/agent.py` — 后端 Agent 请求/响应 schema（参考）

## Tasks & Acceptance

**Execution:**
- [x] `frontend/package.json` — 检查/安装 `@tanstack/react-query` 依赖（已有 v5.101.0）
- [x] `frontend/src/main.tsx` — 在根组件注入 QueryClientProvider
- [x] `frontend/src/services/agent-api.ts` — 创建 Agent API 服务（listAgents, getAgent, createAgent, updateAgent, deleteAgent）
- [x] `frontend/src/pages/agents-page.tsx` — 替换 mock 数据为 TanStack Query useQuery + useMutation，保留现有 UI

**Acceptance Criteria:**
- Given 后端运行中，当访问 /agents 页面，then 调用 GET /api/v1/agents 并渲染真实数据
- Given 搜索框输入关键词，当 300ms 无输入，then 发起 GET /agents?name=xxx 请求
- Given 切换状态下拉框，when 选择 "已发布"，then 请求 GET /agents?status=published
- Given 点击删除按钮，when 确认删除，then DELETE /agents/{id} 成功后自动刷新列表
- Given 后端不可用，当请求失败，then 页面显示错误消息而非崩溃

## Verification

**Commands:**
- `cd frontend && npx tsc --noEmit` — 零 TS 错误
- `npm run build` — 构建成功

**Manual checks:**
- 启动后端，访问 /agents 页面 → 看到真实数据（或空列表状态）
- 搜索/筛选交互正常，loading 态正确展示
- 后端停止时页面不崩溃，显示错误提示

## Suggested Review Order

**QueryClient 注入**

- 全局 QueryClient 配置（staleTime / retry / refetchOnWindowFocus）
  [`main.tsx:8`](../../frontend/src/main.tsx#L8)

**Agent API 服务层**

- 服务入口，类型定义 + 5 个端点方法，URL 已做 encodeURIComponent 防护
  [`agent-api.ts:62`](../../frontend/src/services/agent-api.ts#L62)

- Query key factory，保证 list/detail 缓存隔离
  [`agent-api.ts:113`](../../frontend/src/services/agent-api.ts#L113)

**页面数据流**

- useQuery + debounced 搜索 + status 筛选，TanStack Query 驱动
  [`agents-page.tsx:62`](../../frontend/src/pages/agents-page.tsx#L62)

- deleteMutation + Modal.confirm 二次确认 + 失败兜底
  [`agents-page.tsx:84`](../../frontend/src/pages/agents-page.tsx#L84)

**页面 UI 状态**

- Loading / Error / Empty 三态分支渲染
  [`agents-page.tsx:167`](../../frontend/src/pages/agents-page.tsx#L167)

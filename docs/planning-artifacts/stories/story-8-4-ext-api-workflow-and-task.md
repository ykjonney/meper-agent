# Story 8.4: 外部 API — Workflow 调用与 Task 查询

**Epic**: 8 — 外部 API 集成
**状态**: backlog
**依赖**: Story 8.1
**设计文档**: `docs/planning-artifacts/external-api-design.md`

## 用户故事

As a 外部系统开发者，
I want 通过 API Key 认证查询可用的 Workflow 并触发执行，查询 Task 状态，
So that 我的系统可以集成 Workflow 能力并获取执行结果。

## Acceptance Criteria

### AC-1: 列出可访问的 Workflow

```
GET /api/v1/ext/workflows
Authorization: Bearer af_live_xxx

Query: page=1, page_size=20
```

**Given** API Key 有效且包含 `workflows:read` scope
**When** 请求 Workflow 列表
**Then** 返回 200，仅包含已发布的 Workflow（`status=published`）
**And** 按 API Key 的 `bindings.workflows` 过滤（空 = 不限制）
**And** 响应格式：
```json
{
  "items": [
    {
      "id": "01HYYY",
      "name": "质检报告流程",
      "description": "接收批次数据，生成质检报告",
      "input_schema": {
        "type": "object",
        "properties": {
          "batch_id": { "type": "string", "description": "批次号" }
        },
        "required": ["batch_id"]
      },
      "status": "published",
      "version": "1.2.0"
    }
  ],
  "total": 3,
  "page": 1,
  "page_size": 20
}
```

### AC-2: 获取 Workflow 详情

```
GET /api/v1/ext/workflows/{workflow_id}
```

**Given** Workflow 存在且 API Key 有权访问
**When** 请求详情
**Then** 返回 200，包含 `input_schema`、`nodes`、`edges`、`version` 等完整信息

**Given** Workflow 不存在或 API Key 无权访问
**When** 请求详情
**Then** 返回 404 或 403

### AC-3: 触发 Workflow 执行

```
POST /api/v1/ext/workflows/{workflow_id}/invoke
Authorization: Bearer af_live_xxx
Content-Type: application/json

{
  "input": {
    "batch_id": "A23",
    "data_source": "mes"
  },
  "callback_url": "https://mes.example.com/webhooks/result"
}
```

**Given** API Key 包含 `workflows:invoke` scope 且有权访问该 Workflow
**When** 触发执行
**Then** 调用 `TaskService.create_task()`
**And** Task 的 `created_by` 设为 API Key 的 `owner_user_id`
**And** Task 的 `created_by_type` 设为 `"api_key"`
**And** 异步执行 Workflow
**And** 返回 201：
```json
{
  "task_id": "01HTASK1",
  "status": "pending",
  "workflow_id": "01HYYY",
  "workflow_version": "1.2.0"
}
```
**And** 如果提供了 `callback_url`，记录到 Task 元数据用于单次回调

### AC-4: 查询 Task 状态

```
GET /api/v1/ext/tasks/{task_id}
Authorization: Bearer af_live_xxx
```

**Given** API Key 包含 `executions:read` scope
**When** 查询 Task
**Then** 返回 200：
```json
{
  "id": "01HTASK1",
  "workflow_id": "01HYYY",
  "workflow_version": "1.2.0",
  "status": "completed",
  "input": { ... },
  "output": { ... },
  "error": null,
  "created_at": "...",
  "updated_at": "..."
}
```

**Given** Task 是该 API Key 触发的，或 API Key 有全局 `executions:read` 权限
**When** 查询
**Then** 允许访问

### AC-5: 权限与错误处理

| 场景 | 状态码 | 消息 |
|------|--------|------|
| Scope 不足 | 403 | `"API Key 权限不足，需要 {scope} 权限"` |
| Workflow 不在绑定范围 | 403 | `"API Key 无权访问该 Workflow"` |
| Workflow 不存在 | 404 | `"Workflow not found"` |
| input 不符合 input_schema | 400 | `"Input validation failed: {details}"` |
| Task 不存在 | 404 | `"Task not found"` |

### AC-6: 实现文件

**Given** 开发完成
**Then** 以下文件已创建并通过测试：
- `app/api/v1/ext/workflows.py` — Workflow 资源发现 + 调用端点
- `app/api/v1/ext/tasks.py` — Task 查询端点
- 路由注册到 `app/api/v1/ext/__init__.py`

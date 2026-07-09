# Story 8.3: 外部 API — 资源发现与 Agent 调用

**Epic**: 8 — 外部 API 集成
**状态**: backlog
**依赖**: Story 8.1
**设计文档**: `docs/planning-artifacts/external-api-design.md`

## 用户故事

As a 外部系统开发者，
I want 通过 API Key 认证查询可用的 Agent 并调用它们，
So that 我的系统可以通过 REST API 集成 Agent 能力。

## Acceptance Criteria

### AC-1: 列出可访问的 Agent

```
GET /api/v1/ext/agents
Authorization: Bearer af_live_xxx

Query: page=1, page_size=20
```

**Given** API Key 有效且包含 `agents:read` scope
**When** 请求 Agent 列表
**Then** 返回 200，仅包含已发布的 Agent（`status=published`）
**And** 按 API Key 的 `bindings.agents` 过滤（空 = 不限制）
**And** 响应格式：
```json
{
  "items": [
    {
      "id": "01HXXX",
      "name": "质检助手",
      "description": "分析产线质检数据并生成报告",
      "capabilities": {
        "tools": ["mes_query", "report_generator"],
        "workflow_ids": ["01HYYY"]
      },
      "default_model": "gpt-4o",
      "status": "published"
    }
  ],
  "total": 5,
  "page": 1,
  "page_size": 20
}
```

### AC-2: 获取 Agent 详情

```
GET /api/v1/ext/agents/{agent_id}
```

**Given** Agent 存在且 API Key 有权访问
**When** 请求详情
**Then** 返回 200，包含完整 Agent 信息（描述、能力、模型等）

**Given** Agent 不存在或 API Key 无权访问
**When** 请求详情
**Then** 返回 404（不存在）或 403（无权限）

### AC-3: 同步调用 Agent

```
POST /api/v1/ext/agents/{agent_id}/invoke
Authorization: Bearer af_live_xxx
Content-Type: application/json

{
  "message": "帮我查一下批次 A23 的质检结果",
  "session_id": "01HZZZ"
}
```

**Given** API Key 包含 `agents:invoke` scope 且有权访问该 Agent
**When** 发起同步调用
**Then** 调用 `AgentExecutionService.invoke()`
**And** `session_id` 不传时自动创建新 Session
**And** Session 的 `user_id` 设为 API Key 的 `owner_user_id`
**And** 返回 200：
```json
{
  "session_id": "01HZZZ",
  "request_id": "req_01H...",
  "reply": "批次 A23 质检结果如下：...",
  "task_ids": ["01HTASK1"],
  "files": []
}
```
**And** 如果 Agent 执行过程中触发了 Workflow Task，`task_ids` 包含产生的 task_id 列表

### AC-4: SSE 流式调用 Agent

```
POST /api/v1/ext/agents/{agent_id}/invoke/stream
```

**Given** API Key 包含 `agents:invoke` scope
**When** 发起流式调用
**Then** 调用 `AgentExecutionService.stream()`
**And** 返回 `text/event-stream`
**And** SSE 事件类型包括：`token`、`tool_call`、`task_created`、`done`
**And** 响应头包含 `X-Request-Id` 和 `X-Session-Id`

### AC-5: 中断恢复（追问）

```
POST /api/v1/ext/agents/{agent_id}/invoke/resume
Content-Type: application/json

{
  "session_id": "01HZZZ",
  "answer": "是的，请使用 MES 数据源"
}
```

**Given** Agent 之前通过 `ask_clarification` 中断了执行
**When** 外部系统发送 resume 请求
**Then** 调用 `AgentExecutionService.resume()`
**And** 返回 SSE 流式响应

### AC-6: Session 归属

**Given** 外部系统通过 API Key 创建的 Session
**When** 后续请求带上相同的 `session_id`
**Then** 消息写入该 Session 的历史
**And** 外部系统可通过 Session 实现多轮对话
**And** Session 的归属不受前端用户可见（API Key 创建的 Session 独立管理）

### AC-7: 错误处理

| 场景 | 状态码 | 消息 |
|------|--------|------|
| API Key 无效/过期/吊销 | 401 | `"Invalid or expired API Key"` |
| Scope 不足 | 403 | `"API Key 权限不足，需要 {scope} 权限"` |
| Agent 不在绑定范围 | 403 | `"API Key 无权访问该 Agent"` |
| Agent 不存在 | 404 | `"Agent not found"` |
| Agent 未发布 | 404 | `"Agent not found"` |

### AC-8: 实现文件

**Given** 开发完成
**Then** 以下文件已创建并通过测试：
- `app/api/v1/ext/__init__.py` — 外部 API 路由组
- `app/api/v1/ext/agents.py` — Agent 资源发现 + 调用端点
- 路由注册到 `app/api/v1/router.py`

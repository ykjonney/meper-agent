# 外部 API 集成方案

> 对应 Epic 8：外部系统（MES/ERP/BI）通过 REST API 调用 Agent 和 Workflow 能力。
> 日期：2026-07-06
> 状态：方案已确认，待实施

## 1. 概述

为平台提供面向外部系统的 REST API 集成能力，包括：

- **资源发现**：查询可访问的 Agent 和 Workflow 列表及详情
- **Agent 调用**：支持同步返回和 SSE 流式输出，支持多轮 Session
- **Workflow 调用**：异步创建 Task，轮询获取结果
- **Webhook 回调**：任务完成/失败时主动推送事件到外部系统
- **API Key 认证**：带 scopes 和资源绑定的细粒度权限控制

## 2. 与现有实现的关系

### 已存在的能力（复用，不动）

| 能力 | 现有路由 | 说明 |
|------|----------|------|
| Agent 同步调用 | `POST /agents/{id}/invoke` | `AgentExecutionService.invoke()` |
| Agent 流式调用 | `POST /agents/{id}/stream` | `AgentExecutionService.stream()` |
| Agent 中断恢复 | `POST /agents/{id}/resume` | `AgentExecutionService.resume()` |
| Session 管理 | `POST/GET /sessions` | `SessionService` CRUD |
| Task CRUD + 干预 | `POST/GET /tasks/{id}` | `TaskService` |
| WebSocket 实时推送 | `GET /ws` | JWT 认证，面向前端 |
| JWT + RBAC 认证 | `core/security.py` | access/refresh token |

### 需要新建的部分

| 模块 | 说明 |
|------|------|
| API Key 认证体系 | 数据模型 + 服务 + 认证中间件 |
| 外部 API 路由 | `/api/v1/ext/` 前缀，薄封装转发到现有 Service |
| Webhook 事件推送 | 配置管理 + 事件分发 + HMAC 签名 + 重试 |
| 资源过滤 | 按 API Key bindings 过滤 list 结果 |

## 3. 认证体系

### 3.1 双认证隔离

```
内部用户（前端）  → JWT Bearer token  → 现有 get_current_user 依赖
外部系统（API）   → API Key Bearer    → 新增 get_api_key_principal 依赖
```

外部 API 统一使用 `/api/v1/ext/` 前缀，与内部路由隔离。

### 3.2 API Key 格式

```
af_live_{32位随机字符}    # 生产环境
af_test_{32位随机字符}    # 测试环境（可选）
```

示例：`af_live_a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6`

### 3.3 API Key 数据模型

```python
# app/models/api_key.py
class ApiKey:
    id: str                    # MongoDB _id
    name: str                  # 显示名称，如 "MES 产线 A"
    key_hash: str              # bcrypt hash（不存明文）
    key_prefix: str            # 前 12 位，用于列表展示
    owner_user_id: str         # 创建者 user_id
    scopes: list[str]          # ["agents:invoke", "workflows:invoke", "executions:read", "agents:read", "workflows:read"]
    bindings: ApiKeyBindings   # 资源绑定
    rate_limit: int            # 每分钟请求上限
    status: str                # "active" | "revoked"
    expires_at: str | None     # ISO 时间戳
    last_used_at: str | None
    created_at: str
    updated_at: str

class ApiKeyBindings:
    agents: list[str]          # 允许访问的 Agent ID 列表，空 = 全部
    workflows: list[str]       # 允许访问的 Workflow ID 列表，空 = 全部
```

### 3.4 Scopes 定义

| Scope | 说明 | 对应操作 |
|-------|------|----------|
| `agents:read` | 查询 Agent 列表和详情 | `GET /ext/agents`, `GET /ext/agents/{id}` |
| `agents:invoke` | 调用 Agent（同步/流式） | `POST /ext/agents/{id}/invoke`, `/stream` |
| `workflows:read` | 查询 Workflow 列表和详情 | `GET /ext/workflows`, `GET /ext/workflows/{id}` |
| `workflows:invoke` | 触发 Workflow | `POST /ext/workflows/{id}/invoke` |
| `executions:read` | 查询 Task 状态和结果 | `GET /ext/tasks/{id}` |

### 3.5 认证流程

```python
# app/core/auth_apikey.py
async def get_api_key_principal(authorization: str = Header(None)) -> ApiKeyPrincipal:
    """从 Authorization: Bearer af_live_xxx 解析 API Key 认证"""
    # 1. 提取 Bearer token
    # 2. 匹配 key_prefix 查找候选 Key
    # 3. bcrypt 验证完整 Key
    # 4. 检查 status=active, expires_at 未过期
    # 5. 返回 ApiKeyPrincipal（包含 key_id, scopes, bindings, owner_user_id）
```

## 4. API 设计

### 4.1 资源发现

#### 列出可访问的 Agent

```
GET /api/v1/ext/agents
Authorization: Bearer af_live_xxx

Query:
  page: int = 1
  page_size: int = 20

Response 200:
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

按 API Key 的 `bindings.agents` 自动过滤。`bindings.agents` 为空时返回所有已发布的 Agent。

#### 获取 Agent 详情

```
GET /api/v1/ext/agents/{agent_id}

Response 200:
{
  "id": "01HXXX",
  "name": "质检助手",
  "description": "分析产线质检数据并生成报告",
  "capabilities": {
    "tools": ["mes_query", "report_generator"],
    "workflow_ids": ["01HYYY"]
  },
  "default_model": "gpt-4o",
  "status": "published",
  "created_at": "...",
  "updated_at": "..."
}
```

#### 列出可访问的 Workflow

```
GET /api/v1/ext/workflows

Response 200:
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

#### 获取 Workflow 详情

```
GET /api/v1/ext/workflows/{workflow_id}

Response 200:
{
  "id": "01HYYY",
  "name": "质检报告流程",
  "description": "...",
  "input_schema": { ... },
  "nodes": [ ... ],
  "edges": [ ... ],
  "status": "published",
  "version": "1.2.0"
}
```

### 4.2 Agent 调用

#### 同步调用

```
POST /api/v1/ext/agents/{agent_id}/invoke
Content-Type: application/json

{
  "message": "帮我查一下批次 A23 的质检结果",
  "session_id": "01HZZZ"          // 可选，不传则自动创建新 session
}

Response 200:
{
  "session_id": "01HZZZ",
  "request_id": "req_01H...",
  "reply": "批次 A23 质检结果如下：...",
  "task_ids": ["01HTASK1"],       // 如果触发了 Workflow
  "files": []                     // 如果有产出文件
}
```

**流程**：调用 `AgentExecutionService.invoke()`，传入 `session_id`。返回文本响应，如果 Agent 执行过程中触发了 Workflow Task，返回 `task_ids` 供外部系统自行查询。

#### SSE 流式调用

```
POST /api/v1/ext/agents/{agent_id}/invoke/stream
Content-Type: application/json

{
  "message": "生成一份完整的质检报告",
  "session_id": "01HZZZ"
}

Response 200 (text/event-stream):
event: token
data: {"content": "批次", "type": "text"}

event: token
data: {"content": "A23", "type": "text"}

event: tool_call
data: {"tool": "mes_query", "input": {"batch_id": "A23"}, "status": "started"}

event: tool_call
data: {"tool": "mes_query", "output": {...}, "status": "completed"}

event: task_created
data: {"task_id": "01HTASK1", "workflow_id": "01HYYY", "workflow_name": "质检报告流程"}

event: done
data: {"session_id": "01HZZZ", "request_id": "req_01H..."}
```

**流程**：复用 `AgentExecutionService.stream()`，已有 SSE 输出格式。

#### 中断恢复（追问）

```
POST /api/v1/ext/agents/{agent_id}/invoke/resume
Content-Type: application/json

{
  "session_id": "01HZZZ",
  "answer": "是的，请使用 MES 数据源"
}

Response: SSE 流式（同上）
```

### 4.3 Workflow 调用

```
POST /api/v1/ext/workflows/{workflow_id}/invoke
Content-Type: application/json

{
  "input": {                          // 按 Workflow 的 input_schema 填写
    "batch_id": "A23",
    "data_source": "mes"
  },
  "callback_url": "https://mes.example.com/webhooks/result"   // 可选，单次回调
}

Response 201:
{
  "task_id": "01HTASK1",
  "status": "pending",
  "workflow_id": "01HYYY",
  "workflow_version": "1.2.0"
}
```

异步执行，立即返回 `task_id`。外部系统通过轮询 `GET /ext/tasks/{task_id}` 获取结果。

### 4.4 Task 查询

```
GET /api/v1/ext/tasks/{task_id}

Response 200:
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

复用 `TaskService.get_task_or_404()`。

## 5. Webhook

### 5.1 Webhook 配置

在平台内部（JWT 认证）管理 Webhook 配置：

```
POST /api/v1/webhooks          # 创建 Webhook 配置（admin）
GET  /api/v1/webhooks          # 列出所有 Webhook
PUT  /api/v1/webhooks/{id}     # 更新
DELETE /api/v1/webhooks/{id}   # 删除
POST /api/v1/webhooks/{id}/test  # 发送测试事件
```

#### Webhook 配置数据模型

```python
# app/models/webhook.py
class WebhookConfig:
    id: str
    name: str                    # "MES 产线 A 回调"
    url: str                     # "https://mes.example.com/webhooks/agent-flow"
    secret: str                  # HMAC 签名密钥
    events: list[str]            # 订阅的事件类型
    api_key_id: str | None       # 可选，绑定到特定 API Key
    status: str                  # "active" | "disabled"
    created_at: str
    updated_at: str
```

### 5.2 事件类型

| 事件 | 触发时机 |
|------|----------|
| `agent.completed` | Agent 执行完成（同步调用返回后异步通知） |
| `agent.failed` | Agent 执行失败 |
| `task.completed` | Workflow Task 执行完成 |
| `task.failed` | Workflow Task 执行失败 |
| `task.waiting_human` | Task 进入等待人工审批状态 |

### 5.3 事件 Payload

```json
{
  "event": "task.completed",
  "task_id": "01HTASK1",
  "workflow_id": "01HYYY",
  "status": "completed",
  "output": { "report_url": "/files/xxx.pdf" },
  "timestamp": "2026-07-06T10:00:00Z",
  "api_key_id": "key_01H..."
}
```

### 5.4 HMAC 签名

```
Header:
  X-Webhook-Event: task.completed
  X-Webhook-Signature: sha256=<hmac>
  X-Webhook-Timestamp: 1720252800

签名计算:
  payload = timestamp + "." + request_body
  signature = HMAC-SHA256(secret, payload)
```

### 5.5 重试策略

```
失败判定：响应非 2xx 或超时（10s）
重试次数：最多 5 次
退避策略：1s → 2s → 4s → 8s → 16s（指数退避）
失败处理：记录到 webhook_delivery_logs 集合，管理界面可查
```

### 5.6 单次回调

Workflow 调用时支持传 `callback_url` 参数，无需预注册：

```json
{
  "input": { "batch_id": "A23" },
  "callback_url": "https://mes.example.com/callbacks/once/abc123"
}
```

一次性使用，仅对该 Task 的有效。签名密钥从 Webhook 全局配置取，或由调用方约定。

## 6. 路由注册

```python
# app/api/v1/ext/__init__.py
from fastapi import APIRouter
from app.core.auth_apikey import require_api_key_scope

router = APIRouter(prefix="/ext", tags=["external-api"])

# 所有 ext 路由的认证依赖：API Key 认证
router.dependencies = [Depends(get_api_key_principal)]
```

注册到主路由：

```python
# app/api/v1/router.py
from app.api.v1.ext import router as ext_router
api_v1_router.include_router(ext_router)
```

内部 Webhook 管理路由（JWT 认证）：

```python
from app.api.v1.webhooks import router as webhooks_router
api_v1_router.include_router(webhooks_router)
```

## 7. Rate Limiting

基于 Redis 的滑动窗口限流：

```python
# 每个 API Key 独立的 rate_limit 配置
# 默认 60 次/分钟
# 超限返回 429 Too Many Requests
```

## 8. Story 拆分建议

### Story 8.1: API Key 数据模型与认证
- API Key MongoDB 模型
- `core/auth_apikey.py` 认证依赖
- API Key 服务层（CRUD + 验证）
- Redis 缓存（key_prefix → 快速查找）

### Story 8.2: API Key 管理界面与内部 API
- `POST/GET/PUT/DELETE /api/v1/api-keys`（JWT 认证，admin）
- 前端 API Key 管理页（创建、列表、吊销、scopes/bindings 配置）
- 创建时一次性展示完整 Key + 复制按钮

### Story 8.3: 外部 API — 资源发现与 Agent 调用
- `/api/v1/ext/agents` 列表（bindings 过滤）
- `/api/v1/ext/agents/{id}` 详情
- `/api/v1/ext/agents/{id}/invoke` 同步调用（转发到 AgentExecutionService）
- `/api/v1/ext/agents/{id}/invoke/stream` SSE 流式调用
- `/api/v1/ext/agents/{id}/invoke/resume` 中断恢复

### Story 8.4: 外部 API — Workflow 调用与 Task 查询
- `/api/v1/ext/workflows` 列表（bindings 过滤）
- `/api/v1/ext/workflows/{id}` 详情（含 input_schema）
- `/api/v1/ext/workflows/{id}/invoke` 异步触发
- `/api/v1/ext/tasks/{id}` 查询状态

### Story 8.5: Webhook 事件推送
- Webhook 配置数据模型与 CRUD API
- 事件分发机制（Celery task）
- HMAC-SHA256 签名
- 指数退避重试
- 投递日志记录
- 单次回调（callback_url 参数）

### Story 8.6: Rate Limiting 与监控
- Redis 滑动窗口限流
- 429 响应
- API Key 调用统计

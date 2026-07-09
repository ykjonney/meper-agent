# Story 8.5: Webhook 事件推送

**Epic**: 8 — 外部 API 集成
**状态**: backlog
**依赖**: Story 8.3, Story 8.4
**设计文档**: `docs/planning-artifacts/external-api-design.md`

## 用户故事

As a 外部系统开发者，
I want 在 Agent 或 Task 执行完成/失败时收到自动回调通知，
So that 我的系统不用轮询就能实时获取执行结果。

## Acceptance Criteria

### AC-1: Webhook 配置数据模型

**Given** 平台已部署
**When** 创建 Webhook 配置
**Then** MongoDB 中写入以下字段：
- `id`
- `name`（显示名称）
- `url`（回调 URL）
- `secret`（HMAC 签名密钥）
- `events`（订阅的事件类型列表）
- `api_key_id`（可选，绑定到特定 API Key）
- `status`（`active` | `disabled`）
- `created_at`、`updated_at`

### AC-2: Webhook 内部 CRUD API（JWT 认证）

```
POST   /api/v1/webhooks          → 创建（admin）
GET    /api/v1/webhooks          → 列表（admin）
GET    /api/v1/webhooks/{id}     → 详情
PUT    /api/v1/webhooks/{id}     → 更新
DELETE /api/v1/webhooks/{id}     → 删除
POST   /api/v1/webhooks/{id}/test  → 发送测试事件
```

所有端点需要 `apikey:manage` 权限。

### AC-3: 事件类型

| 事件 | 触发时机 |
|------|----------|
| `agent.completed` | Agent 执行完成 |
| `agent.failed` | Agent 执行失败 |
| `task.completed` | Workflow Task 执行完成 |
| `task.failed` | Workflow Task 执行失败 |
| `task.waiting_human` | Task 进入等待人工审批状态 |

### AC-4: 事件 Payload 格式

```json
{
  "event": "task.completed",
  "task_id": "01HTASK1",
  "workflow_id": "01HYYY",
  "status": "completed",
  "output": { ... },
  "timestamp": "2026-07-06T10:00:00Z",
  "api_key_id": "key_01H..."
}
```

### AC-5: HMAC-SHA256 签名

**Given** 系统向 Webhook URL 发送事件
**When** 构造请求
**Then** 请求头包含：
```
X-Webhook-Event: task.completed
X-Webhook-Signature: sha256=<hmac_hex>
X-Webhook-Timestamp: 1720252800
```
**And** 签名计算方式：
```
payload = timestamp + "." + request_body_json
signature = HMAC-SHA256(secret, payload)
```

### AC-6: 重试策略

**Given** Webhook 回调失败（响应非 2xx 或超时 10s）
**When** 重试机制执行
**Then** 最多重试 5 次
**And** 退避间隔：1s → 2s → 4s → 8s → 16s（指数退避）
**And** 使用 Celery task 执行异步重试

### AC-7: 投递日志

**Given** 每次 Webhook 投递
**When** 投递完成（成功或最终失败）
**Then** 记录到 `webhook_delivery_logs` 集合：
- `webhook_id`
- `event`
- `url`
- `status_code`（HTTP 响应码）
- `success`（bool）
- `attempts`（尝试次数）
- `error`（最后一次错误信息）
- `timestamp`

### AC-8: 单次回调（callback_url）

**Given** Workflow 调用时传入了 `callback_url` 参数
**When** Task 完成或失败
**Then** 向该 URL 发送一次性回调
**And** 签名密钥从 Webhook 全局配置中取第一个 active 的 secret
**And** 回调不经过预注册的 Webhook 事件过滤，仅推送该 Task 的完成/失败事件

### AC-9: 测试端点

**Given** 管理员调用 `POST /api/v1/webhooks/{id}/test`
**When** 执行
**Then** 向配置的 URL 发送一个 `test` 事件
**And** 返回投递结果（成功/失败 + 响应码）

### AC-10: 实现文件

**Given** 开发完成
**Then** 以下文件已创建并通过测试：
- `app/models/webhook.py` — Webhook 配置 + 投递日志数据模型
- `app/schemas/webhook.py` — Pydantic schemas
- `app/services/webhook_service.py` — Webhook CRUD + 事件分发 + 重试
- `app/api/v1/webhooks.py` — 内部 CRUD 路由（JWT 认证）
- `app/workers/webhook_delivery.py` — Celery task（异步投递 + 重试）

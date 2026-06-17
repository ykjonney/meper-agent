# Story 4.14: 事件总线与事件节点

**Epic:** Epic 4 — DAG 工作流编排 + Task 运行时
**Status:** ready-for-dev
**Story ID:** 4-14
**Story Key:** 4-14-event-bus

## Story

As a 开发者，
I want 工作流支持事件节点，Task 执行过程中可通过事件总线收发事件，
So that 工作流之间可解耦通信，外部系统可通过事件触发或响应工作流执行。

> ⚠️ **关键背景**：事件总线是 Workflow 系统的松耦合通信层。
> at-least-once 投递保证 + 死信队列处理失败事件 + 背压保护防止消费者过载。
> 事件节点（Event Node）是第 9 种节点类型，支持发布和订阅两种模式。
>
> 事件不依赖外部消息队列（如 Kafka），使用 MongoDB capped collection + 轮询（MVP 简化方案）。
> 后续可升级到 Redis Streams 或 Kafka。

## Acceptance Criteria

### AC1: 事件数据模型
**Given** 事件总线已实现
**When** 系统发出事件
**Then** 事件包含以下字段：
```yaml
event:
  id: ULID
  type: str                    # 事件类型，如 "task.completed", "custom.event"
  source: str                  # 事件来源，如 "workflow:{id}", "system"
  subject: str | None          # 事件主体，如 task_id
  data: dict                   # 事件负载
  timestamp: datetime          # 事件时间
  idempotency_key: str         # 幂等键（用于去重）
```

### AC2: Event Node（事件节点）
**Given** 工作流中添加了事件节点
**When** 配置事件节点
**Then** 支持两种模式：

**发布模式（Publish）：**
- 配置 `event_type`（自定义事件类型）
- 配置 `payload_template`（从变量池提取数据，支持 `{{node.field}}` 表达式）
- 执行时将 payload 发布到事件总线
- 发布后节点立即完成

**订阅模式（Subscribe）：**
- 配置 `event_type`（订阅的事件类型）
- 配置 `timeout_ms`（等待超时）
- 配置 `match_condition`（可选，通过表达式匹配事件载荷的条件）
- 执行时阻塞等待匹配的事件到达
- 超时后按 `timeout_action` 处理
- 事件数据写入变量池供下游节点使用

### AC3: at-least-once 投递
**Given** 事件已发布到事件总线
**When** 消费者处理事件
**Then** 系统保证每条事件至少被消费一次
**And** 消费者处理成功后需确认（ack），未确认的事件重新投递
**And** 消费端通过 `idempotency_key` 实现幂等处理

### AC4: 死信队列
**Given** 事件投递失败
**When** 重试次数超过上限（默认 3 次）
**Then** 事件移入死信队列（dead letter queue）
**And** 死信队列记录：`{event, failed_at, retry_count, last_error, stack_trace}`
**And** 提供 API 查询和重投死信事件：
- `GET /api/v1/events/dead-letter` — 查询死信列表
- `POST /api/v1/events/dead-letter/{id}/redeliver` — 重投死信事件

### AC5: 背压保护
**Given** 事件消费者处理速度跟不上发布速度
**When** 未确认事件积压超过阈值（默认 1000）
**Then** 事件总线触发背压保护
**And** 新的发布请求返回 429 Too Many Requests
**And** 背压状态记录到监控日志
**And** 背压解除后恢复正常发布

### AC6: 系统内置事件
**Given** Task 执行过程中
**When** 关键状态变更发生
**Then** 系统自动发布以下内置事件：

| 事件类型 | 触发时机 | 数据 |
|---------|---------|------|
| `task.created` | Task 创建 | task_id, workflow_id, input |
| `task.started` | Task 开始执行 | task_id, status: running |
| `task.completed` | Task 完成 | task_id, output |
| `task.failed` | Task 失败 | task_id, error |
| `task.cancelled` | Task 取消 | task_id, reason |
| `task.waiting_human` | Task 等待人工 | task_id, node_id, config |
| `task.node.completed` | 节点执行完成 | task_id, node_id, output |
| `workflow.published` | 工作流发布 | workflow_id, version |
| `workflow.unpublished` | 工作流下架 | workflow_id |

### AC7: 事件管理 API
**Given** 系统运行中
**When** 通过 API 管理事件
**Then** 提供以下端点：
- `GET /api/v1/events/types` — 列出所有事件类型
- `GET /api/v1/events/recent?limit=50` — 查看最近事件
- `GET /api/v1/events/stats` — 事件统计（发布量/消费量/积压量）

## Key Files

| 文件 | 操作 |
|------|------|
| `backend/app/engine/event_bus/__init__.py` | **新建** — 事件总线包 |
| `backend/app/engine/event_bus/event.py` | **新建** — 事件数据模型 |
| `backend/app/engine/event_bus/bus.py` | **新建** — 事件总线核心（发布/订阅/投递） |
| `backend/app/engine/event_bus/dead_letter.py` | **新建** — 死信队列管理 |
| `backend/app/engine/event_bus/backpressure.py` | **新建** — 背压保护 |
| `backend/app/engine/workflow/nodes/event.py` | **新建** — EventNodeExecutor |
| `backend/app/api/v1/events.py` | **新建** — 事件管理路由 |
| `backend/tests/engine/event_bus/test_bus.py` | **新建** — 事件总线测试 |
| `backend/tests/engine/event_bus/test_dead_letter.py` | **新建** — 死信队列测试 |

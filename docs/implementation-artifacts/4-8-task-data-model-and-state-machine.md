# Story 4.8: Task 数据模型与状态机

**Epic:** Epic 4 — DAG 工作流编排 + Task 运行时
**Status:** ready-for-dev
**Story ID:** 4-8
**Story Key:** 4-8-task-data-model-and-state-machine

## Story

As a 开发者，
I want 平台定义 Task 的完整数据模型、6 状态状态机和 CRUD API，
So that 所有 Task 有统一的生命周期管理基础，Workflow 执行引擎可基于这些 API 工作。

> ⚠️ **关键背景**：Task 是 Workflow 的运行时实例。与 Workflow 模板不同，Task 有执行状态、变量池、审计日志等运行时属性。
> Task 状态机设计为 6 状态，不包含前后台模式（已移除）。
> 新增 Task 时，需要同时创建 MongoDB Model + CRUD API + 状态机。

## Acceptance Criteria

### AC1: Task 数据模型
**Given** 平台定义了 Task MongoDB Model
**When** 检查其定义
**Then** 包含以下字段：
| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | ULID | 主键 |
| `workflow_id` | str | 关联的工作流模板 ID |
| `workflow_version` | str | 创建时绑定的模板版本快照 |
| `status` | TaskStatus | 当前状态 |
| `input` | dict | 输入参数 |
| `output` | dict \| None | 最终输出 |
| `variables` | dict | 变量池（运行时执行上下文） |
| `variable_snapshots` | list[dict] | 变量变更历史 |
| `call_chain` | list[str] | 调用链（追踪嵌套关系） |
| `parent_task_id` | str \| None | 父 Task ID（subflow 场景） |
| `created_by` | str | 创建者（user_id 或 agent_id） |
| `created_by_type` | str | "user" 或 "agent" |
| `version` | int | 乐观锁版本号，初始 1 |
| `timeline` | list[dict] | 执行时间线事件 |
| `error` | dict \| None | 错误信息 |
| `scheduled_at` | datetime \| None | 定时执行时间 |
| `created_at` | datetime | 创建时间 |
| `updated_at` | datetime | 更新时间 |

### AC2: 6 状态状态机
**Given** TaskStatus enum 已定义
**When** 检查状态定义
**Then** 包含 6 种状态：`pending`, `running`, `waiting_human`, `completed`, `failed`, `cancelled`
**And** 允许的合法转换如下：

| 当前状态 | 可转换到 |
|---------|---------|
| pending | running, cancelled |
| running | waiting_human, completed, failed |
| waiting_human | running, failed, cancelled |
| completed | (终态) |
| failed | (终态) |
| cancelled | (终态) |

**And** 非法转换抛出 `InvalidStateTransitionError`
**And** 终态（completed/failed/cancelled）不可再转换

### AC3: 乐观锁并发控制
**Given** Task 的 `version` 字段
**When** 更新 Task 状态
**Then** 使用 `findOneAndUpdate` 原子操作，条件包含 `version = current_version`
**And** 更新时 `version` 自增 1
**And** 并发冲突时返回 409 Conflict，提示"请重新获取最新状态后重试"

### AC4: Task CRUD API
**Given** 后端已部署
**When** 通过 API 创建 Task
**Then** `POST /api/v1/tasks` 接受 `workflow_id`, `input`, `scheduled_at`（可选）
**And** 返回包含 `id`, `status: pending`, `version: 1` 的完整 Task 对象
**And** 创建时校验 `workflow_id` 存在且已发布
**And** 校验 `input` 符合工作流的 `input_schema`

**Given** 查询 Task
**When** 调用 `GET /api/v1/tasks`
**Then** 支持分页（page/page_size），按状态筛选，按创建者筛选
**And** 返回列表包含基础信息（不包含 variables 大字段）

**Given** 获取 Task 详情
**When** 调用 `GET /api/v1/tasks/{id}`
**Then** 返回完整 Task 数据（含 variables 和 timeline）
**And** 404 时返回标准错误

**Given** 删除 Task
**When** 调用 `DELETE /api/v1/tasks/{id}`
**Then** 仅允许删除终态 Task（completed/failed/cancelled）
**And** 非终态 Task 返回 409 Conflict

### AC5: 执行时间线
**Given** Task 执行过程中
**When** 每次状态转换或关键事件发生
**Then** timeline 追加记录：`{timestamp, event_type, data, actor}`
**And** 事件类型包括：`created`, `started`, `node_start`, `node_complete`, `waiting_human`, `human_action`, `completed`, `failed`, `cancelled`, `intervened`
**And** timeline 按时间升序排列

### AC6: 审计日志
**Given** Task 状态变更
**When** 每次状态转换
**Then** 写入 audit_logs 集合：`{task_id, from_status, to_status, triggered_by, timestamp, version}`
**And** 审计日志不可修改，仅追加写入

## Key Files

| 文件 | 操作 |
|------|------|
| `backend/app/models/task.py` | **新建** — Task MongoDB Model + TaskStatus enum |
| `backend/app/schemas/task.py` | **新建** — Pydantic schemas（Create/Update/Response） |
| `backend/app/services/task_service.py` | **新建** — CRUD + 状态转换 + 乐观锁 |
| `backend/app/api/v1/tasks.py` | **新建** — Task 路由 |
| `backend/app/models/audit_log.py` | **新建** — 审计日志 Model |
| `backend/tests/api/test_tasks.py` | **新建** — API 测试 |
| `backend/tests/models/test_task.py` | **新建** — 状态机测试 |

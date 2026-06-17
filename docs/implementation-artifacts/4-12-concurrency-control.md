# Story 4.12: 并发控制与乐观锁

**Epic:** Epic 4 — DAG 工作流编排 + Task 运行时
**Status:** ready-for-dev
**Story ID:** 4-12
**Story Key:** 4-12-concurrency-control

## Story

As a 平台管理员，
I want 系统有全局和用户级并发上限，防止资源耗尽，
So that 单用户或单故障不影响其他用户的 Task 执行。

> ⚠️ **关键背景**：并发控制分为三个层面：
> 1. **全局限制** — 所有 Task 同时运行不超过 50 个
> 2. **用户限制** — 单用户同时运行不超过 5 个
> 3. **乐观锁** — Task 干预操作使用 version 字段防冲突
>
> 并发计数基于 Task 状态为 `running` 的数量。队列等待不占用并发槽位。

## Acceptance Criteria

### AC1: 全局并发限制
**Given** 系统配置全局并发上限（默认 50）
**When** 当前 `running` Task 数达到全局上限
**Then** 新的 Task 创建后进入 `pending` 状态（不直接转为 `running`）
**And** 等待队列中有一个 Task 完成（转为终态）后，自动从 pending 中调度一个进入 running
**And** 全局上限可通过环境变量 `GLOBAL_TASK_CONCURRENCY` 配置

### AC2: 用户级并发限制
**Given** 系统配置单用户并发上限（默认 5）
**When** 某用户的 `running` Task 数达到用户上限
**Then** 该用户的新 Task 创建后进入 `pending` 状态
**And** 等待该用户有 Task 完成后自动调度
**And** 用户上限可通过环境变量 `USER_TASK_CONCURRENCY` 配置

### AC3: 并发调度策略
**Given** 有多个 `pending` Task 在等待
**When** 一个 running Task 完成腾出槽位
**Then** 按 FIFO（先进先出）顺序调度
**And** 优先调度短 Task（预估执行时间短的先执行，如有预估字段）
**And** 同一用户的 Task 不超过用户上限时优先调度该用户的

### AC4: 乐观锁实现
**Given** Task 的 `version` 字段
**When** 执行干预操作（approve/reject/skip/cancel/retry/update_variables）
**Then** 请求必须携带 `version` 字段
**And** 后端使用 `findOneAndUpdate({_id, version: req.version}, {$set: {...}, $inc: {version: 1}})`
**And** 匹配结果为 null 时返回 409 Conflict
**And** 响应包含最新 `status` 和 `version`，客户端需更新本地缓存

### AC5: 并发边界情况
**Given** 多个干预请求同时到达
**When** 所有请求携带相同的 version
**Then** 仅第一个请求成功（MongoDB 原子操作保证）
**And** 其余请求返回 409
**And** Task 不会出现状态不一致

**Given** Task 在 running 状态下收到 cancel
**When** Node Executor 正在执行节点
**Then** 节点执行完成后检查 Task 状态
**And** 如检测到 cancelled，停止后续节点执行，Task 进入 cancelled
**And** 当前正在执行的节点允许完成（优雅停止）

### AC6: 并发监控
**Given** Task 并发数据
**When** 管理员查询
**Then** API 提供统计端点：`GET /api/v1/tasks/stats`
**And** 返回：`{global_running, global_pending, global_max, user_stats: [{user_id, running, max}]}`
**And** 统计仅返回当前非终态 Task 数据

## Key Files

| 文件 | 操作 |
|------|------|
| `backend/app/engine/workflow/concurrency.py` | **新建** — 并发控制管理器（槽位分配 + 调度） |
| `backend/app/services/task_service.py` | **改造** — 创建 Task 时检查并发限制 |
| `backend/app/api/v1/tasks.py` | **改造** — 添加 stats 端点 |
| `backend/app/core/config.py` | **改造** — 添加 GLOBAL_TASK_CONCURRENCY / USER_TASK_CONCURRENCY |
| `backend/tests/engine/workflow/test_concurrency.py` | **新建** — 并发控制测试 |

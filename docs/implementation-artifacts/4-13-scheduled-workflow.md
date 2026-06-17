# Story 4.13: 定时工作流

**Epic:** Epic 4 — DAG 工作流编排 + Task 运行时
**Status:** ready-for-dev
**Story ID:** 4-13
**Story Key:** 4-13-scheduled-workflow

## Story

As a 开发者，
I want 工作流可以按 cron 表达式定时触发执行，
So that 周期性任务（如每日报表、定时巡检）可自动化执行无需人工介入。

> ⚠️ **关键背景**：定时工作流依赖 Celery Beat 或 APScheduler 实现 cron 调度。
> Task model 已包含 `scheduled_at` 字段（Story 4-8），本 Story 在其上构建调度层。
> 调度器负责在指定时间创建工作流 Task 实例并触发执行。
>
> 执行失败时支持升级通知。系统层面保证 at-least-once 触发语义。

## Acceptance Criteria

### AC1: 定时规则数据模型
**Given** 开发者创建工作流时
**When** 配置定时触发
**Then** Workflow 模板支持 `schedule` 字段：
```yaml
schedule:
  enabled: true
  cron: "0 8 * * 1-5"  # 工作日早 8 点
  timezone: "Asia/Shanghai"
  input_template:        # 固定输入参数模板
    report_type: "daily"
    recipients: ["ops@company.com"]
  max_instances: 1       # 单次最多运行实例数（防止重叠）
  retry_on_fail: true
  notify_on_fail: true
```

### AC2: 调度器实现
**Given** 系统已启动
**When** 调度器初始化
**Then** 扫描所有已发布且 `schedule.enabled=true` 的工作流
**And** 为每个工作流注册 cron 调度任务
**And** 调度任务在指定时间触发时：
1. 使用 `input_template` 填充 input 参数
2. 调用 `task_service.create_task()` 创建 Task
3. Task 自动进入 running 状态执行
4. 记录调度触发日志

**Given** 调度器重启
**When** 系统恢复
**Then** 扫描数据库中的 Workflow 模板重新注册所有定时规则
**And** 不会重复触发已经执行过的任务（幂等性保证）

### AC3: 防重叠执行
**Given** 工作流配置了 `max_instances: 1`
**When** 上一次执行尚未完成（running/waiting_human 状态）
**Then** 新的定时触发被跳过（不创建新 Task）
**And** 记录调度跳过日志：`{workflow_id, trigger_time, reason: "previous_instance_running"}`

### AC4: 执行失败通知
**Given** 定时工作流执行失败
**When** Task 进入 `failed` 状态
**Then** 如果 `notify_on_fail=true`，发送通知给工作流的维护者
**And** 通知包含：`workflow_name`, `scheduled_time`, `task_id`, `error_message`
**And** 如果 `retry_on_fail=true`，自动重试最多 3 次（指数退避 30s/2m/5m）
**And** 超过重试次数后不再重试，通知管理员

### AC5: 定时规则管理 API
**Given** 定时规则已配置
**When** 通过 API 管理定时规则
**Then** 支持以下操作：
- `PATCH /api/v1/workflows/{id}/schedule` — 启用/禁用/修改定时规则
- `GET /api/v1/workflows/{id}/schedule` — 查看定时规则配置
- `GET /api/v1/workflows/scheduled` — 列出所有已配置定时的工作流
**And** 修改定时规则后调度器自动重新加载

### AC6: 定时 Task 标记
**Given** Task 由定时调度触发
**When** 查看 Task 详情
**Then** `created_by` 标记为 `system:scheduler`
**And** `scheduled_at` 字段记录触发时间
**And** 在 Task 管理面板中可区分手动创建和定时触发的 Task

## Key Files

| 文件 | 操作 |
|------|------|
| `backend/app/engine/workflow/scheduler.py` | **新建** — 基于 APScheduler/Celery Beat 的调度器 |
| `backend/app/services/workflow_schedule_service.py` | **新建** — 定时规则管理 |
| `backend/app/api/v1/workflows.py` | **改造** — 添加 schedule 路由 |
| `backend/app/models/workflow.py` | **改造** — 添加 schedule 字段 |
| `backend/tests/engine/workflow/test_scheduler.py` | **新建** — 调度器测试 |

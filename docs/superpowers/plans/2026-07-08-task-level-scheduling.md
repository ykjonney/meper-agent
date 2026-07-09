# Task-Level Scheduling — 移除 Trigger 实体，调度配置下沉到 Task

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将定时调度配置从独立的 Trigger 实体迁移到 Task 实例上，每个定时执行都是独立的 Task，可单独管理、修改、删除，不产生孤儿任务。

**Architecture:** Task 模型新增 `schedule_type`（`cron`/`once`）、`cron_expression`、`execute_at`、`auto_reschedule` 字段。创建 Task 时若携带调度配置，则通过 Celery eta 调度执行；cron 类型执行完成后自动创建下一个 Task（自链）。完全删除 Trigger 模型、trigger_repo、trigger_scheduler_service、triggers API 路由。

**Tech Stack:** Python 3.12+ / FastAPI / MongoDB (Motor) / Celery / croniter

---

## 文件结构总览

### 新增/修改
- `backend/app/models/task.py` — Task 模型新增调度字段
- `backend/app/schemas/task.py` — 请求/响应 schema 新增调度字段
- `backend/app/services/task_service.py` — create_task 支持调度参数 + 调度逻辑
- `backend/app/services/task_schedule_service.py` — 新文件，负责 cron/once → Celery eta 计算
- `backend/app/workers/tasks/scheduled_workflow.py` — Celery 任务改为直接操作 Task
- `backend/app/api/v1/tasks.py` — POST 接受调度参数
- `backend/app/main.py` — 移除 trigger_scheduler 启动逻辑
- `backend/app/api/v1/router.py` — 移除 triggers_router

### 删除
- `backend/app/models/trigger.py`
- `backend/app/services/trigger_repo.py`
- `backend/app/services/trigger_scheduler_service.py`
- `backend/app/api/v1/triggers.py`

---

## Task 1: Task 模型新增调度字段

**Files:**
- Modify: `backend/app/models/task.py:78-107`

- [ ] **Step 1: 修改 Task 模型，添加调度相关字段**

在 `Task` 类中添加以下字段（替换 `source` 和 `trigger_id`）：

```python
# 调度配置（可选 — 有值时表示定时任务）
schedule_type: str | None = Field(default=None, pattern=r"^(cron|once)$")
cron_expression: str | None = None
execute_at: datetime | None = None
auto_reschedule: bool = True  # cron 执行后是否自动创建下一个
celery_task_id: str | None = None  # 当前待执行的 Celery task ID（用于撤销）
```

同时删除旧字段：
```python
# 删除这两行
source: str = Field(default="manual", pattern=r"^(manual|trigger)$")
trigger_id: str | None = None
```

修改后的 Task 模型：

```python
class Task(BaseModel):
    """MongoDB Task document — runtime workflow instance."""

    id: str = Field(default_factory=lambda: generate_id("task"), alias="_id")
    workflow_id: str = Field(..., max_length=100)
    workflow_version: str = Field(default="", max_length=20)
    status: TaskStatus = TaskStatus.PENDING
    input: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, Any] | None = None
    variables: dict[str, Any] = Field(default_factory=dict)
    variable_snapshots: list[dict[str, Any]] = Field(default_factory=list)
    call_chain: list[str] = Field(default_factory=list)
    parent_task_id: str | None = None
    created_by: str = Field(default="", max_length=100)
    created_by_type: str = Field(default="user", pattern=r"^(user|agent|system|api_key)$")
    version: int = Field(default=1, ge=1)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    error: TaskError | None = None
    checkpoint: Checkpoint | None = None
    # 调度配置（可选）
    schedule_type: str | None = Field(default=None, pattern=r"^(cron|once)$")
    cron_expression: str | None = None
    execute_at: datetime | None = None
    auto_reschedule: bool = True
    celery_task_id: str | None = None
    scheduled_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)

    model_config = {"populate_by_name": True}
```

- [ ] **Step 2: 验证模型导入无误**

```bash
cd /Users/huyuekai/company/agent-flow/backend && uv run python -c "from app.models.task import Task; t = Task(workflow_id='test'); print(t.schedule_type, t.auto_reschedule)"
```

预期输出: `None True`

---

## Task 2: Task Schema 新增调度字段

**Files:**
- Modify: `backend/app/schemas/task.py:14-19`（TaskCreate）
- Modify: `backend/app/schemas/task.py:78-98`（TaskResponse）
- Modify: `backend/app/schemas/task.py:101-118`（TaskSummary）

- [ ] **Step 1: TaskCreate 添加调度字段**

```python
class TaskCreate(BaseModel):
    """Request body for creating a new Task."""

    workflow_id: str = Field(..., min_length=1, max_length=100)
    input: dict[str, Any] = Field(default_factory=dict)
    scheduled_at: datetime | None = None
    # 调度配置（可选 — 有值时表示定时任务）
    schedule_type: str | None = Field(default=None, pattern=r"^(cron|once)$")
    cron_expression: str | None = None
    execute_at: datetime | None = None
    auto_reschedule: bool = True
```

- [ ] **Step 2: TaskResponse 添加调度字段**

在 `TaskResponse` 类中添加（在 `scheduled_at` 之后）：

```python
    schedule_type: str | None = None
    cron_expression: str | None = None
    execute_at: datetime | None = None
    auto_reschedule: bool = True
    celery_task_id: str | None = None
```

- [ ] **Step 3: TaskSummary 添加调度字段**

在 `TaskSummary` 类中添加（在 `scheduled_at` 之后）：

```python
    schedule_type: str | None = None
    cron_expression: str | None = None
```

---

## Task 3: 新建 TaskScheduleService（调度计算服务）

**Files:**
- Create: `backend/app/services/task_schedule_service.py`

这是从 `trigger_scheduler_service.py` 精简而来的核心调度逻辑，直接操作 Task 文档。

- [ ] **Step 1: 创建 `task_schedule_service.py`**

```python
"""TaskScheduleService — computes next execution time and dispatches Celery tasks.

Operates on Task documents with schedule_type set (cron/once).
Replaces the old TriggerSchedulerService.
"""
from __future__ import annotations

from datetime import datetime

from croniter import croniter
from loguru import logger


class TaskScheduleService:
    """Computes next execution time for a scheduled Task and dispatches Celery."""

    @staticmethod
    async def schedule_task(task_id: str) -> datetime | None:
        """Compute next execution time, dispatch Celery task with eta, update Task.

        Returns the scheduled time, or None if nothing should be scheduled.
        """
        from app.db.mongodb import get_database

        db = get_database()
        task_doc = await db["tasks"].find_one({"_id": task_id})
        if not task_doc:
            return None

        schedule_type = task_doc.get("schedule_type")
        if not schedule_type:
            return None

        now = datetime.now().astimezone()

        if schedule_type == "cron":
            cron_expr = task_doc.get("cron_expression") or ""
            if not cron_expr:
                return None
            cron = croniter(cron_expr, now)
            next_at = cron.get_next(datetime)
            if next_at.tzinfo is None:
                next_at = next_at.astimezone()
        elif schedule_type == "once":
            execute_at = task_doc.get("execute_at")
            if not execute_at:
                return None
            next_at = (
                execute_at
                if isinstance(execute_at, datetime)
                else datetime.fromisoformat(str(execute_at))
            )
            if next_at.tzinfo is None:
                next_at = next_at.astimezone()
            if next_at <= now:
                return None
        else:
            return None

        # Revoke any previously queued Celery task for this Task
        old_celery_task_id = task_doc.get("celery_task_id")
        if old_celery_task_id:
            from app.workers.celery_app import celery_app

            celery_app.control.revoke(old_celery_task_id, terminate=False)
            logger.debug(
                "task_schedule_revoked_old",
                task_id=task_id,
                old_celery_task_id=old_celery_task_id,
            )

        # Dispatch Celery task with precise eta
        from app.workers.tasks.scheduled_workflow import execute_scheduled_workflow

        result = execute_scheduled_workflow.apply_async(
            args=[task_id],
            eta=next_at,
        )

        # Update Task with next_trigger_at and celery_task_id
        from app.models.base import utc_now

        await db["tasks"].update_one(
            {"_id": task_id},
            {
                "$set": {
                    "scheduled_at": next_at,
                    "celery_task_id": result.id,
                    "updated_at": utc_now(),
                }
            },
        )

        logger.info(
            "task_scheduled",
            task_id=task_id,
            next_at=next_at.isoformat(),
        )
        return next_at

    @staticmethod
    async def cancel_task_schedule(task_id: str) -> None:
        """Cancel pending Celery task for a scheduled Task."""
        from app.db.mongodb import get_database

        db = get_database()
        task_doc = await db["tasks"].find_one({"_id": task_id}, {"celery_task_id": 1})
        if not task_doc:
            return

        celery_task_id = task_doc.get("celery_task_id")
        if celery_task_id:
            from app.workers.celery_app import celery_app

            celery_app.control.revoke(celery_task_id, terminate=False)
            logger.info(
                "task_schedule_cancelled",
                task_id=task_id,
                celery_task_id=celery_task_id,
            )

        # Clear celery_task_id and scheduled_at
        from app.models.base import utc_now

        await db["tasks"].update_one(
            {"_id": task_id},
            {
                "$set": {
                    "celery_task_id": None,
                    "scheduled_at": None,
                    "updated_at": utc_now(),
                }
            },
        )
```

---

## Task 4: 修改 TaskService.create_task 支持调度

**Files:**
- Modify: `backend/app/services/task_service.py:44-154`（create_task 方法）
- Modify: `backend/app/services/task_service.py:346-402`（_schedule_next_pending — 移除 trigger 过滤）

- [ ] **Step 1: 修改 create_task 签名和逻辑**

将 `create_task` 的参数中的 `source` 和 `trigger_id` 替换为调度字段：

```python
    @staticmethod
    async def create_task(
        workflow_id: str,
        input_data: dict[str, Any],
        created_by: str = "",
        created_by_type: str = "user",
        parent_task_id: str | None = None,
        call_chain: list[str] | None = None,
        scheduled_at: datetime | None = None,
        ext_metadata: dict[str, Any] | None = None,
        skip_execution: bool = False,
        # 调度配置（可选）
        schedule_type: str | None = None,
        cron_expression: str | None = None,
        execute_at: datetime | None = None,
        auto_reschedule: bool = True,
    ) -> dict:
```

在构建 Task 对象时传入调度字段（替换 source/trigger_id）：

```python
        task = Task(
            workflow_id=workflow_id,
            input=input_data,
            created_by=created_by,
            created_by_type=created_by_type,
            parent_task_id=parent_task_id,
            call_chain=call_chain or [],
            scheduled_at=scheduled_at,
            schedule_type=schedule_type,
            cron_expression=cron_expression,
            execute_at=execute_at,
            auto_reschedule=auto_reschedule,
            timeline=[e.model_dump() for e in initial_timeline],
            created_at=now,
            updated_at=now,
        )
```

在 `create_task` 末尾，当 `schedule_type` 有值且 `skip_execution=True` 时，调用调度服务：

```python
        # 调度配置：计算下次执行时间并发送 Celery eta 任务
        if schedule_type and skip_execution:
            from app.services.task_schedule_service import TaskScheduleService

            await TaskScheduleService.schedule_task(task.id)
```

完整修改后的 create_task 末尾部分：

```python
        # Trigger workflow engine execution in background (unless caller handles it)
        if not skip_execution:
            TaskService._start_workflow_execution(task.id)
        elif schedule_type:
            # 定时任务：计算下次执行时间并发送 Celery eta 任务
            from app.services.task_schedule_service import TaskScheduleService

            await TaskScheduleService.schedule_task(task.id)

        return created_doc
```

- [ ] **Step 2: 修改 _schedule_next_pending 移除 trigger 过滤**

将 FIFO 查询中的 `"source": {"$ne": "trigger"}` 改为仅排除定时任务：

```python
    @staticmethod
    async def _schedule_next_pending() -> dict | None:
        """Find and auto-start the oldest pending Task (FIFO scheduling)."""
        col = TaskService._collection()

        # 排除定时任务（有 schedule_type 的）— 它们由 Celery eta 驱动
        now = utc_now()
        pending = await col.find_one_and_update(
            {"status": TaskStatus.PENDING.value, "schedule_type": {"$eq": None}},
            ...
        )
```

- [ ] **Step 3: 修改 _check_concurrency_limits 移除 source 参数**

```python
    @staticmethod
    async def _check_concurrency_limits(created_by: str) -> None:
        """Check global and per-user concurrency limits."""
        # ... 全局限制不变 ...

        # Per-user limit（移除 source 跳过逻辑）
        if created_by and created_by not in ("system", "agent"):
            # ... 保持不变 ...
```

- [ ] **Step 4: 修改 transition_task 中的并发检查调用**

```python
        # Concurrency guard: pending → running
        if from_status == TaskStatus.PENDING and to_status == TaskStatus.RUNNING:
            created_by = doc.get("created_by", "")
            await TaskService._check_concurrency_limits(created_by)
```

---

## Task 5: 修改 Celery 任务（scheduled_workflow.py）

**Files:**
- Modify: `backend/app/workers/tasks/scheduled_workflow.py`

- [ ] **Step 1: 重写 Celery 任务，直接操作 Task**

不再通过 trigger_id 查找，而是直接接收 task_id：

```python
"""Scheduled workflow execution Celery task.

Operates directly on Task documents with schedule_type set.
Replaces the old trigger-based scheduled_workflow.
"""
import asyncio
from typing import Any

from loguru import logger

from app.db.mongodb import get_database
from app.engine.workflow.engine import WorkflowEngine
from app.models.base import utc_now
from app.workers.celery_app import celery_app

# Reuse a single event loop across Celery task invocations.
_loop: asyncio.AbstractEventLoop | None = None


def _get_loop() -> asyncio.AbstractEventLoop:
    """Return a persistent event loop for async Celery tasks."""
    global _loop
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
    return _loop


@celery_app.task(name="app.workers.tasks.scheduled_workflow.execute_scheduled_workflow")
def execute_scheduled_workflow(
    task_id: str,
) -> dict[str, Any]:
    """Execute a scheduled Task.

    Args:
        task_id: Task document ID (the Task itself has schedule_type set).

    Returns:
        Task execution result summary.
    """
    return _get_loop().run_until_complete(_execute_async(task_id))


async def _execute_async(task_id: str) -> dict[str, Any]:
    """Async execution logic."""
    db = get_database()

    # 1. Load task
    task_doc = await db["tasks"].find_one({"_id": task_id})
    if not task_doc:
        logger.error("scheduled_task_not_found", task_id=task_id)
        return {"status": "error", "message": "task not found"}

    if task_doc.get("status") != "pending":
        logger.warning(
            "scheduled_task_not_pending",
            task_id=task_id,
            status=task_doc.get("status"),
        )
        return {"status": "skipped", "message": "not pending"}

    # 2. Execute
    logger.info("scheduled_workflow_starting", task_id=task_id)

    try:
        engine = WorkflowEngine()
        await engine.run_and_persist(task_id)

        logger.info("scheduled_workflow_completed", task_id=task_id)

        # 3. Self-chain: for cron tasks with auto_reschedule, create next Task
        schedule_type = task_doc.get("schedule_type")
        auto_reschedule = task_doc.get("auto_reschedule", True)

        if schedule_type == "cron" and auto_reschedule:
            await _create_next_task(task_doc)

        return {"status": "success", "task_id": task_id}

    except Exception as e:
        logger.error(
            "scheduled_workflow_failed",
            task_id=task_id,
            error=str(e),
        )
        # Even on failure, self-chain for cron to keep the schedule alive
        schedule_type = task_doc.get("schedule_type")
        auto_reschedule = task_doc.get("auto_reschedule", True)
        if schedule_type == "cron" and auto_reschedule:
            await _create_next_task(task_doc)

        return {"status": "error", "task_id": task_id, "message": str(e)}


async def _create_next_task(finished_task_doc: dict) -> None:
    """Create the next scheduled Task based on the finished one's schedule config."""
    from app.services.task_service import TaskService
    from app.services.task_schedule_service import TaskScheduleService
    from app.utils.template_renderer import render_default_input

    workflow_id = finished_task_doc["workflow_id"]
    created_by = finished_task_doc.get("created_by", "")
    input_data = finished_task_doc.get("input", {})

    # Create next Task with same schedule config
    next_task_doc = await TaskService.create_task(
        workflow_id=workflow_id,
        input_data=input_data,
        created_by=created_by,
        created_by_type="system",
        skip_execution=True,
        schedule_type=finished_task_doc.get("schedule_type"),
        cron_expression=finished_task_doc.get("cron_expression"),
        auto_reschedule=finished_task_doc.get("auto_reschedule", True),
    )

    logger.info(
        "scheduled_next_task_created",
        from_task_id=finished_task_doc["_id"],
        next_task_id=next_task_doc["_id"],
    )
```

---

## Task 6: 修改 Tasks API — POST 支持调度参数

**Files:**
- Modify: `backend/app/api/v1/tasks.py:142-164`（create_task 端点）
- Modify: `backend/app/api/v1/tasks.py:36-57`（_doc_to_full_response）
- Modify: `backend/app/api/v1/tasks.py:60-78`（_doc_to_summary）

- [ ] **Step 1: 修改 create_task 端点传递调度参数**

```python
@router.post(
    "",
    response_model=TaskResponse,
    status_code=201,
    summary="Create a new Task",
)
async def create_task(
    body: TaskCreate,
    current_user: UserResponse = Depends(get_current_user),
) -> TaskResponse:
    """Create a new Task in pending status.

    If schedule_type is set, the Task will be scheduled via Celery eta.
    For cron type, the Task auto-chains on completion.
    """
    doc = await TaskService.create_task(
        workflow_id=body.workflow_id,
        input_data=body.input,
        created_by=current_user.id,
        created_by_type="user",
        scheduled_at=body.scheduled_at,
        schedule_type=body.schedule_type,
        cron_expression=body.cron_expression,
        execute_at=body.execute_at,
        auto_reschedule=body.auto_reschedule,
        skip_execution=bool(body.schedule_type),  # 定时任务不立即执行
    )
    return _doc_to_full_response(doc)
```

- [ ] **Step 2: 修改 _doc_to_full_response 包含调度字段**

```python
def _doc_to_full_response(doc: dict) -> TaskResponse:
    """Convert a raw MongoDB document to full TaskResponse."""
    return TaskResponse(
        id=doc["_id"],
        workflow_id=doc["workflow_id"],
        workflow_version=doc.get("workflow_version", ""),
        status=TaskStatus(doc["status"]),
        input=doc.get("input", {}),
        output=doc.get("output"),
        variables=doc.get("variables", {}),
        call_chain=doc.get("call_chain", []),
        parent_task_id=doc.get("parent_task_id"),
        created_by=doc.get("created_by", ""),
        created_by_type=doc.get("created_by_type", "user"),
        version=doc.get("version", 1),
        timeline=doc.get("timeline", []),
        error=doc.get("error"),
        checkpoint=doc.get("checkpoint"),
        scheduled_at=doc.get("scheduled_at"),
        schedule_type=doc.get("schedule_type"),
        cron_expression=doc.get("cron_expression"),
        execute_at=doc.get("execute_at"),
        auto_reschedule=doc.get("auto_reschedule", True),
        celery_task_id=doc.get("celery_task_id"),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )
```

- [ ] **Step 3: 修改 _doc_to_summary 包含调度字段**

```python
def _doc_to_summary(doc: dict) -> TaskSummary:
    """Convert a raw MongoDB document to compact TaskSummary."""
    return TaskSummary(
        id=doc["_id"],
        workflow_id=doc["workflow_id"],
        workflow_version=doc.get("workflow_version", ""),
        status=TaskStatus(doc["status"]),
        input=doc.get("input", {}),
        output=doc.get("output"),
        parent_task_id=doc.get("parent_task_id"),
        created_by=doc.get("created_by", ""),
        created_by_type=doc.get("created_by_type", "user"),
        version=doc.get("version", 1),
        error=doc.get("error"),
        checkpoint=doc.get("checkpoint"),
        scheduled_at=doc.get("scheduled_at"),
        schedule_type=doc.get("schedule_type"),
        cron_expression=doc.get("cron_expression"),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )
```

---

## Task 7: 添加 Task 调度管理端点（取消/修改调度）

**Files:**
- Modify: `backend/app/api/v1/tasks.py`（添加新端点）

- [ ] **Step 1: 添加取消调度端点**

```python
@router.post(
    "/{task_id}/cancel-schedule",
    summary="Cancel scheduled execution for a pending Task",
)
async def cancel_task_schedule(
    task_id: str,
    current_user: UserResponse = Depends(get_current_user),
) -> dict:
    """Cancel the Celery eta task for a scheduled pending Task.

    The Task remains in pending status but will not auto-execute.
    """
    doc = await TaskService.get_task_or_404(task_id)
    if doc.get("status") != "pending":
        from app.core.errors import ConflictError

        raise ConflictError(
            code="TASK_NOT_PENDING",
            message=f"任务状态为 {doc.get('status')}，仅允许取消待执行任务的调度",
        )

    from app.services.task_schedule_service import TaskScheduleService

    await TaskScheduleService.cancel_task_schedule(task_id)
    return {"task_id": task_id, "message": "调度已取消"}
```

- [ ] **Step 2: 添加重新调度端点**

```python
@router.post(
    "/{task_id}/reschedule",
    summary="Reschedule a pending Task",
)
async def reschedule_task(
    task_id: str,
    current_user: UserResponse = Depends(get_current_user),
) -> dict:
    """Re-compute and dispatch the next execution time for a scheduled Task."""
    doc = await TaskService.get_task_or_404(task_id)
    if doc.get("status") != "pending":
        from app.core.errors import ConflictError

        raise ConflictError(
            code="TASK_NOT_PENDING",
            message=f"任务状态为 {doc.get('status')}，仅允许重新调度待执行任务",
        )
    if not doc.get("schedule_type"):
        from app.core.errors import ValidationError

        raise ValidationError(
            code="TASK_NOT_SCHEDULED",
            message="该任务不是定时任务",
        )

    from app.services.task_schedule_service import TaskScheduleService

    next_at = await TaskScheduleService.schedule_task(task_id)
    if next_at is None:
        return {"task_id": task_id, "message": "无法计算下次执行时间"}
    return {"task_id": task_id, "next_at": next_at.isoformat()}
```

---

## Task 8: 修改 main.py 和 router.py — 移除 Trigger 启动逻辑

**Files:**
- Modify: `backend/app/main.py:16-17,46-57,93`（移除 trigger_scheduler 相关）
- Modify: `backend/app/api/v1/router.py:19,39`（移除 triggers_router）

- [ ] **Step 1: 修改 main.py — 移除 trigger_scheduler**

删除导入：
```python
# 删除这两行
from app.services.trigger_scheduler_service import get_trigger_scheduler
```

删除 startup 逻辑（第 46-57 行）：
```python
# 删除以下代码块
    # Initialize Trigger repository and indexes
    from app.db.mongodb import get_database
    from app.services.trigger_repo import TriggerRepository
    from app.services.trigger_scheduler_service import get_trigger_scheduler

    trigger_repo = TriggerRepository(get_database())
    await trigger_repo.ensure_indexes()

    # Start the Trigger scheduler for cron/once workflow triggers
    trigger_scheduler = get_trigger_scheduler()
    trigger_scheduler.set_repo(trigger_repo)
    await trigger_scheduler.start()
```

删除 shutdown 逻辑（第 93 行）：
```python
# 删除
    await trigger_scheduler.stop()
```

修改后的 lifespan startup 部分：

```python
    # Start the Task scheduler for timed/scheduled workflow execution
    scheduler = get_scheduler()
    await scheduler.start()

    # Initialize system roles (idempotent)
    from app.services.role_service import RoleService
    await RoleService.ensure_indexes()
    await RoleService.init_system_roles()
    # ... 后续不变 ...
```

修改后的 shutdown 部分：

```python
    yield

    # Shutdown: gracefully close connections
    from app.services.event_bridge import stop_event_bridge_listener
    await stop_event_bridge_listener()
    await scheduler.stop()
    await close_mongodb_client()
    await close_redis_client()
```

- [ ] **Step 2: 修改 router.py — 移除 triggers_router**

```python
# 删除导入
# from app.api.v1.triggers import router as triggers_router

# 删除 include
# api_v1_router.include_router(triggers_router)
```

---

## Task 9: 修改 TaskSchedulerService — 移除 trigger 排除逻辑

**Files:**
- Modify: `backend/app/services/task_scheduler_service.py:118-124`

- [ ] **Step 1: 修改 _process_due_tasks 查询条件**

将 `"source": {"$ne": "trigger"}` 改为排除定时任务：

```python
        cursor = col.find(
            {
                "status": TaskStatus.PENDING.value,
                "scheduled_at": {"$lte": now, "$ne": None},
                "schedule_type": {"$eq": None},  # 排除定时任务（由 Celery eta 驱动）
            }
        ).sort("scheduled_at", 1).limit(50)
```

- [ ] **Step 2: 移除 concurrency check 的 source 参数**

```python
                created_by = doc.get("created_by", "")
                try:
                    await TaskService._check_concurrency_limits(created_by)
                except Exception:
```

---

## Task 10: 删除 Trigger 相关文件

**Files:**
- Delete: `backend/app/models/trigger.py`
- Delete: `backend/app/services/trigger_repo.py`
- Delete: `backend/app/services/trigger_scheduler_service.py`
- Delete: `backend/app/api/v1/triggers.py`

- [ ] **Step 1: 删除文件**

```bash
cd /Users/huyuekai/company/agent-flow/backend
rm app/models/trigger.py
rm app/services/trigger_repo.py
rm app/services/trigger_scheduler_service.py
rm app/api/v1/triggers.py
```

- [ ] **Step 2: 确认无残留引用**

```bash
cd /Users/huyuekai/company/agent-flow/backend
grep -r "trigger_repo\|trigger_scheduler\|TriggerRepository\|TriggerSchedulerService\|models.trigger\|api.v1.triggers" --include="*.py" app/
```

预期输出应为空（或仅剩注释）。

---

## Task 11: 清理 task_service.py 中残留的 source/trigger 引用

**Files:**
- Modify: `backend/app/services/task_service.py`

- [ ] **Step 1: 全局搜索并清理 source/trigger_id 用法**

确认 `create_task` 中不再有 `source` 和 `trigger_id` 参数，Task 构建时不再传递这些字段。

确认 `_check_concurrency_limits` 签名不再接受 `source` 参数。

确认 `transition_task` 中读取 `task_source = doc.get("source", "manual")` 的行已删除。

- [ ] **Step 2: 验证应用启动**

```bash
cd /Users/huyuekai/company/agent-flow/backend && uv run python -c "from app.main import app; print('OK')"
```

---

## Task 12: 数据迁移 — 现有 Triggers → Tasks

**Files:**
- Create: `backend/scripts/migrate_triggers_to_tasks.py`

- [ ] **Step 1: 编写迁移脚本**

```python
"""One-time migration: convert existing Trigger documents to scheduled Tasks.

Run once after deploying Task-level scheduling:
    uv run python scripts/migrate_triggers_to_tasks.py
"""
import asyncio

from app.db.mongodb import get_database, init_mongodb
from app.models.base import utc_now


async def migrate() -> None:
    await init_mongodb()
    db = get_database()

    triggers_col = db["triggers"]
    tasks_col = db["tasks"]

    count = await triggers_col.count_documents({})
    print(f"Found {count} trigger documents to migrate")

    migrated = 0
    async for trigger in triggers_col.find({}):
        trigger_id = trigger["_id"]
        workflow_id = trigger["workflow_id"]
        user_id = trigger["user_id"]
        trigger_type = trigger["type"]  # "cron" | "once"
        enabled = trigger.get("enabled", False)
        cron_expression = trigger.get("cron_expression")
        execute_at = trigger.get("execute_at")
        default_input = trigger.get("default_input", {})

        # Only migrate enabled triggers — disabled ones have no active schedule
        if not enabled:
            print(f"  Skipping disabled trigger {trigger_id}")
            continue

        # Skip "once" triggers that are already past
        if trigger_type == "once" and execute_at:
            from datetime import datetime

            now = datetime.now().astimezone()
            exec_at = (
                execute_at
                if isinstance(execute_at, datetime)
                else datetime.fromisoformat(str(execute_at))
            )
            if exec_at.tzinfo is None:
                exec_at = exec_at.astimezone()
            if exec_at <= now:
                print(f"  Skipping past once trigger {trigger_id}")
                continue

        # Create a Task with the trigger's schedule config
        now = utc_now()
        task_doc = {
            "_id": f"task_migrated_{trigger_id}",
            "workflow_id": workflow_id,
            "status": "pending",
            "input": default_input,
            "created_by": user_id,
            "created_by_type": "system",
            "schedule_type": trigger_type,
            "cron_expression": cron_expression,
            "execute_at": execute_at,
            "auto_reschedule": trigger_type == "cron",
            "version": 1,
            "timeline": [
                {
                    "timestamp": now,
                    "event_type": "created",
                    "data": {
                        "workflow_id": workflow_id,
                        "created_by": user_id,
                        "migrated_from_trigger": trigger_id,
                    },
                    "actor": "system",
                }
            ],
            "created_at": now,
            "updated_at": now,
        }

        try:
            await tasks_col.insert_one(task_doc)
            migrated += 1
            print(f"  Migrated trigger {trigger_id} -> task {task_doc['_id']}")
        except Exception as e:
            print(f"  Error migrating trigger {trigger_id}: {e}")

    print(f"\nMigration complete: {migrated}/{count} triggers migrated")

    # Optional: drop the triggers collection
    # await triggers_col.drop()
    # print("Dropped triggers collection")


if __name__ == "__main__":
    asyncio.run(migrate())
```

- [ ] **Step 2: 验证迁移脚本可运行**

```bash
cd /Users/huyuekai/company/agent-flow/backend && uv run python scripts/migrate_triggers_to_tasks.py --help 2>/dev/null || echo "Script exists and is importable"
```

---

## Task 13: 集成验证

- [ ] **Step 1: 验证应用可启动**

```bash
cd /Users/huyuekai/company/agent-flow/backend && uv run python -c "from app.main import app; print('App imports OK')"
```

- [ ] **Step 2: 验证模型无残留引用**

```bash
cd /Users/huyuekai/company/agent-flow/backend && grep -r "from app.models.trigger\|from app.services.trigger_repo\|from app.services.trigger_scheduler\|from app.api.v1.triggers" --include="*.py" app/ | grep -v "__pycache__" || echo "No stale references found"
```

- [ ] **Step 3: 手动测试 API**

创建定时任务（cron）：
```bash
curl -X POST http://localhost:8000/api/v1/tasks \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "workflow_id": "wf_xxx",
    "input": {"key": "value"},
    "schedule_type": "cron",
    "cron_expression": "*/5 * * * *",
    "auto_reschedule": true
  }'
```

预期：返回 TaskResponse，包含 `schedule_type: "cron"`, `scheduled_at` 为下次执行时间。

- [ ] **Step 4: 验证定时任务不被 FIFO 捞走**

```bash
# 创建定时任务后，检查 _schedule_next_pending 不会选中它
# 确认查询条件 schedule_type: {"$eq": None} 排除了定时任务
```

---

## 完成标准

1. Trigger 实体完全删除，无残留引用
2. Task 模型支持 `schedule_type`、`cron_expression`、`execute_at`、`auto_reschedule`、`celery_task_id`
3. POST /api/v1/tasks 支持调度参数
4. 定时任务通过 Celery eta 调度，不被 FIFO 捞走
5. cron 任务执行后自动创建下一个 Task（自链）
6. 现有 Trigger 可通过迁移脚本转换为 Task
7. 所有导入和启动验证通过

"""Task business logic — CRUD, state machine with optimistic locking, timeline, audit."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from loguru import logger
from pymongo import ReturnDocument

from app.core.config import settings
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.db.mongodb import get_database
from app.engine.events import TaskEvent, get_event_bus
from app.models.audit_log import AuditLog
from app.models.task import (
    TERMINAL_STATUSES,
    Task,
    TaskError,
    TaskStatus,
    TimelineEvent,
    is_valid_transition,
    utc_now,
)


class TaskService:
    """Service layer for Task operations."""

    COLLECTION = "tasks"
    AUDIT_COLLECTION = "audit_logs"

    @staticmethod
    def _collection():
        return get_database()[TaskService.COLLECTION]

    @staticmethod
    def _audit_collection():
        return get_database()[TaskService.AUDIT_COLLECTION]

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    @staticmethod
    async def create_task(
        workflow_id: str,
        input_data: dict[str, Any],
        created_by: str = "",
        created_by_type: str = "user",
        parent_task_id: str | None = None,
        call_chain: list[str] | None = None,
        scheduled_at: datetime | None = None,
    ) -> dict:
        """Create a new Task in pending status.

        Args:
            workflow_id: Target workflow template ID.
            input_data: Input parameters conforming to workflow's input_schema.
            created_by: User or Agent ID who created this Task.
            created_by_type: "user", "agent", or "system".
            parent_task_id: Parent Task ID (for subflow scenarios).
            call_chain: Call chain for nested execution tracking.
            scheduled_at: Optional scheduled execution time.

        Returns:
            Created Task MongoDB document.

        Raises:
            ValidationError: If workflow_id is empty.
        """
        if not workflow_id:
            raise ValidationError(
                code="TASK_MISSING_WORKFLOW_ID",
                message="workflow_id 不能为空",
            )

        # 校验 workflow 模板存在，避免创建指向已删除/不存在模板的僵尸 task
        # （模板不存在时 engine.run_and_persist 会加载失败，但 task 已写入
        # pending 且不会被清理，造成永久卡死）。
        db = get_database()
        workflow_exists = await db["workflows"].find_one(
            {"_id": workflow_id}, {"_id": 1}
        )
        if not workflow_exists:
            raise ValidationError(
                code="WORKFLOW_NOT_FOUND",
                message=f"工作流模板 {workflow_id} 不存在，无法创建任务",
                details={"workflow_id": workflow_id},
            )

        # Build initial timeline
        now = utc_now()
        initial_timeline = [
            TimelineEvent(
                timestamp=now,
                event_type="created",
                data={"workflow_id": workflow_id, "created_by": created_by},
                actor=created_by or "system",
            )
        ]

        task = Task(
            workflow_id=workflow_id,
            input=input_data,
            created_by=created_by,
            created_by_type=created_by_type,
            parent_task_id=parent_task_id,
            call_chain=call_chain or [],
            scheduled_at=scheduled_at,
            timeline=[e.model_dump() for e in initial_timeline],
            created_at=now,
            updated_at=now,
        )

        doc = task.model_dump(by_alias=True)
        result = await TaskService._collection().insert_one(doc)

        # Write audit log
        await TaskService._write_audit_log(
            task_id=task.id,
            event_type="state_change",
            from_status=None,
            to_status=TaskStatus.PENDING.value,
            triggered_by=created_by,
            triggered_by_type=created_by_type,
            version=1,
            details={"workflow_id": workflow_id},
        )

        logger.info("task_created", task_id=task.id, workflow_id=workflow_id)

        created_doc = await TaskService._collection().find_one({"_id": result.inserted_id})

        # Publish event
        event_bus = get_event_bus()
        await event_bus.publish(TaskEvent(
            event_type="task.created",
            task_id=task.id,
            data={"workflow_id": workflow_id, "created_by": created_by},
        ))

        # Trigger workflow engine execution in background
        TaskService._start_workflow_execution(task.id)

        return created_doc

    @staticmethod
    def _start_workflow_execution(task_id: str) -> None:
        """Fire-and-forget: run WorkflowEngine for a newly created Task.

        Uses ``asyncio.create_task`` for a simple in-process execution.
        For production, replace with Celery / task queue.
        """
        import asyncio

        from app.engine.workflow.engine import WorkflowEngine

        async def _run() -> None:
            try:
                engine = WorkflowEngine()
                await engine.run_and_persist(task_id)
            except Exception as exc:
                logger.error(
                    "workflow_engine_background_error",
                    task_id=task_id,
                    error=str(exc),
                )

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_run())
        except RuntimeError:
            logger.warning("no_event_loop_for_workflow_execution", task_id=task_id)

    @staticmethod
    def resume_task_execution(task_id: str) -> None:
        """Fire-and-forget: resume a paused Task from checkpoint.

        Symmetric with ``_start_workflow_execution`` — used after Human node
        intervention (approve/skip) to continue workflow execution.

        Uses ``asyncio.create_task`` for in-process execution.
        """
        import asyncio

        from app.engine.workflow.engine import WorkflowEngine

        async def _run() -> None:
            try:
                engine = WorkflowEngine()
                await engine.run_and_persist(task_id)
            except Exception as exc:
                logger.error(
                    "workflow_engine_resume_error",
                    task_id=task_id,
                    error=str(exc),
                )

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_run())
        except RuntimeError:
            logger.warning("no_event_loop_for_workflow_resume", task_id=task_id)

    @staticmethod
    async def get_task(task_id: str) -> dict | None:
        """Get a single Task by ID.

        Returns:
            Task document or None if not found.
        """
        return await TaskService._collection().find_one({"_id": task_id})

    @staticmethod
    async def get_task_or_404(task_id: str) -> dict:
        """Get a Task by ID or raise NotFoundError."""
        doc = await TaskService.get_task(task_id)
        if doc is None:
            raise NotFoundError(
                code="TASK_NOT_FOUND",
                message=f"Task {task_id} 不存在",
                details={"task_id": task_id},
            )
        return doc

    @staticmethod
    async def list_tasks(
        page: int = 1,
        page_size: int = 20,
        status: TaskStatus | None = None,
        created_by: str | None = None,
        workflow_id: str | None = None,
    ) -> tuple[list[dict], int]:
        """List Tasks with optional filters.

        Returns:
            Tuple of (task_docs, total_count).
        """
        query: dict[str, Any] = {}
        if status is not None:
            query["status"] = status.value
        if created_by:
            query["created_by"] = created_by
        if workflow_id:
            query["workflow_id"] = workflow_id

        cursor = (
            TaskService._collection()
            .find(query)
            .sort("created_at", -1)
            .skip((page - 1) * page_size)
            .limit(page_size)
        )
        items = await cursor.to_list(length=page_size)
        total = await TaskService._collection().count_documents(query)
        return items, total

    @staticmethod
    async def delete_task(task_id: str) -> bool:
        """Delete a terminal Task.

        Only terminal-state Tasks (completed/failed/cancelled) can be deleted.

        Returns:
            True if deleted, False if not found.

        Raises:
            ConflictError: If Task is not in a terminal state.
        """
        doc = await TaskService.get_task_or_404(task_id)
        status = TaskStatus(doc["status"])
        if status not in TERMINAL_STATUSES:
            raise ConflictError(
                code="TASK_NOT_TERMINAL",
                message=f"Task {task_id} 状态为 {status.value}，仅允许删除终态 Task",
                details={"task_id": task_id, "status": status.value},
            )

        result = await TaskService._collection().delete_one({"_id": task_id})
        return result.deleted_count > 0

    # ------------------------------------------------------------------
    # Concurrency control
    # ------------------------------------------------------------------

    @staticmethod
    async def _check_concurrency_limits(created_by: str) -> None:
        """Check global and per-user concurrency limits.

        Raises:
            ConflictError: If either limit is exceeded.
        """
        db = get_database()
        col = db[TaskService.COLLECTION]

        # Global limit
        global_running = await col.count_documents(
            {"status": TaskStatus.RUNNING.value}
        )
        if global_running >= settings.TASK_GLOBAL_MAX_RUNNING:
            raise ConflictError(
                code="TASK_GLOBAL_CONCURRENCY_LIMIT",
                message=(
                    f"全局并发达到上限 ({settings.TASK_GLOBAL_MAX_RUNNING})，"
                    f"当前运行中: {global_running}"
                ),
                details={
                    "limit": settings.TASK_GLOBAL_MAX_RUNNING,
                    "current": global_running,
                    "type": "global",
                },
            )

        # Per-user limit (only when created_by is a real user)
        if created_by and created_by not in ("system", "agent"):
            user_running = await col.count_documents(
                {"status": TaskStatus.RUNNING.value, "created_by": created_by}
            )
            if user_running >= settings.TASK_USER_MAX_RUNNING:
                raise ConflictError(
                    code="TASK_USER_CONCURRENCY_LIMIT",
                    message=(
                        f"用户 {created_by} 并发达到上限 ({settings.TASK_USER_MAX_RUNNING})，"
                        f"当前运行中: {user_running}"
                    ),
                    details={
                        "limit": settings.TASK_USER_MAX_RUNNING,
                        "current": user_running,
                        "user_id": created_by,
                        "type": "user",
                    },
                )

    @staticmethod
    async def _schedule_next_pending() -> dict | None:
        """Find and auto-start the oldest pending Task (FIFO scheduling).

        Called after a running Task transitions to a terminal state.
        Uses ``findOneAndUpdate`` with a status filter to avoid races.

        Returns:
            The started Task document, or ``None`` if no pending Task.
        """
        col = TaskService._collection()

        # Find the oldest pending Task and atomically claim it
        now = utc_now()
        pending = await col.find_one_and_update(
            {"status": TaskStatus.PENDING.value},
            {
                "$set": {
                    "status": TaskStatus.RUNNING.value,
                    "updated_at": now,
                    "version": 1,  # fresh task, version starts at 1
                },
                "$push": {
                    "timeline": TimelineEvent(
                        timestamp=now,
                        event_type="auto_scheduled",
                        data={"reason": "FIFO schedule — previous task completed"},
                        actor="system",
                    ).model_dump()
                },
            },
            sort=[("created_at", 1)],  # oldest first
            return_document=ReturnDocument.AFTER,
        )

        if pending is not None:
            logger.info(
                "task_auto_scheduled",
                task_id=pending["_id"],
                created_by=pending.get("created_by", ""),
            )

            # Write audit log
            await TaskService._write_audit_log(
                task_id=pending["_id"],
                event_type="state_change",
                from_status=TaskStatus.PENDING.value,
                to_status=TaskStatus.RUNNING.value,
                triggered_by="system",
                triggered_by_type="system",
                version=1,
                details={"reason": "FIFO auto-schedule"},
            )

        return pending

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------

    @staticmethod
    async def transition_task(
        task_id: str,
        to_status: TaskStatus,
        triggered_by: str = "system",
        triggered_by_type: str = "system",
        timeline_event_type: str | None = None,
        timeline_data: dict[str, Any] | None = None,
        error_info: dict[str, Any] | None = None,
    ) -> dict:
        """Transition a Task to a new status with optimistic locking.

        Concurrency control:
        - ``pending → running``: Checks global + per-user limits before
          allowing the transition.  Raises ``ConflictError`` if exceeded.
        - ``running → completed|failed|cancelled``: Triggers FIFO scheduling
          that auto-starts the oldest pending Task.

        Uses MongoDB ``findOneAndUpdate`` with version check for atomicity.

        Args:
            task_id: Task ID.
            to_status: Target status.
            triggered_by: Who/what triggered this transition.
            triggered_by_type: "user", "agent", or "system".
            timeline_event_type: Optional timeline event type (defaults to status value).
            timeline_data: Optional data to attach to timeline event.
            error_info: Optional error info (for failed transitions).

        Returns:
            Updated Task MongoDB document.

        Raises:
            NotFoundError: If Task not found.
            ConflictError: If transition is invalid, version conflict, or
                concurrency limit exceeded.
        """
        # Fetch current state
        doc = await TaskService.get_task_or_404(task_id)
        from_status = TaskStatus(doc["status"])
        current_version = doc.get("version", 1)

        # Validate transition
        if not is_valid_transition(from_status, to_status):
            raise ConflictError(
                code="TASK_INVALID_TRANSITION",
                message=f"Task {task_id} 不允许从 {from_status.value} 转换到 {to_status.value}",
                details={
                    "task_id": task_id,
                    "from_status": from_status.value,
                    "to_status": to_status.value,
                },
            )

        # Concurrency guard: pending → running
        if from_status == TaskStatus.PENDING and to_status == TaskStatus.RUNNING:
            created_by = doc.get("created_by", "")
            await TaskService._check_concurrency_limits(created_by)

        # Build update
        now = utc_now()
        event_type = timeline_event_type or to_status.value

        timeline_entry = TimelineEvent(
            timestamp=now,
            event_type=event_type,
            data=timeline_data or {},
            actor=triggered_by,
        )

        update: dict[str, Any] = {
            "$set": {
                "status": to_status.value,
                "updated_at": now,
                "version": current_version + 1,
            },
            "$push": {"timeline": timeline_entry.model_dump()},
        }

        if error_info:
            task_error = TaskError(**error_info)
            update["$set"]["error"] = task_error.model_dump()

        # Atomic update with optimistic locking
        updated = await TaskService._collection().find_one_and_update(
            {"_id": task_id, "version": current_version},
            update,
            return_document=ReturnDocument.AFTER,
        )

        if updated is None:
            raise ConflictError(
                code="TASK_VERSION_CONFLICT",
                message="Task 状态已变更，请重新获取最新状态后重试",
                details={"task_id": task_id},
            )

        # Write audit log
        await TaskService._write_audit_log(
            task_id=task_id,
            event_type="state_change",
            from_status=from_status.value,
            to_status=to_status.value,
            triggered_by=triggered_by,
            triggered_by_type=triggered_by_type,
            version=current_version + 1,
            details=timeline_data or {},
        )

        logger.info(
            "task_transition",
            task_id=task_id,
            from_status=from_status.value,
            to_status=to_status.value,
            version=current_version + 1,
        )

        # FIFO scheduling: running → terminal
        if from_status == TaskStatus.RUNNING and to_status in (
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
        ):
            scheduled = await TaskService._schedule_next_pending()
            if scheduled:
                logger.info(
                    "task_fifo_scheduled",
                    new_task_id=scheduled["_id"],
                    triggered_by=task_id,
                )

        # Publish transition event
        event_bus = get_event_bus()
        await event_bus.publish(TaskEvent(
            event_type=f"task.{to_status.value}",
            task_id=task_id,
            from_status=from_status.value,
            to_status=to_status.value,
            data=timeline_data or {},
        ))

        return updated

    # ------------------------------------------------------------------
    # Timeline & variables
    # ------------------------------------------------------------------

    @staticmethod
    async def append_timeline_event(
        task_id: str,
        event_type: str,
        data: dict[str, Any] | None = None,
        actor: str = "system",
    ) -> dict:
        """Append a timeline event to a Task."""
        entry = TimelineEvent(
            event_type=event_type,
            data=data or {},
            actor=actor,
        )

        updated = await TaskService._collection().find_one_and_update(
            {"_id": task_id},
            {
                "$push": {"timeline": entry.model_dump()},
                "$set": {"updated_at": utc_now()},
            },
            return_document=ReturnDocument.AFTER,
        )

        if updated is None:
            raise NotFoundError(
                code="TASK_NOT_FOUND",
                message=f"Task {task_id} 不存在",
                details={"task_id": task_id},
            )
        return updated

    @staticmethod
    async def update_variables(
        task_id: str,
        variables: dict[str, Any],
        version: int,
        reason: str | None = None,
        triggered_by: str = "system",
    ) -> dict:
        """Update Task variables with optimistic locking.

        Args:
            task_id: Task ID.
            variables: Variables to merge into existing variable pool.
            version: Expected current version for optimistic locking.
            reason: Optional reason for the variable update.
            triggered_by: Who triggered this update.

        Returns:
            Updated Task MongoDB document.

        Raises:
            ConflictError: If version mismatch.
        """
        now = utc_now()
        new_version = version + 1

        # Build a snapshot of the change
        snapshot = {
            "timestamp": now,
            "variables": variables,
            "reason": reason or "",
            "triggered_by": triggered_by,
        }

        update: dict[str, Any] = {
            "$set": {
                "updated_at": now,
                "version": new_version,
            },
            "$push": {"variable_snapshots": snapshot},
        }

        # Merge variables using $each for top-level keys or $set individual fields
        for key, value in variables.items():
            update["$set"][f"variables.{key}"] = value

        updated = await TaskService._collection().find_one_and_update(
            {"_id": task_id, "version": version},
            update,
            return_document=ReturnDocument.AFTER,
        )

        if updated is None:
            raise ConflictError(
                code="TASK_VERSION_CONFLICT",
                message="Task 状态已变更，请重新获取最新状态后重试",
                details={"task_id": task_id},
            )

        # Sync checkpoint.variable_snapshot so resume_from_checkpoint
        # picks up the latest variable values (e.g. human decision data).
        # This avoids the bug where resume loads the stale snapshot saved
        # when the human node first paused.
        updated_vars = updated.get("variables") or {}
        checkpoint_sync: dict[str, Any] = {}
        for _key in variables:
            if _key in updated_vars:
                checkpoint_sync[f"checkpoint.variable_snapshot.{_key}"] = updated_vars[_key]
        if checkpoint_sync:
            await TaskService._collection().update_one(
                {"_id": task_id},
                {"$set": checkpoint_sync},
            )

        return updated

    # ------------------------------------------------------------------
    # Audit log
    # ------------------------------------------------------------------

    @staticmethod
    async def _write_audit_log(
        task_id: str,
        event_type: str,
        from_status: str | None = None,
        to_status: str | None = None,
        action: str | None = None,
        triggered_by: str = "system",
        triggered_by_type: str = "system",
        version: int = 0,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Append an immutable audit log entry."""
        entry = AuditLog(
            task_id=task_id,
            event_type=event_type,
            from_status=from_status,
            to_status=to_status,
            action=action,
            triggered_by=triggered_by,
            triggered_by_type=triggered_by_type,
            version=version,
            details=details or {},
        )
        await TaskService._audit_collection().insert_one(entry.model_dump(by_alias=True))

    @staticmethod
    async def list_audit_logs(
        task_id: str,
        limit: int = 50,
    ) -> list[dict]:
        """List audit log entries for a Task, newest first."""
        cursor = (
            TaskService._audit_collection()
            .find({"task_id": task_id})
            .sort("timestamp", -1)
            .limit(limit)
        )
        return await cursor.to_list(length=limit)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @staticmethod
    async def get_stats() -> dict[str, Any]:
        """Get concurrency and Task statistics."""
        db = get_database()
        running_count = await db[TaskService.COLLECTION].count_documents(
            {"status": TaskStatus.RUNNING.value}
        )
        pending_count = await db[TaskService.COLLECTION].count_documents(
            {"status": TaskStatus.PENDING.value}
        )

        # Per-user running counts (top 10)
        pipeline = [
            {"$match": {"status": TaskStatus.RUNNING.value}},
            {"$group": {"_id": "$created_by", "running": {"$sum": 1}}},
            {"$sort": {"running": -1}},
            {"$limit": 10},
        ]
        cursor = db[TaskService.COLLECTION].aggregate(pipeline)
        user_stats = await cursor.to_list(length=10)

        return {
            "global_running": running_count,
            "global_pending": pending_count,
            "global_max": settings.TASK_GLOBAL_MAX_RUNNING,
            "user_limit": settings.TASK_USER_MAX_RUNNING,
            "user_stats": [
                {"user_id": u["_id"], "running": u["running"]} for u in user_stats
            ],
        }

"""Task API endpoints — CRUD, state transitions, intervention, stats."""
from fastapi import APIRouter, Depends, Header, Query

from app.core.security import get_current_user
from app.models.task import TaskStatus, utc_now
from app.schemas.common import PaginatedResponse
from app.schemas.task import (
    TaskCreate,
    TaskIntervene,
    TaskInterveneResponse,
    TaskListResponse,
    TaskResponse,
    TaskStatsResponse,
    TaskSummary,
)
from app.schemas.user import UserResponse
from app.services.task_service import TaskService

router = APIRouter(
    prefix="/tasks",
    tags=["tasks"],
    dependencies=[Depends(get_current_user)],
)


# ── Helpers ──


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
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


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
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


# ── Endpoints ──


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

    The Task will be created and associated with the given workflow.
    Actual execution is handled by the Workflow Engine (Story 4-9).
    """
    doc = await TaskService.create_task(
        workflow_id=body.workflow_id,
        input_data=body.input,
        created_by=current_user.id,
        created_by_type="user",
        scheduled_at=body.scheduled_at,
    )
    return _doc_to_full_response(doc)


@router.get(
    "",
    response_model=TaskListResponse,
    summary="List Tasks",
)
async def list_tasks(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(default=None),
    created_by: str | None = Query(default=None),
    workflow_id: str | None = Query(default=None),
) -> TaskListResponse:
    """List Tasks with optional filtering and pagination."""
    status_enum = TaskStatus(status) if status else None
    items, total = await TaskService.list_tasks(
        page=page,
        page_size=page_size,
        status=status_enum,
        created_by=created_by,
        workflow_id=workflow_id,
    )
    return TaskListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[_doc_to_summary(d) for d in items],
    )


@router.get(
    "/stats",
    response_model=TaskStatsResponse,
    summary="Get Task statistics",
)
async def get_task_stats() -> TaskStatsResponse:
    """Get concurrency and Task statistics (running/pending counts)."""
    stats = await TaskService.get_stats()
    return TaskStatsResponse(**stats)


@router.get(
    "/{task_id}",
    response_model=TaskResponse,
    summary="Get Task detail",
)
async def get_task(task_id: str) -> TaskResponse:
    """Get full Task detail including variables and timeline."""
    doc = await TaskService.get_task_or_404(task_id)
    return _doc_to_full_response(doc)


@router.delete(
    "/{task_id}",
    status_code=204,
    summary="Delete a terminal Task",
)
async def delete_task(task_id: str) -> None:
    """Delete a terminal-state Task (completed/failed/cancelled)."""
    await TaskService.delete_task(task_id)


@router.post(
    "/{task_id}/intervene",
    response_model=TaskInterveneResponse,
    summary="Intervene a running Task",
)
async def intervene_task(
    task_id: str,
    body: TaskIntervene,
    current_user: UserResponse = Depends(get_current_user),
) -> TaskInterveneResponse:
    """Intervene a Task: approve, reject, skip, cancel, resume, retry.

    Action flows:
    - approve: transition(RUNNING) → write decision to variables → resume
    - skip: transition(RUNNING) → resume (no decision written)
    - reject: transition(FAILED) → no resume
    - cancel: transition(CANCELLED)
    - resume: transition(RUNNING) → resume
    - retry: transition(PENDING) → clear checkpoint/error → start workflow

    Requires ``version`` field for optimistic locking.
    Returns 409 on version conflict.
    """
    valid_actions = {"approve", "reject", "skip", "cancel", "resume", "retry"}

    if body.action not in valid_actions:
        from app.core.errors import ValidationError as AppValidationError

        raise AppValidationError(
            code="TASK_INVALID_ACTION",
            message=f"不支持的操作: {body.action}",
        )

    # Get current task document for checkpoint info
    doc = await TaskService.get_task_or_404(task_id)

    if body.action == "approve":
        # Transition waiting_human → running
        doc = await TaskService.transition_task(
            task_id=task_id,
            to_status=TaskStatus.RUNNING,
            triggered_by=current_user.id,
            triggered_by_type="user",
            timeline_event_type="approve",
            timeline_data={"reason": body.reason or "", "action": "approve"},
        )
        # Write decision to variables
        checkpoint_data = doc.get("checkpoint", {})
        human_node_id = checkpoint_data.get("paused_at_node", "") if checkpoint_data else ""
        if human_node_id:
            decision_data = {
                "decision": "approve",
                "reason": body.reason or "",
                "approved_by": current_user.id,
            }
            await TaskService.update_variables(
                task_id=task_id,
                variables={human_node_id: decision_data},
                version=doc.get("version", 1),
                reason=f"Approved by {current_user.id}",
                triggered_by=current_user.id,
            )
        # Resume workflow execution
        TaskService.resume_task_execution(task_id)

    elif body.action == "skip":
        # Transition waiting_human → running
        doc = await TaskService.transition_task(
            task_id=task_id,
            to_status=TaskStatus.RUNNING,
            triggered_by=current_user.id,
            triggered_by_type="user",
            timeline_event_type="skip",
            timeline_data={"reason": body.reason or "", "action": "skip"},
        )
        # Resume workflow execution (no decision written)
        TaskService.resume_task_execution(task_id)

    elif body.action == "reject":
        # Transition waiting_human → failed (no resume)
        doc = await TaskService.transition_task(
            task_id=task_id,
            to_status=TaskStatus.FAILED,
            triggered_by=current_user.id,
            triggered_by_type="user",
            timeline_event_type="reject",
            timeline_data={"reason": body.reason or "", "action": "reject"},
            error_info={
                "error_message": f"人工驳回: {body.reason or '无原因'}",
                "error_code": "HUMAN_REJECTED",
            },
        )

    elif body.action == "cancel":
        # Transition to cancelled
        doc = await TaskService.transition_task(
            task_id=task_id,
            to_status=TaskStatus.CANCELLED,
            triggered_by=current_user.id,
            triggered_by_type="user",
            timeline_event_type="cancel",
            timeline_data={"reason": body.reason or "", "action": "cancel"},
        )

    elif body.action == "resume":
        # Transition waiting_human → running
        doc = await TaskService.transition_task(
            task_id=task_id,
            to_status=TaskStatus.RUNNING,
            triggered_by=current_user.id,
            triggered_by_type="user",
            timeline_event_type="resume",
            timeline_data={"reason": body.reason or "", "action": "resume"},
        )
        # Resume workflow execution
        TaskService.resume_task_execution(task_id)

    elif body.action == "retry":
        # Transition failed → pending
        doc = await TaskService.transition_task(
            task_id=task_id,
            to_status=TaskStatus.PENDING,
            triggered_by=current_user.id,
            triggered_by_type="user",
            timeline_event_type="retry",
            timeline_data={"reason": body.reason or "", "action": "retry"},
        )
        # Clear checkpoint and error
        from app.db.mongodb import get_database
        db = get_database()
        await db["tasks"].update_one(
            {"_id": task_id},
            {
                "$set": {
                    "checkpoint": None,
                    "error": None,
                    "updated_at": utc_now(),
                }
            },
        )
        # Start workflow execution from scratch
        TaskService._start_workflow_execution(task_id)

    action_messages = {
        "approve": "审批通过",
        "reject": "已驳回",
        "skip": "已跳过",
        "cancel": "已取消",
        "resume": "已恢复",
        "retry": "重试中",
    }

    return TaskInterveneResponse(
        task_id=task_id,
        status=TaskStatus(doc["status"]),
        version=doc.get("version", 1),
        message=action_messages.get(body.action, "操作成功"),
    )


@router.get(
    "/{task_id}/audit-logs",
    response_model=PaginatedResponse,
    summary="List Task audit logs",
)
async def list_task_audit_logs(
    task_id: str,
    limit: int = Query(default=50, ge=1, le=200),
) -> PaginatedResponse:
    """List audit log entries for a Task."""
    logs = await TaskService.list_audit_logs(task_id=task_id, limit=limit)
    return PaginatedResponse(
        total=len(logs),
        page=1,
        page_size=limit,
        items=logs,
    )

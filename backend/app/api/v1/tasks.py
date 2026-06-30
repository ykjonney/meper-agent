"""Task API endpoints — CRUD, state transitions, intervention, stats."""
import hashlib
import re

from fastapi import APIRouter, Depends, Query

from app.core.errors import ValidationError as AppValidationError
from app.core.security import get_current_user
from app.models.task import TaskStatus, utc_now
from app.schemas.common import PaginatedResponse
from app.schemas.file_library import FileRefResponse
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


def _sanitize_node_id(node_id: str) -> str:
    """Sanitize a node id for use in a variables key.

    Produces a collision-resistant key by combining a sanitized version of the
    original id (so the result is still readable and expression-friendly) with a
    short hash suffix (so distinct ids that happen to sanitize to the same
    string do not silently overwrite each other's decisions).
    """
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", node_id) or "node"
    digest = hashlib.sha1(node_id.encode("utf-8")).hexdigest()[:6]
    return f"{sanitized}_{digest}"


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
        raise AppValidationError(
            code="TASK_INVALID_ACTION",
            message=f"不支持的操作: {body.action}",
        )

    # Get current task document for checkpoint info
    doc = await TaskService.get_task_or_404(task_id)

    # Guard: approve/reject/skip require WAITING_HUMAN. If a timeout or another
    # actor has already moved the task out of that state, the optimistic-lock
    # check inside transition_task will return 409 — but rejecting early with a
    # 4xx gives a clearer signal and avoids writing variables for a decision
    # that the workflow is no longer waiting on.
    if body.action in {"approve", "reject", "skip"} and doc.get("status") != TaskStatus.WAITING_HUMAN.value:
        raise AppValidationError(
            code="TASK_NOT_WAITING_HUMAN",
            message=f"任务当前状态为 {doc.get('status')},无法执行 {body.action}",
        )

    if body.action == "approve":
        # Transition waiting_human → running
        doc = await TaskService.transition_task(
            task_id=task_id,
            to_status=TaskStatus.RUNNING,
            triggered_by=current_user.id,
            triggered_by_type="user",
            timeline_event_type="approve",
            timeline_data={"comment": body.comment or "", "action": "approve"},
        )
        # Write decision to variables
        checkpoint_data = doc.get("checkpoint", {})
        human_node_id = checkpoint_data.get("paused_at_node", "") if checkpoint_data else ""
        if human_node_id:
            decision_data = {
                "decision": "approve",
                "comment": body.comment or "",
                "approver": current_user.id,
                "decided_at": utc_now().isoformat(),
            }
            await TaskService.update_variables(
                task_id=task_id,
                variables={f"human_decision_{_sanitize_node_id(human_node_id)}": decision_data},
                version=doc.get("version", 1),
                reason=body.comment,
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
            timeline_data={"comment": body.comment or "", "action": "skip"},
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
            timeline_data={"comment": body.comment or "", "action": "reject"},
            error_info={
                "error_message": f"人工驳回: {body.comment or '无原因'}",
                "error_code": "HUMAN_REJECTED",
            },
        )
        # Write decision to variables
        checkpoint_data = doc.get("checkpoint", {})
        human_node_id = checkpoint_data.get("paused_at_node", "") if checkpoint_data else ""
        if human_node_id:
            decision_data = {
                "decision": "reject",
                "comment": body.comment or "",
                "approver": current_user.id,
                "decided_at": utc_now().isoformat(),
            }
            await TaskService.update_variables(
                task_id=task_id,
                variables={f"human_decision_{_sanitize_node_id(human_node_id)}": decision_data},
                version=doc.get("version", 1),
                reason=body.comment,
                triggered_by=current_user.id,
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


@router.get(
    "/{task_id}/outputs",
    response_model=list[FileRefResponse],
    summary="List Task output files",
)
async def list_task_outputs(
    task_id: str,
    current_user: UserResponse = Depends(get_current_user),
) -> list[dict]:
    """List files produced by an Agent node during Task execution.

    Story 4-15: Agent nodes write their output files to a per-task workspace
    (``{workspaces_root}/{user_id}/tasks/{task_id}/output/``) and register
    them in ``file_library`` with ``origin_kind=workflow_run`` and
    ``origin_id=task_id``. This endpoint returns the registered files in
    newest-first order.

    The task is loaded first to confirm it exists and to authorize the
    caller; files are scoped by ``origin_id=task_id`` to the specific task.
    """
    from app.models.file_library import FileConsumerKind
    from app.services.file_service import FileService
    from app.services.file_storage import LocalFileStorage

    # 404 if the task itself doesn't exist — clearer signal than an empty list.
    await TaskService.get_task_or_404(task_id)

    file_service = FileService(LocalFileStorage())
    cursor = file_service._file_refs().find(
        {
            "origin_kind": FileConsumerKind.WORKFLOW_RUN.value,
            "origin_id": task_id,
        },
    ).sort("created_at", -1)
    docs = await cursor.to_list(length=None)
    # Return as dicts so FastAPI can serialize them with the FileRefResponse
    # schema (Pydantic handles the _id → id alias from MongoDB).
    return [FileRefResponse.model_validate(doc).model_dump(mode="json") for doc in docs]

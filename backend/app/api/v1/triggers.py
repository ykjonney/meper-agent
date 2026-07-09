"""Trigger API endpoints — independent trigger CRUD + lifecycle."""
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.core.errors import NotFoundError
from app.core.security import get_current_user
from app.models.base import utc_now
from app.models.trigger import Trigger
from app.schemas.user import UserResponse
from app.services.trigger_scheduler_service import get_trigger_scheduler

router = APIRouter(
    prefix="/triggers",
    tags=["triggers"],
    dependencies=[Depends(get_current_user)],
)


# ── Request / Response schemas ──


class TriggerCreate(BaseModel):
    """Request body for creating a trigger."""

    workflow_id: str
    type: str  # "cron" | "once"
    enabled: bool = False
    cron_expression: str | None = None
    execute_at: datetime | None = None
    default_input: dict[str, object] = {}


class TriggerUpdate(BaseModel):
    """Request body for updating a trigger."""

    type: str | None = None
    enabled: bool | None = None
    cron_expression: str | None = None
    execute_at: datetime | None = None
    default_input: dict[str, object] | None = None


class ToggleRequest(BaseModel):
    """Request body for toggling trigger enabled state."""

    enabled: bool


# ── Helpers ──


def _get_repo():
    """Get the trigger repository from the scheduler service."""
    return get_trigger_scheduler().repo


def _trigger_to_dict(trigger: Trigger) -> dict:
    """Convert a Trigger model to a dict for API response."""
    return trigger.model_dump(by_alias=True)


# ── Endpoints ──


@router.post(
    "",
    status_code=201,
    summary="Create a new trigger",
)
async def create_trigger(
    body: TriggerCreate,
    current_user: UserResponse = Depends(get_current_user),
) -> dict:
    """Create a new trigger for a workflow.

    The user_id is taken from the authenticated user. Multiple triggers
    can exist for the same (user, workflow) pair.
    """
    repo = _get_repo()

    trigger = Trigger(
        workflow_id=body.workflow_id,
        user_id=current_user.id,
        type=body.type,
        enabled=body.enabled,
        cron_expression=body.cron_expression,
        execute_at=body.execute_at,
        default_input=body.default_input,
    )

    await repo.insert(trigger)

    # Create placeholder Task (for visibility) and optionally send Celery task
    # send_celery=True only if trigger is enabled
    scheduler = get_trigger_scheduler()
    await scheduler.schedule_next(trigger.id, send_celery=trigger.enabled)

    # Re-fetch to include computed next_trigger_at
    updated = await repo.find_by_id(trigger.id)
    return _trigger_to_dict(updated)


@router.get(
    "",
    summary="List triggers",
)
async def list_triggers(
    workflow_id: str | None = Query(default=None),
    user_id: str | None = Query(default=None),
    current_user: UserResponse = Depends(get_current_user),
) -> dict:
    """List triggers with optional filtering.

    By default, returns triggers for the authenticated user.
    Use workflow_id to filter by workflow.
    Admin users can query other users' triggers with user_id.
    """
    from app.db.mongodb import get_database

    db = get_database()
    query: dict = {}

    # Default: filter by current user
    if user_id is None or user_id != current_user.id:
        # Non-admin can only see their own triggers
        if current_user.role not in ("admin",):
            query["user_id"] = current_user.id
        elif user_id:
            query["user_id"] = user_id
        else:
            query["user_id"] = current_user.id
    else:
        query["user_id"] = user_id

    if workflow_id:
        query["workflow_id"] = workflow_id

    cursor = db["triggers"].find(query).sort("created_at", -1)
    items = []
    async for doc in cursor:
        items.append(Trigger(**doc).model_dump(by_alias=True))

    return {"total": len(items), "items": items}


@router.get(
    "/{trigger_id}",
    summary="Get trigger detail",
)
async def get_trigger(
    trigger_id: str,
    current_user: UserResponse = Depends(get_current_user),
) -> dict:
    """Get a single trigger by ID."""
    repo = _get_repo()
    trigger = await repo.find_by_id(trigger_id)
    if trigger is None:
        raise NotFoundError(
            code="TRIGGER_NOT_FOUND",
            message=f"定时配置 {trigger_id} 不存在",
            details={"trigger_id": trigger_id},
        )

    # Non-admin can only access their own triggers
    if trigger.user_id != current_user.id and current_user.role not in ("admin",):
        raise NotFoundError(
            code="TRIGGER_NOT_FOUND",
            message=f"定时配置 {trigger_id} 不存在",
            details={"trigger_id": trigger_id},
        )

    return _trigger_to_dict(trigger)


@router.put(
    "/{trigger_id}",
    summary="Update trigger",
)
async def update_trigger(
    trigger_id: str,
    body: TriggerUpdate,
    current_user: UserResponse = Depends(get_current_user),
) -> dict:
    """Update a trigger.

    Increments schedule_version so stale Celery tasks are skipped.
    """
    repo = _get_repo()
    trigger = await repo.find_by_id(trigger_id)
    if trigger is None:
        raise NotFoundError(
            code="TRIGGER_NOT_FOUND",
            message=f"定时配置 {trigger_id} 不存在",
            details={"trigger_id": trigger_id},
        )

    # Non-admin can only update their own triggers
    if trigger.user_id != current_user.id and current_user.role not in ("admin",):
        raise NotFoundError(
            code="TRIGGER_NOT_FOUND",
            message=f"定时配置 {trigger_id} 不存在",
            details={"trigger_id": trigger_id},
        )

    updates = body.model_dump(exclude_unset=True, exclude_none=True)
    updates["schedule_version"] = trigger.schedule_version + 1
    updates["updated_at"] = utc_now()

    await repo.update(trigger_id, **updates)

    # Determine final enabled state after this update
    new_enabled = updates.get("enabled", trigger.enabled)

    # Re-schedule: updates existing pending Task's scheduled_at + optionally sends Celery
    # Old Celery message will be skipped by version check in worker
    scheduler = get_trigger_scheduler()
    await scheduler.schedule_next(trigger_id, send_celery=new_enabled)

    # Re-fetch to include computed next_trigger_at
    updated = await repo.find_by_id(trigger_id)
    return _trigger_to_dict(updated)


@router.patch(
    "/{trigger_id}/toggle",
    summary="Toggle trigger enabled state",
)
async def toggle_trigger(
    trigger_id: str,
    body: ToggleRequest,
    current_user: UserResponse = Depends(get_current_user),
) -> dict:
    """Toggle the enabled state of a trigger."""
    repo = _get_repo()
    trigger = await repo.find_by_id(trigger_id)
    if trigger is None:
        raise NotFoundError(
            code="TRIGGER_NOT_FOUND",
            message=f"定时配置 {trigger_id} 不存在",
            details={"trigger_id": trigger_id},
        )

    # Non-admin can only toggle their own triggers
    if trigger.user_id != current_user.id and current_user.role not in ("admin",):
        raise NotFoundError(
            code="TRIGGER_NOT_FOUND",
            message=f"定时配置 {trigger_id} 不存在",
            details={"trigger_id": trigger_id},
        )

    await repo.update(
        trigger_id,
        enabled=body.enabled,
        updated_at=utc_now(),
    )

    scheduler = get_trigger_scheduler()
    if body.enabled:
        # Enable: Task already exists (or create if missing), send Celery
        await scheduler.schedule_next(trigger_id, send_celery=True)
    else:
        # Disable: Keep Task pending for visibility, Celery will skip when it fires
        # (trigger.enabled check in scheduled_workflow.py)
        # Just update next_trigger_at without sending new Celery
        await scheduler.schedule_next(trigger_id, send_celery=False)

    # Re-fetch
    updated = await repo.find_by_id(trigger_id)
    return _trigger_to_dict(updated)

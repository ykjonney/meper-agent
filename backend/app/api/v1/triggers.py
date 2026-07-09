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


def _compute_next_trigger_at(trigger: Trigger) -> datetime | None:
    """Compute the next firing time for a trigger (pure DB bookkeeping).

    The polling scheduler reads next_trigger_at to decide when to fire, so
    API endpoints only need to set/refresh this field — no Celery dispatch.
    Returns None for once-type or when the cron expression is missing.
    """
    scheduler = get_trigger_scheduler()
    now = datetime.now().astimezone()
    return scheduler._compute_next(trigger, now)


async def _ensure_template_placeholder(trigger: Trigger, scheduled_at: datetime | None) -> None:
    """Ensure the always-pending template placeholder Task exists for a trigger.

    The template (source="trigger", status="pending") represents the trigger
    configuration: it's visible in the task board, its scheduled_at shows the
    next firing time, and cancelling it stops the trigger. This helper is
    idempotent — if a template already exists, it just updates scheduled_at.
    Called on create / update / toggle.
    """
    from app.db.mongodb import get_database

    db = get_database()
    existing = await db["tasks"].find_one(
        {"trigger_id": trigger.id, "status": "pending", "source": "trigger"},
        {"_id": 1},
    )
    scheduler = get_trigger_scheduler()
    if existing is None:
        await scheduler._create_placeholder_task(
            trigger, scheduled_at or datetime.now().astimezone()
        )
    elif scheduled_at is not None:
        # Template exists — just refresh its scheduled_at for display.
        from app.models.base import utc_now
        await db["tasks"].update_one(
            {"_id": existing["_id"]},
            {"$set": {"scheduled_at": scheduled_at, "updated_at": utc_now()}},
        )


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

    # Set initial next_trigger_at + create the template placeholder Task.
    next_at = None
    if trigger.enabled:
        next_at = _compute_next_trigger_at(trigger)
        if next_at is not None:
            await repo.update(trigger.id, next_trigger_at=next_at)

    # Always create the template placeholder (even if disabled, so it's
    # ready when the user enables later). It stays pending permanently.
    fresh = await repo.find_by_id(trigger.id)
    await _ensure_template_placeholder(fresh or trigger, next_at)

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

    Increments schedule_version and refreshes next_trigger_at so the polling
    scheduler picks up the new schedule.
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

    # Refresh next_trigger_at based on the updated config. If the trigger is
    # now disabled, clear next_trigger_at so the poller skips it.
    updated_trigger = await repo.find_by_id(trigger_id)
    if updated_trigger is not None:
        if updated_trigger.enabled:
            next_at = _compute_next_trigger_at(updated_trigger)
            await repo.update(trigger_id, next_trigger_at=next_at)
            # Ensure template exists + refresh its scheduled_at.
            await _ensure_template_placeholder(updated_trigger, next_at)
        else:
            # Disabled: clear next_trigger_at (poller filters on enabled anyway,
            # but clearing avoids stale due-time display).
            await repo.update(trigger_id, next_trigger_at=None)

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

    if body.enabled:
        # Enable: compute next_trigger_at so the poller picks it up,
        # and ensure the template placeholder exists.
        updated_trigger = await repo.find_by_id(trigger_id)
        if updated_trigger is not None:
            next_at = _compute_next_trigger_at(updated_trigger)
            await repo.update(trigger_id, next_trigger_at=next_at)
            await _ensure_template_placeholder(updated_trigger, next_at)
    else:
        # Disable: clear next_trigger_at so the poller never fires it.
        await repo.update(trigger_id, next_trigger_at=None)

    # Re-fetch
    updated = await repo.find_by_id(trigger_id)
    return _trigger_to_dict(updated)

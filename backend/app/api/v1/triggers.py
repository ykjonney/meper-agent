"""Trigger API endpoints — independent trigger CRUD + lifecycle.

权限对接（PERMISSIONS.md）：
- 准入判权限键：路由级 ``trigger:read``，写端点 ``trigger:write``。
- 资源归属（own/all）与权限键正交：``trigger:manage`` 持有者可跨用户
  访问/管理（含 ``?all=true`` 全库列表）；非持有者访问他人 trigger 得 404
  （不暴露存在性）。历史实现用 ``role not in ("admin",)`` 判断归属，属
  规范红线写法（自定义角色永远过不了），且 admin 不传 user_id 时也只能
  看到自己的——调度器扫全库但管理面看不全，是隐形 trigger 事故的根因。
"""
from datetime import datetime
from typing import Literal

from croniter import croniter
from fastapi import APIRouter, Depends, Query
from loguru import logger
from pydantic import BaseModel

from app.core.errors import ForbiddenError, NotFoundError, ValidationError
from app.core.security import get_current_user, get_role_permissions, require_permission
from app.models.base import utc_now
from app.models.trigger import Trigger
from app.schemas.user import UserResponse
from app.services.trigger_scheduler_service import get_trigger_scheduler, trigger_now

router = APIRouter(
    prefix="/triggers",
    tags=["triggers"],
    dependencies=[Depends(require_permission("trigger:read"))],
)


# ── Request / Response schemas ──


class TriggerCreate(BaseModel):
    """Request body for creating a trigger."""

    workflow_id: str
    # Literal 而非裸 str：任意字符串会静默通过并让调度器永不触发
    type: Literal["cron", "once"]
    enabled: bool = False
    cron_expression: str | None = None
    execute_at: datetime | None = None
    default_input: dict[str, object] = {}


class TriggerUpdate(BaseModel):
    """Request body for updating a trigger."""

    type: Literal["cron", "once"] | None = None
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


async def _can_manage(current_user: UserResponse) -> bool:
    """Whether the user may access/manage *other users'* triggers.

    Permission-key driven (trigger:manage), resolved live from the role
    service so role edits take effect immediately — never a role-name check.
    """
    perms = await get_role_permissions(current_user.role)
    return "trigger:manage" in perms


async def _get_accessible_trigger(
    trigger_id: str, current_user: UserResponse
) -> Trigger:
    """Fetch a trigger enforcing own/manage ownership.

    404 for both missing and foreign triggers (no existence leak).
    """
    trigger = await _get_repo().find_by_id(trigger_id)
    if trigger is None or (
        trigger.user_id != current_user.id and not await _can_manage(current_user)
    ):
        raise NotFoundError(
            code="TRIGGER_NOT_FOUND",
            message=f"定时配置 {trigger_id} 不存在",
            details={"trigger_id": trigger_id},
        )
    return trigger


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
    return scheduler._compute_next(trigger, trigger_now())


def _validate_cron(trigger_type: str, cron_expression: str | None) -> None:
    """Reject invalid cron expressions with a clear error code.

    Without this, a malformed expression (e.g. from a buggy picker or manual
    input) sails through create/update and only blows up later inside the
    scheduler's _compute_next.
    """
    if trigger_type == "cron":
        expr = (cron_expression or "").strip()
        if not expr:
            raise ValidationError(
                code="TRIGGER_INVALID_CRON",
                message="Cron 表达式不能为空",
            )
        if not croniter.is_valid(expr):
            raise ValidationError(
                code="TRIGGER_INVALID_CRON",
                message=f"Cron 表达式无效: {expr}",
                details={"cron_expression": expr},
            )


# ── Endpoints ──


@router.post(
    "",
    status_code=201,
    summary="Create a new trigger",
)
async def create_trigger(
    body: TriggerCreate,
    current_user: UserResponse = Depends(require_permission("trigger:write")),
) -> dict:
    """Create a trigger for the current user.

    Multiple triggers can exist for the same (user, workflow) pair.
    """
    repo = _get_repo()
    _validate_cron(body.type, body.cron_expression)

    trigger = Trigger(
        workflow_id=body.workflow_id,
        user_id=current_user.id,
        type=body.type,
        enabled=body.enabled,
        cron_expression=body.cron_expression if body.type == "cron" else None,
        execute_at=body.execute_at if body.type == "once" else None,
        default_input=body.default_input,
    )

    await repo.insert(trigger)

    # Set initial next_trigger_at + create the template placeholder Task.
    next_at = None
    if trigger.enabled:
        next_at = _compute_next_trigger_at(trigger)
        if next_at is not None:
            await repo.update(trigger.id, next_trigger_at=next_at)

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
    all_triggers: bool = Query(
        default=False, alias="all", description="全库列表（需 trigger:manage 权限）"
    ),
    current_user: UserResponse = Depends(get_current_user),
) -> dict:
    """List triggers.

    Default: only the authenticated user's triggers. ``trigger:manage``
    holders may pass ``all=true`` for the full collection (optionally
    combined with ``user_id``), or ``user_id`` alone to inspect a specific
    user. Non-holders querying someone else's user_id get a clear 403 —
    never a silent fallback (silent filtering is what hid stray triggers
    from admins in the first place).
    """
    from app.db.mongodb import get_database

    db = get_database()
    query: dict = {}

    # Gate first: any cross-user view (all=true, or someone else's user_id)
    # requires manage. Clear 403 — never a silent fallback to own-only
    # (silent filtering is what hid stray triggers from admins).
    if (
        all_triggers or (user_id is not None and user_id != current_user.id)
    ) and not await _can_manage(current_user):
        raise ForbiddenError(
            code="FORBIDDEN",
            message="权限不足，查看他人/全部定时任务需要 trigger:manage 权限",
        )

    if user_id is not None:
        query["user_id"] = user_id
    elif not all_triggers:
        query["user_id"] = current_user.id  # default: own only

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
    """Get a single trigger by ID.

    Non-manage users can only access their own; others 404.
    """
    trigger = await _get_accessible_trigger(trigger_id, current_user)
    return _trigger_to_dict(trigger)


@router.put(
    "/{trigger_id}",
    summary="Update trigger",
)
async def update_trigger(
    trigger_id: str,
    body: TriggerUpdate,
    current_user: UserResponse = Depends(require_permission("trigger:write")),
) -> dict:
    """Update a trigger.

    Increments schedule_version and refreshes next_trigger_at so the polling
    scheduler picks up the new schedule. Switching type clears the other
    type's field — previously stale cron_expression/execute_at lingered on
    the document (e.g. a once-trigger carrying "0 0 4 * *").
    """
    repo = _get_repo()
    trigger = await _get_accessible_trigger(trigger_id, current_user)

    updates = body.model_dump(exclude_unset=True, exclude_none=True)

    # Resolve the *final* type and validate/clear fields per it.
    final_type = updates.get("type") or trigger.type
    _validate_cron(final_type, updates.get("cron_expression", trigger.cron_expression))
    if final_type == "cron":
        updates["execute_at"] = None  # $set null clears stale residue
    elif final_type == "once":
        updates["cron_expression"] = None

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
    current_user: UserResponse = Depends(require_permission("trigger:write")),
) -> dict:
    """Toggle the enabled state of a trigger."""
    repo = _get_repo()
    await _get_accessible_trigger(trigger_id, current_user)

    await repo.update(
        trigger_id,
        enabled=body.enabled,
        updated_at=utc_now(),
    )

    if body.enabled:
        # Enable: compute next_trigger_at so the poller picks it up.
        updated_trigger = await repo.find_by_id(trigger_id)
        if updated_trigger is not None:
            next_at = _compute_next_trigger_at(updated_trigger)
            await repo.update(trigger_id, next_trigger_at=next_at)
    else:
        # Disable: clear next_trigger_at so the poller never fires it.
        await repo.update(trigger_id, next_trigger_at=None)

    # Re-fetch
    updated = await repo.find_by_id(trigger_id)
    return _trigger_to_dict(updated)


@router.delete(
    "/{trigger_id}",
    status_code=204,
    summary="Delete a trigger",
)
async def delete_trigger(
    trigger_id: str,
    current_user: UserResponse = Depends(require_permission("trigger:write")),
) -> None:
    """Delete a trigger (stops the scheduled task permanently)."""
    repo = _get_repo()
    await _get_accessible_trigger(trigger_id, current_user)

    await repo.delete(trigger_id)
    logger.info("trigger_deleted", trigger_id=trigger_id)

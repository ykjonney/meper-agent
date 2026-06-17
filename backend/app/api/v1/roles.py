"""Roles API endpoints — dynamic role management (admin-only)."""
from fastapi import APIRouter, Depends, Query

from app.core.security import get_current_user, require_role
from app.models.user import UserRole
from app.schemas.role import (
    AllPermissionsResponse,
    RoleCreate,
    RoleResponse,
    RoleUpdate,
)
from app.schemas.user import UserResponse
from app.services.role_service import ALL_PERMISSION_KEYS, RoleService

router = APIRouter(prefix="/roles", tags=["roles"])


def _doc_to_response(doc: dict) -> RoleResponse:
    """Convert a MongoDB role document to RoleResponse."""
    return RoleResponse(
        id=doc["_id"],
        name=doc["name"],
        display_name=doc["display_name"],
        description=doc.get("description", ""),
        role_type=doc["role_type"],
        permissions=doc.get("permissions", []),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


@router.get(
    "",
    response_model=list[RoleResponse],
    summary="List all roles",
)
async def list_roles(
    role_type: str | None = Query(None, description="Filter by role type: system or custom"),
    _: UserResponse = Depends(require_role(UserRole.ADMIN)),
) -> list[RoleResponse]:
    """List all roles (no pagination — role count is small)."""
    from app.models.role import RoleType

    rt = RoleType(role_type) if role_type else None
    docs = await RoleService.list_roles(role_type=rt)
    return [_doc_to_response(d) for d in docs]


@router.post(
    "",
    response_model=RoleResponse,
    status_code=201,
    summary="Create a custom role",
)
async def create_role(
    body: RoleCreate,
    _: UserResponse = Depends(require_role(UserRole.ADMIN)),
) -> RoleResponse:
    """Create a new custom role."""
    doc = await RoleService.create_role(body)
    return _doc_to_response(doc)


@router.patch(
    "/{role_id}",
    response_model=RoleResponse,
    summary="Update a role",
)
async def update_role(
    role_id: str,
    body: RoleUpdate,
    _: UserResponse = Depends(require_role(UserRole.ADMIN)),
) -> RoleResponse:
    """Update a role. System roles can only have their permissions modified."""
    doc = await RoleService.update_role(role_id, body)
    if doc is None:
        from app.core.errors import NotFoundError

        raise NotFoundError(
            code="ROLE_NOT_FOUND",
            message=f"角色 {role_id} 不存在",
        )
    return _doc_to_response(doc)


@router.delete(
    "/{role_id}",
    status_code=204,
    summary="Delete a custom role",
)
async def delete_role(
    role_id: str,
    _: UserResponse = Depends(require_role(UserRole.ADMIN)),
) -> None:
    """Delete a custom role. System roles and roles with assigned users cannot be deleted."""
    await RoleService.delete_role(role_id)


@router.get(
    "/permissions",
    response_model=AllPermissionsResponse,
    summary="Get all available permission keys",
)
async def get_all_permissions(
    _: UserResponse = Depends(get_current_user),
) -> AllPermissionsResponse:
    """Return all available permission keys (for the permission checkbox UI)."""
    return AllPermissionsResponse(permissions=ALL_PERMISSION_KEYS)

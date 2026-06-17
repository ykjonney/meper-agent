"""Workflow Registry API endpoints — list/search published workflows for UI."""
from fastapi import APIRouter, Depends, Query

from app.core.security import get_current_user
from app.schemas.common import PaginatedResponse
from app.schemas.user import UserResponse
from app.services.workflow_registry_service import WorkflowRegistryService

router = APIRouter(
    prefix="/workflow-registry",
    tags=["workflow-registry"],
    dependencies=[Depends(get_current_user)],
)


@router.get(
    "",
    response_model=PaginatedResponse,
    summary="List published workflows",
)
async def list_workflows(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=100),
    search: str | None = Query(default=None),
) -> PaginatedResponse:
    """List all published workflow templates for task creation.

    Supports optional text search by name/description.
    """
    if search and search.strip():
        items = await WorkflowRegistryService.search(query=search.strip(), limit=page_size)
        # Paginate in-memory for simplicity
        total = len(items)
        start = (page - 1) * page_size
        return PaginatedResponse(
            total=total,
            page=page,
            page_size=page_size,
            items=items[start : start + page_size],
        )
    else:
        items, total = await WorkflowRegistryService.list_all(
            page=page,
            page_size=page_size,
            published_only=True,
        )
        return PaginatedResponse(
            total=total,
            page=page,
            page_size=page_size,
            items=items,
        )

"""Internal API Key management endpoints — JWT auth, admin only."""
from fastapi import APIRouter, Depends
from fastapi.responses import Response

from app.core.security import get_current_user, require_role
from app.models.user import UserRole
from app.schemas.api_key import (
    ApiKeyCreate,
    ApiKeyCreateResponse,
    ApiKeyListResponse,
    ApiKeyResponse,
    ApiKeyStatsResponse,
    ApiKeyUpdate,
)
from app.schemas.user import UserResponse
from app.services.api_key_service import ApiKeyService
from app.services.api_key_stats_service import get_stats

router = APIRouter(
    prefix="/api-keys",
    tags=["api-keys"],
    dependencies=[Depends(get_current_user), Depends(require_role(UserRole.ADMIN))],
)


def _doc_to_response(doc: dict) -> ApiKeyResponse:
    """Convert a MongoDB API Key document to the response schema."""
    return ApiKeyResponse(
        id=doc["_id"],
        name=doc["name"],
        key_prefix=doc["key_prefix"],
        owner_user_id=doc["owner_user_id"],
        scopes=doc["scopes"],
        bindings=doc["bindings"],
        rate_limit=doc["rate_limit"],
        status=doc["status"],
        expires_at=doc.get("expires_at"),
        last_used_at=doc.get("last_used_at"),
        user_info_url=doc.get("user_info_url", ""),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


@router.post(
    "",
    response_model=ApiKeyCreateResponse,
    status_code=201,
    summary="Create API Key",
)
async def create_api_key(
    body: ApiKeyCreate,
    user: UserResponse = Depends(get_current_user),
) -> ApiKeyCreateResponse:
    """Create a new API Key. The raw key is returned ONLY once."""
    doc, raw_key = await ApiKeyService.create_api_key(
        name=body.name,
        owner_user_id=user.id,
        scopes=body.scopes,
        bindings=body.bindings.model_dump(),
        rate_limit=body.rate_limit,
        expires_at=body.expires_at,
        user_info_url=body.user_info_url or "",
    )
    return ApiKeyCreateResponse(
        id=doc["_id"],
        name=doc["name"],
        key=raw_key,
        key_prefix=doc["key_prefix"],
        owner_user_id=doc["owner_user_id"],
        scopes=doc["scopes"],
        bindings=doc["bindings"],
        rate_limit=doc["rate_limit"],
        status=doc["status"],
        expires_at=doc.get("expires_at"),
        user_info_url=doc.get("user_info_url", ""),
        created_at=doc["created_at"],
    )


@router.get(
    "",
    response_model=ApiKeyListResponse,
    summary="List API Keys",
)
async def list_api_keys(
    page: int = 1,
    page_size: int = 20,
) -> ApiKeyListResponse:
    """List all API Keys (masked — only key_prefix shown)."""
    items, total = await ApiKeyService.list_api_keys(
        page=page,
        page_size=page_size,
    )
    return ApiKeyListResponse(
        items=[_doc_to_response(d) for d in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{api_key_id}",
    response_model=ApiKeyResponse,
    summary="Get API Key details",
)
async def get_api_key(api_key_id: str) -> ApiKeyResponse:
    """Get API Key details (no raw key returned)."""
    from app.core.errors import NotFoundError

    doc = await ApiKeyService.get_api_key(api_key_id)
    if doc is None:
        raise NotFoundError(code="APIKEY_NOT_FOUND", message="API Key not found")
    return _doc_to_response(doc)


@router.put(
    "/{api_key_id}",
    response_model=ApiKeyResponse,
    summary="Update API Key",
)
async def update_api_key(
    api_key_id: str,
    body: ApiKeyUpdate,
) -> ApiKeyResponse:
    """Update API Key configuration (name, scopes, bindings, etc.)."""
    from app.core.errors import NotFoundError

    doc = await ApiKeyService.update_api_key(
        api_key_id=api_key_id,
        name=body.name,
        scopes=body.scopes,
        bindings=body.bindings.model_dump() if body.bindings else None,
        rate_limit=body.rate_limit,
        expires_at=body.expires_at,
        user_info_url=body.user_info_url,
    )
    if doc is None:
        raise NotFoundError(code="APIKEY_NOT_FOUND", message="API Key not found")
    return _doc_to_response(doc)


@router.delete(
    "/{api_key_id}",
    status_code=204,
    summary="Revoke API Key",
)
async def revoke_api_key(api_key_id: str) -> Response:
    """Revoke an API Key (soft-delete). Cannot be undone."""
    from app.core.errors import NotFoundError

    doc = await ApiKeyService.revoke_api_key(api_key_id)
    if doc is None:
        raise NotFoundError(code="APIKEY_NOT_FOUND", message="API Key not found")
    return Response(status_code=204)


@router.get(
    "/{api_key_id}/stats",
    response_model=ApiKeyStatsResponse,
    summary="Get API Key call statistics",
)
async def get_api_key_stats(api_key_id: str) -> ApiKeyStatsResponse:
    """Get aggregated call statistics for an API Key."""
    from app.core.errors import NotFoundError

    doc = await ApiKeyService.get_api_key(api_key_id)
    if doc is None:
        raise NotFoundError(code="APIKEY_NOT_FOUND", message="API Key not found")

    stats = await get_stats(api_key_id)
    return ApiKeyStatsResponse(**stats)

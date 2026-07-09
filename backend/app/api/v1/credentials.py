"""Credential management API endpoints."""
from fastapi import APIRouter, Depends

from app.core.errors import NotFoundError
from app.core.security import require_any_role
from app.schemas.credential import (
    CredentialCreate,
    CredentialListResponse,
    CredentialResponse,
)
from app.schemas.user import UserResponse
from app.services.credential_service import CredentialService

router = APIRouter(
    prefix="/credentials",
    tags=["credentials"],
    dependencies=[Depends(require_any_role("admin", "developer"))],
)


@router.post("", response_model=CredentialResponse, status_code=201, summary="Create a credential")
async def create_credential(
    body: CredentialCreate,
    user: UserResponse = Depends(require_any_role("admin", "developer")),
) -> CredentialResponse:
    """Create an encrypted credential for tool authentication."""
    doc = await CredentialService.create_credential(
        user_id=user.id,
        name=body.name,
        type=body.type,
        data=body.data,
    )
    masked = CredentialService._to_masked_response(doc)
    return CredentialResponse(**masked)


@router.get("", response_model=CredentialListResponse, summary="List credentials")
async def list_credentials(
    user: UserResponse = Depends(require_any_role("admin", "developer")),
) -> CredentialListResponse:
    """List all credentials for the current user (masked, no plaintext)."""
    items = await CredentialService.list_credentials(user.id)
    return CredentialListResponse(
        items=[CredentialResponse(**item) for item in items],
        total=len(items),
    )


@router.delete("/{credential_id}", status_code=204, summary="Delete a credential")
async def delete_credential(
    credential_id: str,
    user: UserResponse = Depends(require_any_role("admin", "developer")),
) -> None:
    """Delete a credential. Tools referencing it will lose auth."""
    deleted = await CredentialService.delete_credential(credential_id, user.id)
    if not deleted:
        raise NotFoundError(
            code="CREDENTIAL_NOT_FOUND",
            message=f"Credential {credential_id} 不存在",
        )

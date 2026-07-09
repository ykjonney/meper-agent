"""API Key authentication dependency for external API routes.

Provides ``get_api_key_principal`` — a FastAPI Depends that validates
the Bearer token as an API Key (not JWT) and returns an
``ApiKeyPrincipal`` object with scopes and bindings.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from fastapi import Header

from app.core.errors import ForbiddenError, UnauthorizedError


@dataclass
class ApiKeyPrincipal:
    """Authenticated API Key identity.

    Carries the Key's scopes, resource bindings, and owner_user_id
    so that downstream route handlers can enforce authorization.
    """

    key_id: str
    owner_user_id: str
    scopes: list[str] = field(default_factory=list)
    bindings: dict = field(default_factory=dict)
    rate_limit: int = 60

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes

    def require_scope(self, scope: str) -> None:
        if not self.has_scope(scope):
            raise ForbiddenError(
                code="APIKEY_SCOPE_DENIED",
                message=f"API Key 权限不足，需要 {scope} 权限",
            )

    def can_access_agent(self, agent_id: str) -> bool:
        """Check if this key can access the given Agent. Empty bindings = all."""
        allowed = self.bindings.get("agents", [])
        if not allowed:
            return True
        return agent_id in allowed

    def can_access_workflow(self, workflow_id: str) -> bool:
        """Check if this key can access the given Workflow. Empty bindings = all."""
        allowed = self.bindings.get("workflows", [])
        if not allowed:
            return True
        return workflow_id in allowed

    def require_agent_access(self, agent_id: str) -> None:
        if not self.can_access_agent(agent_id):
            raise ForbiddenError(
                code="APIKEY_AGENT_DENIED",
                message="API Key 无权访问该 Agent",
            )

    def require_workflow_access(self, workflow_id: str) -> None:
        if not self.can_access_workflow(workflow_id):
            raise ForbiddenError(
                code="APIKEY_WORKFLOW_DENIED",
                message="API Key 无权访问该 Workflow",
            )


async def get_api_key_principal(
    authorization: str = Header(None, description="Bearer af_live_xxx"),
) -> ApiKeyPrincipal:
    """FastAPI dependency: authenticate via API Key.

    Raises:
        UnauthorizedError: Missing header, invalid/expired/revoked Key.
    """
    from app.services.api_key_service import ApiKeyService

    if not authorization or not authorization.startswith("Bearer "):
        raise UnauthorizedError(
            code="APIKEY_MISSING",
            message="Missing or malformed Authorization header",
        )

    full_key = authorization.removeprefix("Bearer ").strip()

    if not full_key.startswith("af_live_"):
        raise UnauthorizedError(
            code="APIKEY_INVALID",
            message="Invalid or expired API Key",
        )

    doc = await ApiKeyService.verify_key(full_key)
    if doc is None:
        raise UnauthorizedError(
            code="APIKEY_INVALID",
            message="Invalid or expired API Key",
        )

    return ApiKeyPrincipal(
        key_id=doc["_id"],
        owner_user_id=doc["owner_user_id"],
        scopes=doc.get("scopes", []),
        bindings=doc.get("bindings", {}),
        rate_limit=doc.get("rate_limit", 60),
    )

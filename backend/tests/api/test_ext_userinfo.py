"""Tests for external API — /ext/userinfo (end-user name & binding count)."""
from unittest.mock import AsyncMock, patch

import pytest
from app.api.v1.ext import auth_and_rate_limit
from app.core.auth_apikey import ApiKeyPrincipal
from app.main import app
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def enduser_principal():
    """v4 principal with a resolved end-user platform_user_id."""
    return ApiKeyPrincipal(
        key_id="apikey_test",
        owner_user_id="user_owner",
        scopes=["agents:read"],
        bindings={"agents": [], "workflows": []},
        rate_limit=60,
        user_id="user_enduser",
    )


def _override_auth(principal):
    """Override the API Key auth dependency."""
    app.dependency_overrides[auth_and_rate_limit] = lambda: principal
    return lambda: app.dependency_overrides.clear()


class TestGetUserInfo:
    """GET /api/v1/ext/userinfo"""

    def test_userinfo_prefers_ext_username_over_numeric_sub(
        self, client, enduser_principal
    ) -> None:
        """显示名优先取 introspection 的 username——sub 的锚 v4.2 起是
        稳定用户 ID（如 754113802395538714 这类数字），直接抠 sub 会把
        数字 ID 当用户名显示。"""
        enduser_principal.ext_username = "alice_partner"
        cleanup = _override_auth(enduser_principal)
        try:
            with (
                patch(
                    "app.services.external_identity_service.ExternalIdentityService"
                    ".list_by_platform_user",
                    new=AsyncMock(return_value=[
                        {"sub": "app_01:754113802395538714", "platform_user_id": "user_enduser"},
                    ]),
                ),
                patch(
                    "app.services.user_mcp_credential_service.UserMcpCredentialService"
                    ".list_bindings",
                    new=AsyncMock(return_value={
                        "platform_user_id": "user_enduser",
                        "app_bindings": {"app_01": {}},
                    }),
                ),
            ):
                resp = client.get("/api/v1/ext/userinfo")
            assert resp.status_code == 200
            data = resp.json()
            assert data["name"] == "alice_partner"
            assert data["binding_count"] == 1
        finally:
            cleanup()

    def test_userinfo_with_identity_and_bindings(self, client, enduser_principal) -> None:
        """ext_username 提供显示名（鉴权链保证非空）；count from app_bindings."""
        enduser_principal.ext_username = "partner_user_42"
        cleanup = _override_auth(enduser_principal)
        try:
            with patch(
                "app.services.user_mcp_credential_service.UserMcpCredentialService"
                ".list_bindings",
                new=AsyncMock(return_value={
                    "platform_user_id": "user_enduser",
                    "app_bindings": {"app_01": {}, "app_02": {}},
                }),
            ):
                resp = client.get("/api/v1/ext/userinfo")
            assert resp.status_code == 200
            data = resp.json()
            assert data["name"] == "partner_user_42"
            assert data["binding_count"] == 2
        finally:
            cleanup()

    def test_userinfo_no_identity_falls_back(self, client, enduser_principal) -> None:
        """Without identities or bindings the generic fallback is returned."""
        cleanup = _override_auth(enduser_principal)
        try:
            with (
                patch(
                    "app.services.external_identity_service.ExternalIdentityService"
                    ".list_by_platform_user",
                    new=AsyncMock(return_value=[]),
                ),
                patch(
                    "app.services.user_mcp_credential_service.UserMcpCredentialService"
                    ".list_bindings",
                    new=AsyncMock(return_value=None),
                ),
            ):
                resp = client.get("/api/v1/ext/userinfo")
            assert resp.status_code == 200
            data = resp.json()
            assert data["name"] == "用户"
            assert data["binding_count"] == 0
        finally:
            cleanup()

"""Integration tests for /api/v1/auth endpoints."""
from unittest.mock import AsyncMock, patch

import pytest
from app.core.errors import UnauthorizedError, ValidationError
from app.core.security import get_current_user
from app.main import app
from app.schemas.auth import TokenResponse
from app.schemas.user import UserResponse, UserRole, UserStatus
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def override_auth():
    """Override get_current_user dependency for authenticated endpoints."""
    user = UserResponse(
        id="user_01HTEST",
        username="admin",
        email="admin@example.com",
        role=UserRole.ADMIN,
        status=UserStatus.ACTIVE,
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )
    app.dependency_overrides[get_current_user] = lambda: user
    yield
    app.dependency_overrides.clear()


def _make_tokens() -> TokenResponse:
    return TokenResponse(
        access_token="fake.access.token",
        refresh_token="fake.refresh.token",
    )


def _make_tokens() -> TokenResponse:
    return TokenResponse(
        access_token="fake.access.token",
        refresh_token="fake.refresh.token",
    )


class TestLoginEndpoint:
    """AC1 + AC2 + AC5: POST /api/v1/auth/login"""

    def test_login_success(self, client) -> None:
        with patch(
            "app.services.auth_service.AuthService.login",
            new=AsyncMock(return_value=_make_tokens()),
        ):
            resp = client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": "Strong1234"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["access_token"] == "fake.access.token"
        assert data["refresh_token"] == "fake.refresh.token"
        assert data["token_type"] == "bearer"
        assert data["expires_in"] == 900

    def test_login_invalid_credentials(self, client) -> None:
        with patch(
            "app.services.auth_service.AuthService.login",
            new=AsyncMock(
                side_effect=UnauthorizedError(
                    code="INVALID_CREDENTIALS",
                    message="用户名或密码错误",
                )
            ),
        ):
            resp = client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": "wrong"},
            )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "INVALID_CREDENTIALS"

    def test_login_locked_account(self, client) -> None:
        with patch(
            "app.services.auth_service.AuthService.login",
            new=AsyncMock(
                side_effect=UnauthorizedError(
                    code="ACCOUNT_LOCKED",
                    message="账户已锁定，请 15 分钟后重试",
                )
            ),
        ):
            resp = client.post(
                "/api/v1/auth/login",
                json={"username": "admin", "password": "whatever"},
            )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "ACCOUNT_LOCKED"


class TestRefreshEndpoint:
    """AC4: POST /api/v1/auth/refresh"""

    def test_refresh_success(self, client) -> None:
        new_tokens = TokenResponse(
            access_token="new.access.token",
            refresh_token="kept.refresh.token",
        )
        with patch(
            "app.services.auth_service.AuthService.refresh_token",
            new=AsyncMock(return_value=new_tokens),
        ):
            resp = client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": "valid.refresh.token"},
            )
        assert resp.status_code == 200
        assert resp.json()["access_token"] == "new.access.token"

    def test_refresh_invalid_token(self, client) -> None:
        with patch(
            "app.services.auth_service.AuthService.refresh_token",
            new=AsyncMock(
                side_effect=UnauthorizedError(
                    code="TOKEN_INVALID",
                    message="Invalid token",
                )
            ),
        ):
            resp = client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": "invalid.token"},
            )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "TOKEN_INVALID"


class TestChangePasswordEndpoint:
    """AC1: POST /api/v1/auth/change-password"""

    def test_change_password_200(self, client, override_auth) -> None:
        """AC1: Successful password change returns 200."""
        with patch(
            "app.services.auth_service.AuthService.change_password",
            new=AsyncMock(),
        ):
            resp = client.post(
                "/api/v1/auth/change-password",
                json={
                    "current_password": "OldPass123",
                    "new_password": "NewPass567",
                },
            )
        assert resp.status_code == 200
        assert resp.json()["message"] == "密码已修改，请重新登录"

    def test_change_password_401_unauthorized(self, client) -> None:
        """AC1: No auth header → 401."""
        resp = client.post(
            "/api/v1/auth/change-password",
            json={
                "current_password": "OldPass123",
                "new_password": "NewPass567",
            },
        )
        assert resp.status_code == 401

    def test_change_password_422_weak(self, client, override_auth) -> None:
        """AC1: Weak new password → 422."""
        with patch(
            "app.services.auth_service.AuthService.change_password",
            new=AsyncMock(
                side_effect=ValidationError(
                    code="PASSWORD_TOO_SHORT",
                    message="密码至少 8 字符且必须包含字母和数字",
                )
            ),
        ):
            resp = client.post(
                "/api/v1/auth/change-password",
                json={
                    "current_password": "OldPass123",
                    "new_password": "short",
                },
            )
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "PASSWORD_TOO_SHORT"


class TestLogoutEndpoint:
    """AC2: POST /api/v1/auth/logout"""

    def test_logout_200(self, client) -> None:
        """AC2: Successful logout returns 200."""
        with patch(
            "app.services.auth_service.AuthService.logout",
            new=AsyncMock(),
        ):
            resp = client.post(
                "/api/v1/auth/logout",
                json={"refresh_token": "some.valid.token"},
            )
        assert resp.status_code == 200
        assert resp.json()["message"] == "已注销"

    def test_logout_idempotent(self, client) -> None:
        """AC2: Repeated logout returns 200 (idempotent)."""
        with patch(
            "app.services.auth_service.AuthService.logout",
            new=AsyncMock(),
        ):
            resp1 = client.post(
                "/api/v1/auth/logout",
                json={"refresh_token": "some.token"},
            )
            resp2 = client.post(
                "/api/v1/auth/logout",
                json={"refresh_token": "some.token"},
            )
        assert resp1.status_code == 200
        assert resp2.status_code == 200

    def test_refresh_after_logout(self, client) -> None:
        """AC3: Logged-out token cannot refresh."""
        with patch(
            "app.services.auth_service.AuthService.refresh_token",
            new=AsyncMock(
                side_effect=UnauthorizedError(
                    code="TOKEN_REVOKED",
                    message="Token has been revoked",
                )
            ),
        ):
            resp = client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": "revoked.token"},
            )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "TOKEN_REVOKED"

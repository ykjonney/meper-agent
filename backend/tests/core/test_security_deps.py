"""Tests for JWT Depends — get_current_user / get_current_user_optional."""
from unittest.mock import AsyncMock, patch

import pytest
from app.core.errors import UnauthorizedError
from app.core.security import create_access_token, create_refresh_token
from app.schemas.user import UserResponse


def _make_user_response() -> UserResponse:
    return UserResponse(
        id="user_01HTEST",
        username="admin",
        email="admin@example.com",
        role="admin",
        status="active",
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
        last_login_at=None,
    )


def _make_user_doc(status="active") -> dict:
    return {
        "_id": "user_01HTEST",
        "username": "admin",
        "email": "admin@example.com",
        "password_hash": "$2b$12$hash",
        "role": "admin",
        "status": status,
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
        "last_login_at": None,
    }


class TestGetCurrentUser:
    """AC3: JWT auth dependency."""

    async def test_valid_access_token(self) -> None:
        """Valid access token returns UserResponse."""
        from app.core.security import get_current_user

        token = create_access_token(
            subject="user_01HTEST", claims={"role": "admin"}
        )

        with patch(
            "app.services.user_service.UserService.get_user_by_id",
            new=AsyncMock(return_value=_make_user_doc()),
        ):
            user = await get_current_user(authorization=f"Bearer {token}")

        assert isinstance(user, UserResponse)
        assert user.id == "user_01HTEST"
        assert user.role == "admin"

    async def test_missing_authorization_header(self) -> None:
        """Missing Authorization header returns 401."""
        from app.core.security import get_current_user

        with pytest.raises(UnauthorizedError) as exc:
            await get_current_user(authorization="")
        assert exc.value.code == "TOKEN_INVALID"

    async def test_wrong_token_type(self) -> None:
        """Using refresh token instead of access token returns 401."""
        from app.core.security import get_current_user

        refresh = create_refresh_token(subject="user_01HTEST")

        with pytest.raises(UnauthorizedError) as exc:
            await get_current_user(authorization=f"Bearer {refresh}")
        assert "type" in exc.value.message.lower() or "TOKEN" in exc.value.code

    async def test_disabled_user_rejected(self) -> None:
        """Disabled user's valid token returns 401."""
        from app.core.security import get_current_user

        token = create_access_token(
            subject="user_01HTEST", claims={"role": "admin"}
        )

        with patch(
            "app.services.user_service.UserService.get_user_by_id",
            new=AsyncMock(return_value=_make_user_doc(status="disabled")),
        ):
            with pytest.raises(UnauthorizedError) as exc:
                await get_current_user(authorization=f"Bearer {token}")
            assert exc.value.code == "ACCOUNT_DISABLED"

    async def test_user_not_found(self) -> None:
        """Valid token but user deleted returns 401."""
        from app.core.security import get_current_user

        token = create_access_token(
            subject="user_01HTEST", claims={"role": "admin"}
        )

        with patch(
            "app.services.user_service.UserService.get_user_by_id",
            new=AsyncMock(return_value=None),
        ):
            with pytest.raises(UnauthorizedError) as exc:
                await get_current_user(authorization=f"Bearer {token}")
            assert exc.value.code == "USER_NOT_FOUND"


class TestGetCurrentUserOptional:
    """Optional auth — returns None instead of raising."""

    async def test_no_header_returns_none(self) -> None:
        from app.core.security import get_current_user_optional

        result = await get_current_user_optional(authorization=None)
        assert result is None

    async def test_valid_token_returns_user(self) -> None:
        from app.core.security import get_current_user_optional

        token = create_access_token(
            subject="user_01HTEST", claims={"role": "admin"}
        )

        with patch(
            "app.services.user_service.UserService.get_user_by_id",
            new=AsyncMock(return_value=_make_user_doc()),
        ):
            user = await get_current_user_optional(
                authorization=f"Bearer {token}"
            )
        assert isinstance(user, UserResponse)

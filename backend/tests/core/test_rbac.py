"""Tests for RBAC — require_role / require_any_role / has_permission / ROLE_PERMISSIONS."""

import pytest
from app.core.errors import ForbiddenError
from app.core.security import has_permission, require_any_role, require_role
from app.models.user import UserRole
from app.schemas.user import UserResponse


def _make_admin() -> UserResponse:
    return UserResponse(
        id="user_01HADMIN",
        username="admin",
        email="admin@example.com",
        role=UserRole.ADMIN,
        status="active",
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
        last_login_at=None,
    )


def _make_developer() -> UserResponse:
    return UserResponse(
        id="user_01HDEV",
        username="dev",
        email="dev@example.com",
        role=UserRole.DEVELOPER,
        status="active",
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
        last_login_at=None,
    )


def _make_operator() -> UserResponse:
    return UserResponse(
        id="user_01HOP",
        username="op",
        email="op@example.com",
        role=UserRole.OPERATOR,
        status="active",
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
        last_login_at=None,
    )


def _make_viewer() -> UserResponse:
    return UserResponse(
        id="user_01HVIEW",
        username="viewer",
        email="viewer@example.com",
        role=UserRole.VIEWER,
        status="active",
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
        last_login_at=None,
    )


class TestRequireRole:
    """AC6: require_role decorator checks exact role match."""

    async def test_admin_allowed(self) -> None:
        """Admin user passes require_role(admin)."""
        check = require_role(UserRole.ADMIN)
        result = await check(_make_admin())
        assert result.role == UserRole.ADMIN

    async def test_developer_rejected_by_admin_guard(self) -> None:
        """Developer fails require_role(admin) with ForbiddenError."""
        check = require_role(UserRole.ADMIN)
        with pytest.raises(ForbiddenError) as exc:
            await check(_make_developer())
        assert exc.value.code == "FORBIDDEN"

    async def test_operator_rejected_by_admin_guard(self) -> None:
        """Operator fails require_role(admin)."""
        check = require_role(UserRole.ADMIN)
        with pytest.raises(ForbiddenError):
            await check(_make_operator())

    async def test_viewer_rejected_by_admin_guard(self) -> None:
        """Viewer fails require_role(admin)."""
        check = require_role(UserRole.ADMIN)
        with pytest.raises(ForbiddenError):
            await check(_make_viewer())

    async def test_developer_allowed(self) -> None:
        """Developer passes require_role(developer)."""
        check = require_role(UserRole.DEVELOPER)
        result = await check(_make_developer())
        assert result.role == UserRole.DEVELOPER

    async def test_string_role_works(self) -> None:
        """require_role accepts string role name."""
        check = require_role("admin")
        result = await check(_make_admin())
        assert result.role == UserRole.ADMIN


class TestRequireAnyRole:
    """AC6: require_any_role accepts multiple roles."""

    async def test_admin_allowed_with_admin_or_dev(self) -> None:
        """Admin passes require_any_role(admin, developer)."""
        check = require_any_role(UserRole.ADMIN, UserRole.DEVELOPER)
        result = await check(_make_admin())
        assert result.role == UserRole.ADMIN

    async def test_developer_allowed_with_admin_or_dev(self) -> None:
        """Developer passes require_any_role(admin, developer)."""
        check = require_any_role(UserRole.ADMIN, UserRole.DEVELOPER)
        result = await check(_make_developer())
        assert result.role == UserRole.DEVELOPER

    async def test_operator_rejected_by_admin_or_dev(self) -> None:
        """Operator fails require_any_role(admin, developer)."""
        check = require_any_role(UserRole.ADMIN, UserRole.DEVELOPER)
        with pytest.raises(ForbiddenError):
            await check(_make_operator())

    async def test_all_roles_accepts_everyone(self) -> None:
        """require_any_role with all 4 roles accepts everyone."""
        check = require_any_role(
            UserRole.ADMIN, UserRole.DEVELOPER, UserRole.OPERATOR, UserRole.VIEWER
        )
        for maker in [_make_admin, _make_developer, _make_operator, _make_viewer]:
            result = await check(maker())
            assert result is not None


class TestHasPermission:
    """AC7: Permission matrix queries."""

    def test_admin_has_user_read(self) -> None:
        assert has_permission("admin", "user:read") is True

    def test_developer_has_no_user_read(self) -> None:
        assert has_permission("developer", "user:read") is False

    def test_operator_has_no_user_read(self) -> None:
        assert has_permission("operator", "user:read") is False

    def test_viewer_has_no_user_read(self) -> None:
        assert has_permission("viewer", "user:read") is False

    def test_admin_has_agent_write(self) -> None:
        assert has_permission("admin", "agent:write") is True

    def test_developer_has_agent_write(self) -> None:
        assert has_permission("developer", "agent:write") is True

    def test_operator_has_no_agent_write(self) -> None:
        assert has_permission("operator", "agent:write") is False

    def test_viewer_has_agent_read(self) -> None:
        assert has_permission("viewer", "agent:read") is True

    def test_operator_has_invoke(self) -> None:
        assert has_permission("operator", "agent:invoke") is True

    def test_admin_has_apikey_manage(self) -> None:
        assert has_permission("admin", "apikey:manage") is True

    def test_developer_has_no_apikey_manage(self) -> None:
        assert has_permission("developer", "apikey:manage") is False

    def test_unknown_permission_returns_false(self) -> None:
        assert has_permission("admin", "unknown:perm") is False

    def test_unknown_role_returns_false(self) -> None:
        assert has_permission("superadmin", "user:read") is False

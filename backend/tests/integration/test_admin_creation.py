"""Integration tests for admin user creation against real MongoDB.

Verifies the ``_admin_exists()`` guard that prevents creating a
second admin account — a core security invariant that is hard to
test convincingly with mocks.
"""
import pytest
from app.core.errors import ForbiddenError, ValidationError
from app.services.user_service import UserService

pytestmark = pytest.mark.integration


class TestAdminCreationGuard:
    """``create_admin_user`` must reject duplicate admin registration."""

    async def test_create_first_admin_succeeds(
        self,
        mock_collection: None,  # noqa: ARG002
    ) -> None:
        """AC1: The very first admin creation completes successfully."""
        result = await UserService.create_admin_user(
            username="admin",
            password="Strong5678",
            email="admin@example.com",
        )

        assert result.user_id is not None
        assert result.username == "admin"
        assert result.tokens is not None
        assert result.tokens.access_token is not None
        assert result.tokens.refresh_token is not None

    async def test_create_duplicate_admin_raises(
        self,
        mock_collection: None,  # noqa: ARG002
    ) -> None:
        """AC2: A second ``create_admin_user`` call is rejected."""
        # First admin — succeeds
        await UserService.create_admin_user(
            username="admin1",
            password="Strong5678",
            email="admin1@example.com",
        )

        # Second admin — must be rejected
        with pytest.raises(ForbiddenError) as exc:
            await UserService.create_admin_user(
                username="admin2",
                password="Strong5678",
                email="admin2@example.com",
            )
        assert exc.value.code == "ADMIN_ALREADY_EXISTS"
        assert "管理员账户已存在" in exc.value.message

    async def test_create_admin_after_deleted_admin_succeeds(
        self,
        users_collection,  # noqa: ARG002
        mock_collection: None,  # noqa: ARG002
    ) -> None:
        """After deleting the only admin, a new admin can be created."""
        # Create then delete the first admin
        first = await UserService.create_admin_user(
            username="admin1",
            password="Strong5678",
            email="admin1@example.com",
        )

        col = UserService._collection()
        await col.delete_one({"_id": first.user_id})

        # Now creating a new admin should succeed
        result = await UserService.create_admin_user(
            username="admin2",
            password="Strong5678",
            email="admin2@example.com",
        )
        assert result.username == "admin2"

    async def test_admin_exists_flag(
        self,
        mock_collection: None,  # noqa: ARG002
    ) -> None:
        """``_admin_exists()`` correctly reflects database state."""
        # Before — no admin
        assert await UserService._admin_exists() is False

        # Create admin
        await UserService.create_admin_user(
            username="boss",
            password="Strong5678",
            email="boss@example.com",
        )

        # After — admin exists
        assert await UserService._admin_exists() is True


class TestAdminCreationValidation:
    """Input validation in ``create_admin_user`` against real DB."""

    async def test_weak_password_rejected(
        self,
        mock_collection: None,  # noqa: ARG002
    ) -> None:
        """AC3: Weak passwords raise ``ValidationError`` before any DB write."""
        with pytest.raises(ValidationError) as exc:
            await UserService.create_admin_user(
                username="admin",
                password="weak",
                email="admin@example.com",
            )
        assert "PASSWORD" in exc.value.code

    async def test_duplicate_username_rejected(
        self,
        mock_collection: None,  # noqa: ARG002
    ) -> None:
        """Duplicate username is detected by ``get_user_by_username``."""
        await UserService.create_admin_user(
            username="admin",
            password="Strong5678",
            email="admin@example.com",
        )

        doc = await UserService.get_user_by_username("admin")
        assert doc is not None
        assert doc["username"] == "admin"

    async def test_duplicate_email_rejected(
        self,
        mock_collection: None,  # noqa: ARG002
    ) -> None:
        """Duplicate email is detected by ``get_user_by_email``."""
        await UserService.create_admin_user(
            username="admin",
            password="Strong5678",
            email="admin@example.com",
        )

        doc = await UserService.get_user_by_email("admin@example.com")
        assert doc is not None
        assert doc["email"] == "admin@example.com"

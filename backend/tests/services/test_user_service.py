"""Tests for services/user_service.py — admin creation and lookups."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.core.errors import ForbiddenError, ValidationError
from app.services.user_service import UserService


@pytest.fixture
def mock_collection():
    """Mock the async MongoDB users collection."""
    with patch.object(UserService, "_collection") as mock:
        col = MagicMock()
        # Motor collection returns coroutines — use AsyncMock for async methods
        col.find_one = AsyncMock()
        col.insert_one = AsyncMock()
        mock.return_value = col
        yield col


class TestCreateAdminUser:
    """Test UserService.create_admin_user (AC1, AC2, AC4, AC5)."""

    async def test_creates_admin_successfully(
        self, mock_collection: MagicMock
    ) -> None:
        """AC1: First admin is created when no users exist."""
        mock_collection.find_one.return_value = None  # no admin, no conflicts

        result = await UserService.create_admin_user(
            username="admin",
            password="Strong1234",
            email="admin@example.com",
        )

        assert result.username == "admin"
        assert result.message.startswith("管理员账户已创建")
        assert result.user_id.startswith("user_")
        assert result.tokens.access_token
        assert result.tokens.refresh_token
        assert result.tokens.token_type == "bearer"
        assert result.tokens.expires_in == 900  # 15 * 60

        # Verify insert was called with _id (not id)
        mock_collection.insert_one.assert_called_once()
        inserted_doc = mock_collection.insert_one.call_args[0][0]
        assert inserted_doc["_id"].startswith("user_")
        assert inserted_doc["username"] == "admin"
        assert inserted_doc["email"] == "admin@example.com"
        assert inserted_doc["password_hash"] != "Strong1234"  # hashed, not plaintext
        assert inserted_doc["role"] == "admin"
        assert "created_at" in inserted_doc
        assert "updated_at" in inserted_doc

    async def test_rejects_when_admin_exists(
        self, mock_collection: MagicMock
    ) -> None:
        """AC2: Cannot create admin when one already exists."""
        mock_collection.find_one.side_effect = [
            {"id": "user_existing", "role": "admin"},  # _admin_exists returns True
        ]

        with pytest.raises(ForbiddenError) as exc:
            await UserService.create_admin_user(
                username="admin2",
                password="Strong1234",
                email="admin2@example.com",
            )
        assert exc.value.code == "ADMIN_ALREADY_EXISTS"
        assert "管理员账户已存在" in exc.value.message

    async def test_rejects_duplicate_username(
        self, mock_collection: MagicMock
    ) -> None:
        """AC5: Cannot create user with existing username."""
        mock_collection.find_one.side_effect = [
            None,  # no admin
            {"username": "admin"},  # username taken
        ]

        with pytest.raises(ValidationError) as exc:
            await UserService.create_admin_user(
                username="admin",
                password="Strong1234",
                email="new@example.com",
            )
        assert exc.value.code == "USER_REGISTER_CONFLICT"
        assert exc.value.details.get("field") == "username"

    async def test_rejects_duplicate_email(
        self, mock_collection: MagicMock
    ) -> None:
        """AC5: Cannot create user with existing email."""
        mock_collection.find_one.side_effect = [
            None,  # no admin
            None,  # username ok
            {"email": "admin@example.com"},  # email taken
        ]

        with pytest.raises(ValidationError) as exc:
            await UserService.create_admin_user(
                username="newadmin",
                password="Strong1234",
                email="admin@example.com",
            )
        assert exc.value.code == "USER_REGISTER_CONFLICT"
        assert exc.value.details.get("field") == "email"


class TestUserLookups:
    """Test lookup helpers."""

    async def test_get_user_by_username(self, mock_collection: MagicMock) -> None:
        mock_collection.find_one.return_value = {"username": "admin"}
        result = await UserService.get_user_by_username("admin")
        assert result is not None
        assert result["username"] == "admin"
        mock_collection.find_one.assert_called_with({"username": "admin"})

    async def test_get_user_by_email(self, mock_collection: MagicMock) -> None:
        mock_collection.find_one.return_value = {"email": "a@b.com"}
        result = await UserService.get_user_by_email("a@b.com")
        assert result is not None

    async def test_get_user_returns_none_when_not_found(
        self, mock_collection: MagicMock
    ) -> None:
        mock_collection.find_one.return_value = None
        assert await UserService.get_user_by_username("nobody") is None
        assert await UserService.get_user_by_email("nobody@nowhere.com") is None

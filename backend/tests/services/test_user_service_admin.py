"""Tests for UserService admin operations — list, create, update, delete, reset password."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.core.errors import ValidationError
from app.services.user_service import UserService


class AsyncIterator:
    """Wrap items in an async iterator (for cursor mock)."""

    def __init__(self, items):
        self._items = items

    async def to_list(self, length):
        return self._items[:length]


class MockMongoCursor:
    """Motor cursor mock — find() returns this sync."""

    def __init__(self, items):
        self._items = items

    def sort(self, key, direction):
        return self

    def skip(self, n):
        return self

    def limit(self, n):
        return self

    async def to_list(self, length):
        return self._items[:length]


@pytest.fixture
def mock_collection():
    """Mock the async MongoDB users collection."""
    with patch.object(UserService, "_collection") as mock:
        col = MagicMock()
        col.find_one = AsyncMock()
        col.find = MagicMock()
        col.insert_one = AsyncMock()
        col.update_one = AsyncMock()
        col.delete_one = AsyncMock()
        col.count_documents = AsyncMock()
        mock.return_value = col
        yield col


def _make_admin_doc(_id="user_01HADMIN", username="admin", status="active"):
    return {
        "_id": _id,
        "username": username,
        "email": f"{username}@example.com",
        "password_hash": "$2b$12$hash",
        "role": "admin",
        "status": status,
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
        "last_login_at": None,
    }


def _make_user_doc(_id="user_01HDEV", username="dev", role="developer", status="active"):
    return {
        "_id": _id,
        "username": username,
        "email": f"{username}@example.com",
        "password_hash": "$2b$12$hash",
        "role": role,
        "status": status,
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
        "last_login_at": None,
    }


class TestListUsers:
    """AC1: Admin can list users with pagination and filtering."""

    async def test_list_all_users(self, mock_collection) -> None:
        """Returns paginated user list."""
        docs = [_make_admin_doc(), _make_user_doc()]
        mock_collection.count_documents.return_value = 2
        mock_collection.find.return_value = MockMongoCursor(docs)

        items, total = await UserService.list_users(page=1, page_size=20)

        assert total == 2
        assert len(items) == 2
        mock_collection.count_documents.assert_called_once_with({})

    async def test_list_users_with_filters(self, mock_collection) -> None:
        """Filters by username, role, and status."""
        mock_collection.count_documents.return_value = 1
        mock_collection.find.return_value = MockMongoCursor([_make_user_doc()])

        items, total = await UserService.list_users(
            page=1, page_size=20, role="developer", status="active"
        )

        assert total == 1
        # Verify filter was passed
        call_kwargs = mock_collection.count_documents.call_args[0][0]
        assert call_kwargs.get("role") == "developer"
        assert call_kwargs.get("status") == "active"

    async def test_list_users_empty(self, mock_collection) -> None:
        """Returns empty list when no users match."""
        mock_collection.count_documents.return_value = 0
        mock_collection.find.return_value = MockMongoCursor([])

        items, total = await UserService.list_users(page=1, page_size=20)

        assert total == 0
        assert len(items) == 0


class TestCreateUserByAdmin:
    """AC2: Admin can create users."""

    async def test_create_user_success(self, mock_collection) -> None:
        """Creates a user successfully."""
        mock_collection.find_one.return_value = None  # no conflicts
        mock_collection.insert_one.return_value = AsyncMock()

        doc = await UserService.create_user_by_admin(
            username="newuser",
            email="new@example.com",
            password="Strong1234",
            role="developer",
        )

        assert doc["username"] == "newuser"
        assert doc["role"] == "developer"
        assert doc["status"] == "active"
        assert "password_hash" in doc
        mock_collection.insert_one.assert_called_once()

    async def test_create_user_username_conflict(self, mock_collection) -> None:
        """Raises ValidationError on duplicate username."""
        mock_collection.find_one.side_effect = [
            {"_id": "existing", "username": "newuser"},
            None,
        ]

        with pytest.raises(ValidationError) as exc:
            await UserService.create_user_by_admin(
                username="newuser",
                email="new@example.com",
                password="Strong1234",
                role="developer",
            )
        assert exc.value.code == "USERNAME_CONFLICT"

    async def test_create_user_email_conflict(self, mock_collection) -> None:
        """Raises ValidationError on duplicate email."""
        mock_collection.find_one.side_effect = [
            None,
            {"_id": "existing", "email": "new@example.com"},
        ]

        with pytest.raises(ValidationError) as exc:
            await UserService.create_user_by_admin(
                username="newuser",
                email="new@example.com",
                password="Strong1234",
                role="developer",
            )
        assert exc.value.code == "EMAIL_CONFLICT"

    async def test_create_user_weak_password(self, mock_collection) -> None:
        """Raises ValidationError on weak password."""
        with pytest.raises(ValidationError) as exc:
            await UserService.create_user_by_admin(
                username="newuser",
                email="new@example.com",
                password="weak",
                role="developer",
            )
        assert "PASSWORD" in exc.value.code


class TestUpdateUser:
    """AC3: Admin can update user info."""

    async def test_update_role(self, mock_collection) -> None:
        """Updates user role successfully."""
        mock_collection.find_one.return_value = _make_user_doc()

        result = await UserService.update_user(
            user_id="user_01HDEV",
            updates={"role": "operator"},
            current_user_id="user_01HADMIN",
        )

        assert result is not None
        mock_collection.update_one.assert_called_once()

    async def test_update_user_not_found(self, mock_collection) -> None:
        """Raises NotFoundError when user doesn't exist."""
        mock_collection.find_one.return_value = None

        result = await UserService.update_user(
            user_id="user_nonexistent",
            updates={"role": "operator"},
            current_user_id="user_01HADMIN",
        )
        assert result is None

    async def test_cannot_demote_self(self, mock_collection) -> None:
        """Cannot demote own admin role (permission suicide)."""
        mock_collection.find_one.return_value = _make_admin_doc(
            _id="user_01HADMIN", username="admin"
        )

        with pytest.raises(ValidationError) as exc:
            await UserService.update_user(
                user_id="user_01HADMIN",
                updates={"role": "developer"},
                current_user_id="user_01HADMIN",
            )
        assert "self" in exc.value.code.lower() or "PERMISSION" in exc.value.code

    async def test_cannot_disable_last_admin(self, mock_collection) -> None:
        """Cannot disable the last admin."""
        # Only one admin in the system
        mock_collection.find_one.return_value = _make_admin_doc()
        mock_collection.count_documents.return_value = 1

        with pytest.raises(ValidationError) as exc:
            await UserService.update_user(
                user_id="user_01HADMIN",
                updates={"status": "disabled"},
                current_user_id="user_02HANOTHER",
            )
        assert "LAST_ADMIN" in exc.value.code


class TestDeleteUser:
    """AC4: Admin can delete users."""

    async def test_delete_user_success(self, mock_collection) -> None:
        """Deletes a user successfully."""
        mock_collection.find_one.return_value = _make_user_doc()
        mock_collection.delete_one.return_value = MagicMock(deleted_count=1)

        result = await UserService.delete_user(
            user_id="user_01HDEV",
            current_user_id="user_01HADMIN",
        )
        assert result is True

    async def test_cannot_delete_self(self, mock_collection) -> None:
        """Cannot delete own account."""
        with pytest.raises(ValidationError) as exc:
            await UserService.delete_user(
                user_id="user_01HADMIN",
                current_user_id="user_01HADMIN",
            )
        assert "SELF" in exc.value.code

    async def test_cannot_delete_last_admin(self, mock_collection) -> None:
        """Cannot delete the last admin."""
        mock_collection.find_one.return_value = _make_admin_doc()
        mock_collection.count_documents.return_value = 1

        with pytest.raises(ValidationError) as exc:
            await UserService.delete_user(
                user_id="user_01HADMIN",
                current_user_id="user_02HANOTHER",
            )
        assert "LAST_ADMIN" in exc.value.code

    async def test_delete_user_not_found(self, mock_collection) -> None:
        """Returns False when user not found."""
        mock_collection.find_one.return_value = None

        result = await UserService.delete_user(
            user_id="user_nonexistent",
            current_user_id="user_01HADMIN",
        )
        assert result is False


class TestResetPassword:
    """AC5: Admin can reset user password."""

    async def test_reset_password_success(self, mock_collection) -> None:
        """Resets password successfully."""
        mock_collection.find_one.return_value = _make_user_doc()
        mock_collection.update_one.return_value = AsyncMock()
        mock_collection.update_one.return_value.modified_count = 1

        result = await UserService.reset_password(
            user_id="user_01HDEV",
            new_password="NewStrong5678",
        )
        assert result is True
        mock_collection.update_one.assert_called_once()

    async def test_reset_password_weak(self, mock_collection) -> None:
        """Rejects weak password."""
        with pytest.raises(ValidationError):
            await UserService.reset_password(
                user_id="user_01HDEV",
                new_password="weak",
            )

    async def test_reset_password_user_not_found(self, mock_collection) -> None:
        """Returns False when user not found."""
        mock_collection.find_one.return_value = None

        result = await UserService.reset_password(
            user_id="user_nonexistent",
            new_password="NewStrong5678",
        )
        assert result is False

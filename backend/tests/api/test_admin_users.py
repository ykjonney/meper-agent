"""Integration tests for admin user management API endpoints.

All endpoints require JWT auth + admin role.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.core.security import create_access_token
from fastapi.testclient import TestClient


@pytest.fixture
def admin_token() -> str:
    """Generate a valid admin JWT."""
    return create_access_token(
        subject="user_01HADMIN",
        claims={"role": "admin"},
    )


@pytest.fixture
def dev_token() -> str:
    """Generate a valid developer JWT."""
    return create_access_token(
        subject="user_01HDEV",
        claims={"role": "developer"},
    )


def _make_admin_doc():
    return {
        "_id": "user_01HADMIN",
        "username": "admin",
        "email": "admin@example.com",
        "password_hash": "$2b$12$hash",
        "role": "admin",
        "status": "active",
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
        "last_login_at": None,
    }


def _make_user_docs():
    return [
        {
            "_id": "user_01HUSER1",
            "username": "zhangsan",
            "email": "zhangsan@example.com",
            "password_hash": "$2b$12$hash",
            "role": "developer",
            "status": "active",
            "created_at": "2026-01-02T00:00:00",
            "updated_at": "2026-01-02T00:00:00",
            "last_login_at": None,
        },
        {
            "_id": "user_01HUSER2",
            "username": "lisi",
            "email": "lisi@example.com",
            "password_hash": "$2b$12$hash",
            "role": "operator",
            "status": "active",
            "created_at": "2026-01-03T00:00:00",
            "updated_at": "2026-01-03T00:00:00",
            "last_login_at": None,
        },
    ]


class MockMongoCursor:
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


def test_list_users_as_admin(client: TestClient, admin_token: str) -> None:
    """AC1: Admin can list users."""
    docs = [_make_admin_doc()] + _make_user_docs()

    with (
        patch("app.services.user_service.UserService._collection") as mock_col,
        patch("app.services.user_service.UserService.get_user_by_id") as mock_get_user,
    ):
        col = MagicMock()
        col.count_documents = AsyncMock(return_value=len(docs))
        col.find = MagicMock(return_value=MockMongoCursor(docs))
        mock_col.return_value = col
        mock_get_user.return_value = _make_admin_doc()

        resp = client.get(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == len(docs)
    assert len(data["items"]) == len(docs)
    assert data["page"] == 1
    assert data["page_size"] == 20
    # Verify password_hash is NOT in response
    assert "password_hash" not in data["items"][0]


def test_list_users_pagination(client: TestClient, admin_token: str) -> None:
    """AC1: Pagination params work."""
    docs = _make_user_docs()

    with (
        patch("app.services.user_service.UserService._collection") as mock_col,
        patch("app.services.user_service.UserService.get_user_by_id") as mock_get_user,
    ):
        col = MagicMock()
        col.count_documents = AsyncMock(return_value=10)
        col.find = MagicMock(return_value=MockMongoCursor(docs))
        mock_col.return_value = col
        mock_get_user.return_value = _make_admin_doc()

        resp = client.get(
            "/api/v1/admin/users?page=2&page_size=10",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["page"] == 2
    assert data["page_size"] == 10


def test_list_users_forbidden_for_dev(client: TestClient, dev_token: str) -> None:
    """AC6: Non-admin gets 403."""
    with patch("app.services.user_service.UserService.get_user_by_id") as mock_get_user:
        mock_get_user.return_value = {
            "_id": "user_01HDEV",
            "username": "dev",
            "email": "dev@example.com",
            "password_hash": "$2b$12$hash",
            "role": "developer",
            "status": "active",
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
            "last_login_at": None,
        }
        resp = client.get(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {dev_token}"},
        )

    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "FORBIDDEN"


def test_list_users_unauthorized(client: TestClient) -> None:
    """AC6: No token gets 401."""
    resp = client.get("/api/v1/admin/users")
    assert resp.status_code == 401


def test_create_user_as_admin(client: TestClient, admin_token: str) -> None:
    """AC2: Admin can create user."""
    with (
        patch("app.services.user_service.UserService._collection") as mock_col,
        patch("app.services.user_service.UserService.get_user_by_id") as mock_get_user,
    ):
        col = MagicMock()
        col.find_one = AsyncMock(return_value=None)  # no conflicts
        col.insert_one = AsyncMock()
        mock_col.return_value = col
        mock_get_user.return_value = _make_admin_doc()

        resp = client.post(
            "/api/v1/admin/users",
            json={
                "username": "newuser",
                "email": "new@example.com",
                "password": "Strong1234",
                "role": "developer",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert resp.status_code == 201
    data = resp.json()
    assert data["username"] == "newuser"
    assert data["role"] == "developer"
    assert data["status"] == "active"
    assert "password_hash" not in data


def test_create_user_weak_password(client: TestClient, admin_token: str) -> None:
    """AC2: Weak password returns 422."""
    with patch("app.services.user_service.UserService.get_user_by_id") as mock_get_user:
        mock_get_user.return_value = _make_admin_doc()
        resp = client.post(
            "/api/v1/admin/users",
            json={
                "username": "newuser",
                "email": "new@example.com",
                "password": "weak",
                "role": "developer",
            },
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert resp.status_code == 422


def test_update_user_as_admin(client: TestClient, admin_token: str) -> None:
    """AC3: Admin can update user role."""
    target_doc = {
        "_id": "user_01HUSER1",
        "username": "zhangsan",
        "email": "zhangsan@example.com",
        "password_hash": "$2b$12$hash",
        "role": "developer",
        "status": "active",
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
        "last_login_at": None,
    }
    updated_doc = {**target_doc, "role": "operator", "updated_at": "2026-06-09T00:00:00"}

    async def _get_user_side_effect(user_id):
        if user_id == "user_01HADMIN":
            return _make_admin_doc()
        if user_id == "user_01HUSER1":
            return updated_doc
        return None

    with (
        patch(
            "app.services.user_service.UserService.get_user_by_id",
            side_effect=_get_user_side_effect,
        ),
        patch("app.services.user_service.UserService._collection") as mock_col,
    ):
        col = MagicMock()
        col.update_one = AsyncMock()
        col.count_documents = AsyncMock(return_value=2)  # more than 1 admin
        mock_col.return_value = col

        resp = client.patch(
            "/api/v1/admin/users/user_01HUSER1",
            json={"role": "operator"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["role"] == "operator"


def test_update_user_not_found(client: TestClient, admin_token: str) -> None:
    """AC3: User not found returns 404."""
    async def _side_effect(user_id):
        if user_id == "user_01HADMIN":
            return _make_admin_doc()
        return None

    with patch(
        "app.services.user_service.UserService.get_user_by_id",
        side_effect=_side_effect,
    ):
        resp = client.patch(
            "/api/v1/admin/users/user_nonexistent",
            json={"role": "operator"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert resp.status_code == 404


def test_delete_user_as_admin(client: TestClient, admin_token: str) -> None:
    """AC4: Admin can delete user."""
    async def _side_effect(user_id):
        if user_id == "user_01HADMIN":
            return _make_admin_doc()
        return {
            "_id": "user_01HUSER1",
            "username": "zhangsan",
            "email": "zhangsan@example.com",
            "password_hash": "$2b$12$hash",
            "role": "developer",
            "status": "active",
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
            "last_login_at": None,
        }

    with (
        patch(
            "app.services.user_service.UserService.get_user_by_id",
            side_effect=_side_effect,
        ),
        patch("app.services.user_service.UserService._collection") as mock_col,
    ):
        col = MagicMock()
        col.delete_one = AsyncMock(return_value=MagicMock(deleted_count=1))
        mock_col.return_value = col

        resp = client.delete(
            "/api/v1/admin/users/user_01HUSER1",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert resp.status_code == 204


def test_delete_user_not_found(client: TestClient, admin_token: str) -> None:
    """AC4: Delete non-existent user returns 404."""
    async def _side_effect(user_id):
        if user_id == "user_01HADMIN":
            return _make_admin_doc()
        return None

    with patch(
        "app.services.user_service.UserService.get_user_by_id",
        side_effect=_side_effect,
    ):
        resp = client.delete(
            "/api/v1/admin/users/user_nonexistent",
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert resp.status_code == 404


def test_reset_password_as_admin(client: TestClient, admin_token: str) -> None:
    """AC5: Admin can reset user password."""
    with (
        patch("app.services.user_service.UserService.get_user_by_id") as mock_get,
        patch("app.services.user_service.UserService._collection") as mock_col,
        patch("app.services.user_service.UserService.get_user_by_id") as mock_auth_user,
    ):
        mock_get.return_value = {
            "_id": "user_01HUSER1",
            "username": "zhangsan",
            "email": "zhangsan@example.com",
            "password_hash": "$2b$12$hash",
            "role": "developer",
            "status": "active",
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
            "last_login_at": None,
        }
        col = MagicMock()
        col.update_one = AsyncMock()
        mock_col.return_value = col
        mock_auth_user.return_value = _make_admin_doc()

        resp = client.post(
            "/api/v1/admin/users/user_01HUSER1/reset-password",
            json={"new_password": "NewStrong5678"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert resp.status_code == 200
    assert resp.json()["message"] == "密码已重置"


def test_reset_password_weak(client: TestClient, admin_token: str) -> None:
    """AC5: Weak password returns 422."""
    with patch("app.services.user_service.UserService.get_user_by_id") as mock_auth_user:
        mock_auth_user.return_value = _make_admin_doc()
        resp = client.post(
            "/api/v1/admin/users/user_01HUSER1/reset-password",
            json={"new_password": "weak"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert resp.status_code == 422


def test_reset_password_not_found(client: TestClient, admin_token: str) -> None:
    """AC5: User not found returns 404."""
    async def _side_effect(user_id):
        if user_id == "user_01HADMIN":
            return _make_admin_doc()
        return None

    with patch(
        "app.services.user_service.UserService.get_user_by_id",
        side_effect=_side_effect,
    ):
        resp = client.post(
            "/api/v1/admin/users/user_nonexistent/reset-password",
            json={"new_password": "NewStrong5678"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )

    assert resp.status_code == 404

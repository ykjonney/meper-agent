"""Tests for models/user.py — User field validation and serialization."""

from app.models.user import User, UserRole, UserStatus


class TestUserRole:
    def test_user_role_has_admin(self) -> None:
        assert UserRole.ADMIN.value == "admin"

    def test_user_role_has_developer(self) -> None:
        assert UserRole.DEVELOPER.value == "developer"

    def test_user_role_has_operator(self) -> None:
        assert UserRole.OPERATOR.value == "operator"

    def test_user_role_has_viewer(self) -> None:
        assert UserRole.VIEWER.value == "viewer"


class TestUserStatus:
    def test_user_status_has_active(self) -> None:
        assert UserStatus.ACTIVE.value == "active"

    def test_user_status_has_disabled(self) -> None:
        assert UserStatus.DISABLED.value == "disabled"


class TestUserModel:
    def test_user_creation_with_defaults(self) -> None:
        """User can be created with all required fields."""
        user = User(
            username="admin",
            email="admin@example.com",
            password_hash="$2b$12$somehash",
            role=UserRole.ADMIN,
            status=UserStatus.ACTIVE,
        )
        assert user.username == "admin"
        assert user.email == "admin@example.com"
        assert user.role == UserRole.ADMIN
        assert user.status == UserStatus.ACTIVE
        assert user.last_login_at is None

    def test_user_id_starts_with_user_prefix(self) -> None:
        """Generated user ID follows the user_{ulid} pattern."""
        user = User(
            username="test",
            email="test@example.com",
            password_hash="hash",
        )
        assert user.id.startswith("user_")

    def test_user_id_is_unique_each_call(self) -> None:
        """Each User gets a unique ULID."""
        u1 = User(username="u1", email="u1@e.com", password_hash="h")
        u2 = User(username="u2", email="u2@e.com", password_hash="h")
        assert u1.id != u2.id

    def test_user_dump_excludes_password_hash(self) -> None:
        """model_dump() must NOT include password_hash (AC6)."""
        user = User(
            username="admin",
            email="admin@example.com",
            password_hash="$2b$12$secret",
        )
        dumped = user.model_dump()
        assert "password_hash" not in dumped
        assert dumped["username"] == "admin"

    def test_user_dump_json_excludes_password_hash(self) -> None:
        """model_dump_json() must NOT include password_hash."""
        user = User(
            username="admin",
            email="admin@example.com",
            password_hash="$2b$12$secret",
        )
        json_str = user.model_dump_json()
        assert "password_hash" not in json_str

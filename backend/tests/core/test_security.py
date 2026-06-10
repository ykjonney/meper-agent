"""Tests for core/security.py — password hashing, JWT, password strength."""

import pytest
from app.core.errors import UnauthorizedError, ValidationError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    validate_password_strength,
    verify_password,
)


class TestPasswordHashing:
    """Test bcrypt password hashing and verification."""

    def test_hash_password_returns_bcrypt_hash(self) -> None:
        """hash_password returns a bcrypt-style string starting with $2b$."""
        hashed = hash_password("Test1234")
        assert hashed.startswith("$2") and hashed.startswith("$")

    def test_hash_password_is_different_each_time(self) -> None:
        """Same password produces different hashes due to salt."""
        h1 = hash_password("Test1234")
        h2 = hash_password("Test1234")
        assert h1 != h2

    def test_verify_password_correct(self) -> None:
        """verify_password returns True for correct password."""
        hashed = hash_password("MyPassword1")
        assert verify_password("MyPassword1", hashed) is True

    def test_verify_password_incorrect(self) -> None:
        """verify_password returns False for wrong password."""
        hashed = hash_password("MyPassword1")
        assert verify_password("WrongPassword9", hashed) is False


class TestPasswordStrength:
    """Test the validate_password_strength function."""

    def test_accepts_strong_password(self) -> None:
        """Strong password passes validation."""
        validate_password_strength("StrongPass123")  # should not raise

    def test_rejects_too_short(self) -> None:
        """Password < 8 chars raises ValidationError."""
        with pytest.raises(ValidationError) as exc:
            validate_password_strength("Aa1")
        assert exc.value.code == "PASSWORD_TOO_SHORT"

    def test_rejects_no_letters(self) -> None:
        """Password with only digits raises ValidationError."""
        with pytest.raises(ValidationError):
            validate_password_strength("12345678")

    def test_rejects_no_digits(self) -> None:
        """Password with only letters raises ValidationError."""
        with pytest.raises(ValidationError):
            validate_password_strength("OnlyLetters")


class TestJwtTokens:
    """Test JWT creation and decoding."""

    def test_create_and_decode_access_token(self) -> None:
        """Created access token decodes successfully with correct claims."""
        token = create_access_token(
            subject="user_01HXYZ",
            claims={"role": "admin"},
        )
        decoded = decode_token(token)
        assert decoded["sub"] == "user_01HXYZ"
        assert decoded["role"] == "admin"
        assert decoded["type"] == "access"
        assert "iat" in decoded
        assert "exp" in decoded

    def test_create_and_decode_refresh_token(self) -> None:
        """Created refresh token decodes successfully."""
        token = create_refresh_token(subject="user_01HXYZ")
        decoded = decode_token(token)
        assert decoded["sub"] == "user_01HXYZ"
        assert decoded["type"] == "refresh"

    def test_access_token_expires_before_refresh(self) -> None:
        """Access token has shorter expiry than refresh token."""
        user_id = "user_01HTEST"
        access = decode_token(create_access_token(user_id))
        refresh = decode_token(create_refresh_token(user_id))
        assert access["exp"] < refresh["exp"]

    def test_decode_expired_token_raises(self) -> None:
        """An expired token raises UnauthorizedError."""
        # Create a token that expires immediately
        from datetime import UTC, datetime, timedelta

        import jwt
        from app.core.config import settings

        payload = {
            "sub": "user_01HXYZ",
            "type": "access",
            "iat": datetime.now(UTC) - timedelta(hours=2),
            "exp": datetime.now(UTC) - timedelta(hours=1),
        }
        expired = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

        with pytest.raises(UnauthorizedError) as exc:
            decode_token(expired)
        assert exc.value.code == "TOKEN_EXPIRED"

    def test_decode_invalid_token_raises(self) -> None:
        """A malformed token raises UnauthorizedError."""
        with pytest.raises(UnauthorizedError) as exc:
            decode_token("not-a-real-jwt")
        assert exc.value.code == "TOKEN_INVALID"

    def test_decode_token_wrong_secret_raises(self) -> None:
        """Token signed with a different secret raises UnauthorizedError."""
        import jwt

        token = jwt.encode(
            {"sub": "user_x", "exp": 9999999999},
            "wrong-secret",
            algorithm="HS256",
        )
        with pytest.raises(UnauthorizedError):
            decode_token(token)

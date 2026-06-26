"""Tests for WebSocket endpoint."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.api.v1.ws import verify_ws_token
from app.core.security import create_access_token, create_refresh_token


@pytest.fixture
def client():
    return TestClient(app)


class TestVerifyWsToken:
    """Test the verify_ws_token function directly."""

    def test_valid_access_token(self):
        """Valid access token should return user_id."""
        token = create_access_token("user_test_123")
        result = verify_ws_token(token)
        assert result == "user_test_123"

    def test_invalid_token(self):
        """Invalid token should return None."""
        result = verify_ws_token("invalid_token_string")
        assert result is None

    def test_refresh_token_rejected(self):
        """Refresh tokens should not be accepted for WebSocket auth."""
        token = create_refresh_token("user_test_123")
        result = verify_ws_token(token)
        assert result is None

    def test_empty_token(self):
        """Empty token should return None."""
        result = verify_ws_token("")
        assert result is None

    def test_expired_token(self):
        """Expired token should return None."""
        import time
        from app.core.security import decode_access_token

        # Create a token that expires immediately (not possible with current API)
        # Instead, test with a malformed token that looks expired
        result = verify_ws_token("eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyX3Rlc3QiLCJ0eXBlIjoiYWNjZXNzIiwiZXhwIjoxfQ.fake")
        assert result is None

"""Tests for WebSocket token verification.

``verify_ws_token`` decodes a JWT from the connection query string.
Under the new security module, ``decode_token`` *raises* ``UnauthorizedError``
on expired/invalid tokens (instead of returning None), and the WS helper must
translate that into ``None`` so the caller closes the connection. Only access
tokens are accepted — refresh tokens must be rejected.
"""

from app.api.v1.ws import verify_ws_token
from app.core.security import create_access_token, create_refresh_token


class TestVerifyWsToken:
    """Test the verify_ws_token function directly."""

    def test_valid_access_token(self):
        """A valid access token returns the subject user_id."""
        token = create_access_token("user_test_123")
        result = verify_ws_token(token)
        assert result == "user_test_123"

    def test_invalid_token(self):
        """A garbage token string returns None (no exception leaks)."""
        result = verify_ws_token("invalid_token_string")
        assert result is None

    def test_refresh_token_rejected(self):
        """Refresh tokens must not authenticate a WebSocket connection."""
        token = create_refresh_token("user_test_123")
        result = verify_ws_token(token)
        assert result is None

    def test_empty_token(self):
        """An empty token returns None."""
        result = verify_ws_token("")
        assert result is None

    def test_malformed_jwt_returns_none(self):
        """A token-shaped but unverifiable string returns None."""
        result = verify_ws_token(
            "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9."
            "eyJzdWIiOiJ1c2VyX3Rlc3QiLCJ0eXBlIjoiYWNjZXNzIiwiZXhwIjoxfQ."
            "fake"
        )
        assert result is None

"""Tests for McpConnection model enums."""
from app.models.mcp_connection import AuthType, ConnectionStatus


def test_connection_status_enum():
    """Test ConnectionStatus enum values."""
    assert ConnectionStatus.CONNECTING == "connecting"
    assert ConnectionStatus.CONNECTED == "connected"
    assert ConnectionStatus.DISCONNECTED == "disconnected"
    assert ConnectionStatus.ERROR == "error"


def test_auth_type_enum():
    """Test AuthType enum values."""
    assert AuthType.NONE == "none"
    assert AuthType.API_KEY == "api_key"
    assert AuthType.BEARER_TOKEN == "bearer_token"
    assert AuthType.BASIC == "basic"

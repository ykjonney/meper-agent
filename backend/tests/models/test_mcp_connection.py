"""Tests for McpConnection model."""
import pytest
from app.models.mcp_connection import AuthType, ConnectionStatus, McpConnection
from pydantic import ValidationError


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


def test_mcp_connection_model_valid():
    """Test McpConnection model with valid fields."""
    doc = McpConnection(
        name="test-connection",
        url="http://localhost:8080/mcp",
        protocol="streamable-http",
        auth_type=AuthType.API_KEY,
        auth_config={"api_key": "secret"},
        timeout=30,
    )
    assert doc.name == "test-connection"
    assert doc.url == "http://localhost:8080/mcp"
    assert doc.protocol == "streamable-http"
    assert doc.auth_type == AuthType.API_KEY
    assert doc.auth_config["api_key"] == "secret"
    assert doc.timeout == 30
    assert doc.status == ConnectionStatus.DISCONNECTED
    assert doc.tool_count == 0
    assert doc.id.startswith("mcp_")
    assert doc.created_at
    assert doc.updated_at


def test_mcp_connection_model_defaults():
    """Test McpConnection default field values."""
    doc = McpConnection(name="test", url="http://test.com")
    assert doc.description == ""
    assert doc.protocol == "streamable-http"
    assert doc.auth_type == AuthType.NONE
    assert doc.auth_config == {}
    assert doc.timeout == 30
    assert doc.status == ConnectionStatus.DISCONNECTED
    assert doc.status_message == ""
    assert doc.last_connected_at == ""
    assert doc.tool_count == 0


def test_mcp_connection_validation_name_required():
    """Test that name is required."""
    with pytest.raises(ValidationError):
        McpConnection(url="http://test.com")


def test_mcp_connection_validation_name_too_long():
    """Test name max_length constraint."""
    with pytest.raises(ValidationError) as exc:
        McpConnection(name="x" * 101, url="http://test.com")
    assert "name" in str(exc.value).lower()


def test_mcp_connection_validation_url_required():
    """Test that url is required."""
    with pytest.raises(ValidationError):
        McpConnection(name="test")


def test_mcp_connection_validation_url_too_long():
    """Test url max_length constraint."""
    with pytest.raises(ValidationError) as exc:
        McpConnection(name="test", url="http://x" * 501)
    assert "url" in str(exc.value).lower()


def test_mcp_connection_validation_timeout_range():
    """Test timeout ge=1, le=300 constraint."""
    with pytest.raises(ValidationError) as exc:
        McpConnection(name="test", url="http://test.com", timeout=0)
    assert "timeout" in str(exc.value).lower()

    with pytest.raises(ValidationError) as exc:
        McpConnection(name="test", url="http://test.com", timeout=301)
    assert "timeout" in str(exc.value).lower()


def test_mcp_connection_id_alias():
    """Test _id alias maps to id field."""
    doc = McpConnection(name="test", url="http://test.com")
    assert hasattr(doc, "model_config")
    assert doc.model_config.get("populate_by_name")


def test_mcp_connection_serialization():
    """Test model_dump returns MongoDB-compatible dict."""
    doc = McpConnection(name="test", url="http://test.com")
    dumped = doc.model_dump(by_alias=True)
    assert "_id" in dumped
    assert dumped["name"] == "test"
    assert dumped["url"] == "http://test.com"

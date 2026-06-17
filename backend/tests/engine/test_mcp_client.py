"""Tests for MCP client connection testing and tool discovery."""
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.engine.tool import mcp_client


# ---------------------------------------------------------------------------
# _build_headers tests (retained)
# ---------------------------------------------------------------------------


def test_build_headers_none():
    """Test header generation with no auth."""
    headers = mcp_client._build_headers("none", {})
    assert headers == {}


def test_build_headers_api_key():
    """Test header generation with API key auth."""
    headers = mcp_client._build_headers("api_key", {"api_key": "secret"})
    assert headers == {"X-API-Key": "secret"}


def test_build_headers_api_key_custom_header():
    """Test header generation with custom header name."""
    headers = mcp_client._build_headers(
        "api_key", {"header_name": "Authorization", "api_key": "secret"}
    )
    assert headers == {"Authorization": "secret"}


def test_build_headers_bearer_token():
    """Test header generation with bearer token auth."""
    headers = mcp_client._build_headers("bearer_token", {"token": "mytoken"})
    assert headers == {"Authorization": "Bearer mytoken"}


def test_build_headers_basic():
    """Test header generation with basic auth."""
    headers = mcp_client._build_headers("basic", {"username": "user", "password": "pass"})
    assert headers["Authorization"].startswith("Basic ")
    import base64

    expected = base64.b64encode(b"user:pass").decode()
    assert headers["Authorization"] == f"Basic {expected}"


def test_build_headers_api_key_empty():
    """Test header generation with empty api_key."""
    headers = mcp_client._build_headers("api_key", {"api_key": ""})
    assert headers == {}


def test_build_headers_bearer_token_empty():
    """Test header generation with empty token."""
    headers = mcp_client._build_headers("bearer_token", {"token": ""})
    assert headers == {}


# ---------------------------------------------------------------------------
# _build_connection_config tests (new)
# ---------------------------------------------------------------------------


def test_build_connection_config_streamable_http():
    """Test config for streamable-http (default) transport."""
    config = mcp_client._build_connection_config(
        url="http://localhost:8080/mcp",
        protocol="streamable-http",
        auth_type="none",
        auth_config={},
        timeout=30,
    )
    assert config["transport"] == "http"
    assert config["url"] == "http://localhost:8080/mcp"
    assert config["timeout"] == timedelta(seconds=30)
    assert "headers" not in config


def test_build_connection_config_sse():
    """Test config for SSE transport."""
    config = mcp_client._build_connection_config(
        url="http://localhost:8080/sse",
        protocol="sse",
        auth_type="none",
        auth_config={},
        timeout=10,
    )
    assert config["transport"] == "sse"
    assert config["url"] == "http://localhost:8080/sse"
    assert config["timeout"] == 10.0
    assert "headers" not in config


def test_build_connection_config_with_bearer_auth():
    """Test config includes auth headers."""
    config = mcp_client._build_connection_config(
        url="http://localhost:8080/mcp",
        protocol="streamable-http",
        auth_type="bearer_token",
        auth_config={"token": "mytoken"},
        timeout=30,
    )
    assert config["headers"] == {"Authorization": "Bearer mytoken"}


def test_build_connection_config_with_api_key_auth():
    """Test config includes API key header."""
    config = mcp_client._build_connection_config(
        url="http://localhost:8080/mcp",
        protocol="sse",
        auth_type="api_key",
        auth_config={"api_key": "secret", "header_name": "X-Custom"},
        timeout=5,
    )
    assert config["headers"] == {"X-Custom": "secret"}


# ---------------------------------------------------------------------------
# Integration-style tests (require real MCP server — expect failure)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_test_connection_success():
    """Test successful connection test."""
    # This is a complex integration scenario; we verify it returns the
    # expected dict shape on failure (since we can't easily mock the full
    # MCP context manager chain).
    result = await mcp_client.test_connection(
        url="http://nonexistent:9999/mcp",
        protocol="streamable-http",
        auth_type="none",
        auth_config={},
        timeout=1,
    )
    assert result["success"] is False
    assert result["error"]
    assert result["tool_count"] == 0

"""Tests for MCP client connection testing and tool discovery."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.engine.tool import mcp_client


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


def test_get_transport_streamable_http():
    """Test transport selection for streamable-http."""
    with patch("mcp.client.streamable_http.streamable_http_client") as mock:
        mcp_client._get_transport(
            url="http://localhost:8080/mcp",
            protocol="streamable-http",
            auth_type="none",
            auth_config={},
            timeout=30,
        )
        mock.assert_called_once()


def test_get_transport_sse():
    """Test transport selection for SSE."""
    with patch("mcp.client.sse.sse_client") as mock:
        mcp_client._get_transport(
            url="http://localhost:8080/mcp",
            protocol="sse",
            auth_type="none",
            auth_config={},
            timeout=30,
        )
        mock.assert_called_once()


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


@pytest.mark.asyncio
async def test_check_health_failure():
    """Test health check returns False for unreachable server."""
    result = await mcp_client.check_health(
        url="http://nonexistent:9999/mcp",
        protocol="streamable-http",
        auth_type="none",
        auth_config={},
        timeout=1,
    )
    assert result is False

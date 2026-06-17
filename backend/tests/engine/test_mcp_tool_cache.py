"""Tests for MCP tool cache — hit, expiry, invalidation, clear, default_params."""
from __future__ import annotations

import time
from unittest.mock import AsyncMock, patch

import pytest

from app.engine.tool.mcp_tool_cache import (
    McpToolCache,
    _CacheEntry,
    _wrap_tool_with_defaults,
    get_cache,
    get_mcp_tools_cached,
    invalidate_cache,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tool(name: str = "test_tool"):
    """Create a minimal mock StructuredTool."""
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel

    class _EmptyArgs(BaseModel):
        pass

    def _fn() -> str:
        """Mock tool function."""
        return "ok"

    return StructuredTool.from_function(
        _fn, name=name, description=f"Mock tool: {name}", args_schema=_EmptyArgs
    )


# ---------------------------------------------------------------------------
# McpToolCache unit tests
# ---------------------------------------------------------------------------


class TestMcpToolCache:
    """Tests for the McpToolCache data structure."""

    def test_miss_on_empty_cache(self):
        cache = McpToolCache()
        assert cache.get(frozenset(["conn_1"])) is None
        assert cache.size == 0

    def test_set_and_get_hit(self):
        cache = McpToolCache()
        key = frozenset(["conn_1", "conn_2"])
        tools = [_make_tool("a"), _make_tool("b")]

        cache.set(key, tools)
        assert cache.size == 1
        result = cache.get(key)
        assert result is not None
        assert len(result) == 2
        assert result[0].name == "a"

    def test_get_expired_returns_none(self):
        cache = McpToolCache(default_ttl=0.01)
        key = frozenset(["conn_1"])
        cache.set(key, [_make_tool()])

        # Wait for expiry
        time.sleep(0.02)
        assert cache.get(key) is None
        assert cache.size == 0

    def test_invalidate_by_connection_id(self):
        cache = McpToolCache()
        key1 = frozenset(["conn_1", "conn_2"])
        key2 = frozenset(["conn_2", "conn_3"])

        cache.set(key1, [_make_tool("a")])
        cache.set(key2, [_make_tool("b")])
        assert cache.size == 2

        # Invalidate conn_2 — should remove both entries
        removed = cache.invalidate("conn_2")
        assert removed == 2
        assert cache.size == 0
        assert cache.get(key1) is None
        assert cache.get(key2) is None

    def test_invalidate_partial_match(self):
        cache = McpToolCache()
        key1 = frozenset(["conn_1"])
        key2 = frozenset(["conn_2"])

        cache.set(key1, [_make_tool("a")])
        cache.set(key2, [_make_tool("b")])

        removed = cache.invalidate("conn_1")
        assert removed == 1
        assert cache.get(key1) is None
        assert cache.get(key2) is not None

    def test_invalidate_no_match(self):
        cache = McpToolCache()
        cache.set(frozenset(["conn_1"]), [_make_tool()])
        removed = cache.invalidate("conn_nonexistent")
        assert removed == 0
        assert cache.size == 1

    def test_clear(self):
        cache = McpToolCache()
        cache.set(frozenset(["a"]), [_make_tool()])
        cache.set(frozenset(["b"]), [_make_tool()])
        assert cache.size == 2

        cache.clear()
        assert cache.size == 0

    def test_set_with_custom_ttl(self):
        cache = McpToolCache(default_ttl=9999)
        key = frozenset(["conn_1"])

        # Set with very short TTL
        cache.set(key, [_make_tool()], ttl=0.01)
        time.sleep(0.02)

        assert cache.get(key) is None


# ---------------------------------------------------------------------------
# Module-level function tests
# ---------------------------------------------------------------------------


class TestModuleFunctions:
    """Tests for module-level convenience functions."""

    def test_get_cache_returns_singleton(self):
        c1 = get_cache()
        c2 = get_cache()
        assert c1 is c2


@pytest.mark.asyncio
async def test_get_mcp_tools_cached_empty_ids():
    """Empty connection list returns empty tools without hitting cache."""
    result = await get_mcp_tools_cached([])
    assert result == []


@pytest.mark.asyncio
async def test_get_mcp_tools_cached_hit():
    """Cache hit returns cached tools without MCP server call."""
    cache = get_cache()
    key = frozenset(["conn_1"])
    cached_tools = [_make_tool("cached_tool")]
    cache.set(key, cached_tools)

    result = await get_mcp_tools_cached(["conn_1"])
    assert len(result) == 1
    assert result[0].name == "cached_tool"

    # Cleanup
    cache.clear()


@pytest.mark.asyncio
async def test_get_mcp_tools_cached_miss_resolves():
    """Cache miss resolves tools via MCP and stores in cache."""
    cache = get_cache()
    cache.clear()

    mock_tool = _make_tool("discovered_tool")

    with patch(
        "langchain_mcp_adapters.client.MultiServerMCPClient"
    ) as MockClient, patch(
        "app.services.mcp_connection_service.McpConnectionService"
    ) as MockService:
        # Mock connection lookup
        MockService.get_connection = AsyncMock(return_value={
            "_id": "conn_1",
            "name": "TestServer",
            "url": "http://localhost:8080/mcp",
            "protocol": "streamable-http",
            "auth_type": "none",
            "auth_config": {},
            "timeout": 30,
        })

        # Mock MCP client
        mock_client_instance = MockClient.return_value
        mock_client_instance.get_tools = AsyncMock(return_value=[mock_tool])

        result = await get_mcp_tools_cached(["conn_1"])
        assert len(result) == 1
        assert result[0].name == "discovered_tool"

        # Verify it was cached
        cached = cache.get(frozenset(["conn_1"]))
        assert cached is not None
        assert len(cached) == 1

    # Cleanup
    cache.clear()


@pytest.mark.asyncio
async def test_get_mcp_tools_cached_connection_not_found():
    """Returns empty list when all connections are not found."""
    cache = get_cache()
    cache.clear()

    with patch(
        "app.services.mcp_connection_service.McpConnectionService"
    ) as MockService:
        MockService.get_connection = AsyncMock(return_value=None)

        result = await get_mcp_tools_cached(["conn_missing"])
        assert result == []


def test_invalidate_cache_delegates():
    """Module-level invalidate_cache delegates to singleton."""
    cache = get_cache()
    cache.set(frozenset(["conn_test"]), [_make_tool()])
    assert cache.size == 1

    removed = invalidate_cache("conn_test")
    assert removed == 1
    assert cache.size == 0


# ---------------------------------------------------------------------------
# _wrap_tool_with_defaults tests
# ---------------------------------------------------------------------------


def _make_tool_with_args(name: str = "test_tool"):
    """Create a StructuredTool that accepts keyword arguments and records them."""
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel, Field

    class _Args(BaseModel):
        query: str = Field(default="", description="Search query")
        token: str = Field(default="", description="Auth token")
        limit: int = Field(default=10, description="Max results")

    captured: dict = {}

    def _fn(**kwargs) -> str:
        captured.update(kwargs)
        return "ok"

    tool = StructuredTool.from_function(
        _fn, name=name, description=f"Tool: {name}", args_schema=_Args
    )
    return tool, captured


@pytest.mark.asyncio
async def test_wrap_tool_merges_default_params():
    """Default params are merged into tool invocation."""
    tool, captured = _make_tool_with_args("search")

    wrapped = _wrap_tool_with_defaults(
        tool, {"MyServer": {"token": "secret123", "limit": 5}}
    )

    await wrapped.ainvoke({"query": "hello"})
    assert captured["token"] == "secret123"
    assert captured["limit"] == 5
    assert captured["query"] == "hello"


@pytest.mark.asyncio
async def test_wrap_tool_user_args_override_defaults():
    """User-supplied args take precedence over defaults."""
    tool, captured = _make_tool_with_args("search")

    wrapped = _wrap_tool_with_defaults(
        tool, {"MyServer": {"token": "default_token", "limit": 5}}
    )

    await wrapped.ainvoke({"query": "hello", "token": "user_token"})
    assert captured["token"] == "user_token"
    assert captured["limit"] == 5
    assert captured["query"] == "hello"


def test_wrap_tool_empty_defaults_returns_original():
    """Empty default_params returns the original tool unchanged."""
    tool, _ = _make_tool_with_args("search")

    result = _wrap_tool_with_defaults(tool, {"MyServer": {}})
    assert result is tool

    result = _wrap_tool_with_defaults(tool, {})
    assert result is tool


@pytest.mark.asyncio
async def test_wrap_tool_preserves_metadata():
    """Wrapped tool preserves name, description, and args_schema."""
    tool, _ = _make_tool_with_args("search")

    wrapped = _wrap_tool_with_defaults(
        tool, {"MyServer": {"token": "abc"}}
    )

    assert wrapped.name == "search"
    assert "search" in wrapped.description.lower() or wrapped.description == tool.description
    # args_schema is a dynamic subclass with injected defaults
    assert issubclass(wrapped.args_schema, tool.args_schema)


@pytest.mark.asyncio
async def test_get_mcp_tools_cached_with_default_params():
    """Cache miss with default_params wraps tools automatically."""
    cache = get_cache()
    cache.clear()

    mock_tool, captured = _make_tool_with_args("api_call")

    with patch(
        "langchain_mcp_adapters.client.MultiServerMCPClient"
    ) as MockClient, patch(
        "app.services.mcp_connection_service.McpConnectionService"
    ) as MockService:
        MockService.get_connection = AsyncMock(return_value={
            "_id": "conn_1",
            "name": "APIServer",
            "url": "http://localhost:8080/mcp",
            "protocol": "streamable-http",
            "auth_type": "none",
            "auth_config": {},
            "timeout": 30,
            "default_params": {"token": "injected_token", "limit": 20},
        })

        mock_client_instance = MockClient.return_value
        mock_client_instance.get_tools = AsyncMock(return_value=[mock_tool])

        result = await get_mcp_tools_cached(["conn_1"])
        assert len(result) == 1

        # The wrapped tool should inject default_params
        await result[0].ainvoke({"query": "test"})
        assert captured["token"] == "injected_token"
        assert captured["limit"] == 20
        assert captured["query"] == "test"

    cache.clear()

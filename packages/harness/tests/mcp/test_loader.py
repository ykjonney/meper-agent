"""McpToolLoader 测试 — 缓存 + 配置构建 + auth headers（不连真实 server）。"""
from __future__ import annotations

import pytest
from agent_flow_harness.mcp.loader import (
    McpConnectionConfig,
    McpToolLoader,
    _build_auth_headers,
)


# ---------------------------------------------------------------------------
# McpConnectionConfig
# ---------------------------------------------------------------------------


def test_config_defaults():
    c = McpConnectionConfig(name="test", url="http://localhost:8080")
    assert c.protocol == "streamable-http"
    assert c.auth_type == "none"
    assert c.timeout == 30
    assert c.default_params == {}


def test_config_custom():
    c = McpConnectionConfig(
        name="github",
        url="https://api.github.com/mcp",
        protocol="sse",
        auth_type="bearer_token",
        auth_config={"token": "abc123"},
        timeout=60,
        default_params={"owner": "myorg"},
    )
    assert c.protocol == "sse"
    assert c.auth_type == "bearer_token"
    assert c.default_params == {"owner": "myorg"}


# ---------------------------------------------------------------------------
# _build_auth_headers
# ---------------------------------------------------------------------------


def test_auth_headers_none():
    c = McpConnectionConfig(name="t", url="http://x")
    assert _build_auth_headers(c) == {}


def test_auth_headers_api_key():
    c = McpConnectionConfig(
        name="t", url="http://x", auth_type="api_key",
        auth_config={"header_name": "X-Key", "api_key": "secret"},
    )
    h = _build_auth_headers(c)
    assert h["X-Key"] == "secret"


def test_auth_headers_bearer():
    c = McpConnectionConfig(
        name="t", url="http://x", auth_type="bearer_token",
        auth_config={"token": "tok123"},
    )
    h = _build_auth_headers(c)
    assert h["Authorization"] == "Bearer tok123"


def test_auth_headers_basic():
    c = McpConnectionConfig(
        name="t", url="http://x", auth_type="basic",
        auth_config={"username": "user", "password": "pass"},
    )
    h = _build_auth_headers(c)
    assert "Authorization" in h
    assert h["Authorization"].startswith("Basic ")


# ---------------------------------------------------------------------------
# _build_connection (McpToolLoader 静态方法)
# ---------------------------------------------------------------------------


def test_build_connection_streamable_http():
    c = McpConnectionConfig(name="t", url="http://x", protocol="streamable-http")
    conn = McpToolLoader._build_connection(c)
    assert conn["transport"] == "http"
    assert conn["url"] == "http://x"


def test_build_connection_sse():
    c = McpConnectionConfig(name="t", url="http://x", protocol="sse", timeout=60)
    conn = McpToolLoader._build_connection(c)
    assert conn["transport"] == "sse"
    assert conn["timeout"] == 60.0


# ---------------------------------------------------------------------------
# McpToolLoader 缓存逻辑（mock _connect_and_load）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_load_tools_empty_configs():
    loader = McpToolLoader()
    assert await loader.load_tools([]) == []


@pytest.mark.asyncio
async def test_cache_hit(monkeypatch):
    """第二次调 load_tools 相同 config 命中缓存（不重新连接）。"""
    call_count = 0

    async def mock_connect(self, config):
        nonlocal call_count
        call_count += 1
        return []

    monkeypatch.setattr(McpToolLoader, "_connect_and_load", mock_connect)

    loader = McpToolLoader()
    config = McpConnectionConfig(name="test", url="http://x")

    await loader.load_tools([config])
    await loader.load_tools([config])

    assert call_count == 1  # 第二次命中缓存


@pytest.mark.asyncio
async def test_invalidate_all(monkeypatch):
    async def mock_connect(self, config):
        return []

    monkeypatch.setattr(McpToolLoader, "_connect_and_load", mock_connect)

    loader = McpToolLoader()
    config = McpConnectionConfig(name="test", url="http://x")

    await loader.load_tools([config])
    assert len(loader._cache) == 1
    loader.invalidate()
    assert len(loader._cache) == 0


@pytest.mark.asyncio
async def test_invalidate_by_name(monkeypatch):
    async def mock_connect(self, config):
        return []

    monkeypatch.setattr(McpToolLoader, "_connect_and_load", mock_connect)

    loader = McpToolLoader()
    c1 = McpConnectionConfig(name="server_a", url="http://a")
    c2 = McpConnectionConfig(name="server_b", url="http://b")

    await loader.load_tools([c1])
    await loader.load_tools([c2])
    assert len(loader._cache) == 2

    loader.invalidate("server_a")
    assert len(loader._cache) == 1


@pytest.mark.asyncio
async def test_connection_failure_skipped(monkeypatch):
    """连接失败的 server 被跳过（不中断其他 server）。"""
    async def mock_connect(self, config):
        if config.name == "bad":
            raise ConnectionError("refused")
        return []

    monkeypatch.setattr(McpToolLoader, "_connect_and_load", mock_connect)

    loader = McpToolLoader()
    configs = [
        McpConnectionConfig(name="bad", url="http://bad"),
        McpConnectionConfig(name="good", url="http://good"),
    ]
    tools = await loader.load_tools(configs)
    assert tools == []  # bad 抛错跳过，good 返回空列表

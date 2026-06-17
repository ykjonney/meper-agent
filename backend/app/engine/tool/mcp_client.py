"""MCP client — connection testing and tool discovery.

Uses ``langchain_mcp_adapters.MultiServerMCPClient`` to connect to MCP
servers via SSE or Streamable HTTP transports.  Discovered tools are
registered into the ``tools`` MongoDB collection with ``source="mcp"``.
"""
from __future__ import annotations

from datetime import timedelta
from typing import Any

from langchain_mcp_adapters.client import MultiServerMCPClient
from loguru import logger


# ---------------------------------------------------------------------------
# Connection config builder
# ---------------------------------------------------------------------------


def _build_connection_config(
    url: str,
    protocol: str = "streamable-http",
    auth_type: str = "none",
    auth_config: dict | None = None,
    timeout: int = 30,
) -> dict:
    """Build a connection config dict for ``MultiServerMCPClient``.

    Maps the MongoDB connection document fields to the adapter's expected
    ``Connection`` TypedDict format.

    Args:
        url: MCP server endpoint URL.
        protocol: Transport protocol — ``"streamable-http"`` or ``"sse"``.
        auth_type: Authentication type — ``"none"``, ``"api_key"``,
            ``"bearer_token"``, or ``"basic"``.
        auth_config: Auth configuration dict (keys depend on auth_type).
        timeout: Connection timeout in seconds.

    Returns:
        A dict compatible with ``MultiServerMCPClient`` connections.
    """
    headers = _build_headers(auth_type, auth_config or {})

    if protocol == "sse":
        config: dict = {
            "transport": "sse",
            "url": url,
        }
        if headers:
            config["headers"] = headers
        if timeout:
            config["timeout"] = float(timeout)
        return config

    # Default to streamable-http (also accepts "http")
    config = {
        "transport": "http",
        "url": url,
    }
    if headers:
        config["headers"] = headers
    if timeout:
        config["timeout"] = timedelta(seconds=timeout)
    return config


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def test_connection(
    url: str,
    protocol: str = "streamable-http",
    auth_type: str = "none",
    auth_config: dict | None = None,
    timeout: int = 30,
) -> dict:
    """Test an MCP server connection.

    Returns:
        dict with keys: success, server_info, tool_count, error
    """
    try:
        config = _build_connection_config(url, protocol, auth_type, auth_config, timeout)
        client = MultiServerMCPClient({"_test": config})
        async with client.session("_test") as session:
            server_info = {
                "name": getattr(session, "server_name", "") or "",
                "version": getattr(session, "server_version", "") or "",
            }
            tools_result = await session.list_tools()
            tool_count = len(tools_result.tools) if tools_result.tools else 0

            return {
                "success": True,
                "server_info": server_info,
                "tool_count": tool_count,
                "error": "",
            }
    except Exception as exc:
        logger.warning("mcp_connection_test_failed", url=url, error=str(exc))
        return {
            "success": False,
            "server_info": {},
            "tool_count": 0,
            "error": str(exc),
        }


async def discover_tools(
    connection_doc: dict,
) -> list[dict]:
    """Discover tools from an MCP server and return as Tool documents.

    Args:
        connection_doc: MCP connection MongoDB document.

    Returns:
        List of tool info dicts: [{name, description, input_schema, ...}]
    """
    url = connection_doc["url"]
    protocol = connection_doc.get("protocol", "streamable-http")
    auth_type = connection_doc.get("auth_type", "none")
    auth_config = connection_doc.get("auth_config", {})
    timeout = connection_doc.get("timeout", 30)

    try:
        config = _build_connection_config(url, protocol, auth_type, auth_config, timeout)
        client = MultiServerMCPClient({"_discover": config})
        async with client.session("_discover") as session:
            tools_result = await session.list_tools()

            discovered = []
            for t in tools_result.tools or []:
                discovered.append({
                    "name": t.name,
                    "description": t.description or "",
                    "input_schema": t.inputSchema or {},
                    "output_schema": {},
                    "instructions": t.description or "",
                })

            logger.info(
                "mcp_tools_discovered",
                connection_id=connection_doc["_id"],
                tool_count=len(discovered),
            )
            return discovered
    except Exception as exc:
        logger.error(
            "mcp_tool_discovery_failed",
            connection_id=connection_doc["_id"],
            error=str(exc),
        )
        raise


# ---------------------------------------------------------------------------
# Auth helpers (retained — used by _build_connection_config)
# ---------------------------------------------------------------------------

def _build_headers(auth_type: str, auth_config: dict) -> dict[str, str]:
    """Build HTTP headers based on auth type."""
    headers: dict[str, str] = {}

    if auth_type == "api_key":
        header_name = auth_config.get("header_name", "X-API-Key")
        api_key = auth_config.get("api_key", "")
        if api_key:
            headers[header_name] = api_key

    elif auth_type == "bearer_token":
        token = auth_config.get("token", "")
        if token:
            headers["Authorization"] = f"Bearer {token}"

    elif auth_type == "basic":
        import base64

        username = auth_config.get("username", "")
        password = auth_config.get("password", "")
        if username:
            cred = base64.b64encode(f"{username}:{password}".encode()).decode()
            headers["Authorization"] = f"Basic {cred}"

    return headers

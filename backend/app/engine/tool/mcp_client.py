"""MCP client — connection testing, tool discovery, and health checks.

Uses the ``mcp`` Python SDK to connect to MCP servers via SSE or
Streamable HTTP transports.  Discovered tools are registered into
the ``tools`` MongoDB collection with ``source="mcp"``.
"""
from __future__ import annotations

from typing import Any

from loguru import logger

from app.models.base import generate_id, utc_now
from app.models.tool import ToolStatus


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
        transport_ctx = _get_transport(url, protocol, auth_type, auth_config, timeout)
        async with transport_ctx as streams:
            read, write = streams[:2]
            from mcp import ClientSession

            async with ClientSession(read, write) as session:
                await session.initialize()
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
        transport_ctx = _get_transport(url, protocol, auth_type, auth_config, timeout)
        async with transport_ctx as streams:
            read, write = streams[:2]
            from mcp import ClientSession

            async with ClientSession(read, write) as session:
                await session.initialize()
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


async def check_health(
    url: str,
    protocol: str = "streamable-http",
    auth_type: str = "none",
    auth_config: dict | None = None,
    timeout: int = 30,
) -> bool:
    """Check if an MCP server is reachable.

    Returns True if the server responds to initialize(), False otherwise.
    """
    try:
        transport_ctx = _get_transport(url, protocol, auth_type, auth_config, timeout)
        async with transport_ctx as streams:
            read, write = streams[:2]
            from mcp import ClientSession

            async with ClientSession(read, write) as session:
                await session.initialize()
                return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Transport helpers
# ---------------------------------------------------------------------------

def _get_transport(
    url: str,
    protocol: str,
    auth_type: str,
    auth_config: dict | None,
    timeout: int,
):
    """Return the appropriate MCP transport context manager.

    Supports:
    - ``streamable-http`` (default): Uses ``streamable_http_client``
    - ``sse``: Uses ``sse_client``
    """
    headers = _build_headers(auth_type, auth_config or {})

    if protocol == "sse":
        from mcp.client.sse import sse_client

        return sse_client(url=url, headers=headers, timeout=timeout)
    else:
        # Default to streamable-http
        from mcp.client.streamable_http import streamable_http_client

        return streamable_http_client(url=url, headers=headers, timeout=timeout)


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

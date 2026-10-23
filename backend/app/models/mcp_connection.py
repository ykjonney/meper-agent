"""MCP connection data model for MongoDB."""
from enum import StrEnum


class ConnectionStatus(StrEnum):
    """MCP connection lifecycle status."""

    CONNECTING = "connecting"
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    ERROR = "error"


class AuthType(StrEnum):
    """MCP server authentication type."""

    NONE = "none"
    API_KEY = "api_key"
    BEARER_TOKEN = "bearer_token"
    BASIC = "basic"

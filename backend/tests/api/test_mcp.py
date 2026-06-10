"""Tests for MCP connection API endpoints."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.core.errors import ConflictError, NotFoundError
from app.models.mcp_connection import ConnectionStatus


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------

@pytest.fixture(autouse=True)
def mock_service():
    """Mock McpConnectionService for all API tests."""
    with patch("app.api.v1.mcp.McpConnectionService") as mock:
        yield mock


@pytest.fixture
def client():
    """Create a TestClient with auth mock."""
    from app.main import app
    from app.core.security import get_current_user

    mock_user = MagicMock()
    mock_user.id = "user_01"
    mock_user.username = "admin"
    mock_user.role = "admin"

    app.dependency_overrides[get_current_user] = lambda: mock_user
    tc = TestClient(app, raise_server_exceptions=False)
    yield tc
    app.dependency_overrides.clear()


# ------------------------------------------------------------------
# CREATE
# ------------------------------------------------------------------

def test_create_connection(client, mock_service):
    """Test POST /mcp/connections creates a connection."""
    mock_service.create_connection = AsyncMock(return_value={
        "_id": "mcp_001",
        "name": "test",
        "description": "",
        "url": "http://localhost:8080/mcp",
        "protocol": "streamable-http",
        "auth_type": "none",
        "auth_config": {},
        "timeout": 30,
        "status": "disconnected",
        "status_message": "",
        "last_connected_at": "",
        "tool_count": 0,
        "created_at": "2026-06-10T00:00:00",
        "updated_at": "2026-06-10T00:00:00",
    })

    resp = client.post("/api/v1/mcp/connections", json={
        "name": "test",
        "url": "http://localhost:8080/mcp",
    })
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "test"
    assert data["url"] == "http://localhost:8080/mcp"
    assert data["status"] == "disconnected"


def test_create_connection_conflict(client, mock_service):
    """Test POST /mcp/connections with duplicate name returns 409."""
    mock_service.create_connection = AsyncMock(
        side_effect=ConflictError(code="MCP_CONN_NAME_CONFLICT", message="Name conflict")
    )

    resp = client.post("/api/v1/mcp/connections", json={
        "name": "dup",
        "url": "http://localhost:8080/mcp",
    })
    assert resp.status_code == 409


# ------------------------------------------------------------------
# LIST
# ------------------------------------------------------------------

def test_list_connections(client, mock_service):
    """Test GET /mcp/connections returns paginated list."""
    mock_service.list_connections = AsyncMock(return_value=(
        [{
            "_id": "mcp_001",
            "name": "conn1",
            "description": "",
            "url": "http://localhost:8080/mcp",
            "protocol": "streamable-http",
            "auth_type": "none",
            "auth_config": {},
            "timeout": 30,
            "status": "connected",
            "status_message": "",
            "last_connected_at": "2026-06-10T00:00:00",
            "tool_count": 5,
            "created_at": "2026-06-10T00:00:00",
            "updated_at": "2026-06-10T00:00:00",
        }],
        1,
    ))

    resp = client.get("/api/v1/mcp/connections")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert len(data["items"]) == 1
    assert data["items"][0]["name"] == "conn1"


# ------------------------------------------------------------------
# GET
# ------------------------------------------------------------------

def test_get_connection(client, mock_service):
    """Test GET /mcp/connections/{id} returns connection detail."""
    mock_service.get_connection = AsyncMock(return_value={
        "_id": "mcp_001",
        "name": "conn1",
        "description": "Test",
        "url": "http://localhost:8080/mcp",
        "protocol": "streamable-http",
        "auth_type": "api_key",
        "auth_config": {"api_key": "secret123"},
        "timeout": 30,
        "status": "connected",
        "status_message": "",
        "last_connected_at": "2026-06-10T00:00:00",
        "tool_count": 3,
        "created_at": "2026-06-10T00:00:00",
        "updated_at": "2026-06-10T00:00:00",
    })

    resp = client.get("/api/v1/mcp/connections/mcp_001")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "conn1"
    # Verify auth_config is masked
    assert data["auth_config"]["api_key"] == "***"


def test_get_connection_not_found(client, mock_service):
    """Test GET /mcp/connections/{id} returns 404."""
    mock_service.get_connection = AsyncMock(return_value=None)

    resp = client.get("/api/v1/mcp/connections/nonexistent")
    assert resp.status_code == 404


# ------------------------------------------------------------------
# UPDATE
# ------------------------------------------------------------------

def test_update_connection(client, mock_service):
    """Test PUT /mcp/connections/{id} updates connection."""
    mock_service.update_connection = AsyncMock(return_value={
        "_id": "mcp_001",
        "name": "updated",
        "description": "",
        "url": "http://new.com/mcp",
        "protocol": "sse",
        "auth_type": "none",
        "auth_config": {},
        "timeout": 60,
        "status": "disconnected",
        "status_message": "",
        "last_connected_at": "",
        "tool_count": 0,
        "created_at": "2026-06-10T00:00:00",
        "updated_at": "2026-06-10T01:00:00",
    })

    resp = client.put("/api/v1/mcp/connections/mcp_001", json={
        "name": "updated",
        "url": "http://new.com/mcp",
        "protocol": "sse",
        "timeout": 60,
    })
    assert resp.status_code == 200
    assert resp.json()["name"] == "updated"


def test_update_connection_not_found(client, mock_service):
    """Test PUT /mcp/connections/{id} returns 404."""
    mock_service.update_connection = AsyncMock(return_value=None)

    resp = client.put("/api/v1/mcp/connections/nonexistent", json={
        "name": "test",
        "url": "http://test.com",
    })
    assert resp.status_code == 404


# ------------------------------------------------------------------
# DELETE
# ------------------------------------------------------------------

def test_delete_connection(client, mock_service):
    """Test DELETE /mcp/connections/{id} returns 204."""
    mock_service.delete_connection = AsyncMock(return_value=True)

    resp = client.delete("/api/v1/mcp/connections/mcp_001")
    assert resp.status_code == 204


def test_delete_connection_not_found(client, mock_service):
    """Test DELETE /mcp/connections/{id} returns 404."""
    mock_service.delete_connection = AsyncMock(return_value=False)

    resp = client.delete("/api/v1/mcp/connections/nonexistent")
    assert resp.status_code == 404


# ------------------------------------------------------------------
# TEST CONNECTION
# ------------------------------------------------------------------

def test_test_connection(client, mock_service):
    """Test POST /mcp/connections/{id}/test returns test result."""
    mock_service.test_connection = AsyncMock(return_value={
        "success": True,
        "server_info": {"name": "test-server", "version": "1.0"},
        "tool_count": 3,
        "error": "",
    })

    resp = client.post("/api/v1/mcp/connections/mcp_001/test")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["tool_count"] == 3


def test_test_connection_not_found(client, mock_service):
    """Test POST /mcp/connections/{id}/test returns 404."""
    mock_service.test_connection = AsyncMock(
        side_effect=NotFoundError(code="MCP_CONN_NOT_FOUND", message="Not found")
    )

    resp = client.post("/api/v1/mcp/connections/nonexistent/test")
    assert resp.status_code == 404


# ------------------------------------------------------------------
# DISCOVER TOOLS
# ------------------------------------------------------------------

def test_discover_tools(client, mock_service):
    """Test POST /mcp/connections/{id}/discover returns discover result."""
    mock_service.discover_tools = AsyncMock(return_value={
        "connection_id": "mcp_001",
        "discovered": 3,
        "created": 2,
        "updated": 1,
        "deactivated": 0,
        "tools": ["tool1", "tool2", "tool3"],
        "error": "",
    })

    resp = client.post("/api/v1/mcp/connections/mcp_001/discover")
    assert resp.status_code == 200
    data = resp.json()
    assert data["discovered"] == 3
    assert data["created"] == 2
    assert data["tools"] == ["tool1", "tool2", "tool3"]


def test_discover_tools_not_found(client, mock_service):
    """Test POST /mcp/connections/{id}/discover returns 404."""
    mock_service.discover_tools = AsyncMock(
        side_effect=NotFoundError(code="MCP_CONN_NOT_FOUND", message="Not found")
    )

    resp = client.post("/api/v1/mcp/connections/nonexistent/discover")
    assert resp.status_code == 404


def test_discover_tools_connection_error(client, mock_service):
    """Test POST /mcp/connections/{id}/discover returns error on failure."""
    mock_service.discover_tools = AsyncMock(return_value={
        "connection_id": "mcp_001",
        "discovered": 0,
        "created": 0,
        "updated": 0,
        "deactivated": 0,
        "tools": [],
        "error": "Connection refused",
    })

    resp = client.post("/api/v1/mcp/connections/mcp_001/discover")
    assert resp.status_code == 200
    data = resp.json()
    assert data["error"] == "Connection refused"
    assert data["discovered"] == 0

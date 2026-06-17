"""API tests for /api/v1/agents endpoints (mock-based).

Uses ``unittest.mock`` to mock the AgentService layer so tests
run without a real MongoDB connection.

NOTE: Mock-based tests cannot detect interface-contract mismatches
(e.g. wrong keyword argument names passed from API to Service).
The contract tests at the bottom of this file cover that gap.
"""
import inspect
from unittest.mock import AsyncMock, patch

import pytest
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.core.security import get_current_user
from app.main import app
from app.schemas.user import UserResponse, UserRole, UserStatus
from app.services.agent_service import AgentService
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_admin():
    """Override get_current_user for admin-level authentication."""
    user = UserResponse(
        id="user_01HTEST",
        username="admin",
        email="admin@example.com",
        role=UserRole.ADMIN,
        status=UserStatus.ACTIVE,
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )
    app.dependency_overrides[get_current_user] = lambda: user
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def auth_viewer():
    """Override get_current_user for viewer-level authentication."""
    user = UserResponse(
        id="user_02HTEST",
        username="viewer",
        email="viewer@example.com",
        role=UserRole.VIEWER,
        status=UserStatus.ACTIVE,
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
    )
    app.dependency_overrides[get_current_user] = lambda: user
    yield
    app.dependency_overrides.clear()


def _fake_doc(agent_id: str = "agent_01HTEST", name: str = "Test Agent") -> dict:
    return {
        "_id": agent_id,
        "name": name,
        "description": "A test agent",
        "system_prompt": "You are a helpful assistant.",
        "saved_system_prompts": [],
        "skill_ids": [],
        "mcp_connection_ids": [],
        "builtin_config": [],
        "workflow_ids": [],
        "knowledge_base_ids": [],
        "llm_config": {"default_model": "gpt-4", "temperature": 0.7, "max_retry": 3},
        "status": "draft",
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
    }


class TestListAgents:
    """GET /api/v1/agents"""

    def test_list_agents_200(self, client, auth_admin) -> None:
        with patch(
            "app.api.v1.agents.AgentService.list_agents",
            new=AsyncMock(return_value=([_fake_doc()], 1)),
        ):
            resp = client.get("/api/v1/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["name"] == "Test Agent"

    def test_list_agents_empty(self, client, auth_admin) -> None:
        with patch(
            "app.api.v1.agents.AgentService.list_agents",
            new=AsyncMock(return_value=([], 0)),
        ):
            resp = client.get("/api/v1/agents")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["items"] == []

    def test_list_agents_with_filters(self, client, auth_admin) -> None:
        with patch(
            "app.api.v1.agents.AgentService.list_agents",
            new=AsyncMock(return_value=([_fake_doc(name="Filtered")], 1)),
        ) as mock_list:
            resp = client.get("/api/v1/agents?name=Filtered&status=draft")
        assert resp.status_code == 200
        assert resp.json()["items"][0]["name"] == "Filtered"
        _, kwargs = mock_list.call_args
        assert kwargs["name"] == "Filtered"
        assert kwargs["status"] == "draft"

    def test_list_agents_pagination(self, client, auth_admin) -> None:
        docs = [_fake_doc(agent_id=f"agent_{i:02d}", name=f"Agent {i}") for i in range(5)]
        with patch(
            "app.api.v1.agents.AgentService.list_agents",
            new=AsyncMock(return_value=(docs[:2], 5)),
        ):
            resp = client.get("/api/v1/agents?page=1&page_size=2")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 2
        assert data["total"] == 5
        assert data["page"] == 1
        assert data["page_size"] == 2

    def test_list_agents_401_unauthorized(self, client) -> None:
        resp = client.get("/api/v1/agents")
        assert resp.status_code == 401

    def test_list_agents_viewer_allowed(self, client, auth_viewer) -> None:
        with patch(
            "app.api.v1.agents.AgentService.list_agents",
            new=AsyncMock(return_value=([_fake_doc()], 1)),
        ):
            resp = client.get("/api/v1/agents")
        assert resp.status_code == 200


class TestCreateAgent:
    """POST /api/v1/agents"""

    def test_create_agent_201(self, client, auth_admin) -> None:
        with patch(
            "app.api.v1.agents.AgentService.create_agent",
            new=AsyncMock(return_value=_fake_doc()),
        ):
            resp = client.post(
                "/api/v1/agents",
                json={"name": "New Agent", "description": "A new agent"},
            )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Test Agent"
        assert data["status"] == "draft"

    def test_create_agent_409_conflict(self, client, auth_admin) -> None:
        with patch(
            "app.api.v1.agents.AgentService.create_agent",
            new=AsyncMock(
                side_effect=ConflictError(
                    code="AGENT_NAME_CONFLICT",
                    message="Agent 名称 'New Agent' 已被占用",
                )
            ),
        ):
            resp = client.post(
                "/api/v1/agents",
                json={"name": "New Agent"},
            )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "AGENT_NAME_CONFLICT"

    def test_create_agent_422_validation(self, client, auth_admin) -> None:
        resp = client.post("/api/v1/agents", json={"name": ""})
        assert resp.status_code == 422

    def test_create_agent_401_unauthorized(self, client) -> None:
        resp = client.post(
            "/api/v1/agents",
            json={"name": "New Agent"},
        )
        assert resp.status_code == 401


class TestGetAgent:
    """GET /api/v1/agents/{agent_id}"""

    def test_get_agent_200(self, client, auth_admin) -> None:
        with patch(
            "app.api.v1.agents.AgentService.get_agent",
            new=AsyncMock(return_value=_fake_doc()),
        ):
            resp = client.get("/api/v1/agents/agent_01HTEST")
        assert resp.status_code == 200
        assert resp.json()["id"] == "agent_01HTEST"

    def test_get_agent_404(self, client, auth_admin) -> None:
        with patch(
            "app.api.v1.agents.AgentService.get_agent",
            new=AsyncMock(return_value=None),
        ):
            resp = client.get("/api/v1/agents/agent_NONEXIST")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "AGENT_NOT_FOUND"


class TestUpdateAgent:
    """PUT /api/v1/agents/{agent_id}"""

    def test_update_agent_200(self, client, auth_admin) -> None:
        updated = _fake_doc(name="Updated Agent")
        with patch(
            "app.api.v1.agents.AgentService.update_agent",
            new=AsyncMock(return_value=updated),
        ):
            resp = client.put(
                "/api/v1/agents/agent_01HTEST",
                json={"name": "Updated Agent", "description": "Updated"},
            )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated Agent"

    def test_update_agent_404(self, client, auth_admin) -> None:
        with patch(
            "app.api.v1.agents.AgentService.update_agent",
            new=AsyncMock(return_value=None),
        ):
            resp = client.put(
                "/api/v1/agents/agent_NONEXIST",
                json={"name": "Ghost", "description": ""},
            )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "AGENT_NOT_FOUND"

    def test_update_agent_409_conflict(self, client, auth_admin) -> None:
        with patch(
            "app.api.v1.agents.AgentService.update_agent",
            new=AsyncMock(
                side_effect=ConflictError(
                    code="AGENT_NAME_CONFLICT",
                    message="Agent 名称 'Dup' 已被占用",
                )
            ),
        ):
            resp = client.put(
                "/api/v1/agents/agent_01HTEST",
                json={"name": "Dup", "description": ""},
            )
        assert resp.status_code == 409

    def test_update_published_409(self, client, auth_admin) -> None:
        """Published agent should return 409."""
        with patch(
            "app.api.v1.agents.AgentService.update_agent",
            new=AsyncMock(
                side_effect=ConflictError(
                    code="AGENT_PUBLISHED_IMMUTABLE",
                    message="Agent 'Published' 已发布，不可直接编辑。",
                )
            ),
        ):
            resp = client.put(
                "/api/v1/agents/agent_01HTEST",
                json={"name": "Published", "description": ""},
            )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "AGENT_PUBLISHED_IMMUTABLE"

    def test_update_agent_viewer_forbidden(self, client, auth_viewer) -> None:
        resp = client.put(
            "/api/v1/agents/agent_01HTEST",
            json={"name": "Hacked", "description": ""},
        )
        assert resp.status_code == 403


class TestPublishAgent:
    """POST /api/v1/agents/{agent_id}/publish"""

    def test_publish_agent_200(self, client, auth_admin) -> None:
        published = _fake_doc()
        published["status"] = "published"
        with patch(
            "app.api.v1.agents.AgentService.publish_agent",
            new=AsyncMock(return_value=published),
        ):
            resp = client.post("/api/v1/agents/agent_01HTEST/publish")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "published"

    def test_publish_agent_404(self, client, auth_admin) -> None:
        with patch(
            "app.api.v1.agents.AgentService.publish_agent",
            new=AsyncMock(return_value=None),
        ):
            resp = client.post("/api/v1/agents/agent_NONEXIST/publish")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "AGENT_NOT_FOUND"

    def test_publish_agent_viewer_forbidden(self, client, auth_viewer) -> None:
        resp = client.post("/api/v1/agents/agent_01HTEST/publish")
        assert resp.status_code == 403

    def test_publish_agent_401_unauthorized(self, client) -> None:
        resp = client.post("/api/v1/agents/agent_01HTEST/publish")
        assert resp.status_code == 401


class TestArchiveAgent:
    """POST /api/v1/agents/{agent_id}/archive"""

    def test_archive_agent_200(self, client, auth_admin) -> None:
        archived = _fake_doc()
        archived["status"] = "archived"
        with patch(
            "app.api.v1.agents.AgentService.archive_agent",
            new=AsyncMock(return_value=archived),
        ):
            resp = client.post("/api/v1/agents/agent_01HTEST/archive")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "archived"

    def test_archive_agent_404(self, client, auth_admin) -> None:
        with patch(
            "app.api.v1.agents.AgentService.archive_agent",
            new=AsyncMock(return_value=None),
        ):
            resp = client.post("/api/v1/agents/agent_NONEXIST/archive")
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "AGENT_NOT_FOUND"

    def test_archive_agent_viewer_forbidden(self, client, auth_viewer) -> None:
        resp = client.post("/api/v1/agents/agent_01HTEST/archive")
        assert resp.status_code == 403


class TestDuplicateAgent:
    """POST /api/v1/agents/{agent_id}/duplicate"""

    def test_duplicate_agent_201(self, client, auth_admin) -> None:
        dup_doc = _fake_doc(agent_id="agent_02HDUP", name="Test Agent_copy")
        dup_doc["status"] = "draft"
        with patch(
            "app.api.v1.agents.AgentService.duplicate_agent",
            new=AsyncMock(return_value=dup_doc),
        ):
            resp = client.post("/api/v1/agents/agent_01HTEST/duplicate")
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Test Agent_copy"
        assert data["status"] == "draft"

    def test_duplicate_agent_404(self, client, auth_admin) -> None:
        with patch(
            "app.api.v1.agents.AgentService.duplicate_agent",
            new=AsyncMock(side_effect=NotFoundError(
                code="AGENT_NOT_FOUND",
                message="Agent agent_NONEXIST 不存在",
            )),
        ):
            resp = client.post("/api/v1/agents/agent_NONEXIST/duplicate")
        assert resp.status_code == 404

    def test_duplicate_agent_409_name_conflict(self, client, auth_admin) -> None:
        with patch(
            "app.api.v1.agents.AgentService.duplicate_agent",
            new=AsyncMock(side_effect=ConflictError(
                code="AGENT_DUPLICATE_NAME_CONFLICT",
                message="无法生成唯一名称，请手动创建",
            )),
        ):
            resp = client.post("/api/v1/agents/agent_01HTEST/duplicate")
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "AGENT_DUPLICATE_NAME_CONFLICT"

    def test_duplicate_agent_viewer_forbidden(self, client, auth_viewer) -> None:
        resp = client.post("/api/v1/agents/agent_01HTEST/duplicate")
        assert resp.status_code == 403


class TestDeleteAgent:
    """DELETE /api/v1/agents/{agent_id}"""

    def test_delete_agent_204(self, client, auth_admin) -> None:
        with patch(
            "app.api.v1.agents.AgentService.delete_agent",
            new=AsyncMock(return_value=True),
        ):
            resp = client.delete("/api/v1/agents/agent_01HTEST")
        assert resp.status_code == 204

    def test_delete_agent_404(self, client, auth_admin) -> None:
        with patch(
            "app.api.v1.agents.AgentService.delete_agent",
            new=AsyncMock(return_value=False),
        ):
            resp = client.delete("/api/v1/agents/agent_NONEXIST")
        assert resp.status_code == 404

    def test_delete_agent_viewer_forbidden(self, client, auth_viewer) -> None:
        resp = client.delete("/api/v1/agents/agent_01HTEST")
        assert resp.status_code == 403


class TestVersionEndpointsRemoved:
    """Version endpoints should return 404 (removed)."""

    def test_list_versions_not_found(self, client, auth_admin) -> None:
        resp = client.get("/api/v1/agents/agent_01HTEST/versions")
        assert resp.status_code == 404

    def test_get_version_not_found(self, client, auth_admin) -> None:
        resp = client.get("/api/v1/agents/agent_01HTEST/versions/1")
        assert resp.status_code == 404


# =========================================================================
# Contract tests — verify API→Service parameter name alignment
# =========================================================================


class TestAgentApiServiceContract:
    """Verify API handlers call service methods with correct kwarg names."""

    def test_create_agent_kwargs_match_service(self) -> None:
        sig = inspect.signature(AgentService.create_agent)
        valid_params = set(sig.parameters.keys())
        api_kwargs = {
            "name", "description", "system_prompt",
            "skill_ids", "mcp_connection_ids", "builtin_config",
            "workflow_ids", "knowledge_base_ids",
            "llm_config",
        }
        unknown = api_kwargs - valid_params
        assert not unknown, (
            f"API passes unknown kwarg(s) to AgentService.create_agent: "
            f"{unknown}. Valid params: {valid_params}"
        )

    def test_update_agent_kwargs_match_service(self) -> None:
        sig = inspect.signature(AgentService.update_agent)
        valid_params = set(sig.parameters.keys())
        api_kwargs = {
            "agent_id", "name", "description", "system_prompt",
            "skill_ids", "mcp_connection_ids", "builtin_config",
            "workflow_ids", "knowledge_base_ids",
            "llm_config",
        }
        unknown = api_kwargs - valid_params
        assert not unknown, (
            f"API passes unknown kwarg(s) to AgentService.update_agent: "
            f"{unknown}. Valid params: {valid_params}"
        )

    def test_update_agent_no_status_param(self) -> None:
        sig = inspect.signature(AgentService.update_agent)
        assert "status" not in sig.parameters, (
            "AgentService.update_agent should not accept 'status' parameter. "
            "Status changes must go through publish_agent / archive_agent."
        )

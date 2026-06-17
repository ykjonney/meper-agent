"""API tests for /api/v1/agents/{id}/invoke and /stream endpoints.

Uses ``unittest.mock`` to mock both the AgentService layer and the
LangGraph execution engine so tests run without MongoDB or real LLMs.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.core.security import get_current_user
from app.main import app
from app.schemas.user import UserResponse, UserStatus
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
        role="admin",
        status=UserStatus.ACTIVE,
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
        permissions=[],
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
        role="viewer",
        status=UserStatus.ACTIVE,
        created_at="2026-01-01T00:00:00",
        updated_at="2026-01-01T00:00:00",
        permissions=[],
    )
    app.dependency_overrides[get_current_user] = lambda: user
    yield
    app.dependency_overrides.clear()


def _fake_agent_doc() -> dict:
    return {
        "_id": "agent_01HTEST",
        "name": "Test Agent",
        "description": "A test agent",
        "prompt_slots": {},
        "skill_ids": [],
        "mcp_connection_ids": [],
        "builtin_config": [],
        "workflow_ids": [],
        "knowledge_base_ids": [],
        "default_model": "gpt-4o-mini",
        "max_retry": 3,
        "status": "published",
        "version": 1,
        "created_at": "2026-01-01T00:00:00",
        "updated_at": "2026-01-01T00:00:00",
    }


def _mock_graph(result: dict | None = None) -> MagicMock:
    """Create a mock compiled StateGraph."""
    graph = MagicMock()
    graph.ainvoke = AsyncMock(return_value=result or {
        "messages": [{"role": "assistant", "content": "Hello from test agent!"}],
        "execution_path": "react",
        "request_id": "req_01HTEST",
        "agent_id": "agent_01HTEST",
        "step_count": 1,
        "tool_results": {},
        "error": None,
    })
    return graph


async def _async_gen(events):
    """Helper: yield events as an async generator would."""
    for event in events:
        yield event


class TestInvokeAgent:
    """POST /api/v1/agents/{agent_id}/invoke"""

    def test_invoke_200(self, client, auth_admin) -> None:
        from langchain_core.messages import AIMessage

        fake_doc = _fake_agent_doc()
        fake_result = {
            "messages": [AIMessage(content="Hello!")],
            "execution_path": "react",
            "request_id": "req_001",
            "agent_id": "agent_01HTEST",
            "step_count": 2,
        }
        mock_graph = _mock_graph(fake_result)

        with (
            patch("app.api.v1.agents.AgentService.get_agent", return_value=fake_doc),
            patch("app.engine.agent.builder.build_tool_declaration", new_callable=AsyncMock, return_value=""),
            patch("app.engine.agent.builder.build_agent_graph", return_value=mock_graph),
        ):
            resp = client.post(
                "/api/v1/agents/agent_01HTEST/invoke",
                json={"input": "Hello agent!"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["execution_path"] == "react"
        assert data["agent_id"] == "agent_01HTEST"
        assert data["step_count"] == 2
        assert isinstance(data["request_id"], str) and len(data["request_id"]) > 10
        # Output should be the extracted final answer text
        assert data["output"] == "Hello!"

    def test_invoke_404(self, client, auth_admin) -> None:
        with patch("app.api.v1.agents.AgentService.get_agent", return_value=None):
            resp = client.post(
                "/api/v1/agents/agent_NONEXIST/invoke",
                json={"input": "Hello"},
            )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "AGENT_NOT_FOUND"

    def test_invoke_401_unauthorized(self, client) -> None:
        resp = client.post(
            "/api/v1/agents/agent_01HTEST/invoke",
            json={"input": "Hello"},
        )
        assert resp.status_code == 401

    def test_invoke_viewer_allowed(self, client, auth_viewer) -> None:
        fake_doc = _fake_agent_doc()
        mock_graph = _mock_graph()

        with (
            patch("app.api.v1.agents.AgentService.get_agent", return_value=fake_doc),
            patch("app.engine.agent.builder.build_agent_graph", return_value=mock_graph),
            patch("app.engine.agent.builder.build_tool_declaration", new_callable=AsyncMock, return_value=""),
            patch("app.services.session_service.SessionService.create_session", new_callable=AsyncMock, return_value={"_id": "session_mock"}),
            patch("app.services.session_service.MessageService.add_message", new_callable=AsyncMock),
        ):
            resp = client.post(
                "/api/v1/agents/agent_01HTEST/invoke",
                json={"input": "Hello"},
            )
        assert resp.status_code == 200

    def test_invoke_422_empty_input(self, client, auth_admin) -> None:
        resp = client.post(
            "/api/v1/agents/agent_01HTEST/invoke",
            json={"input": ""},
        )
        assert resp.status_code == 422

    def test_invoke_with_session_id(self, client, auth_admin) -> None:
        from langchain_core.messages import AIMessage

        fake_doc = _fake_agent_doc()
        mock_graph = _mock_graph()
        mock_graph.ainvoke = AsyncMock(return_value={
            "messages": [AIMessage(content="Hello with session!")],
            "execution_path": "direct",
            "request_id": "req_002",
            "agent_id": "agent_01HTEST",
            "step_count": 1,
        })

        with (
            patch("app.api.v1.agents.AgentService.get_agent", return_value=fake_doc),
            patch("app.engine.agent.builder.build_agent_graph", return_value=mock_graph),
            patch("app.engine.agent.builder.build_tool_declaration", new_callable=AsyncMock, return_value=""),
            patch("app.services.session_service.MessageService.add_message", new_callable=AsyncMock),
        ):
            resp = client.post(
                "/api/v1/agents/agent_01HTEST/invoke",
                json={"input": "Hello", "session_id": "session_001"},
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["execution_path"] == "direct"
        assert isinstance(data["request_id"], str)


class TestStreamAgent:
    """POST /api/v1/agents/{agent_id}/stream"""

    def test_stream_200(self, client, auth_admin) -> None:
        from langchain_core.messages import AIMessage

        fake_doc = _fake_agent_doc()

        # Mock run_agent_streaming to push simulated events to the on_event callback
        async def _mock_run_agent_streaming(doc, state, on_event, enable_thinking=False, context_window=None):
            # Simulate REACT executor events
            await on_event({"type": "final_answer", "content": "Hello!"})
            return {"messages": [AIMessage(content="Hello!")], "step_count": 1}

        with (
            patch("app.api.v1.agents.AgentService.get_agent", return_value=fake_doc),
            patch("app.engine.agent.builder.run_agent_streaming", side_effect=_mock_run_agent_streaming),
            patch("app.services.session_service.SessionService.create_session", new_callable=AsyncMock, return_value={"_id": "session_mock"}),
            patch("app.services.session_service.MessageService.add_message", new_callable=AsyncMock),
        ):
            resp = client.post(
                "/api/v1/agents/agent_01HTEST/stream",
                json={"input": "Hello agent!"},
            )
        assert resp.status_code == 200
        assert resp.headers.get("content-type", "").startswith("text/event-stream")
        assert resp.headers.get("x-request-id", "")
        # Verify SSE content — structured events
        assert "final_answer" in resp.text
        assert "Hello!" in resp.text
        assert "done" in resp.text

    def test_stream_404(self, client, auth_admin) -> None:
        with patch("app.api.v1.agents.AgentService.get_agent", return_value=None):
            resp = client.post(
                "/api/v1/agents/agent_NONEXIST/stream",
                json={"input": "Hello"},
            )
        assert resp.status_code == 404

    def test_stream_401_unauthorized(self, client) -> None:
        resp = client.post(
            "/api/v1/agents/agent_01HTEST/stream",
            json={"input": "Hello"},
        )
        assert resp.status_code == 401

    def test_stream_viewer_allowed(self, client, auth_viewer) -> None:
        fake_doc = _fake_agent_doc()
        mock_graph = MagicMock()

        async def _astream_gen(*args, **kwargs):
            if False:
                yield  # make this an async generator
            return

        mock_graph.astream = _astream_gen

        with (
            patch("app.api.v1.agents.AgentService.get_agent", return_value=fake_doc),
            patch("app.engine.agent.builder.build_agent_graph", return_value=mock_graph),
            patch("app.engine.agent.builder.build_tool_declaration", new_callable=AsyncMock, return_value=""),
            patch("app.services.session_service.SessionService.create_session", new_callable=AsyncMock, return_value={"_id": "session_mock"}),
            patch("app.services.session_service.MessageService.add_message", new_callable=AsyncMock),
        ):
            resp = client.post(
                "/api/v1/agents/agent_01HTEST/stream",
                json={"input": "Hello"},
            )
        assert resp.status_code == 200

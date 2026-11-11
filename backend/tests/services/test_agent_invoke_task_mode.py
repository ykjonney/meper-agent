"""invoke 任务模式增强：execution_context/cancel_checker 透传 + total_tokens 出参。"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from app.schemas.execution import ExecutionRequest, ExecutionResponse
from app.services.agent_execution_service import AgentExecutionService


@pytest.mark.asyncio
async def test_invoke_passes_workflow_context_and_checker() -> None:
    """execution_context="workflow" + cancel_checker 应透传 harness_invoke。"""
    captured: dict = {}

    async def fake_harness_invoke(exec_doc, initial_state, **kwargs):
        captured.update(kwargs)
        return {
            "messages": [], "usage": {"total_tokens": 15},
            "execution_path": "react", "step_count": 2,
        }

    async def fake_resolve(agent_id, body, user_id):
        return "session_new"

    async def fake_system_prompt(exec_doc, user_id, **kwargs):
        return "sys"

    with (
        patch("app.services.agent_service.AgentService.get_agent", new=AsyncMock(return_value={"_id": "agent_1"})),
        patch("app.services.agent_execution_service._resolve_session", new=fake_resolve),
        patch("app.services.agent_execution_service._load_chat_subagents", new=AsyncMock(return_value=([], []))),
        patch("app.services.agent_execution_service._build_system_prompt_checked", new=fake_system_prompt),
        patch("app.services.agent_execution_service._build_user_content", new=AsyncMock(return_value="hi")),
        patch("app.services.agent_execution_service._assemble_messages", new=lambda *a: []),
        patch("app.services.agent_execution_service._load_legacy_records", new=AsyncMock(return_value=[])),
        patch("app.services.session_service.SessionService.get_session", new=AsyncMock(return_value={"total_tokens": 0})),
        patch("app.engine.harness_integration.invoke", new=fake_harness_invoke),
        patch("app.services.agent_execution_service._record_execution_log", new=AsyncMock()),
        patch("app.services.agent_execution_service.messages_to_timeline_entries", new=lambda *a, **k: []),
        patch("app.services.agent_execution_service._should_persist_messages", new=lambda uid: False),
    ):
        checker = lambda: False  # noqa: E731
        resp = await AgentExecutionService.invoke(
            "agent_1", ExecutionRequest(input="hi"), "user_1",
            execution_context="workflow", cancel_checker=checker,
        )

    assert captured.get("execution_context") == "workflow"
    assert captured.get("cancel_checker") is checker
    assert isinstance(resp, ExecutionResponse)
    assert resp.total_tokens == 15

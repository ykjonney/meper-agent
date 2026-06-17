"""Tests for the direct executor (single LLM call, no tool calling)."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.engine.agent.direct_executor import run
from langchain_core.messages import AIMessage


@pytest.fixture
def mock_llm():
    """Create a mock LLM that returns a canned response."""
    llm = MagicMock()
    llm.ainvoke = AsyncMock(
        return_value=AIMessage(content="This is a direct response.")
    )
    return llm


class TestDirectExecutor:
    """Direct executor — single LLM call, no tool loop."""

    async def test_basic_response(self, mock_llm):
        """Should return an AI response message."""
        state = {
            "messages": [{"role": "user", "content": "Hello!"}],
            "agent_id": "agent_01HTEST",
            "execution_path": "direct",
            "request_id": "req_001",
            "tool_results": {},
            "step_count": 0,
            "error": None,
        }

        result = await run(state, mock_llm)

        assert result["step_count"] == 1
        assert len(result["messages"]) == 1
        assert result["messages"][0]["role"] == "assistant"
        assert "direct response" in result["messages"][0]["content"].lower()

    async def test_increments_step_count(self, mock_llm):
        """Should increment step_count from the state."""
        state = {
            "messages": [{"role": "user", "content": "Hi"}],
            "agent_id": "agent_01HTEST",
            "execution_path": "direct",
            "request_id": "req_002",
            "tool_results": {},
            "step_count": 5,
            "error": None,
        }

        result = await run(state, mock_llm)
        assert result["step_count"] == 6

    async def test_calls_llm_with_messages(self, mock_llm):
        """Should pass state messages to LLM."""
        state = {
            "messages": [{"role": "user", "content": "What is 2+2?"}],
            "agent_id": "agent_01HTEST",
            "execution_path": "direct",
            "request_id": "req_003",
            "tool_results": {},
            "step_count": 1,
            "error": None,
        }

        await run(state, mock_llm)

        mock_llm.ainvoke.assert_awaited_once()
        # Check that the LLM received messages
        call_args = mock_llm.ainvoke.call_args[0][0]
        assert len(call_args) >= 1
        assert any(
            (hasattr(m, "content") and m.content == "What is 2+2?")
            or (isinstance(m, dict) and m.get("content") == "What is 2+2?")
            for m in call_args
        )

    async def test_preserves_other_state_fields(self, mock_llm):
        """Should preserve non-message state fields."""
        state = {
            "messages": [{"role": "user", "content": "Test"}],
            "agent_id": "agent_01HTEST",
            "execution_path": "direct",
            "request_id": "req_004",
            "tool_results": {"prev_tool": "result"},
            "step_count": 0,
            "error": None,
        }

        result = await run(state, mock_llm)

        assert result["agent_id"] == "agent_01HTEST"
        assert result["execution_path"] == "direct"
        assert result["request_id"] == "req_004"
        assert result["tool_results"] == {"prev_tool": "result"}

    async def test_empty_messages(self, mock_llm):
        """Should handle empty messages list gracefully."""
        mock_llm.ainvoke = AsyncMock(
            return_value=AIMessage(content="No input provided.")
        )

        state = {
            "messages": [],
            "agent_id": "agent_01HTEST",
            "execution_path": "direct",
            "request_id": "req_005",
            "tool_results": {},
            "step_count": 0,
            "error": None,
        }

        result = await run(state, mock_llm)
        assert result["step_count"] == 1
        assert "No input" in result["messages"][0]["content"]

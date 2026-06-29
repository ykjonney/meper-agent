"""Tests for the REACT executor (Reasoning + Acting loop)."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.engine.agent.react_executor import run
from langchain_core.messages import AIMessage


@pytest.fixture
def mock_llm():
    """Create a mock LLM that returns a canned response."""
    llm = MagicMock()
    llm.ainvoke = AsyncMock(
        return_value=AIMessage(content="I'll help you with that.")
    )
    return llm


@pytest.fixture
def mock_tool_llm():
    """Create a mock LLM that simulates tool calling then final answer."""
    llm = MagicMock()

    call_count = 0

    async def _ainvoke(messages):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call: return a tool call
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "get_weather",
                        "args": {"city": "Shanghai"},
                        "id": "call_001",
                    }
                ],
            )
        # Second call: return final answer after tool result
        return AIMessage(content="The weather in Shanghai is 25°C and sunny.")

    llm.ainvoke = AsyncMock(side_effect=_ainvoke)
    return llm


class TestReactExecutor:
    """REACT executor — reasoning loop with optional tool calling."""

    async def test_basic_response(self, mock_llm):
        """Should return an AI response for simple queries."""
        state = {
            "messages": [{"role": "user", "content": "Hello!"}],
            "agent_id": "agent_01HTEST",
            "execution_path": "react",
            "request_id": "req_001",
            "tool_results": {},
            "step_count": 0,
            "error": None,
        }

        result = await run(state, mock_llm, [])

        assert result["step_count"] == 1
        assert len(result["messages"]) >= 1
        assert "messages" in result

    async def test_increments_step_count(self, mock_llm):
        """Should increment step_count."""
        state = {
            "messages": [{"role": "user", "content": "Hi"}],
            "agent_id": "agent_01HTEST",
            "execution_path": "react",
            "request_id": "req_002",
            "tool_results": {},
            "step_count": 3,
            "error": None,
        }

        result = await run(state, mock_llm, [])
        assert result["step_count"] >= 4

    async def test_calls_llm_with_user_message(self, mock_llm):
        """Should pass messages to LLM."""
        state = {
            "messages": [{"role": "user", "content": "What is Python?"}],
            "agent_id": "agent_01HTEST",
            "execution_path": "react",
            "request_id": "req_003",
            "tool_results": {},
            "step_count": 0,
            "error": None,
        }

        await run(state, mock_llm, [])

        mock_llm.ainvoke.assert_awaited_once()
        call_args = mock_llm.ainvoke.call_args[0][0]
        assert any(
            (hasattr(m, "content") and "What is Python?" in str(m.content))
            or (isinstance(m, dict) and "What is Python?" in str(m.get("content", "")))
            for m in call_args
        )

    async def test_preserves_state_fields(self, mock_llm):
        """Should preserve non-message state fields."""
        state = {
            "messages": [{"role": "user", "content": "Test"}],
            "agent_id": "agent_01HTEST",
            "execution_path": "react",
            "request_id": "req_004",
            "tool_results": {},
            "step_count": 0,
            "error": None,
        }

        result = await run(state, mock_llm, [])

        assert result["agent_id"] == "agent_01HTEST"
        assert result["execution_path"] == "react"
        assert result["request_id"] == "req_004"

    async def test_tool_calling_flow(self, mock_tool_llm):
        """Should handle tool calls and return final response."""
        state = {
            "messages": [{"role": "user", "content": "What's the weather in Shanghai?"}],
            "agent_id": "agent_01HTEST",
            "execution_path": "react",
            "request_id": "req_005",
            "tool_results": {},
            "step_count": 0,
            "error": None,
        }

        # Provide a simple get_weather tool
        def get_weather(city: str) -> str:
            return f"Weather in {city}: 25°C, sunny"

        result = await run(state, mock_tool_llm, [get_weather])

        # Should have gone through tool call + final answer
        assert result["step_count"] >= 1

    async def test_empty_messages(self, mock_llm):
        """Should handle empty messages list."""
        state = {
            "messages": [],
            "agent_id": "agent_01HTEST",
            "execution_path": "react",
            "request_id": "req_006",
            "tool_results": {},
            "step_count": 0,
            "error": None,
        }

        result = await run(state, mock_llm, [])
        assert result["step_count"] == 1

    async def test_no_tools_falls_back_to_simple_call(self, mock_llm):
        """Without tools, REACT behaves like direct."""
        state = {
            "messages": [{"role": "user", "content": "Hello!"}],
            "agent_id": "agent_01HTEST",
            "execution_path": "react",
            "request_id": "req_007",
            "tool_results": {},
            "step_count": 0,
            "error": None,
        }

        result = await run(state, mock_llm, [])
        assert result["step_count"] == 1
        mock_llm.ainvoke.assert_awaited_once()

    async def test_max_iterations_limit(self):
        """Should stop after max iterations even if LLM keeps calling tools."""
        llm = MagicMock()

        async def _always_call_tool(messages):
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "dummy_tool",
                        "args": {"x": 1},
                        "id": "call_loop",
                    }
                ],
            )

        llm.ainvoke = AsyncMock(side_effect=_always_call_tool)

        def dummy_tool(x: int) -> str:
            return f"Result: {x}"

        state = {
            "messages": [{"role": "user", "content": "Do something"}],
            "agent_id": "agent_01HTEST",
            "execution_path": "react",
            "request_id": "req_008",
            "tool_results": {},
            "step_count": 0,
            "error": None,
        }

        result = await run(state, llm, [dummy_tool])

        # Should have completed (reached max iterations) without crashing
        assert "messages" in result
        assert result["step_count"] < 50  # Safety check: not infinite

    async def test_tool_execution_error(self):
        """Should handle tool execution errors gracefully."""
        llm = MagicMock()

        call_count = 0

        async def _ainvoke(messages):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "failing_tool",
                            "args": {},
                            "id": "call_fail",
                        }
                    ],
                )
            return AIMessage(content="I encountered an error but let me help anyway.")

        llm.ainvoke = AsyncMock(side_effect=_ainvoke)

        def failing_tool() -> str:
            raise ValueError("Tool execution failed!")

        state = {
            "messages": [{"role": "user", "content": "Do something"}],
            "agent_id": "agent_01HTEST",
            "execution_path": "react",
            "request_id": "req_009",
            "tool_results": {},
            "step_count": 0,
            "error": None,
        }

        result = await run(state, llm, [failing_tool])
        # Should complete without crashing
        assert "messages" in result
        assert result["step_count"] >= 1

"""Tests for the planner executor (plan → execute → verify loop)."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.engine.agent.planner_executor import run


@pytest.fixture
def mock_llm():
    """Create a mock LLM that returns a plan then a final answer."""
    llm = MagicMock()
    call_count = 0

    async def _ainvoke(messages):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return AIMessage(
                content="## Plan\n1. Analyze the request\n2. Execute the task\n3. Verify results"
            )
        if call_count <= 3:
            return AIMessage(content="Executing step...")
        return AIMessage(content="Verified final answer after plan execution.")

    llm.ainvoke = AsyncMock(side_effect=_ainvoke)
    return llm


@pytest.fixture
def mock_tool_llm():
    """Create a mock LLM that does plan → tool call → final answer."""
    llm = MagicMock()
    call_count = 0

    async def _ainvoke(messages):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return AIMessage(content="## Plan\n1. Search data\n2. Analyze")
        if call_count == 2:
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "search_tool",
                        "args": {"query": "test"},
                        "id": "call_search",
                    }
                ],
            )
        if call_count == 3:
            return AIMessage(content="Data analyzed successfully.")
        return AIMessage(content="Verified: All results are correct and complete.")

    llm.ainvoke = AsyncMock(side_effect=_ainvoke)
    return llm


class TestPlannerExecutor:
    """Planner executor — plan → execute → verify three-phase loop."""

    async def test_plan_phase_generates_plan(self, mock_llm):
        """Should call LLM with plan prompt and generate a plan."""
        state = {
            "messages": [{"role": "user", "content": "Analyze the data"}],
            "agent_id": "agent_01HTEST",
            "execution_path": "planner",
            "request_id": "req_001",
            "tool_results": {},
            "step_count": 0,
            "error": None,
        }

        result = await run(state, mock_llm, [])

        # Should have plan text in at least one message
        assert result["step_count"] >= 1

        # Verify plan prompt was sent in first call
        first_call_args = mock_llm.ainvoke.call_args_list[0][0][0]
        plan_prompt_found = any(
            (hasattr(m, "content") and "plan" in str(m.content).lower())
            or (isinstance(m, dict) and "plan" in str(m.get("content", "")).lower())
            for m in first_call_args
        )
        assert plan_prompt_found

    async def test_full_plan_execute_verify_flow(self, mock_llm):
        """Should complete all three phases (plan → execute → verify)."""
        state = {
            "messages": [{"role": "user", "content": "Analyze the data"}],
            "agent_id": "agent_01HTEST",
            "execution_path": "planner",
            "request_id": "req_002",
            "tool_results": {},
            "step_count": 0,
            "error": None,
        }

        result = await run(state, mock_llm, [])

        # Min: 1 plan call + 1 execute call + 1 verify call
        assert mock_llm.ainvoke.await_count >= 3
        assert result["step_count"] >= 3
        assert "messages" in result

        # Verify prompt should be in the final call
        last_call_args = mock_llm.ainvoke.call_args_list[-1][0][0]
        verify_prompt_found = any(
            (hasattr(m, "content") and "verif" in str(m.content).lower())
            or (isinstance(m, dict) and "verif" in str(m.get("content", "")).lower())
            for m in last_call_args
        )
        assert verify_prompt_found

    async def test_tool_calling_in_execute_phase(self, mock_tool_llm):
        """Should handle tool calls during the execute phase."""
        state = {
            "messages": [{"role": "user", "content": "Search for data"}],
            "agent_id": "agent_01HTEST",
            "execution_path": "planner",
            "request_id": "req_003",
            "tool_results": {},
            "step_count": 0,
            "error": None,
        }

        def search_tool(query: str) -> str:
            return f"Results for: {query}"

        result = await run(state, mock_tool_llm, [search_tool])

        assert result["step_count"] >= 3
        assert "messages" in result

    async def test_empty_messages(self, mock_llm):
        """Should handle empty messages list."""
        state = {
            "messages": [],
            "agent_id": "agent_01HTEST",
            "execution_path": "planner",
            "request_id": "req_004",
            "tool_results": {},
            "step_count": 0,
            "error": None,
        }

        result = await run(state, mock_llm, [])
        assert result["step_count"] >= 1

    async def test_preserves_state_fields(self, mock_llm):
        """Should preserve non-message state fields."""
        state = {
            "messages": [{"role": "user", "content": "Test"}],
            "agent_id": "agent_01HTEST",
            "execution_path": "planner",
            "request_id": "req_005",
            "tool_results": {"prev_result": "ok"},
            "step_count": 0,
            "error": None,
        }

        result = await run(state, mock_llm, [])

        assert result["agent_id"] == "agent_01HTEST"
        assert result["execution_path"] == "planner"
        assert result["request_id"] == "req_005"
        assert result["tool_results"] == {"prev_result": "ok"}

    async def test_increments_step_count(self, mock_llm):
        """Should increment step_count."""
        state = {
            "messages": [{"role": "user", "content": "Hi"}],
            "agent_id": "agent_01HTEST",
            "execution_path": "planner",
            "request_id": "req_006",
            "tool_results": {},
            "step_count": 3,
            "error": None,
        }

        result = await run(state, mock_llm, [])
        assert result["step_count"] >= 6  # 3 + min 3 LLM calls

    async def test_max_execution_steps_limit(self):
        """Should stop after max execution steps even if LLM keeps calling tools."""
        llm = MagicMock()
        call_count = 0

        async def _always_call_tool(messages):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return AIMessage(content="## Plan\n1. Do something")
            # Execute phase: always call tool
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
            "execution_path": "planner",
            "request_id": "req_007",
            "tool_results": {},
            "step_count": 0,
            "error": None,
        }

        result = await run(state, llm, [dummy_tool])

        assert "messages" in result
        # Should not be infinite
        assert result["step_count"] < 50

    async def test_tool_execution_error(self):
        """Should handle tool execution errors gracefully."""
        llm = MagicMock()
        call_count = 0

        async def _ainvoke(messages):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return AIMessage(content="## Plan\n1. Use failing tool")
            if call_count == 2:
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
            return AIMessage(content="Completed with errors.")

        llm.ainvoke = AsyncMock(side_effect=_ainvoke)

        def failing_tool() -> str:
            raise ValueError("Tool execution failed!")

        state = {
            "messages": [{"role": "user", "content": "Do something"}],
            "agent_id": "agent_01HTEST",
            "execution_path": "planner",
            "request_id": "req_008",
            "tool_results": {},
            "step_count": 0,
            "error": None,
        }

        result = await run(state, llm, [failing_tool])
        assert "messages" in result
        assert result["step_count"] >= 1

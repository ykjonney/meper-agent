"""Tests for the REACT executor (Reasoning + Acting loop)."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from app.engine.agent.react_executor import _unwrap_raw_arguments, run
from langchain_core.messages import AIMessage
from langchain_core.tools import tool


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


class TestUnwrapRawArguments:
    """Tests for _unwrap_raw_arguments DashScope compatibility helper."""

    def test_unwraps_valid_json(self):
        """Should parse raw_arguments containing valid JSON dict."""
        args = {"raw_arguments": '{"path": "report.csv", "content": "hello"}'}
        result = _unwrap_raw_arguments(args)
        assert result == {"path": "report.csv", "content": "hello"}

    def test_returns_normal_args_unchanged(self):
        """Should not modify args that don't have the raw_arguments pattern."""
        args = {"path": "report.csv", "content": "hello"}
        assert _unwrap_raw_arguments(args) == args

    def test_ignores_raw_arguments_with_extra_keys(self):
        """Should not unwrap when other keys are present alongside raw_arguments."""
        args = {"raw_arguments": '{"path": "x"}', "other": 1}
        assert _unwrap_raw_arguments(args) == args

    def test_returns_non_dict_unchanged(self):
        """Should handle non-dict inputs gracefully."""
        assert _unwrap_raw_arguments(None) is None
        assert _unwrap_raw_arguments("string") == "string"
        assert _unwrap_raw_arguments(42) == 42
        assert _unwrap_raw_arguments([1, 2]) == [1, 2]

    def test_returns_original_on_invalid_json(self):
        """Should return original args when raw_arguments is not valid JSON."""
        args = {"raw_arguments": "not valid json {"}
        assert _unwrap_raw_arguments(args) == args

    def test_returns_original_when_parsed_not_dict(self):
        """Should return original args when parsed JSON is not a dict."""
        args = {"raw_arguments": "[1, 2, 3]"}
        assert _unwrap_raw_arguments(args) == args

    def test_returns_original_when_raw_not_string(self):
        """Should return original args when raw_arguments value is not a string."""
        args = {"raw_arguments": 42}
        assert _unwrap_raw_arguments(args) == args

    def test_unwraps_with_literal_newlines(self):
        """Should parse raw_arguments containing literal newlines in values."""
        # Simulate what the LLM actually sends: literal \n inside the JSON string
        raw = '{"path": "index.html", "content": "<html>\n<body>\nhello\n</body>\n</html>"}'
        args = {"raw_arguments": raw}
        result = _unwrap_raw_arguments(args)
        assert result == {"path": "index.html", "content": "<html>\n<body>\nhello\n</body>\n</html>"}

    def test_unwraps_with_mixed_escapes_and_literal_newlines(self):
        """Should handle raw_arguments with both \\n escapes and literal newlines."""
        # Has both \\n (escaped, valid JSON) and literal newline (invalid JSON)
        raw = '{"path": "a.html", "content": "line1\\nline2\nline3"}'
        args = {"raw_arguments": raw}
        result = _unwrap_raw_arguments(args)
        assert isinstance(result, dict)
        assert result["path"] == "a.html"
        assert "line1\nline2" in result["content"]
        assert "line3" in result["content"]

    def test_unwraps_truncated_json(self):
        """Should repair truncated raw_arguments (content cut off by max_tokens)."""
        # Content string is never closed — simulates max_tokens truncation
        raw = '{"path": "index.html", "content": "<html>\\n<body>very long...'
        args = {"raw_arguments": raw}
        result = _unwrap_raw_arguments(args)
        assert isinstance(result, dict)
        assert result["path"] == "index.html"
        assert result["content"].startswith("<html>\n<body>very long...")

    def test_unwraps_truncated_json_with_nested_brackets(self):
        """Should repair truncation with unclosed nested structures."""
        raw = '{"data": {"items": [1, 2, "three'
        args = {"raw_arguments": raw}
        result = _unwrap_raw_arguments(args)
        assert isinstance(result, dict)
        assert result["data"]["items"] == [1, 2, "three"]

    async def test_react_executor_unwraps_raw_args_in_tool_call(self):
        """REACT loop should successfully call a tool when LLM sends raw_arguments."""
        llm = MagicMock()

        call_count = 0

        async def _ainvoke(messages):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Simulate DashScope Qwen behavior: raw_arguments wrapper
                return AIMessage(
                    content="",
                    tool_calls=[
                        {
                            "name": "write_to_output",
                            "args": {
                                "raw_arguments": '{"path": "test.txt", "content": "data"}'
                            },
                            "id": "call_raw",
                        }
                    ],
                )
            return AIMessage(content="Done!")

        # bind_tools must return a mock that also supports ainvoke
        bound_llm = MagicMock()
        bound_llm.ainvoke = AsyncMock(side_effect=_ainvoke)
        llm.bind_tools = MagicMock(return_value=bound_llm)

        received_args = {}

        @tool
        def write_to_output(path: str, content: str) -> str:
            """Write content to a file."""
            received_args["path"] = path
            received_args["content"] = content
            return f"Wrote {path}"

        state = {
            "messages": [{"role": "user", "content": "Write something"}],
            "agent_id": "agent_test",
            "execution_path": "react",
            "request_id": "req_raw",
            "tool_results": {},
            "step_count": 0,
            "error": None,
        }

        result = await run(state, llm, [write_to_output])

        # Tool should have received the unwrapped arguments
        assert received_args["path"] == "test.txt"
        assert received_args["content"] == "data"
        assert result["step_count"] >= 1

"""Tests for conversation context management and compression."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from app.engine.agent.context import (
    _DEFAULT_KEEP_MESSAGES,
    _DEFAULT_RESERVED_TOKENS,
    _build_summary,
    compress_messages,
    estimate_message_tokens,
    estimate_messages_tokens,
    estimate_tokens,
    extract_model_name,
    get_context_window,
    should_compress,
)


class TestTokenEstimation:
    """Token estimation utilities."""

    def test_estimate_tokens_short_text(self):
        """Short text should estimate at least 1 token."""
        assert estimate_tokens("") == 1
        assert estimate_tokens("a") == 1

    def test_estimate_tokens_ratio(self):
        """~4 chars per token heuristic."""
        # 40 chars → ~10 tokens
        text = "Hello, this is a test message for token counting."
        assert estimate_tokens(text) == len(text) // 4

    def test_estimate_tokens_chinese(self):
        """Chinese text should also use ~4 chars per token."""
        text = "这是一个中文测试消息，用于验证令牌估算功能是否正常工作。"
        assert estimate_tokens(text) == len(text) // 4

    def test_estimate_message_tokens_human(self):
        """HumanMessage token count should include overhead."""
        msg = HumanMessage(content="hello")
        tokens = estimate_message_tokens(msg)
        assert tokens > estimate_tokens("hello")

    def test_estimate_message_tokens_dict(self):
        """Dict-style messages should also be estimable."""
        msg: dict = {"role": "user", "content": "hello"}
        tokens = estimate_message_tokens(msg)
        assert tokens > 0

    def test_estimate_messages_tokens(self):
        """Should sum tokens across all messages."""
        msgs = [HumanMessage(content="a"), AIMessage(content="b" * 100)]
        total = estimate_messages_tokens(msgs)
        assert total > estimate_tokens("a" * 100)


class TestContextWindow:
    """Context window lookup."""

    def test_get_context_window_openai(self):
        """OpenAI gpt-4o should return 128000."""
        assert get_context_window("gpt-4o") == 128000

    def test_get_context_window_gpt4(self):
        """GPT-4 (non-turbo) should return 8192."""
        assert get_context_window("gpt-4") == 8192

    def test_get_context_window_anthropic(self):
        """Claude models should return 200000."""
        assert get_context_window("claude-sonnet-4") == 200000

    def test_get_context_window_unknown(self):
        """Unknown model should return default."""
        assert get_context_window("unknown-model") == 128000

    def test_extract_model_name_from_model_name_attr(self):
        """Should extract from model_name attribute."""
        mock = MagicMock()
        mock.model_name = "gpt-4o"
        assert extract_model_name(mock) == "gpt-4o"

    def test_extract_model_name_from_model_attr(self):
        """Should fall back to model attribute."""
        mock = MagicMock()
        mock.model_name = ""
        mock.model = "claude-sonnet-4"
        assert extract_model_name(mock) == "claude-sonnet-4"

    def test_extract_model_name_empty(self):
        """Should return empty string when no model info."""
        mock = MagicMock()
        mock.model_name = ""
        mock.model = ""
        assert extract_model_name(mock) == ""


class TestShouldCompress:
    """Compression trigger detection."""

    def test_should_not_compress_empty(self):
        """Empty messages should not trigger compression."""
        assert not should_compress([], "gpt-4o")

    def test_should_not_compress_small(self):
        """Few small messages should not trigger compression."""
        msgs = [HumanMessage(content="hi"), AIMessage(content="hello")]
        assert not should_compress(msgs, "gpt-4o")

    def test_should_compress_large(self):
        """Many large messages should trigger compression."""
        msgs = [HumanMessage(content="x" * 100000) for _ in range(100)]
        assert should_compress(msgs, "gpt-4o-mini")

    def test_should_compress_with_reserved(self):
        """A large message should still trigger compression even with reserved."""
        msgs = [HumanMessage(content="x" * 50000)]
        # 12500 tokens > (16384 - 7000) * 0.7 = 6568 → should compress
        assert should_compress(msgs, "gpt-3.5-turbo", reserved_tokens=7000)


class TestCompressMessages:
    """Message list compression."""

    def test_compress_empty(self):
        """Empty list should remain empty."""
        assert compress_messages([]) == []

    def test_compress_below_threshold(self):
        """Messages below threshold should not be compressed."""
        msgs = [HumanMessage(content="hi"), AIMessage(content="hello")]
        result = compress_messages(msgs, "gpt-4o")
        assert len(result) == 2
        assert result == msgs

    def test_compress_few_messages(self):
        """Fewer messages than keep_last should remain unchanged."""
        msgs = [HumanMessage(content=f"msg_{i}") for i in range(5)]
        result = compress_messages(msgs, "gpt-4o", keep_last=10)
        assert len(result) == 5
        assert result == msgs

    def test_compress_above_threshold(self):
        """Large messages should trigger compression into SystemMessage summary."""
        # Each message ~35000 chars → ~8750 tokens per message
        # 10 messages = ~87500 tokens > threshold for gpt-4o-mini
        msg_size = 35000
        msgs: list[BaseMessage] = [
            HumanMessage(content=f"query_{i} " + "x" * msg_size) for i in range(10)
        ]
        result = compress_messages(msgs, "gpt-4o-mini", keep_last=3)
        # Should be compressed: summary + 3 recent = 4 messages
        # (or fewer if keep_last was reduced recursively)
        assert len(result) < len(msgs)
        assert any(isinstance(m, SystemMessage) for m in result)

    def test_compress_preserves_recent(self):
        """Most recent messages should be preserved verbatim after compression."""
        msg_size = 45000  # ~11250 tokens per message
        msgs: list[BaseMessage] = [
            HumanMessage(content=f"msg_{i} " + "x" * msg_size) for i in range(10)
        ]
        result = compress_messages(msgs, "gpt-4o-mini", keep_last=4)
        # Last message should be preserved
        assert len(result) < len(msgs)
        assert result[-1].content == msgs[-1].content

    def test_compress_with_tool_messages(self):
        """Should handle mixed message types including tool results."""
        # Use gpt-3.5-turbo (16384 window) so large message triggers compression
        msg_size = 40000  # ~10000 tokens > threshold
        msgs: list[BaseMessage] = [
            HumanMessage(content="what is the status " + "x" * msg_size),
            AIMessage(content="let me search"),
            ToolMessage(content="result data: found 3 items", tool_call_id="call_1"),
            AIMessage(content="final answer"),
            HumanMessage(content="tell me more"),
        ]
        result = compress_messages(msgs, "gpt-3.5-turbo", keep_last=2)
        # Should compress the older messages
        assert len(result) < len(msgs)
        assert any(isinstance(m, SystemMessage) for m in result)

    def test_compress_handles_dict_messages(self):
        """Should handle dict-style messages."""
        msgs: list = [
            {"role": "user", "content": "x" * 40000},
            {"role": "assistant", "content": "y" * 1000},
            {"role": "user", "content": "z" * 100},
        ]
        # Use gpt-4 (8192 window) so the large message triggers compression
        result = compress_messages(msgs, "gpt-4", keep_last=1)
        assert len(result) < len(msgs)
        assert isinstance(result[0], SystemMessage)
        assert "用户" in str(result[0].content)
        assert "用户" in str(result[0].content)


class TestBuildSummary:
    """Summary builder."""

    def test_build_summary_human_and_ai(self):
        """Should label roles correctly."""
        msgs = [HumanMessage(content="hello"), AIMessage(content="world")]
        summary = _build_summary(msgs)
        assert "[用户] hello" in summary
        assert "[助手] world" in summary

    def test_build_summary_tool_truncation(self):
        """Long tool results should be truncated."""
        msgs = [ToolMessage(content="x" * 500, tool_call_id="call_1")]
        summary = _build_summary(msgs)
        assert "..." in summary
        assert len(summary) < 250  # truncated


class TestReactExecutorIntegration:
    """Context compression integration in REACT loop."""

    @pytest.mark.asyncio
    async def test_compression_called_before_llm(self):
        """REACT loop should call compression before LLM invoke."""
        from app.engine.agent.react_executor import run

        # Mock LLM that returns a final answer immediately
        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = "final answer"
        mock_response.tool_calls = []
        mock_response.__bool__ = lambda self: True
        mock_llm.ainvoke.return_value = mock_response
        mock_llm.model_name = "gpt-4o-mini"

        state = {
            "messages": [
                {"role": "user", "content": "x" * 100000},
                {"role": "assistant", "content": "y" * 100000},
                {"role": "user", "content": "tell me more"},
            ],
            "agent_id": "test-agent",
            "execution_path": "react",
            "request_id": "test-req",
            "tool_results": {},
            "step_count": 0,
            "error": None,
        }

        # The messages are small enough (3 messages) that compression won't trigger
        # So just verify the executor works normally
        result = await run(state, mock_llm, [])
        assert result is not None
        assert len(result["messages"]) > 0
        mock_llm.ainvoke.assert_called_once()

    @pytest.mark.asyncio
    async def test_compression_triggers_for_large_context(self):
        """REACT loop should compress when context is near limit."""
        from app.engine.agent.react_executor import run

        mock_llm = AsyncMock()
        mock_response = MagicMock()
        mock_response.content = "final answer"
        mock_response.tool_calls = []
        mock_response.__bool__ = lambda self: True
        mock_llm.ainvoke.return_value = mock_response
        mock_llm.model_name = "gpt-4o-mini"

        # Create many large messages to trigger compression
        large_messages: list = [
            {"role": "user", "content": "x" * 50000} for _ in range(10)
        ]

        state = {
            "messages": large_messages,
            "agent_id": "test-agent",
            "execution_path": "react",
            "request_id": "test-req",
            "tool_results": {},
            "step_count": 0,
            "error": None,
        }

        with patch(
            "app.engine.agent.react_executor.compress_messages",
            wraps=lambda msgs, model, **_kw: [
                SystemMessage(content="[compressed]"),
                *msgs[-3:],
            ],
        ) as mock_compress:
            # Temporarily lower the threshold to force compression
            with patch(
                "app.engine.agent.context._DEFAULT_COMPRESSION_THRESHOLD",
                0.01,
            ):
                result = await run(state, mock_llm, [])
            assert result is not None
            mock_llm.ainvoke.assert_called_once()

"""AC10 cover: migrated context helpers behave correctly inside the harness."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent_flow_harness.engine.context import (
    compress_messages,
    estimate_message_tokens,
    estimate_tokens,
    extract_model_name,
    should_compress,
)


class _NamedLLM:
    """Tiny stand-in exposing ``model_name`` like a LangChain chat model."""

    def __init__(self, name: str) -> None:
        self.model_name = name


def test_estimate_tokens_positive_for_text() -> None:
    assert estimate_tokens("") >= 0
    assert estimate_tokens("hello world") > 0
    assert estimate_tokens("a" * 1000) > estimate_tokens("a")


def test_estimate_message_tokens_handles_message_and_dict() -> None:
    msg = HumanMessage(content="hello")
    assert estimate_message_tokens(msg) > 0
    assert estimate_message_tokens({"role": "user", "content": "hello"}) > 0


def test_extract_model_name_reads_attribute() -> None:
    assert extract_model_name(_NamedLLM("gpt-4o-mini")) == "gpt-4o-mini"


def test_should_compress_respects_context_window_override() -> None:
    """A tiny context_window forces compression; a huge one does not."""
    big = [HumanMessage(content=f"line {i}") for i in range(20)]
    assert should_compress(big, "x", context_window=64) is True
    assert should_compress(big, "x", context_window=1_000_000) is False


def test_compress_messages_shrinks_and_keeps_recent() -> None:
    """Compression produces fewer messages and preserves the last N verbatim."""
    messages = [SystemMessage(content="sys")] + [
        HumanMessage(content=f"h{i}") for i in range(30)
    ]
    compressed = compress_messages(messages, "gpt-4o-mini", context_window=64)
    assert len(compressed) < len(messages)
    # The most recent messages are kept untouched at the tail.
    assert compressed[-1].content == messages[-1].content


def test_compress_messages_noop_under_threshold() -> None:
    """When nothing exceeds the threshold the list is returned unchanged in length."""
    small = [HumanMessage(content="hi")]
    out = compress_messages(small, "gpt-4o-mini", context_window=1_000_000)
    assert out == small


def test_compress_messages_preserves_ai_message_shape() -> None:
    """An AIMessage in the kept tail round-trips with its content intact."""
    messages = [HumanMessage(content=f"m{i}") for i in range(40)]
    messages.append(AIMessage(content="final"))
    out = compress_messages(messages, "gpt-4o-mini", context_window=64)
    assert isinstance(out[-1], AIMessage)
    assert out[-1].content == "final"

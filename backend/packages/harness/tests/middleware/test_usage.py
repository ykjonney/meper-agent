"""UsageMiddleware token tracking tests."""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage

from agent_flow_harness.middleware import UsageMiddleware, resolve_middleware


# ---------------------------------------------------------------------------
# UsageMiddleware 单元测试
# ---------------------------------------------------------------------------


class _FakeLLM:
    """带 response_metadata(token usage) 的假 LLM。"""

    def __init__(self, response: AIMessage):
        self._response = response

    @property
    def model_name(self):
        return "fake"

    def bind_tools(self, _tools):
        return self

    async def ainvoke(self, messages, _config=None):
        return self._response


def _ai_with_openai_usage(content="ok", prompt=100, completion=20):
    """构造 OpenAI 格式 token usage 的 AIMessage。"""
    return AIMessage(
        content=content,
        response_metadata={
            "model_name": "gpt-4o",
            "token_usage": {
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": prompt + completion,
            },
        },
    )


def _ai_with_anthropic_usage(content="ok", input_t=200, output_t=30):
    """构造 Anthropic 格式 token usage 的 AIMessage。"""
    return AIMessage(
        content=content,
        response_metadata={
            "usage": {"input_tokens": input_t, "output_tokens": output_t},
        },
    )


@pytest.mark.asyncio
async def test_openai_usage_extracted():
    mw = UsageMiddleware()
    resp = _ai_with_openai_usage(prompt=100, completion=20)
    await mw.before_llm({})
    await mw.after_llm({}, resp)
    s = mw.summary
    assert s["input_tokens"] == 100
    assert s["output_tokens"] == 20
    assert s["total_tokens"] == 120
    assert s["llm_calls"] == 1


@pytest.mark.asyncio
async def test_anthropic_usage_extracted():
    mw = UsageMiddleware()
    resp = _ai_with_anthropic_usage(input_t=200, output_t=30)
    await mw.before_llm({})
    await mw.after_llm({}, resp)
    s = mw.summary
    assert s["input_tokens"] == 200
    assert s["output_tokens"] == 30
    assert s["total_tokens"] == 230


@pytest.mark.asyncio
async def test_accumulates_across_calls():
    mw = UsageMiddleware()
    for _ in range(3):
        await mw.before_llm({})
        await mw.after_llm({}, _ai_with_openai_usage(prompt=50, completion=10))
    s = mw.summary
    assert s["total_tokens"] == 180  # 3 * 60
    assert s["llm_calls"] == 3


@pytest.mark.asyncio
async def test_no_usage_metadata():
    """无 usage metadata 时不崩溃，token 为 0。"""
    mw = UsageMiddleware()
    resp = AIMessage(content="ok")  # 无 response_metadata
    await mw.before_llm({})
    await mw.after_llm({}, resp)
    assert mw.summary["total_tokens"] == 0
    assert mw.summary["llm_calls"] == 1


@pytest.mark.asyncio
async def test_writes_total_tokens_to_state():
    mw = UsageMiddleware()
    state: dict = {}
    await mw.before_llm(state)
    await mw.after_llm(state, _ai_with_openai_usage(prompt=100, completion=20))
    assert state["total_tokens"] == 120
    assert state["step_tokens"] == 120


@pytest.mark.asyncio
async def test_seeds_from_state_total_tokens():
    """A pre-existing state["total_tokens"] (carried over from a prior
    request in the same session) must be adopted as the baseline on the
    first after_llm, so the middleware does not overwrite it with 0.
    """
    mw = UsageMiddleware()
    state: dict = {"total_tokens": 5000}
    await mw.before_llm(state)
    await mw.after_llm(state, _ai_with_openai_usage(prompt=100, completion=20))
    # 5000 baseline + 120 this step
    assert state["total_tokens"] == 5120
    assert mw.summary["total_tokens"] == 5120


@pytest.mark.asyncio
async def test_seeds_only_once_then_accumulates():
    """The baseline is adopted once; subsequent calls keep accumulating on
    top of it rather than re-seeding.
    """
    mw = UsageMiddleware()
    state: dict = {"total_tokens": 5000}
    await mw.before_llm(state)
    await mw.after_llm(state, _ai_with_openai_usage(prompt=100, completion=20))  # +120
    state["total_tokens"] = 5120  # as the runner would merge
    await mw.before_llm(state)
    await mw.after_llm(state, _ai_with_openai_usage(prompt=50, completion=10))  # +60
    assert state["total_tokens"] == 5180  # 5000 + 120 + 60, not re-seeded
    assert mw.summary["total_tokens"] == 5180


@pytest.mark.asyncio
async def test_tool_duration_tracked():
    mw = UsageMiddleware()
    await mw.before_tool({}, {"id": "tc1", "name": "bash"})
    await mw.after_tool({}, {"id": "tc1", "name": "bash"}, "result")
    s = mw.summary
    assert s["tool_calls"] == 1
    assert s["tool_duration"] >= 0.0


@pytest.mark.asyncio
async def test_llm_duration_tracked():
    mw = UsageMiddleware()
    await mw.before_llm({})
    await mw.after_llm({}, _ai_with_openai_usage())
    assert mw.summary["llm_duration"] >= 0.0


def test_reset():
    mw = UsageMiddleware()
    mw.metrics["total_tokens"] = 999
    mw.reset()
    assert mw.summary["total_tokens"] == 0


def test_name_and_order():
    mw = UsageMiddleware()
    assert mw.name == "usage"
    assert mw.order == 50


def test_resolve_by_name():
    """resolve_middleware 能按 'usage' 名实例化。"""
    mws = resolve_middleware([{"name": "usage"}])
    assert len(mws) == 1
    assert isinstance(mws[0], UsageMiddleware)


# ---------------------------------------------------------------------------
# cached_input_tokens（KV-cache 命中可观测，Manus：生产 agent 最重要指标）
# ---------------------------------------------------------------------------


def _ai_with_usage_metadata(
    *, input_t: int, output_t: int, cached: int,
) -> AIMessage:
    """构造带 LangChain 标准 usage_metadata（含 input_token_details）的消息。"""
    return AIMessage(
        content="ok",
        usage_metadata={
            "input_tokens": input_t,
            "output_tokens": output_t,
            "total_tokens": input_t + output_t,
            "input_token_details": {"cached_tokens": cached},
        },
    )


@pytest.mark.asyncio
async def test_cached_tokens_from_usage_metadata():
    """LangChain usage_metadata.input_token_details.cached_tokens 被提取累计。"""
    mw = UsageMiddleware()
    resp = _ai_with_usage_metadata(input_t=1000, output_t=50, cached=800)
    await mw.before_llm({})
    await mw.after_llm({}, resp)
    s = mw.summary
    assert s["cached_input_tokens"] == 800
    # cached 是 input 的子集——纯观测字段，不改计费口径。
    assert s["input_tokens"] == 1000
    assert s["total_tokens"] == 1050


@pytest.mark.asyncio
async def test_cached_tokens_accumulate_across_calls():
    mw = UsageMiddleware()
    for cached in (100, 200, 300):
        resp = _ai_with_usage_metadata(input_t=500, output_t=10, cached=cached)
        await mw.before_llm({})
        await mw.after_llm({}, resp)
    assert mw.summary["cached_input_tokens"] == 600


@pytest.mark.asyncio
async def test_cached_tokens_from_openai_fallback_details():
    """兜底路径：response_metadata.token_usage.prompt_tokens_details.cached_tokens。"""
    mw = UsageMiddleware()
    resp = AIMessage(
        content="ok",
        response_metadata={
            "token_usage": {
                "prompt_tokens": 400,
                "completion_tokens": 10,
                "total_tokens": 410,
                "prompt_tokens_details": {"cached_tokens": 320},
            },
        },
    )
    await mw.before_llm({})
    await mw.after_llm({}, resp)
    assert mw.summary["cached_input_tokens"] == 320


@pytest.mark.asyncio
async def test_cached_tokens_from_anthropic_fallback():
    """兜底路径：Anthropic usage.cache_read_input_tokens。"""
    mw = UsageMiddleware()
    resp = AIMessage(
        content="ok",
        response_metadata={
            "usage": {
                "input_tokens": 400,
                "output_tokens": 10,
                "cache_read_input_tokens": 350,
            },
        },
    )
    await mw.before_llm({})
    await mw.after_llm({}, resp)
    assert mw.summary["cached_input_tokens"] == 350


@pytest.mark.asyncio
async def test_cached_tokens_zero_when_absent():
    """无缓存数据时 cached=0（不抛错、不影响其它字段）。"""
    mw = UsageMiddleware()
    resp = _ai_with_openai_usage(prompt=100, completion=20)
    await mw.before_llm({})
    await mw.after_llm({}, resp)
    assert mw.summary["cached_input_tokens"] == 0

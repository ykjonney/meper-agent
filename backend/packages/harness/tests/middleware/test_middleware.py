"""AC1-AC11 cover: Middleware protocol, chain, 3 built-ins, registry, react wiring."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent_flow_harness.graph import build_config
from agent_flow_harness.middleware import (
    MIDDLEWARE_REGISTRY,
    AuditMiddleware,
    Middleware,
    MiddlewareChain,
    PromptInjectionMiddleware,
    TraceMiddleware,
    resolve_middleware,
)
from agent_flow_harness.engine.react import react_node


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


def test_builtins_satisfy_protocol() -> None:
    for mw in (AuditMiddleware(), PromptInjectionMiddleware(), TraceMiddleware()):
        assert isinstance(mw, Middleware)


def test_default_orders() -> None:
    assert PromptInjectionMiddleware().order == 50
    assert AuditMiddleware().order == 100
    assert TraceMiddleware().order == 200


# ---------------------------------------------------------------------------
# Chain: ordering + passthrough + exception isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_chain_runs_in_ascending_order() -> None:
    """Lower order runs first; the chain threads values through."""
    calls: list[str] = []

    class _M:
        def __init__(self, name: str, order: int) -> None:
            self.name, self.order = name, order

        async def before_llm(self, state):
            calls.append(self.name)
            return state

    chain = MiddlewareChain([_M("late", 200), _M("early", 10), _M("mid", 100)])
    await chain.run_before_llm({})
    assert calls == ["early", "mid", "late"]


@pytest.mark.asyncio
async def test_empty_chain_passes_state_through() -> None:
    chain = MiddlewareChain([])
    s = {"agent_id": "a"}
    assert await chain.run_before_llm(s) is s


@pytest.mark.asyncio
async def test_chain_isolates_exceptions() -> None:
    """A failing middleware is skipped; the previous value flows on."""
    seen: list[str] = []

    class _Boom:
        name = "boom"
        order = 10

        async def before_llm(self, state):
            raise RuntimeError("kaboom")

    class _Ok:
        name = "ok"
        order = 20

        async def before_llm(self, state):
            seen.append("ok")
            return state

    chain = MiddlewareChain([_Boom(), _Ok()])
    out = await chain.run_before_llm({"x": 1})
    assert seen == ["ok"]  # second middleware still ran
    assert out == {"x": 1}  # original value preserved


@pytest.mark.asyncio
async def test_chain_threads_tool_call_rewrites() -> None:
    class _Rewrite:
        name = "rw"
        order = 10

        async def before_tool(self, state, tool_call):
            return {**tool_call, "args": {**tool_call.get("args", {}), "injected": True}}

    chain = MiddlewareChain([_Rewrite()])
    out = await chain.run_before_tool({}, {"name": "bash", "args": {}, "id": "1"})
    assert out["args"]["injected"] is True


@pytest.mark.asyncio
async def test_chain_threads_state_rewrites_after_llm() -> None:
    class _Tag:
        name = "tag"
        order = 10

        async def after_llm(self, state, response):
            return {**state, "tagged": True}

    chain = MiddlewareChain([_Tag()])
    out = await chain.run_after_llm({"a": 1}, SimpleNamespace())
    assert out["tagged"] is True


@pytest.mark.asyncio
async def test_chain_equal_orders_preserve_registration_order() -> None:
    calls: list[str] = []

    class _M:
        def __init__(self, n: str) -> None:
            self.name, self.order = n, 100

        async def before_llm(self, state):
            calls.append(self.name)
            return state

    chain = MiddlewareChain([_M("first"), _M("second")])
    await chain.run_before_llm({})
    assert calls == ["first", "second"]


# ---------------------------------------------------------------------------
# AuditMiddleware
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_before_llm_passthrough() -> None:
    mw = AuditMiddleware()
    state = {"agent_id": "a", "session_id": "s", "step_count": 1, "messages": [object()]}
    out = await mw.before_llm(state)
    assert out is state  # passthrough


@pytest.mark.asyncio
async def test_audit_after_llm_reads_response() -> None:
    mw = AuditMiddleware()
    resp = AIMessage(content="hi", tool_calls=[{"name": "x", "args": {}, "id": "1"}])
    out = await mw.after_llm({"agent_id": "a"}, resp)
    assert out == {"agent_id": "a"}


@pytest.mark.asyncio
async def test_audit_tool_methods_passthrough() -> None:
    mw = AuditMiddleware()
    tc = {"name": "bash", "id": "1"}
    assert await mw.before_tool({}, tc) is tc
    assert await mw.after_tool({}, tc, "result") == {}


def test_audit_log_level_resolved() -> None:
    """An unknown level name falls back to info without raising."""
    # Both should construct cleanly; unknown falls back to info.
    assert callable(AuditMiddleware(log_level="debug")._log)
    assert callable(AuditMiddleware(log_level="bogus")._log)


# ---------------------------------------------------------------------------
# PromptInjectionMiddleware
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prompt_injection_appends_reminder() -> None:
    mw = PromptInjectionMiddleware(reminders=["be concise"])
    state = {"messages": [HumanMessage(content="hi")]}
    out = await mw.before_llm(state)
    last = out["messages"][-1]
    assert isinstance(last, SystemMessage)
    assert "be concise" in last.content


@pytest.mark.asyncio
async def test_prompt_injection_no_reminders_passthrough() -> None:
    mw = PromptInjectionMiddleware()
    state = {"messages": []}
    assert await mw.before_llm(state) is state


@pytest.mark.asyncio
async def test_prompt_injection_multiple_reminders_joined() -> None:
    mw = PromptInjectionMiddleware(reminders=["a", "b"])
    out = await mw.before_llm({"messages": []})
    content = out["messages"][-1].content
    assert "[系统提醒] a" in content
    assert "[系统提醒] b" in content


@pytest.mark.asyncio
async def test_prompt_injection_tool_methods_passthrough() -> None:
    mw = PromptInjectionMiddleware()
    tc = {"name": "x", "id": "1"}
    assert await mw.before_tool({}, tc) is tc
    assert await mw.after_tool({}, tc, "r") == {}


@pytest.mark.asyncio
async def test_prompt_injection_preserves_existing_messages() -> None:
    mw = PromptInjectionMiddleware(reminders=["r"])
    state = {"messages": [HumanMessage(content="orig")], "agent_id": "a"}
    out = await mw.before_llm(state)
    assert out["messages"][0].content == "orig"
    assert out["agent_id"] == "a"


# ---------------------------------------------------------------------------
# TraceMiddleware
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trace_emits_llm_span() -> None:
    spans: list[dict] = []
    mw = TraceMiddleware(emit=spans.append)
    await mw.before_llm({"step_count": 1})
    resp = AIMessage(content="x")
    await mw.after_llm({}, resp)
    assert len(spans) == 1
    assert spans[0]["type"] == "llm"
    assert "duration" in spans[0]


@pytest.mark.asyncio
async def test_trace_emits_tool_span() -> None:
    spans: list[dict] = []
    mw = TraceMiddleware(emit=spans.append)
    tc = {"name": "bash", "id": "1"}
    await mw.before_tool({}, tc)
    await mw.after_tool({}, tc, "done")
    assert spans[0]["type"] == "tool"
    assert spans[0]["tool_name"] == "bash"


@pytest.mark.asyncio
async def test_trace_emit_failure_does_not_raise() -> None:
    def _bad(span):
        raise RuntimeError("emit broke")

    mw = TraceMiddleware(emit=_bad)
    await mw.before_llm({})
    # Should not raise.
    await mw.after_llm({}, AIMessage(content="x"))


@pytest.mark.asyncio
async def test_trace_after_without_span_is_safe() -> None:
    mw = TraceMiddleware()
    out = await mw.after_llm({}, AIMessage(content="x"))
    assert out == {}


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_registry_has_four_builtins() -> None:
    assert set(MIDDLEWARE_REGISTRY) == {
        "audit",
        "prompt_injection",
        "trace",
        "usage",
    }


def test_resolve_middleware_from_specs() -> None:
    mws = resolve_middleware(
        [
            {"name": "audit", "config": {"log_level": "debug"}},
            {"name": "trace", "config": {}},
        ]
    )
    assert [m.name for m in mws] == ["audit", "trace"]


def test_resolve_middleware_empty_returns_empty() -> None:
    assert resolve_middleware(None) == []
    assert resolve_middleware([]) == []


def test_resolve_middleware_unknown_raises() -> None:
    with pytest.raises(ValueError, match="Unknown middleware"):
        resolve_middleware([{"name": "nope"}])


# ---------------------------------------------------------------------------
# react_node wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_react_node_runs_middleware_before_llm(
    base_state, fake_llm_factory, make_run_config
) -> None:
    """A before_llm middleware observes the LLM call."""
    seen: list[int] = []

    class _Observe:
        name = "observe"
        order = 10

        async def before_llm(self, state):
            seen.append(len(state.get("messages", [])))
            return state

        async def after_llm(self, state, response):
            return state

        async def before_tool(self, state, tool_call):
            return tool_call

        async def after_tool(self, state, tool_call, result):
            return state

    llm = fake_llm_factory([AIMessage(content="done")])
    config = make_run_config(llm, tools=[])
    config["configurable"]["middlewares"] = [_Observe()]

    result = await react_node(base_state, config)
    assert seen  # middleware ran
    assert result["step_count"] == 1


@pytest.mark.asyncio
async def test_react_node_middleware_rewrites_tool_args(
    base_state, fake_llm_factory, make_test_tool, make_run_config
) -> None:
    """A before_tool middleware rewrites args seen by the tool."""

    class _Inject:
        name = "inject"
        order = 10

        async def before_llm(self, state):
            return state

        async def after_llm(self, state, response):
            return state

        async def before_tool(self, state, tool_call):
            return {**tool_call, "args": {"touched": True}}

        async def after_tool(self, state, tool_call, result):
            return state

    def _fn(touched: bool = False) -> str:
        return f"got:{touched}"

    from langchain_core.tools import StructuredTool

    tool = StructuredTool.from_function(_fn, name="probe", description="d")
    llm = fake_llm_factory(
        [AIMessage(content="", tool_calls=[{"name": "probe", "args": {}, "id": "c1"}]), AIMessage(content="ok")]
    )
    config = make_run_config(llm, tools=[tool])
    config["configurable"]["middlewares"] = [_Inject()]

    result = await react_node(base_state, config)
    tool_msgs = [m for m in result["messages"] if m.type == "tool"]
    assert tool_msgs[0].content == "got:True"


@pytest.mark.asyncio
async def test_react_node_no_middleware_behaves_unchanged(
    base_state, fake_llm_factory, make_run_config
) -> None:
    """Without middlewares, react_node behaves as in v0.1-2."""
    llm = fake_llm_factory([AIMessage(content="hi")])
    config = make_run_config(llm, tools=[])
    result = await react_node(base_state, config)
    assert result["step_count"] == 1
    assert result["messages"][-1].content == "hi"


# ---------------------------------------------------------------------------
# build_config wiring
# ---------------------------------------------------------------------------


def test_build_config_resolves_middleware_from_agent_doc() -> None:
    llm = object()
    cfg = build_config({"middleware": [{"name": "audit"}, {"name": "trace"}]}, llm)
    names = [m.name for m in cfg["configurable"]["middlewares"]]
    assert names == ["audit", "trace"]


def test_build_config_no_middleware_omits_key() -> None:
    cfg = build_config({}, object())
    assert "middlewares" not in cfg["configurable"]


def test_build_config_explicit_empty_middleware_disables() -> None:
    cfg = build_config({"middleware": [{"name": "audit"}]}, object(), middlewares=[])
    assert "middlewares" not in cfg["configurable"]

"""Middleware protocol, chain, registry and build_config wiring cover."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from agent_flow_harness.graph import build_config
from agent_flow_harness.middleware import (
    MIDDLEWARE_REGISTRY,
    Middleware,
    MiddlewareChain,
    UsageMiddleware,
    resolve_middleware,
)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


def test_builtins_satisfy_protocol() -> None:
    assert isinstance(UsageMiddleware(), Middleware)


def test_default_orders() -> None:
    assert UsageMiddleware().order == 50


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
# Registry
# ---------------------------------------------------------------------------


def test_registry_has_one_builtin() -> None:
    assert set(MIDDLEWARE_REGISTRY) == {"usage"}


def test_resolve_middleware_from_specs() -> None:
    mws = resolve_middleware([{"name": "usage", "config": {}}])
    assert [m.name for m in mws] == ["usage"]


def test_resolve_middleware_empty_returns_empty() -> None:
    assert resolve_middleware(None) == []
    assert resolve_middleware([]) == []


def test_resolve_middleware_unknown_raises() -> None:
    with pytest.raises(ValueError, match="Unknown middleware"):
        resolve_middleware([{"name": "nope"}])


# ---------------------------------------------------------------------------
# build_config wiring
# ---------------------------------------------------------------------------


def test_build_config_resolves_middleware_from_agent_doc() -> None:
    llm = object()
    cfg = build_config({"middleware": [{"name": "usage"}]}, llm)
    names = [m.name for m in cfg["configurable"]["middlewares"]]
    assert names == ["usage"]


def test_build_config_no_middleware_omits_key() -> None:
    cfg = build_config({}, object())
    assert "middlewares" not in cfg["configurable"]


def test_build_config_explicit_empty_middleware_disables() -> None:
    cfg = build_config({"middleware": [{"name": "usage"}]}, object(), middlewares=[])
    assert "middlewares" not in cfg["configurable"]

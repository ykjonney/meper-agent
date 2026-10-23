"""Guard protocol, TokenBudgetGuard, nodes, registry, builder cover."""

from __future__ import annotations

import pytest

from agent_flow_harness.guards import (
    GUARD_REGISTRY,
    Guard,
    TokenBudgetGuard,
    make_guard_in_node,
    resolve_guards,
)
from agent_flow_harness.guards.base import Allow, Block, Warn


# ---------------------------------------------------------------------------
# base
# ---------------------------------------------------------------------------


def test_guard_result_factories() -> None:
    assert Allow().decision == "allow"
    assert Allow().reason == ""
    assert Block("nope").decision == "block"
    assert Block("nope").reason == "nope"
    assert Warn("careful").decision == "warn"


def test_built_in_guards_satisfy_protocol() -> None:
    assert isinstance(TokenBudgetGuard(max_total_tokens=10), Guard)


# ---------------------------------------------------------------------------
# TokenBudgetGuard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_budget_allow() -> None:
    g = TokenBudgetGuard(max_total_tokens=1000)
    assert (await g.check_in({"total_tokens": 100})).decision == "allow"


@pytest.mark.asyncio
async def test_token_budget_warn_at_90_percent() -> None:
    g = TokenBudgetGuard(max_total_tokens=1000)
    result = await g.check_in({"total_tokens": 950})
    assert result.decision == "warn"
    assert "90%" in result.reason


@pytest.mark.asyncio
async def test_token_budget_block_over_limit() -> None:
    g = TokenBudgetGuard(max_total_tokens=1000)
    result = await g.check_in({"total_tokens": 1000})
    assert result.decision == "block"


# ---------------------------------------------------------------------------
# node factories
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_guard_in_node_block_sets_error() -> None:
    guard = TokenBudgetGuard(max_total_tokens=10)
    node = make_guard_in_node(guard)
    out = await node({"total_tokens": 100}, {"configurable": {}})
    assert "error" in out
    assert "token_budget" in out["error"]


@pytest.mark.asyncio
async def test_guard_in_node_warn_appends_warnings() -> None:
    guard = TokenBudgetGuard(max_total_tokens=1000)
    node = make_guard_in_node(guard)
    out = await node({"total_tokens": 950, "warnings": ["prior"]}, {"configurable": {}})
    # Existing warning preserved; new warning appended.
    assert isinstance(out.get("warnings"), list)
    assert out["warnings"][0] == "prior"
    assert len(out["warnings"]) == 2
    assert "90%" in out["warnings"][1]


@pytest.mark.asyncio
async def test_guard_in_node_allow_no_patch() -> None:
    guard = TokenBudgetGuard(max_total_tokens=1000)
    node = make_guard_in_node(guard)
    out = await node({"total_tokens": 10}, {"configurable": {}})
    assert out == {}


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------


def test_registry_has_one_builtin() -> None:
    assert set(GUARD_REGISTRY) == {"token_budget"}


def test_resolve_guards_from_specs() -> None:
    guards = resolve_guards([{"name": "token_budget", "config": {"max_total_tokens": 5}}])
    assert [g.name for g in guards] == ["token_budget"]


def test_resolve_guards_empty_returns_empty() -> None:
    assert resolve_guards(None) == []
    assert resolve_guards([]) == []


def test_resolve_guards_unknown_name_raises() -> None:
    with pytest.raises(ValueError, match="Unknown guard"):
        resolve_guards([{"name": "nope"}])


# ---------------------------------------------------------------------------
# builder topology
# ---------------------------------------------------------------------------


def test_builder_no_guards_is_react_end() -> None:
    from agent_flow_harness.graph import build_agent_graph

    graph = build_agent_graph({"_id": "a"}, tools=[], middleware=[])
    user_nodes = set(graph.nodes) - {"__start__", "__end__"}
    assert user_nodes == {"compress", "llm", "tools"}


def test_builder_explicit_guards_adds_nodes() -> None:
    from agent_flow_harness.graph import build_agent_graph

    graph = build_agent_graph(
        {"_id": "a"},
        guards=[TokenBudgetGuard(max_total_tokens=100)],
        tools=[], middleware=[],
    )
    user_nodes = set(graph.nodes) - {"__start__", "__end__"}
    assert user_nodes == {
        "compress", "llm", "tools",
        "guard_in_token_budget",
    }


def test_builder_resolves_guards_from_agent_doc() -> None:
    from agent_flow_harness.graph import build_agent_graph

    graph = build_agent_graph(
        {"_id": "a", "guards": [{"name": "token_budget", "config": {"max_total_tokens": 10}}]},
        tools=[], middleware=[],
    )
    user_nodes = set(graph.nodes) - {"__start__", "__end__"}
    assert "guard_in_token_budget" in user_nodes


def test_builder_explicit_guards_override_agent_doc() -> None:
    from agent_flow_harness.graph import build_agent_graph

    # agent_doc lists token_budget but explicit guards=[] wins → plain graph.
    graph = build_agent_graph(
        {"_id": "a", "guards": [{"name": "token_budget", "config": {"max_total_tokens": 10}}]},
        guards=[],
        tools=[], middleware=[],
    )
    user_nodes = set(graph.nodes) - {"__start__", "__end__"}
    assert user_nodes == {"compress", "llm", "tools"}


# ---------------------------------------------------------------------------
# integration: full guard stack short-circuits on block
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_guard_in_node_short_circuits_react(base_state) -> None:
    """A blocking guard_in prevents the react node from running.

    We exercise the node directly: a token-budget over-limit returns an error
    patch that the graph would route to termination.
    """
    guard = TokenBudgetGuard(max_total_tokens=10)
    node = make_guard_in_node(guard)
    out = await node({"total_tokens": 100}, {"configurable": {}})
    assert out["error"]

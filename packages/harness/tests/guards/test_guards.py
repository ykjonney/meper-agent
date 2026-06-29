"""AC1-AC12 cover: Guard protocol, the 4 built-in guards, nodes, registry, builder."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from agent_flow_harness.guards import (
    ContentGuard,
    GUARD_REGISTRY,
    Guard,
    TimeBudgetGuard,
    TokenBudgetGuard,
    ToolRateLimitGuard,
    make_guard_in_node,
    make_guard_out_node,
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
    for g in (
        TokenBudgetGuard(max_total_tokens=10),
        TimeBudgetGuard(max_wall_seconds=10),
        ToolRateLimitGuard(),
        ContentGuard(),
    ):
        assert isinstance(g, Guard)


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


@pytest.mark.asyncio
async def test_token_budget_check_out_blocks_overflow() -> None:
    g = TokenBudgetGuard(max_total_tokens=1000)
    result = await g.check_out({"total_tokens": 990}, {"step_tokens": 50})
    assert result.decision == "block"


# ---------------------------------------------------------------------------
# TimeBudgetGuard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_time_budget_allow() -> None:
    g = TimeBudgetGuard(max_wall_seconds=60)
    started = time.time() - 1
    assert (await g.check_in({"started_at": started})).decision == "allow"


@pytest.mark.asyncio
async def test_time_budget_warn_near_limit() -> None:
    g = TimeBudgetGuard(max_wall_seconds=60)
    started = time.time() - 55  # ~92%
    result = await g.check_in({"started_at": started})
    assert result.decision == "warn"


@pytest.mark.asyncio
async def test_time_budget_block_over_limit() -> None:
    g = TimeBudgetGuard(max_wall_seconds=1)
    started = time.time() - 5
    result = await g.check_in({"started_at": started})
    assert result.decision == "block"


@pytest.mark.asyncio
async def test_time_budget_defaults_started_at_to_now() -> None:
    """Missing started_at is treated as 'just started' → allow."""
    g = TimeBudgetGuard(max_wall_seconds=60)
    assert (await g.check_in({})).decision == "allow"


# ---------------------------------------------------------------------------
# ToolRateLimitGuard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tool_rate_limit_allow_under_limit() -> None:
    g = ToolRateLimitGuard(max_calls_per_tool=30)
    assert (await g.check_in({"tool_call_count": {"bash": 5}})).decision == "allow"


@pytest.mark.asyncio
async def test_tool_rate_limit_block_over_calls() -> None:
    g = ToolRateLimitGuard(max_calls_per_tool=3)
    result = await g.check_in({"tool_call_count": {"bash": 3}})
    assert result.decision == "block"
    assert "bash" in result.reason


@pytest.mark.asyncio
async def test_tool_rate_limit_block_repeated_args() -> None:
    g = ToolRateLimitGuard(max_repeat_args=3)
    same = {"name": "read", "args": {"path": "x"}}
    result = await g.check_out({}, {"tool_calls_this_step": [same, same, same]})
    assert result.decision == "block"
    assert "same args" in result.reason


@pytest.mark.asyncio
async def test_tool_rate_limit_allows_distinct_args() -> None:
    g = ToolRateLimitGuard(max_repeat_args=3)
    calls = [
        {"name": "read", "args": {"path": "a"}},
        {"name": "read", "args": {"path": "b"}},
    ]
    assert (await g.check_out({}, {"tool_calls_this_step": calls})).decision == "allow"


# ---------------------------------------------------------------------------
# ContentGuard
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_content_allow_clean_message() -> None:
    g = ContentGuard(deny_patterns=["rm -rf"])
    msg = SimpleNamespace(content="hello world")
    assert (await g.check_in({"messages": [msg]})).decision == "allow"


@pytest.mark.asyncio
async def test_content_block_deny_pattern_in_message() -> None:
    g = ContentGuard(deny_patterns=["rm -rf"])
    msg = SimpleNamespace(content="run rm -rf /")
    result = await g.check_in({"messages": [msg]})
    assert result.decision == "block"


@pytest.mark.asyncio
async def test_content_block_deny_pattern_in_tool_args() -> None:
    g = ContentGuard(deny_patterns=["forbidden"])
    result = await g.check_out(
        {}, {"tool_calls_this_step": [{"name": "bash", "args": {"cmd": "forbidden"}}]}
    )
    assert result.decision == "block"


@pytest.mark.asyncio
async def test_content_handles_list_content_blocks() -> None:
    g = ContentGuard(deny_patterns=["secret"])
    msg = SimpleNamespace(content=[{"type": "text", "text": "a secret value"}])
    result = await g.check_in({"messages": [msg]})
    assert result.decision == "block"


@pytest.mark.asyncio
async def test_content_empty_messages_allow() -> None:
    g = ContentGuard(deny_patterns=["x"])
    assert (await g.check_in({"messages": []})).decision == "allow"


# ---------------------------------------------------------------------------
# node factories
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_guard_in_node_block_sets_error() -> None:
    guard = TokenBudgetGuard(max_total_tokens=10)
    node = make_guard_in_node(guard)
    out = await node({"total_tokens": 100})
    assert "error" in out
    assert "token_budget" in out["error"]


@pytest.mark.asyncio
async def test_guard_in_node_warn_appends_warnings() -> None:
    guard = TokenBudgetGuard(max_total_tokens=1000)
    node = make_guard_in_node(guard)
    out = await node({"total_tokens": 950, "warnings": ["prior"]})
    # Existing warning preserved; new warning appended.
    assert isinstance(out.get("warnings"), list)
    assert out["warnings"][0] == "prior"
    assert len(out["warnings"]) == 2
    assert "90%" in out["warnings"][1]


@pytest.mark.asyncio
async def test_guard_in_node_allow_no_patch() -> None:
    guard = TokenBudgetGuard(max_total_tokens=1000)
    node = make_guard_in_node(guard)
    out = await node({"total_tokens": 10})
    assert out == {}


@pytest.mark.asyncio
async def test_guard_out_node_block_sets_error() -> None:
    guard = ToolRateLimitGuard(max_repeat_args=2)
    node = make_guard_out_node(guard)
    same = {"name": "read", "args": {"path": "x"}}
    out = await node({"tool_calls_this_step": [same, same]})
    assert "error" in out


# ---------------------------------------------------------------------------
# registry
# ---------------------------------------------------------------------------


def test_registry_has_four_builtins() -> None:
    assert set(GUARD_REGISTRY) == {
        "token_budget",
        "time_budget",
        "tool_rate_limit",
        "content",
    }


def test_resolve_guards_from_specs() -> None:
    guards = resolve_guards(
        [
            {"name": "token_budget", "config": {"max_total_tokens": 5}},
            {"name": "content", "config": {"deny_patterns": ["x"]}},
        ]
    )
    assert [g.name for g in guards] == ["token_budget", "content"]


def test_resolve_guards_defaults_when_no_config() -> None:
    # tool_rate_limit has defaults for both kwargs.
    guards = resolve_guards([{"name": "tool_rate_limit"}])
    assert guards[0].name == "tool_rate_limit"


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

    graph = build_agent_graph({"_id": "a"})
    user_nodes = set(graph.nodes) - {"__start__", "__end__"}
    assert user_nodes == {"react"}


def test_builder_explicit_guards_adds_nodes() -> None:
    from agent_flow_harness.graph import build_agent_graph

    graph = build_agent_graph(
        {"_id": "a"},
        guards=[TimeBudgetGuard(max_wall_seconds=30), ContentGuard()],
    )
    user_nodes = set(graph.nodes) - {"__start__", "__end__"}
    assert user_nodes == {
        "react",
        "guard_in_time_budget",
        "guard_out_time_budget",
        "guard_in_content",
        "guard_out_content",
    }


def test_builder_resolves_guards_from_agent_doc() -> None:
    from agent_flow_harness.graph import build_agent_graph

    graph = build_agent_graph(
        {"_id": "a", "guards": [{"name": "token_budget", "config": {"max_total_tokens": 10}}]}
    )
    user_nodes = set(graph.nodes) - {"__start__", "__end__"}
    assert "guard_in_token_budget" in user_nodes


def test_builder_explicit_guards_override_agent_doc() -> None:
    from agent_flow_harness.graph import build_agent_graph

    # agent_doc lists token_budget but explicit guards=[] wins → plain graph.
    graph = build_agent_graph(
        {"_id": "a", "guards": [{"name": "token_budget", "config": {"max_total_tokens": 10}}]},
        guards=[],
    )
    user_nodes = set(graph.nodes) - {"__start__", "__end__"}
    assert user_nodes == {"react"}


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
    out = await node({"total_tokens": 100})
    assert out["error"]

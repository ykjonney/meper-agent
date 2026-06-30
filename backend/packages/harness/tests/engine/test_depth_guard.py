"""AC11 cover: migrated depth guard behaves correctly inside the harness."""

from __future__ import annotations

from agent_flow_harness.engine.depth_guard import (
    MAX_DEPTH,
    DepthCheckResult,
    check_depth,
    detect_cycle,
    format_call_chain,
)


def _state(**over):
    base = {
        "call_chain": [],
        "current_depth": 0,
        "agent_id": "a",
    }
    base.update(over)
    return base


def test_check_depth_allows_shallow_chain() -> None:
    result = check_depth(_state(current_depth=0, call_chain=["a"]))
    assert isinstance(result, DepthCheckResult)
    assert result.allowed is True
    assert result.reason is None


def test_check_depth_blocks_when_depth_exceeds_max() -> None:
    result = check_depth(_state(current_depth=MAX_DEPTH + 5))
    assert result.allowed is False
    assert result.reason is not None
    assert "Depth limit" in result.reason
    assert result.cycle is None


def test_check_depth_blocks_circular_call() -> None:
    """A repeated id in the call chain is a cycle and is blocked first."""
    result = check_depth(_state(current_depth=0, call_chain=["a", "b", "a"]))
    assert result.allowed is False
    assert result.cycle is not None
    assert "Circular" in (result.reason or "")


def test_detect_cycle_finds_repeat() -> None:
    assert detect_cycle(["x", "y", "x"]) is not None
    assert detect_cycle(["a", "b", "c"]) is None


def test_format_call_chain_renders_readably() -> None:
    rendered = format_call_chain(["a", "b", "c"])
    assert "a" in rendered and "c" in rendered

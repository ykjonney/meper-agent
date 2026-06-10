"""Tests for the depth_guard module — depth limits and cycle detection.

Covers:
- check_depth: allowed / depth exceeded / cycle detected
- detect_cycle: various chain patterns
- format_call_chain: human-readable output
- Custom MAX_DEPTH via AGENT_MAX_DEPTH env var
- Empty / missing call_chain defaults
"""
from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from app.engine.agent.depth_guard import (
    MAX_DEPTH,
    DepthCheckResult,
    check_depth,
    detect_cycle,
    format_call_chain,
)


# ---------------------------------------------------------------------------
# detect_cycle
# ---------------------------------------------------------------------------


class TestDetectCycle:
    """Tests for the detect_cycle helper."""

    def test_empty_chain_returns_none(self) -> None:
        assert detect_cycle([]) is None

    def test_single_element_returns_none(self) -> None:
        assert detect_cycle(["agent_a"]) is None

    def test_no_cycle_returns_none(self) -> None:
        chain = ["agent_a", "task_x", "agent_b"]
        assert detect_cycle(chain) is None

    def test_simple_cycle(self) -> None:
        chain = ["agent_a", "agent_b", "agent_a"]
        result = detect_cycle(chain)
        assert result is not None
        assert result == ["agent_a", "agent_b", "agent_a"]

    def test_cycle_at_end(self) -> None:
        chain = ["a", "b", "c", "a"]
        result = detect_cycle(chain)
        assert result is not None
        assert result == ["a", "b", "c", "a"]

    def test_cycle_in_middle(self) -> None:
        chain = ["x", "a", "b", "a", "y"]
        result = detect_cycle(chain)
        assert result is not None
        assert result == ["a", "b", "a"]

    def test_long_chain_no_cycle(self) -> None:
        chain = [f"entity_{i}" for i in range(100)]
        assert detect_cycle(chain) is None

    def test_two_element_cycle(self) -> None:
        chain = ["agent_a", "agent_a"]
        result = detect_cycle(chain)
        assert result == ["agent_a", "agent_a"]


# ---------------------------------------------------------------------------
# format_call_chain
# ---------------------------------------------------------------------------


class TestFormatCallChain:
    """Tests for the format_call_chain helper."""

    def test_empty_chain(self) -> None:
        assert format_call_chain([]) == "(empty)"

    def test_single_element(self) -> None:
        assert format_call_chain(["agent_a"]) == "agent_a"

    def test_multiple_elements(self) -> None:
        result = format_call_chain(["a", "b", "c"])
        assert result == "a → b → c"

    def test_cycle_display(self) -> None:
        result = format_call_chain(["agent_a", "task_x", "agent_a"])
        assert result == "agent_a → task_x → agent_a"


# ---------------------------------------------------------------------------
# check_depth
# ---------------------------------------------------------------------------


class TestCheckDepth:
    """Tests for the check_depth function."""

    def _make_state(
        self,
        call_chain: list[str] | None = None,
        current_depth: int = 0,
        agent_id: str = "test_agent",
    ) -> dict:
        """Build a minimal AgentState-like dict for testing."""
        return {
            "messages": [],
            "agent_id": agent_id,
            "execution_path": "react",
            "request_id": "req-test",
            "tool_results": {},
            "step_count": 0,
            "error": None,
            "call_chain": call_chain if call_chain is not None else [agent_id],
            "current_depth": current_depth,
        }

    def test_depth_zero_allowed(self) -> None:
        state = self._make_state(call_chain=["agent_a"], current_depth=0)
        result = check_depth(state)
        assert result.allowed is True
        assert result.current_depth == 0
        assert result.reason is None
        assert result.cycle is None

    def test_depth_below_max_allowed(self) -> None:
        state = self._make_state(call_chain=["agent_a"], current_depth=MAX_DEPTH - 1)
        result = check_depth(state)
        assert result.allowed is True
        assert result.current_depth == MAX_DEPTH - 1

    def test_depth_at_max_rejected(self) -> None:
        state = self._make_state(call_chain=["agent_a"], current_depth=MAX_DEPTH)
        result = check_depth(state)
        assert result.allowed is False
        assert result.current_depth == MAX_DEPTH
        assert result.reason is not None
        assert "Depth limit exceeded" in result.reason
        assert str(MAX_DEPTH) in result.reason

    def test_depth_above_max_rejected(self) -> None:
        state = self._make_state(call_chain=["agent_a"], current_depth=MAX_DEPTH + 5)
        result = check_depth(state)
        assert result.allowed is False
        assert "Depth limit exceeded" in result.reason

    def test_cycle_detected_even_at_depth_zero(self) -> None:
        state = self._make_state(
            call_chain=["agent_a", "task_x", "agent_a"],
            current_depth=0,
        )
        result = check_depth(state)
        assert result.allowed is False
        assert result.cycle is not None
        assert "Circular call detected" in result.reason

    def test_cycle_priority_over_depth(self) -> None:
        """Cycle detection takes priority even when depth is fine."""
        state = self._make_state(
            call_chain=["agent_a", "agent_a"],
            current_depth=0,
        )
        result = check_depth(state)
        assert result.allowed is False
        assert result.cycle is not None
        assert "Circular call detected" in result.reason

    def test_error_reason_contains_call_chain(self) -> None:
        state = self._make_state(
            call_chain=["agent_a", "task_x"],
            current_depth=MAX_DEPTH,
        )
        result = check_depth(state)
        assert result.allowed is False
        assert "agent_a → task_x" in result.reason

    def test_empty_call_chain_allowed(self) -> None:
        state = self._make_state(call_chain=[], current_depth=0)
        result = check_depth(state)
        assert result.allowed is True

    def test_none_call_chain_treated_as_empty(self) -> None:
        state = self._make_state(call_chain=None, current_depth=0)
        result = check_depth(state)
        assert result.allowed is True


# ---------------------------------------------------------------------------
# Custom MAX_DEPTH via environment variable
# ---------------------------------------------------------------------------


class TestCustomMaxDepth:
    """Tests for AGENT_MAX_DEPTH environment variable override."""

    def test_custom_max_depth_5(self) -> None:
        with patch.dict(os.environ, {"AGENT_MAX_DEPTH": "5"}):
            # Re-import to pick up the new env var
            from app.engine.agent.depth_guard import _resolve_max_depth

            assert _resolve_max_depth() == 5

    def test_custom_max_depth_10(self) -> None:
        with patch.dict(os.environ, {"AGENT_MAX_DEPTH": "10"}):
            from app.engine.agent.depth_guard import _resolve_max_depth

            assert _resolve_max_depth() == 10

    def test_invalid_env_falls_back_to_default(self) -> None:
        with patch.dict(os.environ, {"AGENT_MAX_DEPTH": "not_a_number"}):
            from app.engine.agent.depth_guard import _resolve_max_depth

            assert _resolve_max_depth() == 3

    def test_negative_env_falls_back_to_default(self) -> None:
        with patch.dict(os.environ, {"AGENT_MAX_DEPTH": "-1"}):
            from app.engine.agent.depth_guard import _resolve_max_depth

            assert _resolve_max_depth() == 3

    def test_zero_env_falls_back_to_default(self) -> None:
        with patch.dict(os.environ, {"AGENT_MAX_DEPTH": "0"}):
            from app.engine.agent.depth_guard import _resolve_max_depth

            assert _resolve_max_depth() == 3


# ---------------------------------------------------------------------------
# DepthCheckResult dataclass
# ---------------------------------------------------------------------------


class TestDepthCheckResult:
    """Tests for the DepthCheckResult dataclass."""

    def test_allowed_result(self) -> None:
        result = DepthCheckResult(allowed=True, current_depth=0, max_depth=3)
        assert result.allowed is True
        assert result.reason is None
        assert result.cycle is None

    def test_rejected_result(self) -> None:
        result = DepthCheckResult(
            allowed=False,
            current_depth=3,
            max_depth=3,
            reason="Depth limit exceeded",
        )
        assert result.allowed is False
        assert result.reason == "Depth limit exceeded"

    def test_cycle_result(self) -> None:
        result = DepthCheckResult(
            allowed=False,
            current_depth=1,
            max_depth=3,
            reason="Circular call detected",
            cycle=["a", "b", "a"],
        )
        assert result.cycle == ["a", "b", "a"]

    def test_frozen(self) -> None:
        result = DepthCheckResult(allowed=True, current_depth=0, max_depth=3)
        with pytest.raises(AttributeError):
            result.allowed = False  # type: ignore[misc]

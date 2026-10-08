"""Tests for parallel node branch exception propagation.

Regression lock for the M0 fix: ``gather(return_exceptions=True)`` /
``asyncio.wait`` silently swallow exceptions raised inside parallel branch
coroutines. Covers:

- Unit: ``_propagate_branch_exceptions`` — collects branch task exceptions,
  cancels pending branches before raising, priority Cancelled > Paused > failure
- all: branch node failure propagates (WorkflowNodeError)
- all: human pause inside a branch propagates (WorkflowPausedError) —
  previously the pause was swallowed, Task ended up WAITING_HUMAN then
  overwritten COMPLETED
- all: successful branches unaffected (regression)
- any: first-completed branch failure propagates, slow branch cancelled
- n-of-m: failing branch propagates immediately (not counted toward join_count)
"""
from __future__ import annotations

import asyncio
import contextlib
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.engine.workflow.engine import (
    WorkflowCancelledError,
    WorkflowEngine,
    WorkflowNodeError,
    WorkflowPausedError,
)
from app.engine.workflow.node_executor import NodeResult
from app.engine.workflow.variable_pool import VariablePool

# ── Test fixtures / helpers ──


def _make_engine(nodes: list[dict[str, Any]]) -> WorkflowEngine:
    """Build an engine with node map + variable pool, no DB touches."""
    engine = WorkflowEngine()
    engine._task_id = "task_parallel_test"
    engine._nodes = nodes
    engine._node_map = {n["node_id"]: n for n in nodes}
    engine._pool = VariablePool()
    return engine


def _executor_returning(result: NodeResult) -> MagicMock:
    ex = MagicMock()
    ex.execute = AsyncMock(return_value=result)
    return ex


def _parallel_result(
    branches: list[dict[str, Any]], strategy: str, join_count: Any = None,
) -> NodeResult:
    """Mirror ParallelNodeExecutor output structure (node_executor.py)."""
    return NodeResult(
        success=True,
        output={
            "branches": [b.get("id", f"branch_{i}") for i, b in enumerate(branches)],
            "start_nodes": {
                b.get("id", f"branch_{i}"): b.get("start_node", "")
                for i, b in enumerate(branches)
            },
            "join_strategy": strategy,
            "join_count": join_count,
            "scope": "shared",
        },
    )


async def _spawn_and_wait(exc: BaseException) -> asyncio.Task:
    """Create a completed task that raised ``exc``."""

    async def _raise() -> None:
        raise exc

    t = asyncio.ensure_future(_raise())
    await asyncio.sleep(0)
    return t


async def _spawn_ok() -> asyncio.Task:
    """Create a successfully completed task."""

    async def _ok() -> None:
        return None

    t = asyncio.ensure_future(_ok())
    await asyncio.sleep(0)
    return t


def _db_mock() -> MagicMock:
    """Mongo mock: task status running (not cancelled), writes are no-ops."""
    mock_db = MagicMock()
    mock_col = MagicMock()
    mock_col.find_one = AsyncMock(return_value={"status": "running"})
    mock_col.update_one = AsyncMock()
    mock_db.return_value.__getitem__.return_value = mock_col
    return mock_db


def _task_service_mock() -> MagicMock:
    ts = MagicMock()
    ts.append_timeline_event = AsyncMock()
    ts.add_total_tokens = AsyncMock()
    ts.transition_task = AsyncMock()
    return ts


# ── Unit: _propagate_branch_exceptions ──


class TestPropagateBranchExceptions:
    """_propagate_branch_exceptions raises swallowed branch exceptions."""

    @pytest.mark.asyncio
    async def test_no_exceptions_no_raise(self) -> None:
        engine = WorkflowEngine()
        done = {await _spawn_ok() for _ in range(3)}
        await engine._propagate_branch_exceptions(done)  # should not raise

    @pytest.mark.asyncio
    async def test_branch_failure_raises(self) -> None:
        engine = WorkflowEngine()
        err = WorkflowNodeError("a2", "agent", "boom")
        done = {await _spawn_ok(), await _spawn_and_wait(err)}
        with pytest.raises(WorkflowNodeError):
            await engine._propagate_branch_exceptions(done)

    @pytest.mark.asyncio
    async def test_priority_cancelled_beats_pause_and_failure(self) -> None:
        engine = WorkflowEngine()
        done = {
            await _spawn_and_wait(WorkflowNodeError("a1", "agent", "fail")),
            await _spawn_and_wait(WorkflowPausedError("h1", "human", "wait")),
            await _spawn_and_wait(WorkflowCancelledError()),
        }
        with pytest.raises(WorkflowCancelledError):
            await engine._propagate_branch_exceptions(done)

    @pytest.mark.asyncio
    async def test_priority_pause_beats_failure(self) -> None:
        """Pause wins over failure: human branch already moved Task to
        WAITING_HUMAN — raising failure first would overwrite it FAILED."""
        engine = WorkflowEngine()
        done = {
            await _spawn_and_wait(WorkflowNodeError("a1", "agent", "fail")),
            await _spawn_and_wait(WorkflowPausedError("h1", "human", "wait")),
        }
        with pytest.raises(WorkflowPausedError):
            await engine._propagate_branch_exceptions(done)

    @pytest.mark.asyncio
    async def test_cancelled_tasks_skipped(self) -> None:
        """Branches cancelled by join semantics (any/n-of-m) are not errors."""

        async def _hang() -> None:
            await asyncio.sleep(30)

        engine = WorkflowEngine()
        t = asyncio.ensure_future(_hang())
        await asyncio.sleep(0)
        t.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await t
        done = {t, await _spawn_ok()}
        await engine._propagate_branch_exceptions(done)  # should not raise

    @pytest.mark.asyncio
    async def test_pending_cancelled_before_raise(self) -> None:
        """Pending branches are cancelled when an exception propagates, so no
        orphan coroutine keeps writing to DB / variable pool."""
        engine = WorkflowEngine()

        async def _hang() -> None:
            await asyncio.sleep(30)

        pending_t = asyncio.ensure_future(_hang())
        done = {await _spawn_and_wait(WorkflowNodeError("a1", "agent", "boom"))}
        with pytest.raises(WorkflowNodeError):
            await engine._propagate_branch_exceptions(done, {pending_t})
        # Give the loop a tick to deliver the cancellation, then assert.
        assert pending_t.cancelled() or pending_t.cancel()


# ── Integration: parallel execution via _execute_node ──


class TestParallelExecution:
    """Parallel fan-out propagates branch exceptions (all/any/n-of-m)."""

    @pytest.mark.asyncio
    async def test_all_strategy_branch_failure_propagates(self) -> None:
        """all: a failing branch fails the workflow instead of being
        silently swallowed into a bogus success."""
        engine = _make_engine([
            {"node_id": "p1", "type": "parallel", "config": {}},
            {"node_id": "a1", "type": "agent", "config": {}},
            {"node_id": "a2", "type": "agent", "config": {}},
        ])
        branches = [
            {"id": "b1", "start_node": "a1"},
            {"id": "b2", "start_node": "a2"},
        ]

        def _get_executor(node_type: str, node_id: str, cfg: dict) -> MagicMock:
            if node_id == "p1":
                return _executor_returning(_parallel_result(branches, "all"))
            if node_id == "a2":
                return _executor_returning(
                    NodeResult(success=False, error_message="boom")
                )
            return _executor_returning(
                NodeResult(success=True, output={"response": "ok"})
            )

        with patch(
            "app.engine.workflow.engine.get_node_executor",
            side_effect=_get_executor,
        ), patch(
            "app.engine.workflow.engine.TaskService", new=_task_service_mock(),
        ), patch(
            "app.db.mongodb.get_database", new=_db_mock(),
        ), pytest.raises(WorkflowNodeError):
            await engine._execute_node("p1")

        # all waits for every branch: the successful sibling still wrote output
        assert engine._pool.get("a1.response") == "ok"

    @pytest.mark.asyncio
    async def test_all_strategy_success_regression(self) -> None:
        """all: both branches succeed → parallel result returned, no raise."""
        engine = _make_engine([
            {"node_id": "p1", "type": "parallel", "config": {}},
            {"node_id": "a1", "type": "agent", "config": {}},
            {"node_id": "a2", "type": "agent", "config": {}},
        ])
        branches = [
            {"id": "b1", "start_node": "a1"},
            {"id": "b2", "start_node": "a2"},
        ]

        def _get_executor(node_type: str, node_id: str, cfg: dict) -> MagicMock:
            if node_id == "p1":
                return _executor_returning(_parallel_result(branches, "all"))
            return _executor_returning(
                NodeResult(success=True, output={"response": f"ok-{node_id}"})
            )

        with patch(
            "app.engine.workflow.engine.get_node_executor",
            side_effect=_get_executor,
        ), patch(
            "app.engine.workflow.engine.TaskService", new=_task_service_mock(),
        ), patch(
            "app.db.mongodb.get_database", new=_db_mock(),
        ):
            result = await engine._execute_node("p1")

        assert result is not None and result.success
        assert engine._pool.get("a1.response") == "ok-a1"
        assert engine._pool.get("a2.response") == "ok-a2"

    @pytest.mark.asyncio
    async def test_human_pause_in_branch_propagates(self) -> None:
        """all: a human node inside a branch pauses the whole workflow —
        the WorkflowPausedError must reach the outer handler (which keeps
        WAITING_HUMAN status), not be swallowed by the join."""
        engine = _make_engine([
            {"node_id": "p1", "type": "parallel", "config": {}},
            {"node_id": "h1", "type": "human", "config": {}},
            {"node_id": "a2", "type": "agent", "config": {}},
        ])
        branches = [
            {"id": "b1", "start_node": "h1"},
            {"id": "b2", "start_node": "a2"},
        ]

        def _get_executor(node_type: str, node_id: str, cfg: dict) -> MagicMock:
            if node_id == "p1":
                return _executor_returning(_parallel_result(branches, "all"))
            if node_id == "h1":
                return _executor_returning(NodeResult(
                    success=True,
                    output={
                        "status": "waiting_human",
                        "title": "review",
                        "description": "please approve",
                        "options": [],
                        "timeout_ms": 0,
                        "timeout_action": "fail",
                    },
                ))
            return _executor_returning(
                NodeResult(success=True, output={"response": "ok"})
            )

        with patch(
            "app.engine.workflow.engine.get_node_executor",
            side_effect=_get_executor,
        ), patch(
            "app.engine.workflow.engine.TaskService", new=_task_service_mock(),
        ), patch(
            "app.db.mongodb.get_database", new=_db_mock(),
        ), pytest.raises(WorkflowPausedError):
            await engine._execute_node("p1")

    @pytest.mark.asyncio
    async def test_any_strategy_failure_propagates_and_cancels_slow(self) -> None:
        """any: a branch that completes by failing propagates the failure;
        the slow sibling is cancelled and writes nothing."""
        engine = _make_engine([
            {"node_id": "p1", "type": "parallel", "config": {}},
            {"node_id": "a1", "type": "agent", "config": {}},
            {"node_id": "a2", "type": "agent", "config": {}},
        ])
        branches = [
            {"id": "b1", "start_node": "a1"},
            {"id": "b2", "start_node": "a2"},
        ]

        slow_executor = MagicMock()

        async def _slow_execute(variables: dict) -> NodeResult:
            await asyncio.sleep(1.0)
            return NodeResult(success=True, output={"response": "late"})

        slow_executor.execute = _slow_execute

        def _get_executor(node_type: str, node_id: str, cfg: dict) -> MagicMock:
            if node_id == "p1":
                return _executor_returning(_parallel_result(branches, "any"))
            if node_id == "a2":
                return slow_executor
            return _executor_returning(
                NodeResult(success=False, error_message="fast fail")
            )

        with patch(
            "app.engine.workflow.engine.get_node_executor",
            side_effect=_get_executor,
        ), patch(
            "app.engine.workflow.engine.TaskService", new=_task_service_mock(),
        ), patch(
            "app.db.mongodb.get_database", new=_db_mock(),
        ), pytest.raises(WorkflowNodeError):
            await engine._execute_node("p1")

        # The slow branch was cancelled before writing its output
        assert engine._pool.get("a2") is None

    @pytest.mark.asyncio
    async def test_n_of_m_failure_propagates_immediately(self) -> None:
        """n-of-m: an exception-completed branch propagates immediately and
        is NOT counted toward join_count."""
        engine = _make_engine([
            {"node_id": "p1", "type": "parallel", "config": {}},
            {"node_id": "a1", "type": "agent", "config": {}},
            {"node_id": "a2", "type": "agent", "config": {}},
            {"node_id": "a3", "type": "agent", "config": {}},
        ])
        branches = [
            {"id": "b1", "start_node": "a1"},
            {"id": "b2", "start_node": "a2"},
            {"id": "b3", "start_node": "a3"},
        ]

        hanging_executor = MagicMock()

        async def _hang_execute(variables: dict) -> NodeResult:
            await asyncio.sleep(30)
            return NodeResult(success=True)

        hanging_executor.execute = _hang_execute

        def _get_executor(node_type: str, node_id: str, cfg: dict) -> MagicMock:
            if node_id == "p1":
                return _executor_returning(
                    _parallel_result(branches, "n-of-m", join_count=2),
                )
            if node_id == "a1":
                return _executor_returning(
                    NodeResult(success=False, error_message="boom")
                )
            return hanging_executor

        with patch(
            "app.engine.workflow.engine.get_node_executor",
            side_effect=_get_executor,
        ), patch(
            "app.engine.workflow.engine.TaskService", new=_task_service_mock(),
        ), patch(
            "app.db.mongodb.get_database", new=_db_mock(),
        ), pytest.raises(WorkflowNodeError):
            await engine._execute_node("p1")

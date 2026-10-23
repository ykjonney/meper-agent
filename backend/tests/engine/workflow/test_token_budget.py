"""Tests for workflow-level token budget (节点边界检查，M3 前置).

Covers:
- 预算耗尽（spent >= budget）→ WorkflowTokenBudgetExceededError
- budget=0（默认）不限制
- 未达预算不抛
- 取消优先于预算（同一次边界检查）
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.engine.workflow.engine import (
    WorkflowCancelledError,
    WorkflowEngine,
    WorkflowTokenBudgetExceededError,
)


def _db_with_task(status: str, total_tokens: int, token_budget: int) -> MagicMock:
    mock_db = MagicMock()
    mock_col = MagicMock()
    mock_col.find_one = AsyncMock(return_value={
        "status": status,
        "total_tokens": total_tokens,
        "token_budget": token_budget,
    })
    mock_db.return_value.__getitem__.return_value = mock_col
    return mock_db


def _engine() -> WorkflowEngine:
    engine = WorkflowEngine()
    engine._task_id = "task_budget"
    return engine


class TestTokenBudgetBoundary:
    """_check_cancelled 顺带的工作流级预算检查。"""

    @pytest.mark.asyncio
    async def test_exceeded_raises(self) -> None:
        engine = _engine()
        with patch(
            "app.db.mongodb.get_database",
            new=_db_with_task("running", total_tokens=1500, token_budget=1500),
        ), pytest.raises(WorkflowTokenBudgetExceededError) as ei:
            await engine._check_cancelled("node_x")
        assert ei.value.total_tokens == 1500
        assert ei.value.token_budget == 1500
        assert ei.value.node_id == "node_x"

    @pytest.mark.asyncio
    async def test_over_spent_raises(self) -> None:
        engine = _engine()
        with patch(
            "app.db.mongodb.get_database",
            new=_db_with_task("running", total_tokens=2000, token_budget=1500),
        ), pytest.raises(WorkflowTokenBudgetExceededError):
            await engine._check_cancelled("node_x")

    @pytest.mark.asyncio
    async def test_zero_budget_unlimited(self) -> None:
        """budget=0（默认）不限制——现有任务行为不变。"""
        engine = _engine()
        with patch(
            "app.db.mongodb.get_database",
            new=_db_with_task("running", total_tokens=999_999_999, token_budget=0),
        ):
            await engine._check_cancelled("node_x")  # should not raise

    @pytest.mark.asyncio
    async def test_under_budget_no_raise(self) -> None:
        engine = _engine()
        with patch(
            "app.db.mongodb.get_database",
            new=_db_with_task("running", total_tokens=1499, token_budget=1500),
        ):
            await engine._check_cancelled("node_x")

    @pytest.mark.asyncio
    async def test_cancel_takes_priority(self) -> None:
        """同一边界：取消优先于预算（status 检查在前）。"""
        engine = _engine()
        with patch(
            "app.db.mongodb.get_database",
            new=_db_with_task("cancelled", total_tokens=9999, token_budget=100),
        ), pytest.raises(WorkflowCancelledError):
            await engine._check_cancelled("node_x")

    @pytest.mark.asyncio
    async def test_missing_task_doc_no_raise(self) -> None:
        engine = _engine()
        mock_db = MagicMock()
        mock_col = MagicMock()
        mock_col.find_one = AsyncMock(return_value=None)
        mock_db.return_value.__getitem__.return_value = mock_col
        with patch("app.db.mongodb.get_database", new=mock_db):
            await engine._check_cancelled("node_x")

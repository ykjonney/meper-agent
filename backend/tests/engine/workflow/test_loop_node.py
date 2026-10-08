"""Tests for loop node (M3) — validator codes + engine round semantics.

Covers (ADR docs/loop-node-adr.md):
- Validator: body/entry/range/nested/structural/closed/cycle/converge-ref/
  forward-ref, 体引用循环前上游不误报
- Engine: 收敛退出、跑满上限、裸键=最新轮、rounds 不可变历史、converge
  求值失败视为未收敛、体内节点失败传播、轮次键防重入、体内 human 暂停
  携带 loop_state、每轮 progress checkpoint
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.engine.workflow.engine import (
    WorkflowEngine,
    WorkflowNodeError,
    WorkflowPausedError,
)
from app.engine.workflow.node_executor import NodeResult
from app.engine.workflow.validator import validate_workflow
from app.engine.workflow.variable_pool import VariablePool

# ── Fixtures ──


def _wf(nodes: list[dict]) -> dict:
    return {"nodes": nodes, "edges": []}


def _loop_node(body: list[str], entry: str, max_iter: int = 5,
               converge: str | None = "{{ critic.verdict == 'approve' }}",
               next_nodes: list[dict] | None = None,
               node_id: str = "loop1") -> dict:
    return {
        "node_id": node_id, "type": "loop",
        "config": {
            "body": body, "body_entry": entry, "max_iterations": max_iter,
            **({"converge_expr": converge} if converge else {}),
            **({"next_nodes": next_nodes} if next_nodes else {}),
        },
    }


def _body_pair() -> list[dict]:
    """writer → critic（体成员，writer 引用循环前上游 research 不误报）。"""
    return [
        {"node_id": "research", "type": "agent", "config": {"next_nodes": [{"target": "loop1"}]}},
        _loop_node(["writer", "critic"], "writer"),
        {"node_id": "writer", "type": "agent",
         "config": {"input_query": "{{research.summary}}",
                    "next_nodes": [{"target": "critic"}]}},
        {"node_id": "crit", "type": "agent", "config": {}},  # 干扰项（非成员）
        {"node_id": "critic", "type": "agent", "config": {}},
    ]


def _codes(issues: list) -> set[str]:
    return {i.code for i in issues}


# ── Validator ──


class TestLoopValidation:
    def test_valid_loop_passes(self) -> None:
        result = validate_workflow(_wf(_body_pair()))
        assert "LOOP_BODY_EMPTY" not in _codes(result.issues)
        assert "LOOP_BODY_NOT_CLOSED" not in _codes(result.issues)
        assert "LOOP_BODY_CYCLE" not in _codes(result.issues)
        assert "FORWARD_REFERENCE" not in _codes(result.issues)

    def test_body_empty_or_missing_member(self) -> None:
        result = validate_workflow(_wf([
            _loop_node([], "writer"),
            {"node_id": "writer", "type": "agent", "config": {}},
        ]))
        assert "LOOP_BODY_EMPTY" in _codes(result.issues)

        result = validate_workflow(_wf([_loop_node(["ghost"], "ghost")]))
        assert "LOOP_BODY_EMPTY" in _codes(result.issues)

    def test_entry_not_in_body(self) -> None:
        result = validate_workflow(_wf([
            _loop_node(["writer"], "someone_else"),
            {"node_id": "writer", "type": "agent", "config": {}},
        ]))
        assert "LOOP_ENTRY_NOT_IN_BODY" in _codes(result.issues)

    def test_max_iterations_range(self) -> None:
        for bad in (0, 21, "5", None):
            result = validate_workflow(_wf([
                _loop_node(["writer"], "writer", max_iter=bad),  # type: ignore[arg-type]
                {"node_id": "writer", "type": "agent", "config": {}},
            ]))
            assert "LOOP_MAX_ITERATIONS_RANGE" in _codes(result.issues), bad

    def test_nested_loop_rejected(self) -> None:
        result = validate_workflow(_wf([
            _loop_node(["writer", "loop2"], "writer"),
            {"node_id": "writer", "type": "agent", "config": {}},
            _loop_node(["x"], "x", node_id="loop2"),
            {"node_id": "x", "type": "agent", "config": {}},
        ]))
        assert "LOOP_NESTED_NOT_SUPPORTED" in _codes(result.issues)

    def test_structural_nodes_rejected(self) -> None:
        result = validate_workflow(_wf([
            _loop_node(["start", "writer"], "writer"),
            {"node_id": "start", "type": "start", "config": {}},
            {"node_id": "writer", "type": "agent", "config": {}},
        ]))
        assert "LOOP_STRUCTURAL_NODE_IN_BODY" in _codes(result.issues)

    def test_body_not_closed(self) -> None:
        # 体成员连到 body 之外的非 loop 节点 → 违规
        wf = _wf([
            {"node_id": "research", "type": "agent", "config": {"next_nodes": [{"target": "loop1"}]}},
            _loop_node(["writer", "critic"], "writer"),
            {"node_id": "writer", "type": "agent", "config": {"next_nodes": [{"target": "critic"}]}},
            {"node_id": "critic", "type": "agent", "config": {"next_nodes": [{"target": "escape"}]}},
            {"node_id": "escape", "type": "agent", "config": {}},
        ])
        result = validate_workflow(wf)
        assert "LOOP_BODY_NOT_CLOSED" in _codes(result.issues)

    def test_return_edge_to_loop_is_legal(self) -> None:
        """回边（体尾 → 所属 loop）合法——连线驱动交互的循环闭合表达。"""
        wf = _wf([
            {"node_id": "research", "type": "agent", "config": {"next_nodes": [{"target": "loop1"}]}},
            _loop_node(["writer", "critic"], "writer"),
            {"node_id": "writer", "type": "agent", "config": {"next_nodes": [{"target": "critic"}]}},
            {"node_id": "critic", "type": "agent", "config": {"next_nodes": [{"target": "loop1"}]}},
        ])
        result = validate_workflow(wf)
        assert "LOOP_BODY_NOT_CLOSED" not in _codes(result.issues)

    def test_body_cycle_detected(self) -> None:
        # writer ↔ critic 互指（体内环）
        wf = _wf([
            _loop_node(["writer", "critic"], "writer"),
            {"node_id": "writer", "type": "agent", "config": {"next_nodes": [{"target": "critic"}]}},
            {"node_id": "critic", "type": "agent", "config": {"next_nodes": [{"target": "writer"}]}},
        ])
        result = validate_workflow(wf)
        assert "LOOP_BODY_CYCLE" in _codes(result.issues)
        # 全局环检测不重复报 CYCLE_DETECTED（体成员出边被跳过）
        assert "CYCLE_DETECTED" not in _codes(result.issues)

    def test_converge_ref_invalid(self) -> None:
        result = validate_workflow(_wf([
            _loop_node(["writer"], "writer", converge="{{downstream.x}} == 1"),
            {"node_id": "writer", "type": "agent", "config": {}},
            {"node_id": "downstream", "type": "agent", "config": {}},
        ]))
        assert "LOOP_CONVERGE_REF_INVALID" in _codes(result.issues)

    def test_body_member_referencing_loop_output_rejected(self) -> None:
        wf = _wf([
            {"node_id": "research", "type": "agent", "config": {"next_nodes": [{"target": "loop1"}]}},
            _loop_node(["writer"], "writer"),
            {"node_id": "writer", "type": "agent",
             "config": {"input_query": "{{loop1.iterations}}", "next_nodes": []}},
        ])
        result = validate_workflow(wf)
        assert "LOOP_FORWARD_REF" in _codes(result.issues)

    def test_global_cycle_outside_body_still_detected(self) -> None:
        """loop 之外的全局环仍然拦截（开洞只限体内部）。"""
        wf = _wf([
            {"node_id": "start", "type": "start", "config": {"next_nodes": [{"target": "a"}]}},
            {"node_id": "a", "type": "agent", "config": {"next_nodes": [{"target": "b"}]}},
            {"node_id": "b", "type": "agent", "config": {"next_nodes": [{"target": "a"}]}},
        ])
        result = validate_workflow(wf)
        assert "CYCLE_DETECTED" in _codes(result.issues)


# ── Engine ──


def _db_mock() -> MagicMock:
    mock_db = MagicMock()
    mock_col = MagicMock()
    mock_col.find_one = AsyncMock(return_value={"status": "running"})
    mock_col.update_one = AsyncMock()
    mock_db.return_value.__getitem__.return_value = mock_col
    return mock_db


def _ts_mock() -> MagicMock:
    ts = MagicMock()
    ts.append_timeline_event = AsyncMock()
    ts.add_total_tokens = AsyncMock()
    ts.transition_task = AsyncMock()
    return ts


def _engine(nodes: list[dict]) -> WorkflowEngine:
    engine = WorkflowEngine()
    engine._task_id = "task_loop"
    engine._nodes = nodes
    engine._node_map = {n["node_id"]: n for n in nodes}
    engine._pool = VariablePool()
    return engine


def _loop_result(config: dict) -> NodeResult:
    return NodeResult(success=True, output={
        "body": [m for m in config.get("body", []) if isinstance(m, str)],
        "body_entry": config.get("body_entry", ""),
        "max_iterations": config.get("max_iterations", 1),
        "converge_expr": config.get("converge_expr"),
    })


class TestLoopExecution:
    """引擎轮次循环语义（mock executor 驱动）。"""

    def _make_executors(self, nodes, critic_verdicts: list[str]):
        """critic 按调用次数依次返回 verdict（控制收敛轮次）。"""
        call_idx = {"n": 0}

        def _get(node_type: str, node_id: str, cfg: dict) -> MagicMock:
            ex = MagicMock()
            if node_id == "loop1":
                ex.execute = AsyncMock(return_value=_loop_result(cfg))
            elif node_id == "critic":
                async def _critic(variables):
                    verdict = critic_verdicts[min(call_idx["n"], len(critic_verdicts) - 1)]
                    call_idx["n"] += 1
                    return NodeResult(success=True, output={"verdict": verdict})
                ex.execute = _critic
            else:
                async def _ok(variables):
                    return NodeResult(success=True, output={"draft": f"v{call_idx['n']}"})
                ex.execute = _ok
            return ex

        return _get

    @pytest.mark.asyncio
    async def test_converge_at_round2(self) -> None:
        """第 2 轮收敛退出：iterations=2/converged=True，rounds 不可变。"""
        nodes = [
            _loop_node(["writer", "critic"], "writer", max_iter=5),
            {"node_id": "writer", "type": "agent", "config": {"next_nodes": [{"target": "critic"}]}},
            {"node_id": "critic", "type": "agent", "config": {}},
        ]
        engine = _engine(nodes)
        with patch("app.engine.workflow.engine.get_node_executor",
                   side_effect=self._make_executors(nodes, ["reject", "approve"])), \
             patch("app.engine.workflow.engine.TaskService", new=_ts_mock()), \
             patch("app.db.mongodb.get_database", new=_db_mock()):
            result = await engine._execute_node("loop1")

        assert result is not None and result.success
        loop_out = engine._pool.get("loop1")
        assert loop_out["iterations"] == 2
        assert loop_out["converged"] is True
        # rounds 快照：两轮历史，每轮含体成员输出
        assert set(loop_out["rounds"].keys()) == {"1", "2"}
        # 裸键 = 最新轮（critic 最新 verdict=approve）
        assert engine._pool.get("critic.verdict") == "approve"
        # 轮次键：每成员每轮一个
        keys = engine._completed_nodes
        assert {"writer#r1", "critic#r1", "writer#r2", "critic#r2", "loop1"} <= keys

    @pytest.mark.asyncio
    async def test_runs_to_max_without_converge_expr(self) -> None:
        """converge_expr=None → 跑满轮数（批量映射模式）。"""
        nodes = [
            _loop_node(["worker"], "worker", max_iter=3, converge=None),
            {"node_id": "worker", "type": "agent", "config": {}},
        ]
        engine = _engine(nodes)
        with patch("app.engine.workflow.engine.get_node_executor",
                   side_effect=self._make_executors(nodes, [])), \
             patch("app.engine.workflow.engine.TaskService", new=_ts_mock()), \
             patch("app.db.mongodb.get_database", new=_db_mock()):
            await engine._execute_node("loop1")

        loop_out = engine._pool.get("loop1")
        assert loop_out["iterations"] == 3
        assert loop_out["converged"] is False
        assert set(loop_out["rounds"].keys()) == {"1", "2", "3"}

    @pytest.mark.asyncio
    async def test_converge_eval_failure_treated_as_not_converged(self) -> None:
        """收敛表达式求值失败 → warning + 视为未收敛（跑满上限诚实结束）。"""
        nodes = [
            _loop_node(["worker"], "worker", max_iter=2,
                       converge="{{ worker.nonexistent == 'x' }}"),
            {"node_id": "worker", "type": "agent", "config": {}},
        ]
        engine = _engine(nodes)
        with patch("app.engine.workflow.engine.get_node_executor",
                   side_effect=self._make_executors(nodes, [])), \
             patch("app.engine.workflow.engine.TaskService", new=_ts_mock()), \
             patch("app.db.mongodb.get_database", new=_db_mock()):
            await engine._execute_node("loop1")

        loop_out = engine._pool.get("loop1")
        assert loop_out["iterations"] == 2
        assert loop_out["converged"] is False

    @pytest.mark.asyncio
    async def test_body_node_failure_propagates(self) -> None:
        """体内节点失败 → WorkflowNodeError 传播（诚实失败）。"""
        nodes = [
            _loop_node(["worker"], "worker", max_iter=3),
            {"node_id": "worker", "type": "agent", "config": {}},
        ]

        def _get(node_type, node_id, cfg):
            ex = MagicMock()
            if node_id == "loop1":
                ex.execute = AsyncMock(return_value=_loop_result(cfg))
            else:
                ex.execute = AsyncMock(return_value=NodeResult(success=False, error_message="boom"))
            return ex

        engine = _engine(nodes)
        with patch("app.engine.workflow.engine.get_node_executor", side_effect=_get), \
             patch("app.engine.workflow.engine.TaskService", new=_ts_mock()), \
             patch("app.db.mongodb.get_database", new=_db_mock()), \
             pytest.raises(WorkflowNodeError):
            await engine._execute_node("loop1")

    @pytest.mark.asyncio
    async def test_human_pause_inside_body_saves_loop_state(self) -> None:
        """体内 human 暂停 → WorkflowPausedError + checkpoint 带 loop 位置。"""
        nodes = [
            _loop_node(["worker", "reviewer"], "worker", max_iter=3),
            {"node_id": "worker", "type": "agent", "config": {"next_nodes": [{"target": "reviewer"}]}},
            {"node_id": "reviewer", "type": "human", "config": {}},
        ]

        def _get(node_type, node_id, cfg):
            ex = MagicMock()
            if node_id == "loop1":
                ex.execute = AsyncMock(return_value=_loop_result(cfg))
            elif node_id == "reviewer":
                ex.execute = AsyncMock(return_value=NodeResult(success=True, output={
                    "status": "waiting_human", "title": "审核", "description": "",
                    "options": [], "timeout_ms": 0, "timeout_action": "fail",
                }))
            else:
                ex.execute = AsyncMock(return_value=NodeResult(success=True, output={"draft": "v1"}))
            return ex

        engine = _engine(nodes)
        with patch("app.engine.workflow.engine.get_node_executor", side_effect=_get), \
             patch("app.engine.workflow.engine.TaskService", new=_ts_mock()), \
             patch("app.db.mongodb.get_database", new=_db_mock()), \
             pytest.raises(WorkflowPausedError):
            await engine._execute_node("loop1")

        # 暂停后 active loop 已清理（防止泄漏影响后续节点语义）
        assert engine._active_loop_node == ""

    @pytest.mark.asyncio
    async def test_progress_checkpoint_written_per_round(self) -> None:
        """每轮完成即写 progress checkpoint（长程稳定性硬规范）。"""
        nodes = [
            _loop_node(["worker"], "worker", max_iter=2),
            {"node_id": "worker", "type": "agent", "config": {}},
        ]
        engine = _engine(nodes)
        db = _db_mock()
        with patch("app.engine.workflow.engine.get_node_executor",
                   side_effect=self._make_executors(nodes, [])), \
             patch("app.engine.workflow.engine.TaskService", new=_ts_mock()), \
             patch("app.db.mongodb.get_database", new=db):
            await engine._execute_node("loop1")

        # 2 轮 → 2 次 progress checkpoint 写入（update_one 中 checkpoint $set）
        checkpoint_sets = [
            c for c in db.return_value.__getitem__.return_value.update_one.call_args_list
            if isinstance(c.args[1], dict) and "checkpoint" in (c.args[1].get("$set") or {})
        ]
        assert len(checkpoint_sets) == 2
        last = checkpoint_sets[-1].args[1]["$set"]["checkpoint"]
        assert last["kind"] == "progress"
        assert last["loop_state"] == {"loop_node_id": "loop1", "round": 3}


class TestReturnEdgeExecution:
    """回边（体成员 next→loop）在执行层被跳过——不重入 loop 分支。"""

    @pytest.mark.asyncio
    async def test_return_edge_skipped_during_round(self) -> None:
        """体成员残留回边（旧数据）时，轮末由链耗尽决定而非重入 loop。"""
        nodes = [
            _loop_node(["worker", "checker"], "worker", max_iter=2,
                       converge=None),
            # worker 的 next 同时指向 checker 和 loop1（回边）——回边应被跳过
            {"node_id": "worker", "type": "agent",
             "config": {"next_nodes": [{"target": "checker"}, {"target": "loop1"}]}},
            {"node_id": "checker", "type": "agent", "config": {}},
        ]
        calls: list[str] = []

        def _get(node_type, node_id, cfg):
            ex = MagicMock()
            if node_id == "loop1":
                ex.execute = AsyncMock(return_value=_loop_result(cfg))
            else:
                async def _track(variables):
                    calls.append(node_id)
                    return NodeResult(success=True, output={"ok": True})
                ex.execute = _track
            return ex

        engine = _engine(nodes)
        with patch("app.engine.workflow.engine.get_node_executor", side_effect=_get), \
             patch("app.engine.workflow.engine.TaskService", new=_ts_mock()), \
             patch("app.db.mongodb.get_database", new=_db_mock()):
            await engine._execute_node("loop1")

        # 2 轮 × (worker, checker) 各一次，loop1 执行器仅 1 次（无重入）
        assert calls.count("worker") == 2
        assert calls.count("checker") == 2
        assert engine._pool.get("loop1")["iterations"] == 2

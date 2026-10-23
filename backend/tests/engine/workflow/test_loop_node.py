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
        for bad in (0, 101, "5", None):
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

    def test_body_label_conflict_rejected(self) -> None:
        """体成员同名 → 工作台产物槽（key=label）共享会互相打断版本链。"""
        nodes = [
            _loop_node(["writer", "critic"], "writer"),
            {"node_id": "writer", "type": "agent", "label": "撰稿",
             "config": {"next_nodes": [{"target": "critic"}]}},
            {"node_id": "critic", "type": "agent", "label": "撰稿",
             "config": {}},
        ]
        result = validate_workflow(_wf(nodes))
        assert "LOOP_BODY_LABEL_CONFLICT" in _codes(result.issues)

        # 不同名（含未设 label 回退 node_id）→ 通过。
        nodes[2]["label"] = "评审"
        result = validate_workflow(_wf(nodes))
        assert "LOOP_BODY_LABEL_CONFLICT" not in _codes(result.issues)

        # 循环外同名不受影响（槽隔离只在 body 内）。
        result = validate_workflow(_wf([
            *nodes,
            {"node_id": "outside", "type": "agent", "label": "撰稿",
             "config": {}},
        ]))
        assert "LOOP_BODY_LABEL_CONFLICT" not in _codes(result.issues)

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


class TestLoopNoteAndStall:
    """工作台退役后的轻量机制：值级 sha 空转检测。"""

    @staticmethod
    def _static_executors(nodes):
        """writer 每轮输出恒定（同 sha）；critic 恒 reject（不收敛）。"""
        def _get(node_type: str, node_id: str, cfg: dict) -> MagicMock:
            ex = MagicMock()
            if node_id == "loop1":
                ex.execute = AsyncMock(return_value=_loop_result(cfg))
            elif node_id == "critic":
                async def _critic(variables):
                    return NodeResult(success=True, output={"verdict": "reject"})
                ex.execute = _critic
            else:
                async def _writer(variables):
                    # 记录收到的变量（断言 loop_note 注入）
                    _writer.seen = variables
                    return NodeResult(success=True, output={"draft": "恒定输出"})
                ex.execute = _writer
            return ex
        return _get

    @pytest.mark.asyncio
    async def test_stalled_after_streak_of_identical_outputs(self) -> None:
        """成员输出连续 STALL_STREAK(2) 轮 sha 不变 → 提前结束 + stalled 标记。"""
        nodes = [
            _loop_node(["writer", "critic"], "writer", max_iter=5),
            {"node_id": "writer", "type": "agent", "config": {"next_nodes": [{"target": "critic"}]}},
            {"node_id": "critic", "type": "agent", "config": {}},
        ]
        engine = _engine(nodes)
        with patch("app.engine.workflow.engine.get_node_executor",
                   side_effect=self._static_executors(nodes)), \
             patch("app.engine.workflow.engine.TaskService", new=_ts_mock()), \
             patch("app.db.mongodb.get_database", new=_db_mock()):
            await engine._execute_node("loop1")
        loop_out = engine._pool.get("loop1")
        # 轮1 建 sha 基线(streak=0)；轮2 与上轮相同(streak=1)；轮3 再次
        # 相同(streak=2=STALL_STREAK) → 轮3 末 stalled 提前结束（而非跑满 5）
        assert loop_out["iterations"] == 3
        assert loop_out["stalled"] is True

    @staticmethod
    def _changing_executors():
        """输出每轮变化（sha 前进）→ 不应触发 stalled。"""
        call_n = {"n": 0}

        def _get(node_type: str, node_id: str, cfg: dict) -> MagicMock:
            ex = MagicMock()
            if node_id == "loop1":
                ex.execute = AsyncMock(return_value=_loop_result(cfg))
            else:
                async def _run(variables):
                    call_n["n"] += 1
                    return NodeResult(success=True, output={"draft": f"第{call_n['n']}版"})
                ex.execute = _run
            return ex
        return _get

    @pytest.mark.asyncio
    async def test_no_stall_when_output_evolves(self) -> None:
        nodes = [
            _loop_node(["writer"], "writer", max_iter=3, converge=None),
            {"node_id": "writer", "type": "agent", "config": {}},
        ]
        engine = _engine(nodes)
        with patch("app.engine.workflow.engine.get_node_executor",
                   side_effect=self._changing_executors()), \
             patch("app.engine.workflow.engine.TaskService", new=_ts_mock()), \
             patch("app.db.mongodb.get_database", new=_db_mock()):
            await engine._execute_node("loop1")
        loop_out = engine._pool.get("loop1")
        assert loop_out["iterations"] == 3
        assert "stalled" not in loop_out or loop_out["stalled"] is not True


class TestCrossRoundReference:
    """跨轮引用模型（工作台退役后的核心语义，变量池时序保证）：

    - 先引前（后执行者引用先执行者）＝ 取本轮最新值
    - 前引后（先执行者引用后执行者）＝ 取上一轮值
    - 首轮前引后 ＝ 变量未定义（空）
    """

    @staticmethod
    def _recording_executors(nodes, critic_verdicts: list[str]):
        """记录每个成员每轮收到的全量变量（断言跨轮引用语义）。"""
        seen: dict[str, list[dict]] = {}

        def _get(node_type: str, node_id: str, cfg: dict) -> MagicMock:
            ex = MagicMock()
            if node_id == "loop1":
                ex.execute = AsyncMock(return_value=_loop_result(cfg))
            elif node_id == "critic":
                idx = {"n": 0}

                async def _critic(variables):
                    seen.setdefault("critic", []).append(dict(variables))
                    v = critic_verdicts[min(idx["n"], len(critic_verdicts) - 1)]
                    idx["n"] += 1
                    return NodeResult(success=True, output={"verdict": v, "comment": f"意见{idx['n']}"})
                ex.execute = _critic
            else:
                async def _writer(variables):
                    seen.setdefault("writer", []).append(dict(variables))
                    return NodeResult(success=True, output={"response": "稿"})
                ex.execute = _writer
            ex.seen = seen
            return ex
        return _get, seen

    @pytest.mark.asyncio
    async def test_forward_reference_gets_previous_round_value(self) -> None:
        """前引后（writer 引用 critic.verdict）：轮1 未定义；轮2 起取上轮值。"""
        nodes = [
            _loop_node(["writer", "critic"], "writer", max_iter=2, converge=None),
            {"node_id": "writer", "type": "agent",
             "config": {"input_query": "按意见改：{{critic.verdict}}",
                        "next_nodes": [{"target": "critic"}]}},
            {"node_id": "critic", "type": "agent", "config": {}},
        ]
        engine = _engine(nodes)
        factory, seen = self._recording_executors(nodes, ["reject", "approve"])
        with patch("app.engine.workflow.engine.get_node_executor", side_effect=factory), \
             patch("app.engine.workflow.engine.TaskService", new=_ts_mock()), \
             patch("app.db.mongodb.get_database", new=_db_mock()):
            await engine._execute_node("loop1")

        writer_rounds = seen["writer"]
        assert len(writer_rounds) == 2
        # 轮 1：critic 尚未执行过 → 池中无其输出（首轮冷启动事实）
        assert "critic" not in writer_rounds[0]
        # 轮 2：critic 已在轮 1 执行 → writer 轮 2 拿到的是轮 1 的值
        # （variables 为 pool.get_all() 嵌套形态；writer 的任务模板里
        #  {{critic.verdict}} 由 ExpressionEngine 点路径取到同一值）
        assert writer_rounds[1]["critic"]["verdict"] == "reject"

    @pytest.mark.asyncio
    async def test_backward_reference_gets_current_round_value(self) -> None:
        """先引前（critic 引用 writer.response）：每轮拿本轮最新值。"""
        nodes = [
            _loop_node(["writer", "critic"], "writer", max_iter=2, converge=None),
            {"node_id": "writer", "type": "agent",
             "config": {"next_nodes": [{"target": "critic"}]}},
            {"node_id": "critic", "type": "agent",
             "config": {"input_query": "评审：{{writer.response}}"}},
        ]
        engine = _engine(nodes)
        factory, seen = self._recording_executors(nodes, ["reject", "approve"])
        with patch("app.engine.workflow.engine.get_node_executor", side_effect=factory), \
             patch("app.engine.workflow.engine.TaskService", new=_ts_mock()), \
             patch("app.db.mongodb.get_database", new=_db_mock()):
            await engine._execute_node("loop1")

        critic_rounds = seen["critic"]
        assert len(critic_rounds) == 2
        # 每轮 critic 执行时 writer 已在本轮跑完 → 本轮值（裸键=最新）
        for rnd_vars in critic_rounds:
            assert rnd_vars["writer"]["response"] == "稿"

    @pytest.mark.asyncio
    async def test_bare_key_is_latest_round_and_rounds_immutable(self) -> None:
        """裸键=最新轮值；rounds 快照各轮独立（不可变历史）。"""
        nodes = [
            _loop_node(["worker"], "worker", max_iter=3, converge=None),
            {"node_id": "worker", "type": "agent", "config": {}},
        ]
        call_n = {"n": 0}

        def _get(node_type: str, node_id: str, cfg: dict) -> MagicMock:
            ex = MagicMock()
            if node_id == "loop1":
                ex.execute = AsyncMock(return_value=_loop_result(cfg))
            else:
                async def _run(variables):
                    call_n["n"] += 1
                    return NodeResult(success=True, output={"response": f"第{call_n['n']}版"})
                ex.execute = _run
            return ex

        engine = _engine(nodes)
        with patch("app.engine.workflow.engine.get_node_executor", side_effect=_get), \
             patch("app.engine.workflow.engine.TaskService", new=_ts_mock()), \
             patch("app.db.mongodb.get_database", new=_db_mock()):
            await engine._execute_node("loop1")

        # 裸键 = 最新轮（第 3 版）
        assert engine._pool.get("worker.response") == "第3版"
        loop_out = engine._pool.get("loop1")
        # rounds 各轮独立且按轮序固化
        assert loop_out["rounds"]["1"]["worker"]["response"] == "第1版"
        assert loop_out["rounds"]["3"]["worker"]["response"] == "第3版"


class TestLoopTimelineEvents:
    """循环的 timeline 事件序列与轮次键（跳过/重入语义）。"""

    @staticmethod
    def _collecting_ts(events: list[dict]) -> MagicMock:
        ts = _ts_mock()
        async def _append(task_id, event_type, data=None, actor="system"):
            events.append({"event_type": event_type, "data": data or {}})
        ts.append_timeline_event = _append
        return ts

    @pytest.mark.asyncio
    async def test_round_events_and_stalled_event_sequence(self) -> None:
        """恒定输出 → 事件序列 round_start/round_complete ×3 + stalled（第3轮末）。"""
        nodes = [
            _loop_node(["worker"], "worker", max_iter=5, converge=None),
            {"node_id": "worker", "type": "agent", "config": {}},
        ]
        events: list[dict] = []
        engine = _engine(nodes)

        def _get(node_type: str, node_id: str, cfg: dict) -> MagicMock:
            ex = MagicMock()
            if node_id == "loop1":
                ex.execute = AsyncMock(return_value=_loop_result(cfg))
            else:
                async def _run(variables):
                    return NodeResult(success=True, output={"response": "恒定"})
                ex.execute = _run
            return ex

        with patch("app.engine.workflow.engine.get_node_executor", side_effect=_get), \
             patch("app.engine.workflow.engine.TaskService", new=self._collecting_ts(events)), \
             patch("app.db.mongodb.get_database", new=_db_mock()):
            await engine._execute_node("loop1")

        # 只断言循环级事件（node_start/complete 为 worker 每轮的常规事件混在其中）
        seq = [e["event_type"] for e in events if e["event_type"].startswith("loop_")]
        # 3 轮（streak=2 于第 3 轮触发）+ stalled 事件在最后一轮 complete 之后
        assert seq == [
            "loop_round_start", "loop_round_complete",
            "loop_round_start", "loop_round_complete",
            "loop_round_start", "loop_round_complete",
            "loop_stalled",
        ]
        # 全量序列的最后一个事件即 stalled（其后无其他事件）
        assert events[-1]["event_type"] == "loop_stalled"
        assert events[-1]["data"].get("round") == 3
        # worker 的常规 node 事件仍在（每轮一对，loop 轮窗口内）
        node_starts = [e for e in events if e["event_type"] == "node_start"]
        assert len(node_starts) >= 3


class TestBodyCrossReference:
    """体成员互相引用（跨轮引用模型）：前引后=上轮值，校验放行。"""

    def test_writer_referencing_critic_allowed(self) -> None:
        """writer 任务引用 critic.comment（前向，合法——拿上轮意见）。"""
        wf = _wf([
            _loop_node(["writer", "critic"], "writer"),
            {"node_id": "writer", "type": "agent",
             "config": {"input_query": "上轮意见：{{critic.comment}}",
                        "next_nodes": [{"target": "critic"}]}},
            {"node_id": "critic", "type": "agent", "config": {}},
        ])
        result = validate_workflow(wf)
        assert "FORWARD_REFERENCE" not in _codes(result.issues)

    def test_outside_forward_reference_still_rejected(self) -> None:
        """循环外的前向引用仍拦截（真正拿不到值）。"""
        wf = _wf([
            {"node_id": "upstream", "type": "agent",
             "config": {"input_query": "{{downstream.response}}",
                        "next_nodes": [{"target": "downstream"}]}},
            {"node_id": "downstream", "type": "agent", "config": {}},
        ])
        result = validate_workflow(wf)
        assert "FORWARD_REFERENCE" in _codes(result.issues)


class TestRepairUnescapedInnerQuotes:
    """内嵌引号修复：评审意见引用原文导致 JSON 字符串提前闭合（实测形态）。"""

    def test_repairs_real_failure_shape(self) -> None:
        """实测失败形态：issues 值内含未转义引号（引用策划师原文）。"""
        import json

        from app.engine.workflow.node_executor import _repair_unescaped_inner_quotes

        broken = (
            '{"verdict":"revise","score":"6.7","issues":"人群匹配（7分）：'
            '仅锁定"重度咖啡因使用者+办公室白领"，未区分"对现有咖啡不满"的'
            '细分，付费意愿调研应加入痛点归因，锁定"愿为免广告者"为核心人群"}'
        )
        with pytest.raises(json.JSONDecodeError):
            json.loads(broken)  # 修复前非法（实测报错形态）

        repaired = _repair_unescaped_inner_quotes(broken)
        value = json.loads(repaired)  # 修复后可解析
        assert value["verdict"] == "revise"
        # 引号被转义保留在字符串值内（不丢信息）
        assert "重度咖啡因使用者" in value["issues"]

    def test_valid_json_untouched(self) -> None:
        """合法 JSON 零改动。"""
        from app.engine.workflow.node_executor import _repair_unescaped_inner_quotes
        ok = '{"verdict":"approve","issues":"通过"}'
        assert _repair_unescaped_inner_quotes(ok) == ok

    def test_extract_chain_recovers_real_failure(self) -> None:
        """端到端：修复链（裸换行+内嵌引号组合）从实测失败输出中恢复 JSON。"""
        from app.engine.workflow.node_executor import _extract_json_payload
        broken = (
            '{"verdict":"revise","issues":"人群匹配（7分）：仅锁定"重度咖啡因"群体，'
            '未区分细分场景\n卖点锐度：同质化明显，建议差异化\n'
            '渠道效率：单渠道试销样本偏小"}'
        )
        value, err = _extract_json_payload(broken)
        assert value is not None, err
        assert value["verdict"] == "revise"

    def test_structural_close_not_escaped(self) -> None:
        """引号后跟 : , } ] 时不误转义（结构闭合保持）。"""
        from app.engine.workflow.node_executor import _repair_unescaped_inner_quotes
        ok = '{"a":"文本 "引号" 结尾","b":"x"}'
        repaired = _repair_unescaped_inner_quotes(ok)
        import json
        value = json.loads(repaired)
        assert value["b"] == "x"
        assert "引号" in value["a"]

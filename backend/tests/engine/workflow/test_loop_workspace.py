"""Tests for LoopWorkspace（refine 模板 MVP）— 状态中心循环的引擎层。

覆盖（docs/multi-agent-collaboration.md 续篇 / 本 session 设计修正）：
- 模块：约定式吸收（artifact 版本/sha、issue 双向流转、approve 隐式全关、
  delta 生成）、视图分区纪律、空转/通胀检测、序列化回环
- 注入组合：fresh/第1轮→全量视图，continue 后续轮→增量；非体成员不注入
- 引擎：建台/轮末吸收/loop_output 携带 workspace/未配置零影响/
  checkpoint 恢复（progress 崩溃续跑带已吸收状态）/空转提前结束
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.engine.workflow.engine import WorkflowEngine
from app.engine.workflow.loop_workspace import (
    LoopWorkspace,
    compose_workspace_message,
)
from app.engine.workflow.node_executor import NodeResult
from app.engine.workflow.variable_pool import VariablePool

# ── Fixtures（对齐 test_loop_node.py 的 mock 基建） ──


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
    engine._task_id = "task_ws"
    engine._nodes = nodes
    engine._node_map = {n["node_id"]: n for n in nodes}
    engine._pool = VariablePool()
    return engine


def _loop_node(body: list[str], entry: str, max_iter: int = 5,
               converge: str | None = None, goal: str | None = None) -> dict:
    cfg = {"body": body, "body_entry": entry, "max_iterations": max_iter}
    if converge:
        cfg["converge_expr"] = converge
    if goal:
        cfg["workspace_goal"] = goal
    return {"node_id": "loop1", "type": "loop", "config": cfg}


def _loop_result(config: dict) -> NodeResult:
    return NodeResult(success=True, output={"body": config.get("body", [])})


def _executors(critic_outputs: list[dict], writer_drafts: list[str]):
    """writer 依次产 draft；critic 依次回结构化输出（verdict/issues/resolved）。"""
    idx = {"w": 0, "c": 0}

    def _get(node_type: str, node_id: str, cfg: dict) -> MagicMock:
        ex = MagicMock()
        if node_id == "loop1":
            ex.execute = AsyncMock(return_value=_loop_result(cfg))
        elif node_id == "critic":
            async def _critic(variables):
                out = critic_outputs[min(idx["c"], len(critic_outputs) - 1)]
                idx["c"] += 1
                return NodeResult(success=True, output=out)
            ex.execute = _critic
        else:
            async def _writer(variables):
                d = writer_drafts[min(idx["w"], len(writer_drafts) - 1)]
                idx["w"] += 1
                return NodeResult(success=True, output={"draft": d})
            ex.execute = _writer
        return ex

    return _get


PAIR_NODES = lambda goal=None, converge=None, max_iter=5: [  # noqa: E731
    _loop_node(["writer", "critic"], "writer", max_iter=max_iter,
               converge=converge, goal=goal),
    {"node_id": "writer", "type": "agent", "label": "写手",
     "config": {"next_nodes": [{"target": "critic"}]}},
    {"node_id": "critic", "type": "agent", "label": "审核", "config": {}},
]


# ── 模块级：吸收约定 ──


class TestAbsorbConventions:
    def test_artifact_versioning_and_stall_count(self) -> None:
        ws = LoopWorkspace("目标")
        ws.absorb("写手", {"draft": "第一稿内容"}, 1)
        a1 = ws.artifacts["写手"]
        assert a1["version"] == 1 and a1["stall"] == 0
        ws.absorb("写手", {"draft": "第二稿内容"}, 2)
        assert ws.artifacts["写手"]["version"] == 2
        # 同内容重交：版本不前进，stall 计数
        ws.absorb("写手", {"draft": "第二稿内容"}, 3)
        assert ws.artifacts["写手"]["version"] == 2
        assert ws.artifacts["写手"]["stall"] == 1
        assert ws.is_stalled() is False
        ws.absorb("写手", {"draft": "第二稿内容"}, 4)
        assert ws.is_stalled() is True  # 连续 2 轮无变化

    def test_object_contract_fields_inside_response(self) -> None:
        """v3 契约 object 模式：verdict/comment 等在 response 内层（首跑实测
        发现的映射缺口）；revise + comment 兜底成一个待解决项。"""
        ws = LoopWorkspace("目标")
        ws.absorb("审核", {
            "response": {"verdict": "revise", "comment": "开头钩子太弱，缺具体场景"},
        }, 1)
        # verdict 从内层取到
        assert ws.verdicts[-1]["verdict"] == "revise"
        # comment 兜底为单个待解决项（不强行拆解）
        assert len(ws.issues) == 1
        assert "钩子太弱" in ws.issues[0]["text"]
        # approve（内层）隐式关闭
        ws.absorb("审核", {"response": {"verdict": "approve", "comment": "无"}}, 2)
        assert ws.issues[0]["status"] == "resolved"
        # text 模式（response=str）不受内层查找影响，全文即产物
        ws.absorb("写手", {"response": "初稿全文"}, 1)
        assert ws.artifacts["写手"]["version"] == 1

    def test_issue_lifecycle_fixes_then_resolved(self) -> None:
        ws = LoopWorkspace("目标")
        ws.absorb("审核", {"verdict": "revise", "issues": ["钩子太弱", "缺数据"]}, 1)
        assert len(ws.issues) == 2 and all(i["status"] == "open" for i in ws.issues)
        # writer 声明修复 #1（可虚假，待确认）
        ws.absorb("写手", {"fixes": [1]}, 2)
        assert ws.issues[0]["status"] == "claimed"
        # critic 确认 #1 关闭、又提新问题
        ws.absorb("审核", {"verdict": "revise", "resolved": [1], "issues": ["结尾仓促"]}, 2)
        assert ws.issues[0]["status"] == "resolved"
        assert ws.issues[2]["text"] == "结尾仓促"

    def test_approve_closes_only_own_issues(self) -> None:
        """approve 只关闭本节点提出的 issue——多评审场景下他人 approve
        不能代替提出者确认（实测 bug：风险审核 approve 关掉了语义审核
        刚提出的问题，writer 无活可干）。单评审循环行为不变。"""
        ws = LoopWorkspace("目标")
        ws.absorb("语义审核", {"verdict": "revise", "issues": ["a", "b", "c"]}, 1)
        # 另一个评审 approve：语义审核的问题必须保持 open
        ws.absorb("风险审核", {"verdict": "approve"}, 1)
        assert all(i["status"] == "open" for i in ws.issues)
        # 提出者自己 approve：其问题全部关闭
        ws.absorb("语义审核", {"verdict": "approve"}, 2)
        assert all(i["status"] == "resolved" for i in ws.issues)
        assert all(i["resolved_round"] == 2 for i in ws.issues)

    def test_round_delta_accumulates_across_members(self) -> None:
        """delta 按轮累计：同轮多成员的变化全部保留（按成员覆盖会只剩
        末位成员——实测 writer 轮 2 只看到风险审核的动静，看不到语义
        审核新增的待解决问题）。"""
        ws = LoopWorkspace("目标")
        ws.absorb("写手", {"draft": "v1"}, 1)
        ws.absorb("语义审核", {"verdict": "revise", "issues": ["钩子太弱"]}, 1)
        ws.absorb("风险审核", {"verdict": "approve"}, 1)
        assert "钩子太弱" in ws.last_delta          # 语义审核的 issue 在
        assert "写手更新为 v1" in ws.last_delta or "v1" in ws.last_delta
        assert "风险审核判定：approve" in ws.last_delta
        # 下一轮重置
        ws.absorb("写手", {"draft": "v2"}, 2)
        assert ws.last_delta.startswith("【第 2 轮工作台变化】")
        assert "钩子太弱" not in ws.last_delta

    def test_text_mode_response_becomes_artifact(self) -> None:
        ws = LoopWorkspace("目标")
        ws.absorb("写手", {"response": "text 模式全文即产物"}, 1)
        assert ws.artifacts["写手"]["version"] == 1
        # object 模式（response 是 dict）不进产物槽
        ws.absorb("审核", {"response": {"verdict": "x"}, "verdict": "x"}, 1)
        assert "审核" not in ws.artifacts
        assert ws.verdicts[-1]["verdict"] == "x"

    def test_delta_records_changes(self) -> None:
        ws = LoopWorkspace("目标")
        ws.absorb("审核", {"verdict": "revise", "issues": ["钩子弱"]}, 1)
        assert "钩子弱" in ws.last_delta and "revise" in ws.last_delta

    def test_diverging_detection(self) -> None:
        ws = LoopWorkspace("目标")
        for rnd, n in enumerate([1, 2, 3], start=1):  # open 数连续递增
            ws.absorb("审核", {"verdict": "revise", "issues": [f"问题{i}" for i in range(n)]}, rnd)
        assert ws.is_diverging() is True

    def test_roundtrip_serialization(self) -> None:
        ws = LoopWorkspace("目标")
        ws.absorb("写手", {"draft": "v1"}, 1)
        ws.absorb("审核", {"verdict": "revise", "issues": ["x"]}, 1)
        restored = LoopWorkspace.from_dict(ws.to_dict())
        assert restored is not None
        assert restored.artifacts["写手"]["sha8"] == ws.artifacts["写手"]["sha8"]
        assert restored.issues[0]["text"] == "x"
        assert LoopWorkspace.from_dict({}) is None
        assert LoopWorkspace.from_dict(None) is None


# ── 注入组合规则 ──


class TestComposeMessage:
    def test_first_round_gets_full_view(self) -> None:
        sys_vars = {"loop_round": 1, "workspace_view": "【工作台】目标：X", "workspace_delta": ""}
        msg = compose_workspace_message(sys_vars, {})
        assert msg == "【工作台】目标：X"

    def test_continue_later_rounds_get_delta(self) -> None:
        sys_vars = {
            "loop_round": 3,
            "workspace_view": "【工作台】目标：X\n当前稿v3\n待解决…",
            "workspace_delta": "【第 2 轮工作台变化】新增待解决：y",
        }
        msg = compose_workspace_message(sys_vars, {})  # 默认 continue
        assert msg.startswith("【第 2 轮")

    def test_fresh_always_gets_full_view(self) -> None:
        sys_vars = {
            "loop_round": 4,
            "workspace_view": "【工作台】目标：X",
            "workspace_delta": "增量",
        }
        msg = compose_workspace_message(sys_vars, {"loop_thread_policy": "fresh"})
        assert msg == "【工作台】目标：X"

    def test_no_injection_outside_loop_or_without_workspace(self) -> None:
        assert compose_workspace_message({"workspace_view": "V"}, {}) == ""  # 非体成员
        assert compose_workspace_message({"loop_round": 2}, {}) == ""  # 未启用工作台


# ── 引擎级 ──


class TestEngineWorkspace:
    @pytest.mark.asyncio
    async def test_goal_once_and_absorb_into_loop_output(self) -> None:
        """工作台模式：goal 渲染、吸收进 loop_output、系统变量带视图/增量。"""
        nodes = PAIR_NODES(
            goal="{{input.topic}} 改到审核通过", converge="{{ critic.verdict == 'approve' }}",
        )
        engine = _engine(nodes)
        engine._pool.set("input", {"topic": "写文案"})
        captured: list[dict] = []

        def _get(node_type: str, node_id: str, cfg: dict) -> MagicMock:
            ex = MagicMock()
            if node_id == "loop1":
                ex.execute = AsyncMock(return_value=_loop_result(cfg))
            else:
                async def _run(variables):
                    captured.append(dict(variables.get("system", {})))
                    if node_id == "writer":
                        return NodeResult(success=True, output={"draft": f"稿{len(captured)}"})
                    return NodeResult(success=True, output={
                        "verdict": "revise" if len(captured) < 3 else "approve",
                        "issues": ["钩子弱"] if len(captured) < 3 else [],
                        "resolved": [1] if len(captured) >= 3 else [],
                    })
                ex.execute = _run
            return ex

        with patch("app.engine.workflow.engine.get_node_executor", side_effect=_get), \
             patch("app.engine.workflow.engine.TaskService", new=_ts_mock()), \
             patch("app.db.mongodb.get_database", new=_db_mock()):
            await engine._execute_node("loop1")

        loop_out = engine._pool.get("loop1")
        ws = loop_out["workspace"]
        assert ws["goal"] == "写文案 改到审核通过"
        # issue 全流程：提出→resolved
        assert ws["issues"][0]["status"] == "resolved"
        assert ws["verdicts"][-1]["verdict"] == "approve"
        # 注入协议：轮 1 全量视图（含 goal），轮 2 起有增量
        assert any("workspace_view" in s and "目标" in s["workspace_view"] for s in captured[:2])
        assert any(s.get("workspace_delta") for s in captured[2:])
        # 系统变量不泄漏到循环外（finally 后清空？——worktree 变量仍在 pool，
        # 但 compose gate 于 loop_round，循环外不注入，见 TestComposeMessage）
        assert engine._active_workspace is None

    @pytest.mark.asyncio
    async def test_without_goal_no_workspace(self) -> None:
        """未配置 workspace_goal → 零影响（loop_output 无 workspace 键）。"""
        nodes = PAIR_NODES(converge="{{ critic.verdict == 'approve' }}")
        engine = _engine(nodes)
        with patch("app.engine.workflow.engine.get_node_executor",
                   side_effect=_executors(
                       [{"verdict": "approve"}], ["v1"])), \
             patch("app.engine.workflow.engine.TaskService", new=_ts_mock()), \
             patch("app.db.mongodb.get_database", new=_db_mock()):
            await engine._execute_node("loop1")
        assert "workspace" not in engine._pool.get("loop1")
        assert "workspace_view" not in (engine._pool.get("system") or {})

    @pytest.mark.asyncio
    async def test_stall_breaks_early(self) -> None:
        """空转检测：同稿连续重交 → 提前结束 + stalled 标记。"""
        nodes = PAIR_NODES(goal="打磨", max_iter=8)  # 无 converge
        engine = _engine(nodes)
        ts = _ts_mock()
        with patch("app.engine.workflow.engine.get_node_executor",
                   side_effect=_executors(
                       [{"verdict": "revise", "issues": ["再改"]} for _ in range(8)],
                       ["完全一样的稿子"] * 8)), \
             patch("app.engine.workflow.engine.TaskService", new=ts), \
             patch("app.db.mongodb.get_database", new=_db_mock()):
            await engine._execute_node("loop1")
        loop_out = engine._pool.get("loop1")
        # 轮1 产出、轮2/3 同稿（stall 累计到 2）→ 第 3 轮后 break
        assert loop_out["iterations"] == 3
        assert loop_out["stalled"] is True
        assert any(
            c.kwargs.get("event_type") == "loop_stalled"
            for c in ts.append_timeline_event.await_args_list
        )

    @pytest.mark.asyncio
    async def test_restore_from_progress_checkpoint(self) -> None:
        """崩溃恢复：checkpoint 带的工作台（已吸收状态）优先于新建。"""
        nodes = PAIR_NODES(
            goal="打磨",
            converge="{{ critic.verdict == 'approve' }}",
        )
        engine = _engine(nodes)
        # 模拟轮 2 起恢复：已有 1 个 issue、产物 v1
        engine._checkpoint_loop_state = {"loop_node_id": "loop1", "round": 2}
        engine._checkpoint_kind = "progress"
        engine._checkpoint_workspace = LoopWorkspace("打磨").to_dict()
        engine._checkpoint_workspace["issues"] = [{
            "id": 1, "text": "钩子弱", "raised_by": "审核", "raised_round": 1,
            "status": "open", "resolved_round": None,
        }]
        engine._checkpoint_workspace["artifacts"] = {
            "写手": {"version": 1, "sha8": "abc", "chars": 10, "head": "旧稿", "round": 1, "stall": 0},
        }

        def _get(node_type: str, node_id: str, cfg: dict) -> MagicMock:
            ex = MagicMock()
            if node_id == "loop1":
                ex.execute = AsyncMock(return_value=_loop_result(cfg))
            elif node_id == "critic":
                async def _c(variables):
                    return NodeResult(success=True, output={"verdict": "approve", "resolved": [1]})
                ex.execute = _c
            else:
                async def _w(variables):
                    return NodeResult(success=True, output={"draft": "新稿"})
                ex.execute = _w
            return ex

        with patch("app.engine.workflow.engine.get_node_executor", side_effect=_get), \
             patch("app.engine.workflow.engine.TaskService", new=_ts_mock()), \
             patch("app.db.mongodb.get_database", new=_db_mock()):
            await engine._execute_node("loop1")

        ws = engine._pool.get("loop1")["workspace"]
        # 恢复的 issue 被本轮 resolved；产物版本从恢复点续（旧稿 v1 → 新稿 v2）
        assert ws["issues"][0]["status"] == "resolved"
        assert ws["artifacts"]["写手"]["version"] == 2
        assert engine._pool.get("loop1")["iterations"] == 2  # 从第 2 轮起跑

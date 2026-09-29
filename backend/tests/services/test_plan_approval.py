"""计划批准链路测试 — PLAN.md 落盘 + 合成 tool_result + 探针推断。

批准 = 零 LLM 成本（approve 端点写文件 + dismiss 式合成结果，不 resume
不跑模型）；反馈链根治 = resume 前探针读 checkpoint 推断挂起类型。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.schemas.execution import ApprovePlanRequest

# ---------------------------------------------------------------------------
# AgentExecutionService.approve_plan
# ---------------------------------------------------------------------------


@pytest.fixture
def _ws_root(monkeypatch, tmp_path):
    """把 workspace 根指到临时目录（真实文件写入断言用）。"""
    from app.engine.tool.workspace import WorkspaceManager

    monkeypatch.setattr(WorkspaceManager, "_workspaces_root", staticmethod(lambda: tmp_path))
    return tmp_path


def _patch_agent_and_messages(monkeypatch, approved_return=True):
    from app.services.agent_execution_service import AgentExecutionService
    from app.services.session_service import MessageService

    agent_doc = {"_id": "agent_1", "name": "A"}
    monkeypatch.setattr(
        AgentExecutionService, "_get_agent_doc",
        AsyncMock(return_value=agent_doc), raising=False,
    )
    # get_agent 是模块内 import 的 AgentService.get_agent——patch 真实服务
    called: dict = {}

    async def fake_dismiss(session_id, *, result_text=None, tool_names=None):
        called["result_text"] = result_text
        called["tool_names"] = tool_names
        return approved_return

    monkeypatch.setattr(MessageService, "dismiss_pending_clarification", staticmethod(fake_dismiss))
    return called


async def test_approve_plan_writes_plan_md(monkeypatch, _ws_root):
    """批准：PLAN.md 写入 session workspace 根目录，内容为请求计划全文。"""
    from app.services.agent_execution_service import AgentExecutionService

    called = _patch_agent_and_messages(monkeypatch)
    with patch(
        "app.services.agent_service.AgentService.get_agent",
        new=AsyncMock(return_value={"_id": "agent_1"}),
    ):
        result = await AgentExecutionService.approve_plan(
            "agent_1",
            ApprovePlanRequest(session_id="sess_1", plan="# 目标\n修复测试"),
            "user_1",
        )
    assert result["approved"] is True
    plan_file = _ws_root / "user_1" / "sess_1" / "PLAN.md"
    assert plan_file.exists()
    assert plan_file.read_text(encoding="utf-8").startswith("# 目标")
    # 合成 tool_result：批准文案 + 只匹配 propose_plan
    assert called["result_text"].startswith("用户已批准")
    assert called["tool_names"] == ("propose_plan",)


async def test_approve_plan_rejects_empty(monkeypatch, _ws_root):
    """空计划拒绝（ValidationError）。"""
    from app.core.errors import ValidationError
    from app.services.agent_execution_service import AgentExecutionService

    with patch(
        "app.services.agent_service.AgentService.get_agent",
        new=AsyncMock(return_value={"_id": "agent_1"}),
    ), pytest.raises(ValidationError):
        await AgentExecutionService.approve_plan(
            "agent_1",
            ApprovePlanRequest(session_id="sess_1", plan="   "),
            "user_1",
        )


# ---------------------------------------------------------------------------
# MessageService.dismiss_pending_clarification 泛化参数
# ---------------------------------------------------------------------------


async def test_dismiss_custom_result_and_tools(monkeypatch):
    """result_text/tool_names 覆盖默认：批准走批准文案 + 收窄到 propose_plan。"""
    from app.services.session_service import MessageService

    col = MagicMock()
    col.find_one = AsyncMock(
        return_value={
            "_id": "m1",
            "timeline_entries": [
                {"type": "tool_call", "tool_name": "ask_clarification", "id": "c1"},
                {"type": "tool_call", "tool_name": "propose_plan", "id": "c2"},
            ],
        }
    )
    col.update_one = AsyncMock()
    mock_db = MagicMock()
    mock_db.__getitem__.side_effect = lambda key: col if key == "messages" else MagicMock()
    monkeypatch.setattr("app.services.session_service.get_database", lambda: mock_db)

    ok = await MessageService.dismiss_pending_clarification(
        "sess_1",
        result_text="用户已批准该计划。",
        tool_names=("propose_plan",),
    )
    assert ok is True
    pushed = col.update_one.call_args.args[1]["$push"]["timeline_entries"]
    assert pushed["tool_call_id"] == "c2"  # 命中 propose_plan（跳过 clarification）
    assert pushed["content"].startswith("用户已批准")


# ---------------------------------------------------------------------------
# 反馈链根治：探针推断
# ---------------------------------------------------------------------------


class _FakeIntr:
    def __init__(self, value):
        self.value = value


class _FakeTask:
    def __init__(self, interrupts):
        self.interrupts = interrupts


class _FakeSnap:
    def __init__(self, tasks):
        self.tasks = tasks


class _FakeGraph:
    def __init__(self, snap):
        self._snap = snap

    async def aget_state(self, config):
        return self._snap


async def test_peek_detects_pending_plan(monkeypatch):
    """挂起 propose_plan（type=plan）→ 探针返回 True；其他挂起 → False。"""
    import agent_flow_harness
    from app.engine.harness_integration.execution import _peek_has_pending_plan

    plan_snap = _FakeSnap([_FakeTask([_FakeIntr({"type": "plan", "plan": "# 目标"})])])
    monkeypatch.setattr(
        agent_flow_harness, "build_agent_graph",
        lambda *a, **k: _FakeGraph(plan_snap),
    )
    assert await _peek_has_pending_plan({}, "sess_1") is True

    clar_snap = _FakeSnap([_FakeTask([_FakeIntr({"question": "哪个方案？"})])])
    monkeypatch.setattr(
        agent_flow_harness, "build_agent_graph",
        lambda *a, **k: _FakeGraph(clar_snap),
    )
    assert await _peek_has_pending_plan({}, "sess_1") is False

    # 空会话/异常 → False（退回调用方上下文）
    monkeypatch.setattr(
        agent_flow_harness, "build_agent_graph",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    assert await _peek_has_pending_plan({}, "sess_1") is False
    assert await _peek_has_pending_plan({}, "") is False


# ---------------------------------------------------------------------------
# ② 双重确认抑制：授权清单写入 + confirm_workflow 白名单跳卡
# ---------------------------------------------------------------------------


async def test_approve_plan_records_authorized_workflows(monkeypatch, _ws_root):
    """批准：计划中点名的已绑定工作流记入 session 授权清单（名称+id）。"""
    from app.services.agent_execution_service import AgentExecutionService
    from app.services.workflow_registry_service import WorkflowRegistryService

    _patch_agent_and_messages(monkeypatch)
    plan = "# 目标：跑周报\n# 验收标准\n产出周报\n步骤含 派发工作流 周报生成"
    updates: dict = {}

    async def fake_get_by_workflow_id(wid):
        return {"name": "周报生成"} if wid == "wf_1" else {"name": "别的"}

    async def fake_update(session_id, fields):
        updates.update(fields)

    monkeypatch.setattr(
        WorkflowRegistryService, "get_by_workflow_id", staticmethod(fake_get_by_workflow_id)
    )
    from app.services.session_service import SessionService

    monkeypatch.setattr(SessionService, "update_session", staticmethod(fake_update))
    with patch(
        "app.services.agent_service.AgentService.get_agent",
        new=AsyncMock(return_value={"_id": "agent_1", "workflow_ids": ["wf_1", "wf_2"]}),
    ):
        await AgentExecutionService.approve_plan(
            "agent_1", ApprovePlanRequest(session_id="sess_1", plan=plan), "user_1",
        )
    # wf_1（周报生成，被计划点名）进清单；wf_2 未提及不进
    assert "周报生成" in updates.get("plan_authorized_workflows", [])
    assert "wf_1" in updates.get("plan_authorized_workflows", [])
    assert "别的" not in updates.get("plan_authorized_workflows", [])


async def test_confirm_workflow_skips_card_when_authorized(monkeypatch):
    """白名单内：跳过 interrupt 自动确认；清单外：正常走 interrupt 弹卡。"""
    from pathlib import Path

    import langgraph.types as lgt
    from app.engine.agent.builtin_tools import (
        reset_workspace_context,
        set_workspace_context,
    )
    from app.engine.agent.workflow_executor import confirm_workflow
    from app.engine.tool.workspace import Workspace
    from app.services.session_service import SessionService

    root = Path("/tmp/ws_test_plan_auth")
    ws = Workspace(root=root, input_dir=root / "input", output_dir=root / "output", tmp_dir=root / "tmp")
    monkeypatch.setattr(SessionService, "get_session", staticmethod(
        AsyncMock(return_value={"plan_authorized_workflows": ["周报生成"]})
    ))

    # 白名单内 → 不触发 interrupt，直接自动确认
    def must_not_interrupt(payload):
        raise AssertionError("白名单内不应弹确认卡")

    monkeypatch.setattr(lgt, "interrupt", must_not_interrupt)
    token = set_workspace_context(ws)
    try:
        result = await confirm_workflow.ainvoke(
            {"workflow_name": "周报生成", "description": "周报", "params": None}
        )
    finally:
        reset_workspace_context(token)
    assert "已自动确认" in result

    # 清单外 → 走 interrupt 正常弹卡
    monkeypatch.setattr(lgt, "interrupt", lambda payload: "用户确认")
    token = set_workspace_context(ws)
    try:
        result2 = await confirm_workflow.ainvoke(
            {"workflow_name": "未授权工作流", "description": "x", "params": None}
        )
    finally:
        reset_workspace_context(token)
    assert result2 == "用户确认"

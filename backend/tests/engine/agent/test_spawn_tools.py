"""spawn 工具测试 — 能力门控注入规则 + 创建治理（draft/不放大/审计）。"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True, scope="function")
def _platform_ws(tmp_path):
    """全文件自动 fixture：设平台用户 workspace（spawn 守卫需 _is_platform_user）。"""
    from app.engine.agent.builtin_tools import (
        reset_workspace_context,
        set_workspace_context,
    )
    from app.engine.tool.workspace import Workspace

    root = tmp_path / "user_plat" / "sess_spawn"
    root.mkdir(parents=True, exist_ok=True)
    ws = Workspace(root=root, input_dir=root / "input",
                   output_dir=root / "output", tmp_dir=root / "tmp")
    token = set_workspace_context(ws)
    yield ws
    reset_workspace_context(token)


def _tool_names(tools: list) -> set[str]:
    return {t.name for t in tools}


class TestSpawnInjection:
    """context 注入规则：门控 × 语境矩阵。"""

    def test_off_no_spawn_tools(self):
        from app.engine.harness_integration.context import _resolve_builtin_tools

        names = _tool_names(_resolve_builtin_tools({}, "chat"))
        assert "create_agent" not in names and "list_capabilities" not in names

    def test_on_chat_both(self):
        from app.engine.harness_integration.context import _resolve_builtin_tools

        agent = {"can_spawn_agents": True}
        names = _tool_names(_resolve_builtin_tools(agent, "chat"))
        assert {"create_agent", "list_capabilities"} <= names

    def test_on_plan_list_only(self):
        """plan 语境剥离 create_agent（变更操作）——实验对照的机制保证：
        plan 下只能走 计划→批准→执行期创建。"""
        from app.engine.harness_integration.context import _resolve_builtin_tools

        agent = {"can_spawn_agents": True}
        names = _tool_names(_resolve_builtin_tools(agent, "plan"))
        assert "list_capabilities" in names
        assert "create_agent" not in names

    def test_on_workflow_neither(self):
        """无人值守不繁殖。"""
        from app.engine.harness_integration.context import _resolve_builtin_tools

        agent = {"can_spawn_agents": True}
        names = _tool_names(_resolve_builtin_tools(agent, "workflow"))
        assert "create_agent" not in names and "list_capabilities" not in names


class TestCreateAgentTool:
    """创建治理：draft 态 / 权限不放大 / 审计标记。"""

    async def test_creates_draft_without_spawn_flag(self):
        from app.engine.agent.spawn_tools import create_agent_tool

        captured: dict = {}

        async def fake_create(**kwargs):
            captured.update(kwargs)
            return {"_id": "agent_new", "name": kwargs["name"]}

        with patch(
            "app.services.agent_service.AgentService.create_agent",
            new=AsyncMock(side_effect=fake_create),
        ):
            result = await create_agent_tool.ainvoke(
                {"name": "退款助手", "description": "处理退款", "system_prompt": "你是退款专家"}
            )
        assert "agent_new" in result and "draft" in result
        # 治理断言：草稿 + 不放大 + prompt 槽位
        assert captured["can_spawn_agents"] is False
        assert captured["spawned_by_agent_id"] == ""  # 无上下文时为空（经 contextvar）
        assert captured["prompt_slots"]["role"] == "你是退款专家"

    async def test_rejects_empty_fields(self):
        from app.engine.agent.spawn_tools import create_agent_tool

        result = await create_agent_tool.ainvoke(
            {"name": "x", "description": "", "system_prompt": "  "}
        )
        assert result.startswith("[create_agent]")

    async def test_service_error_feeds_back(self):
        from app.engine.agent.spawn_tools import create_agent_tool

        with patch(
            "app.services.agent_service.AgentService.create_agent",
            new=AsyncMock(side_effect=RuntimeError("名称冲突")),
        ):
            result = await create_agent_tool.ainvoke(
                {"name": "冲突", "description": "x", "system_prompt": "y"}
            )
        assert "创建失败" in result and "名称冲突" in result


async def test_list_capabilities_inventory(monkeypatch):
    """能力清单：tools 集合按 source 分拣 + 模型 + 参考 agent。"""
    from app.engine.agent.spawn_tools import list_capabilities

    class _Cur:
        def __init__(self, rows):
            self._rows = rows

        def limit(self, n):
            return self

        async def to_list(self, length=None):
            return self._rows

    def fake_getitem(key):
        col = MagicMock()
        if key == "tools":
            col.find = MagicMock(
                return_value=_Cur([
                    {"_id": "t1", "name": "查订单", "description": "查订单", "source": "openapi"},
                    {"_id": "t2", "name": "mcp_x", "description": "mcp 工具", "source": "mcp",
                     "mcp_connection_id": "mcp_c1"},
                    {"_id": "t3", "name": "写作技能", "description": "技能", "source": "markdown"},
                ])
            )
        elif key == "mcp_connections":

            class _ConnCur:
                def __init__(self, rows): self._rows = rows
                def __aiter__(self):
                    async def gen():
                        for r in self._rows:
                            yield r
                    return gen()

            col.find = MagicMock(
                return_value=_ConnCur([{"_id": "mcp_c1", "name": "合作系统"}])
            )
        elif key == "models":
            col.find = MagicMock(
                return_value=_Cur([{"_id": "m1", "name": "主力模型", "model_id": "gpt-x"}])
            )
        elif key == "agents":
            col.find = MagicMock(
                return_value=_Cur([{"_id": "a1", "name": "客服一号", "description": "客服"}])
            )
        return col

    db = MagicMock()
    db.__getitem__.side_effect = fake_getitem
    monkeypatch.setattr("app.db.mongodb.get_database", lambda: db)

    result = await list_capabilities.ainvoke({})
    assert "内置工具" in result
    assert "自定义工具" in result and "查订单" in result
    # MCP 节按连接分组（绑定粒度）+ 组内全量工具带描述
    assert "MCP 连接" in result and "合作系统" in result and "mcp_c1" in result
    assert "mcp_x" in result and "mcp 工具" in result and "绑定粒度=整连接" in result
    assert "技能" in result and "写作技能" in result
    assert "主力模型" in result
    assert "客服一号" in result


async def test_create_agent_normalizes_mcp_tool_id_to_connection(monkeypatch):
    """连接 id 归一：模型误填工具级 id → 映射回所属连接（去重）；未知 id 报错。"""
    from app.engine.agent.spawn_tools import create_agent_tool

    class _Cur:
        def __init__(self, rows): self._rows = rows
        def limit(self, n): return self
        async def to_list(self, length=None): return self._rows

    def fake_getitem(key):
        col = MagicMock()
        if key == "mcp_connections":
            col.find_one = AsyncMock(side_effect=lambda q, *a, **k: (
                {"_id": "mcp_c1"} if q.get("_id") == "mcp_c1" else None
            ))
            col.find = MagicMock(return_value=_Cur([{"_id": "mcp_c1", "name": "合作系统"}]))
        elif key == "tools":
            async def fake_find_one(q, *a, **k):
                if q.get("_id") == "tool_t2" and q.get("source") == "mcp":
                    return {"_id": "tool_t2", "mcp_connection_id": "mcp_c1"}
                return None
            col.find_one = AsyncMock(side_effect=fake_find_one)
        return col

    db = MagicMock()
    db.__getitem__.side_effect = fake_getitem
    captured: dict = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return {"_id": "agent_new", "name": kwargs["name"]}

    monkeypatch.setattr("app.db.mongodb.get_database", lambda: db)
    with patch(
        "app.services.agent_service.AgentService.create_agent",
        new=AsyncMock(side_effect=fake_create),
    ):
        # 工具 id（tool_t2）→ 归一为连接 mcp_c1
        result = await create_agent_tool.ainvoke({
            "name": "X", "description": "d", "system_prompt": "s",
            "mcp_connection_ids": ["tool_t2", "mcp_c1"],
        })
    assert "agent_new" in result
    assert captured["mcp_connection_ids"] == ["mcp_c1"]  # 去重+归一

    # 未知 id → 报错回灌可用连接清单
    with patch(
        "app.services.agent_service.AgentService.create_agent",
        new=AsyncMock(side_effect=fake_create),
    ):
        result2 = await create_agent_tool.ainvoke({
            "name": "X", "description": "d", "system_prompt": "s",
            "mcp_connection_ids": ["不存在"],
        })
    assert "不存在" in result2 and "合作系统" in result2 and "绑定粒度是整连接" in result2


class TestTestAgentTool:
    """验收测试工具：独立会话试跑 + 守卫（自身/不存在/归档）。"""

    async def test_invokes_child_and_returns_output(self):
        from pathlib import Path

        from app.engine.agent.builtin_tools import (
            set_workspace_context,
        )
        from app.engine.agent.spawn_tools import TEST_AGENT_TOOL
        from app.engine.tool.workspace import Workspace

        _root = Path("/tmp/ws_test/user_plat/sess_t")
        _ws = Workspace(root=_root, input_dir=_root / "input",
                        output_dir=_root / "output", tmp_dir=_root / "tmp")
        _ws_token = set_workspace_context(_ws)
        resp = MagicMock(output="退款已受理，单号 R123", session_id="sess_test", step_count=2)
        with patch(
            "app.services.agent_service.AgentService.get_agent",
            new=AsyncMock(return_value={"_id": "agent_child", "name": "子", "status": "draft"}),
        ), patch(
            "app.services.agent_execution_service.AgentExecutionService.invoke",
            new=AsyncMock(return_value=resp),
        ) as mock_invoke:
            result = await TEST_AGENT_TOOL.ainvoke(
                {"agent_id": "agent_child", "input": "我要退款"}
            )
        assert "退款已受理" in result and "sess_test" in result
        # 独立会话（不传 session_id → invoke 自动新建）+ 验收标记
        body = mock_invoke.call_args.args[1]
        assert body.display_text == "[验收测试]"
        assert body.input == "我要退款"

    async def test_guards(self, tmp_path):
        from app.engine.agent.builtin_tools import (
            reset_workspace_context,
            set_workspace_context,
        )
        from app.engine.agent.spawn_tools import (
            TEST_AGENT_TOOL,
            _is_platform_user,
            reset_spawn_agent_context,
            set_spawn_agent_context,
        )
        from app.engine.tool.workspace import Workspace

        _root = tmp_path / "u1" / "s1"
        _root.mkdir(parents=True, exist_ok=True)
        _ws = Workspace(root=_root, input_dir=_root / "input",
                        output_dir=_root / "output", tmp_dir=_root / "tmp")
        _ws_token = set_workspace_context(_ws)
        assert _is_platform_user(), "fixture 未生效"

        try:
            token = set_spawn_agent_context("agent_me")
            try:
                r = await TEST_AGENT_TOOL.ainvoke({"agent_id": "agent_me", "input": "x"})
                assert "不能测试自身" in r
            finally:
                reset_spawn_agent_context(token)

            with patch(
                "app.services.agent_service.AgentService.get_agent",
                new=AsyncMock(return_value=None),
            ):
                r2 = await TEST_AGENT_TOOL.ainvoke({"agent_id": "gone", "input": "x"})
                assert "不存在" in r2

            with patch(
                "app.services.agent_service.AgentService.get_agent",
                new=AsyncMock(return_value={"_id": "a", "name": "旧", "status": "archived"}),
            ):
                r3 = await TEST_AGENT_TOOL.ainvoke({"agent_id": "a", "input": "x"})
                assert "归档" in r3
        finally:
            reset_workspace_context(_ws_token)


async def test_channel_user_blocked():
    """渠道/外部用户 → spawn 三工具全部拒绝（能力隔离）。"""
    from pathlib import Path

    from app.engine.agent.builtin_tools import (
        reset_workspace_context,
        set_workspace_context,
    )
    from app.engine.agent.spawn_tools import (
        TEST_AGENT_TOOL,
        create_agent_tool,
    )
    from app.engine.tool.workspace import Workspace

    # 渠道用户 workspace：{user_id}/{session_id}/ 嵌套结构（user_id 从 parent 取）
    ch_root = Path("/tmp/ws_test/channel:ch_1:chat_1/sess_ch")
    ch_ws = Workspace(root=ch_root, input_dir=ch_root / "input",
                      output_dir=ch_root / "output", tmp_dir=ch_root / "tmp")
    ws_token = set_workspace_context(ch_ws)
    try:
        r = await create_agent_tool.ainvoke(
            {"name": "X", "description": "d", "system_prompt": "s"}
        )
        assert "仅平台用户" in r
        r2 = await TEST_AGENT_TOOL.ainvoke({"agent_id": "any", "input": "x"})
        assert "仅平台用户" in r2
    finally:
        reset_workspace_context(ws_token)

"""Tests for the fixed-slot system prompt renderer (no-template architecture).

The renderer reads prompt_slots directly from the agent document.
Two-layer priority: node overrides > agent prompt_slots.
tool_declaration is always auto-appended at the end.

Rendering rules (current):
- Each filled slot renders as "【<label>】\\n<value>".
- Required slots (role / task) missing → ValueError raised.
"""
from unittest.mock import AsyncMock, patch

import pytest


def _fake_agent(
    prompt_slots: dict | None = None,
) -> dict:
    return {
        "_id": "agent_01HTEST",
        "name": "Test Agent",
        "prompt_slots": prompt_slots or {},
        "skill_ids": [],
        "mcp_connection_ids": [],
        "builtin_config": [],
        "workflow_ids": [],
        "default_model": "gpt-4",
        "max_retry": 3,
    }


def _no_tools() -> object:
    """Patch helper that disables tool_declaration."""
    return patch(
        "app.engine.agent.builder.build_tool_declaration",
        new=AsyncMock(return_value=""),
    )


class TestEmptyPromptSlots:
    """When agent has no prompt_slots, required validation fires first."""

    @pytest.mark.asyncio
    async def test_empty_slots_raises_required(self):
        """role + task both missing → ValueError, before tool_declaration is queried."""
        from app.engine.agent.slot_renderer import render_system_prompt_full

        agent = _fake_agent()
        # Even with tool_declaration available, required check short-circuits.
        with patch(
            "app.engine.agent.builder.build_tool_declaration",
            new=AsyncMock(return_value="## Tools\n- bash"),
        ), pytest.raises(ValueError) as exc_info:
            await render_system_prompt_full(agent)

        msg = str(exc_info.value)
        assert "角色定义" in msg
        assert "任务描述" in msg

    @pytest.mark.asyncio
    async def test_empty_slots_no_tools_raises(self):
        from app.engine.agent.slot_renderer import render_system_prompt_full

        agent = _fake_agent()
        with _no_tools(), pytest.raises(ValueError):
            await render_system_prompt_full(agent)


class TestSlotPriority:
    """Two-layer priority: node > agent prompt_slots."""

    @pytest.mark.asyncio
    async def test_agent_slot_rendered(self):
        from app.engine.agent.slot_renderer import render_system_prompt_full

        # task 补齐以满足 required 校验，用例重点仍是验证 agent slot 被渲染
        agent = _fake_agent(prompt_slots={
            "role": "You are a pirate.",
            "task": "Answer the user.",
        })

        with _no_tools():
            result = await render_system_prompt_full(agent)
        assert "You are a pirate." in result
        assert "【角色定义】" in result

    @pytest.mark.asyncio
    async def test_node_override_highest_priority(self):
        from app.engine.agent.slot_renderer import render_system_prompt_full

        agent = _fake_agent(prompt_slots={
            "role": "You are a pirate.",
            "task": "Answer the user.",
        })

        with _no_tools():
            result = await render_system_prompt_full(
                agent,
                node_slot_overrides={"role": "You are a ninja."},
            )
        assert "You are a ninja." in result
        assert "You are a pirate." not in result


class TestFixedRenderOrder:
    """Slots render in fixed order with structured labels."""

    @pytest.mark.asyncio
    async def test_render_order_with_labels(self):
        from app.engine.agent.slot_renderer import render_system_prompt_full

        agent = _fake_agent(prompt_slots={
            "role": "ROLE_CONTENT",
            "task": "TASK_CONTENT",
            "constraints": "CONSTRAINTS_CONTENT",
            "context": "CONTEXT_CONTENT",
            "output_format": "OUTPUT_FORMAT_CONTENT",
        })

        with patch(
            "app.engine.agent.builder.build_tool_declaration",
            new=AsyncMock(return_value="TOOLS_CONTENT"),
        ):
            result = await render_system_prompt_full(agent)

        # Label prefixes appear in schema order
        assert result.index("【角色定义】") < result.index("【任务描述】")
        assert result.index("【任务描述】") < result.index("【约束规则】")
        assert result.index("【约束规则】") < result.index("【上下文信息】")
        assert result.index("【上下文信息】") < result.index("【输出格式】")
        # Tool declaration (no 【】 label) stays at the end
        assert result.index("【输出格式】") < result.index("TOOLS_CONTENT")
        # Values still rendered in order
        assert result.index("ROLE_CONTENT") < result.index("TASK_CONTENT")
        assert result.index("TASK_CONTENT") < result.index("CONSTRAINTS_CONTENT")
        assert result.index("CONSTRAINTS_CONTENT") < result.index("CONTEXT_CONTENT")
        assert result.index("CONTEXT_CONTENT") < result.index("OUTPUT_FORMAT_CONTENT")
        assert result.index("OUTPUT_FORMAT_CONTENT") < result.index("TOOLS_CONTENT")


class TestToolDeclaration:
    """tool_declaration is always auto-appended at the end."""

    @pytest.mark.asyncio
    async def test_tool_declaration_auto_appended(self):
        from app.engine.agent.slot_renderer import render_system_prompt_full

        agent = _fake_agent(prompt_slots={
            "role": "Helper.",
            "task": "Do things.",
        })

        with patch(
            "app.engine.agent.builder.build_tool_declaration",
            new=AsyncMock(return_value="## Tools\n- bash"),
        ):
            result = await render_system_prompt_full(agent)
        assert "Helper." in result
        assert "【角色定义】" in result
        assert "## Tools" in result
        assert result.index("Helper.") < result.index("## Tools")

    @pytest.mark.asyncio
    async def test_tool_declaration_empty_omitted(self):
        from app.engine.agent.slot_renderer import render_system_prompt_full

        agent = _fake_agent(prompt_slots={
            "role": "Helper.",
            "task": "Do things.",
        })

        with _no_tools():
            result = await render_system_prompt_full(agent)
        assert "Helper." in result
        assert "## Tools" not in result
        assert "【工具声明】" not in result


class TestEmptySlotsSkipped:
    """Optional empty slots are skipped; required slots must be present."""

    @pytest.mark.asyncio
    async def test_optional_empty_slots_not_in_output(self):
        from app.engine.agent.slot_renderer import render_system_prompt_full

        # role + task 必填都给值；constraints 等可选 slot 留空，应被跳过
        agent = _fake_agent(prompt_slots={
            "role": "Role here.",
            "task": "Task here.",
            # constraints / context / output_format 留空
        })

        with _no_tools():
            result = await render_system_prompt_full(agent)
        assert result == "【角色定义】\nRole here.\n\n【任务描述】\nTask here."
        # 被跳过的可选 slot 的 label 不应出现
        assert "【约束规则】" not in result
        assert "【上下文信息】" not in result


class TestRequiredValidation:
    """Required slots (role / task) missing → ValueError."""

    @pytest.mark.asyncio
    async def test_missing_role_raises(self):
        from app.engine.agent.slot_renderer import render_system_prompt_full

        # 只给 task，role 缺失
        agent = _fake_agent(prompt_slots={"task": "Do something."})

        with _no_tools(), pytest.raises(ValueError) as exc_info:
            await render_system_prompt_full(agent)

        assert "角色定义" in str(exc_info.value)
        # task 已给值，不应出现在缺失列表
        assert "任务描述" not in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_missing_task_raises(self):
        from app.engine.agent.slot_renderer import render_system_prompt_full

        # 只给 role，task 缺失
        agent = _fake_agent(prompt_slots={"role": "You are X."})

        with _no_tools(), pytest.raises(ValueError) as exc_info:
            await render_system_prompt_full(agent)

        assert "任务描述" in str(exc_info.value)
        assert "角色定义" not in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_missing_both_lists_all_labels(self):
        from app.engine.agent.slot_renderer import render_system_prompt_full

        agent = _fake_agent(prompt_slots={})

        with _no_tools(), pytest.raises(ValueError) as exc_info:
            await render_system_prompt_full(agent)

        msg = str(exc_info.value)
        # 两个必填 label 都应列出
        assert "角色定义" in msg
        assert "任务描述" in msg

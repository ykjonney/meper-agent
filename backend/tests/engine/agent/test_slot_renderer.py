"""Tests for the whole-prompt system prompt renderer.

The renderer reads ``system_prompt`` (整段自由文本) from the agent document.
旧五槽（prompt_slots）已废弃并迁移为整段。

Rendering order: system_prompt (Jinja2 resolve over the whole text) →
node override ``【key】`` 段（存量兼容）→ environment → tool_declaration
(always last).

strict 模式（默认）下空 system_prompt 抛 ValueError，且区分两种根因：
「未配置」vs「含变量引用但渲染后为空」。
"""
from unittest.mock import AsyncMock, patch

import pytest


def _fake_agent(system_prompt: str = "") -> dict:
    return {
        "_id": "agent_01HTEST",
        "name": "Test Agent",
        "system_prompt": system_prompt,
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


class TestEmptyPrompt:
    """strict 下空 system_prompt 报错；strict=False 静默跳过。"""

    @pytest.mark.asyncio
    async def test_empty_prompt_raises_configured(self):
        """system_prompt 未配置 → ValueError，即使 tool_declaration 可用。"""
        from app.engine.agent.slot_renderer import render_system_prompt_full

        agent = _fake_agent()
        with patch(
            "app.engine.agent.builder.build_tool_declaration",
            new=AsyncMock(return_value="## Tools\n- bash"),
        ), pytest.raises(ValueError) as exc_info:
            await render_system_prompt_full(agent)

        msg = str(exc_info.value)
        assert "system_prompt 未配置" in msg

    @pytest.mark.asyncio
    async def test_empty_prompt_no_tools_raises(self):
        from app.engine.agent.slot_renderer import render_system_prompt_full

        agent = _fake_agent()
        with _no_tools(), pytest.raises(ValueError):
            await render_system_prompt_full(agent)

    @pytest.mark.asyncio
    async def test_empty_prompt_not_strict_silent(self):
        """strict=False（preview 场景）：空 prompt 静默跳过不报错。"""
        from app.engine.agent.slot_renderer import render_system_prompt_full

        agent = _fake_agent()
        with _no_tools():
            result = await render_system_prompt_full(agent, strict=False)
        assert result == ""

    @pytest.mark.asyncio
    async def test_empty_prompt_with_overrides_no_raise(self):
        """空整段但有节点槽覆写 → 以覆写段成文，不报「未配置」。"""
        from app.engine.agent.slot_renderer import render_system_prompt_full

        agent = _fake_agent()
        with _no_tools():
            result = await render_system_prompt_full(
                agent, node_slot_overrides={"role": "You are a pirate."},
            )
        assert "【role】" in result
        assert "You are a pirate." in result


class TestWholePromptPassthrough:
    """整段直通：文本原样保留（含换行结构），不做任何槽位拼接。"""

    @pytest.mark.asyncio
    async def test_prompt_rendered_verbatim(self):
        from app.engine.agent.slot_renderer import render_system_prompt_full

        prompt = "# 角色\n你是退款专家。\n\n# 规则\n- 先核实订单"
        agent = _fake_agent(system_prompt=prompt)

        with _no_tools():
            result = await render_system_prompt_full(agent)
        assert prompt in result
        # 不应出现五槽时代的 label 拼接
        assert "【角色定义】" not in result

    @pytest.mark.asyncio
    async def test_whitespace_stripped(self):
        from app.engine.agent.slot_renderer import render_system_prompt_full

        agent = _fake_agent(system_prompt="  Hello.  \n")

        with _no_tools():
            result = await render_system_prompt_full(agent)
        assert result == "Hello."


class TestVariableResolution:
    """整段上的 Jinja2 {{var}} 解析——dict/空值场景的回归测试。"""

    @pytest.mark.asyncio
    async def test_prompt_referencing_dict_renders_as_json_text(self):
        """整段引用上游返回 dict 的变量 → 渲染为合法 JSON 文本。

        回归场景：上游 agent 节点返回 JSON（dict），下游整段写
        ``{{ upstream.response }}``。ExpressionEngine 对单一变量引用保留
        原类型返回 dict，此前 f-string 拼出 Python repr（单引号/True），
        现在应归一化为合法 JSON 文本。
        """
        from app.engine.agent.slot_renderer import render_system_prompt_full

        agent = _fake_agent(system_prompt="上游数据：{{ upstream.response }}")
        variables = {
            "upstream": {
                "response": {"success": True, "alarmRecordId": "10503041101"},
            },
        }

        with _no_tools():
            result = await render_system_prompt_full(agent, variable_pool=variables)

        # dict 应被渲染成合法 JSON 文本（双引号、true 小写），而非 Python repr
        assert '"success": true' in result
        assert '"alarmRecordId": "10503041101"' in result
        assert "'success'" not in result

    @pytest.mark.asyncio
    async def test_prompt_var_resolves_empty_reports_precise_cause(self):
        """整段全是变量引用且渲染为空 → 报错指出「渲染后为空」+ 原始模板。

        回归场景：``{{ upstream.missing_field }}`` 字段不存在渲染为空，
        应指向「上游变量可能不存在」而非笼统「未配置」。
        """
        from app.engine.agent.slot_renderer import render_system_prompt_full

        agent = _fake_agent(system_prompt="{{ upstream.missing_field }}")
        variables = {"upstream": {"response": "有数据但没 missing_field"}}

        with _no_tools(), pytest.raises(ValueError) as exc_info:
            await render_system_prompt_full(agent, variable_pool=variables)

        msg = str(exc_info.value)
        assert "渲染后为空" in msg
        assert "upstream.missing_field" in msg

    @pytest.mark.asyncio
    async def test_prompt_mixed_text_and_dict_var(self):
        """混合模板（前缀文字 + dict 变量）→ 文字 + JSON 文本拼接正常。"""
        from app.engine.agent.slot_renderer import render_system_prompt_full

        agent = _fake_agent(system_prompt="上游结果：{{ upstream.response }}")
        variables = {"upstream": {"response": {"branch": "HEAVY", "score": 8}}}

        with _no_tools():
            result = await render_system_prompt_full(agent, variable_pool=variables)

        assert "上游结果：" in result
        assert '"branch": "HEAVY"' in result

    @pytest.mark.asyncio
    async def test_prompt_var_none_does_not_crash(self):
        """引用的变量值为 None → 渲染为空走「渲染后为空」报错，不崩溃。"""
        from app.engine.agent.slot_renderer import render_system_prompt_full

        agent = _fake_agent(system_prompt="{{ upstream.response }}")
        variables = {"upstream": {"response": None}}

        with _no_tools(), pytest.raises(ValueError) as exc_info:
            await render_system_prompt_full(agent, variable_pool=variables)

        assert "渲染后为空" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_plain_prompt_untouched_by_pool(self):
        """无 {{ 的整段不受 variable_pool 影响，原文直出。"""
        from app.engine.agent.slot_renderer import render_system_prompt_full

        agent = _fake_agent(system_prompt="Plain prompt, no variables.")
        variables = {"upstream": {"response": "x"}}

        with _no_tools():
            result = await render_system_prompt_full(agent, variable_pool=variables)
        assert result == "Plain prompt, no variables."

    @pytest.mark.asyncio
    async def test_override_also_resolves_variables(self):
        """节点槽覆写值同样走 Jinja resolve + 类型归一化。"""
        from app.engine.agent.slot_renderer import render_system_prompt_full

        agent = _fake_agent(system_prompt="主提示词。")
        variables = {"upstream": {"cfg": {"k": 1}}}

        with _no_tools():
            result = await render_system_prompt_full(
                agent,
                node_slot_overrides={"extra": "{{ upstream.cfg }}"},
                variable_pool=variables,
            )
        assert '"k": 1' in result


class TestNodeOverrides:
    """节点槽覆写以【key】段追加在整段之后（存量兼容，追加不替换）。"""

    @pytest.mark.asyncio
    async def test_override_appended_after_prompt(self):
        from app.engine.agent.slot_renderer import render_system_prompt_full

        agent = _fake_agent(system_prompt="Base prompt.")
        with _no_tools():
            result = await render_system_prompt_full(
                agent, node_slot_overrides={"role": "You are a ninja."},
            )
        assert "Base prompt." in result
        assert "【role】\nYou are a ninja." in result
        # 追加语义：整段在前，覆写段在后
        assert result.index("Base prompt.") < result.index("【role】")

    @pytest.mark.asyncio
    async def test_empty_override_value_skipped(self):
        """覆写值为空串的 key 不产生空【】段。"""
        from app.engine.agent.slot_renderer import render_system_prompt_full

        agent = _fake_agent(system_prompt="Base.")
        with _no_tools():
            result = await render_system_prompt_full(
                agent, node_slot_overrides={"empty": "", "kept": "v"},
            )
        assert "【empty】" not in result
        assert "【kept】" in result


class TestRenderOrder:
    """整段 → environment → tool_declaration 固定顺序。"""

    @pytest.mark.asyncio
    async def test_environment_between_prompt_and_tools(self):
        from app.engine.agent.slot_renderer import render_system_prompt_full

        agent = _fake_agent(system_prompt="PROMPT_CONTENT")
        with patch(
            "app.engine.agent.builder.build_tool_declaration",
            new=AsyncMock(return_value="TOOLS_CONTENT"),
        ):
            result = await render_system_prompt_full(agent, environment="ws layout")
        assert result.index("PROMPT_CONTENT") < result.index("## Environment")
        assert result.index("## Environment") < result.index("TOOLS_CONTENT")


class TestToolDeclaration:
    """tool_declaration is always auto-appended at the end."""

    @pytest.mark.asyncio
    async def test_tool_declaration_auto_appended(self):
        from app.engine.agent.slot_renderer import render_system_prompt_full

        agent = _fake_agent(system_prompt="Helper.")
        with patch(
            "app.engine.agent.builder.build_tool_declaration",
            new=AsyncMock(return_value="## Tools\n- bash"),
        ):
            result = await render_system_prompt_full(agent)
        assert "Helper." in result
        assert "## Tools" in result
        assert result.index("Helper.") < result.index("## Tools")

    @pytest.mark.asyncio
    async def test_tool_declaration_empty_omitted(self):
        from app.engine.agent.slot_renderer import render_system_prompt_full

        agent = _fake_agent(system_prompt="Helper.")
        with _no_tools():
            result = await render_system_prompt_full(agent)
        assert "Helper." in result
        assert "## Tools" not in result

    @pytest.mark.asyncio
    async def test_execution_context_forwarded(self):
        """execution_context 透传给 build_tool_declaration（workflow 无人值守语义）。"""
        from app.engine.agent.slot_renderer import render_system_prompt_full

        agent = _fake_agent(system_prompt="P.")
        mock_decl = AsyncMock(return_value="")
        with patch(
            "app.engine.agent.builder.build_tool_declaration", new=mock_decl,
        ):
            await render_system_prompt_full(agent, execution_context="workflow")
        assert mock_decl.call_args.kwargs.get("execution_context") == "workflow"

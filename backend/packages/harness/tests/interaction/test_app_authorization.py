"""request_app_authorization 工具 + ask_clarification 防冲突 veto 测试。

不跑 LangGraph runtime（interrupt 挂起语义由既有 ask_clarification 机制
保证），聚焦：
- 工具注册（name/args schema/coroutine）——保证 BUILTIN_TOOLS 可解析
- authorization_guard_veto 的 state 消息扫描逻辑（拦截 / 放行 / 失效标记）
"""
from __future__ import annotations

from langchain_core.messages import ToolMessage

from agent_flow_harness.interaction.app_authorization import (
    UNBOUND_MARKER_KEY,
    authorization_guard_veto,
    request_app_authorization,
)


def _tool_message(name: str, content: str) -> ToolMessage:
    return ToolMessage(content=content, name=name, tool_call_id=f"call_{name}")


MARKER_TEXT = (
    '{"mcp_credential_error": "UNBOUND", "app_id": "app_1", "app_name": "合作系统"}\n'
    "用户尚未授权应用「合作系统」，无法调用服务 partner。"
)


class TestToolRegistration:
    def test_tool_shape(self):
        """工具以 request_app_authorization 注册，args 含 app_id/app_name/reason。"""
        assert request_app_authorization.name == "request_app_authorization"
        schema = request_app_authorization.args_schema.model_json_schema()
        props = schema.get("properties", {})
        assert "app_id" in props
        assert "app_name" in props
        assert "reason" in props
        required = set(schema.get("required", []))
        assert {"app_id", "app_name"} <= required

    def test_tool_in_builtin_registry(self):
        from agent_flow_harness.tools.builtin import BUILTIN_TOOLS

        assert "request_app_authorization" in BUILTIN_TOOLS


class TestAuthorizationGuardVeto:
    def test_no_marker_no_veto(self):
        """无未授权标记 → ask_clarification 正常放行。"""
        state = {"messages": [_tool_message("mcp__partner__query", "ok")]}
        assert authorization_guard_veto("ask_clarification", state) is None

    def test_marker_blocks_clarification(self):
        """近期 tool 结果含 UNBOUND 标记 → 拦下 ask_clarification 并给纠正文案。"""
        state = {"messages": [_tool_message("mcp__partner__query", MARKER_TEXT)]}
        veto = authorization_guard_veto("ask_clarification", state)
        assert veto is not None
        # 断言引导语义；刻意不断言含标记字面量（那是自我延续的病灶，
        # 见 test_veto_message_omits_marker_literal）。
        assert "request_app_authorization" in veto

    def test_other_tools_not_blocked(self):
        """veto 只作用于 ask_clarification，其他工具不受影响。"""
        state = {"messages": [_tool_message("mcp__partner__query", MARKER_TEXT)]}
        assert authorization_guard_veto("bash", state) is None
        assert authorization_guard_veto("request_app_authorization", state) is None

    def test_marker_stale_after_authorization_request(self):
        """request_app_authorization 已被调用（其结果在标记之后）→ 标记失效，放行。"""
        state = {
            "messages": [
                _tool_message("mcp__partner__query", MARKER_TEXT),
                _tool_message("request_app_authorization", "授权已完成"),
            ]
        }
        assert authorization_guard_veto("ask_clarification", state) is None

    def test_new_marker_after_authorization_request_still_blocks(self):
        """授权后又遇到新的未授权错误 → 再次拦截（多个应用按需授权场景）。"""
        state = {
            "messages": [
                _tool_message("mcp__partner__query", MARKER_TEXT),
                _tool_message("request_app_authorization", "授权已完成"),
                _tool_message(
                    "mcp__other__fetch",
                    '{"mcp_credential_error": "UNBOUND", "app_id": "app_2", '
                    '"app_name": "另一系统"}\n用户尚未授权应用「另一系统」。',
                ),
            ]
        }
        assert authorization_guard_veto("ask_clarification", state) is not None

    def test_empty_state_no_veto(self):
        assert authorization_guard_veto("ask_clarification", {"messages": []}) is None
        assert authorization_guard_veto("ask_clarification", None) is None

    def test_object_state_supported(self):
        """AgentState 对象形态（非 dict）也能取 messages。"""

        class _State:
            messages = [_tool_message("mcp__partner__query", MARKER_TEXT)]

        assert authorization_guard_veto("ask_clarification", _State()) is not None

    def test_stale_marker_from_previous_turn_passes(self):
        """回归（幽灵拦截 bug）：标记属历史轮次（其后有新的用户消息）
        → 过期放行——早期某轮未消化的 UNBOUND 不得永久污染会话。"""
        from langchain_core.messages import HumanMessage

        state = {
            "messages": [
                _tool_message("mcp__partner__query", MARKER_TEXT),
                HumanMessage(content="帮我处理退款"),  # 新话题开启
            ]
        }
        assert authorization_guard_veto("ask_clarification", state) is None

    def test_current_turn_marker_still_blocks(self):
        """标记在最近一条用户消息之后（本轮内）→ 照常拦截。"""
        from langchain_core.messages import HumanMessage

        state = {
            "messages": [
                HumanMessage(content="查一下合作系统的订单"),
                _tool_message("mcp__partner__query", MARKER_TEXT),
            ]
        }
        veto = authorization_guard_veto("ask_clarification", state)
        assert veto is not None
        assert "request_app_authorization" in veto

    def test_authorization_digest_within_current_turn(self):
        """本轮内：标记 → 授权请求完成 → 追问放行（边界1 优先于边界2）。"""
        from langchain_core.messages import HumanMessage

        state = {
            "messages": [
                HumanMessage(content="查订单"),
                _tool_message("mcp__partner__query", MARKER_TEXT),
                _tool_message("request_app_authorization", "授权完成"),
            ]
        }
        assert authorization_guard_veto("ask_clarification", state) is None

    def test_veto_does_not_self_perpetuate(self):
        """回归（自我延续 bug）：state 里只有上一次 veto 的结果（ask_clarification
        同名消息、文案含标记字面量）而无任何真实 MCP 错误 → 放行。
        证据链：UNBOUND_MARKER_KEY 为子串匹配，旧 veto 文案自带该字面量，
        第一次拦截的结果回灌 state 后会永久喂饱后续所有追问。"""
        previous_veto_result = _tool_message(
            "ask_clarification",
            "检测到有待授权的应用（工具返回了 mcp_credential_error 标记）。"
            "请改用 request_app_authorization 工具…",
        )
        state = {"messages": [previous_veto_result]}
        assert authorization_guard_veto("ask_clarification", state) is None

    def test_veto_message_omits_marker_literal(self):
        """双保险：veto 文案本身不得含 UNBOUND_MARKER_KEY 字面量。"""
        from agent_flow_harness.interaction.app_authorization import _VETO_MESSAGE

        assert UNBOUND_MARKER_KEY not in _VETO_MESSAGE

    def test_documentation_text_does_not_trigger_veto(self):
        """回归（取证定案）：清单类工具搬运的工具描述文档含
        "mcp_credential_error" 字面量（如 request_app_authorization 的
        description），不是 JSON 错误形态 → 不得误触发授权引导 veto。"""
        # 取证到的真实文本片段（session_01M3KATV 的 list_capabilities 结果）
        doc_text = (
            "- request_app_authorization（始终启用）：当工具调用返回凭证错误时"
            "调用：错误文本首行含 mcp_credential_error JSON 标记"
            '（"UNBOUND"=用户尚未授权该应用；"INVALID"=已授权但凭证失效）'
        )
        state = {"messages": [_tool_message("list_capabilities", doc_text)]}
        assert authorization_guard_veto("ask_clarification", state) is None

    def test_unavailable_forbidden_markers_do_not_veto(self):
        """UNAVAILABLE/FORBIDDEN 的标记不触发——与前端 marker 过滤语义
        对齐（loader 注释明说这两类不渲染授权卡、不该引导授权）。"""
        for reason in ("UNAVAILABLE", "FORBIDDEN"):
            content = (
                '{"mcp_credential_error": "%s", "app_id": "app_1", '
                '"app_name": "X"}\\n服务暂不可用。' % reason
            )
            state = {"messages": [_tool_message("mcp__x__y", content)]}
            assert authorization_guard_veto("ask_clarification", state) is None, reason

    def test_structured_marker_json_still_triggers(self):
        """真实错误的 JSON 形态（UNBOUND/INVALID）照常触发。"""
        for reason in ("UNBOUND", "INVALID"):
            content = (
                '{"mcp_credential_error": "%s", "app_id": "app_1", '
                '"app_name": "合作系统"}\\n用户尚未授权应用。' % reason
            )
            state = {"messages": [_tool_message("mcp__partner__query", content)]}
            veto = authorization_guard_veto("ask_clarification", state)
            assert veto is not None and "request_app_authorization" in veto, reason

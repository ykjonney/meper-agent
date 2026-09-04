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
        assert UNBOUND_MARKER_KEY in veto
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

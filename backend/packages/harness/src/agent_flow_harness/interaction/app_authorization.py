"""request_app_authorization 工具 — 运行时按需授权的 HITL 中断。

与 ask_clarification 同机制（直调 langgraph interrupt() 挂起 graph），
但语义专用：MCP 工具返回「用户尚未授权应用」错误（错误文本首行带
``mcp_credential_error`` JSON 标记）后，LLM 调用本工具请求用户完成
对应应用的授权。宿主收到 interrupt 事件后在前端渲染授权表单卡片；
用户提交凭证（由前端经绑定 API 完成，凭证不进对话）或忽略后
resume，resume 值作为本工具返回值交给 LLM 继续推理（重试工具或
优雅降级）。

设计约束（LangGraph interrupt 契约）：
- 节点在 resume 时确定性重放——payload 必须完全由工具参数驱动
  （LLM 从 MCP 错误标记里读 app_id/app_name 传入），**不读**任何
  ContextVar / 外部可变态。
- 工具参数允许 LLM 填写任意 app_id：真正约束在宿主侧（前端卡片
  只提交到绑定 API，账密须经应用 login_url 验证 + sub 抢注保护）。

ask_clarification 防冲突（authorization_guard_veto）：本轮消息里存在
未消化的 UNBOUND 标记时，ask_clarification 被 tool_wrapper 拦下并
返回纠正性结果——防止 LLM 把用户引向"在对话里发凭证"的错路。
"""
from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

# 未授权错误标记的识别子串（与 mcp/loader.py 的错误文本约定一致）
UNBOUND_MARKER_KEY = "mcp_credential_error"


class _RequestAuthorizationArgs(BaseModel):
    """request_app_authorization 的 LLM 可见参数。"""

    app_id: str = Field(..., description="待授权应用 id（取自错误标记 JSON 的 app_id）")
    app_name: str = Field(..., description="待授权应用名（取自错误标记 JSON 的 app_name）")
    reason: str = Field(
        default="",
        description="为什么需要该应用授权（给用户看的简短说明，如任务需要查询其中的数据）",
    )


async def _request_app_authorization(app_id: str, app_name: str, reason: str = "") -> str:
    """请求用户完成某应用的授权。执行会中断，等待用户处理后继续。

    interrupt 挂起 graph；宿主 resume 时传入的值（处理结果说明）作为
    本函数返回值，交给 LLM 继续推理——通常应重试刚才失败的工具。
    """
    from langgraph.types import interrupt

    payload = {
        "type": "app_authorization",
        "app_id": app_id,
        "app_name": app_name,
        "reason": reason,
    }
    answer = interrupt(payload)
    return answer if isinstance(answer, str) else str(answer)


request_app_authorization = StructuredTool.from_function(
    _request_app_authorization,
    name="request_app_authorization",
    description=(
        "当工具调用返回凭证错误时调用：错误文本首行含 mcp_credential_error "
        "JSON 标记（\"UNBOUND\"=用户尚未授权该应用；\"INVALID\"=已授权但"
        "凭证失效，通常因用户修改了外部系统的密码或用户名）。app_id/"
        "app_name 从错误标记 JSON 中照抄。调用后执行会中断，用户在表单中"
        "完成授权或更新凭证后继续。禁止绕过本工具直接向用户索要任何应用"
        "的账号或密码。"
    ),
    args_schema=_RequestAuthorizationArgs,
    coroutine=_request_app_authorization,
)


def authorization_guard_veto(tool_name: str, state: Any) -> str | None:
    """ask_clarification 防冲突 veto：存在未消化的授权错误时拦截追问。

    扫描 state["messages"]：最近一次 request_app_authorization 的工具
    结果之后的 ToolMessage 里若仍有 UNBOUND 标记，说明本轮还有待授权
    应用未处理——此时 ask_clarification（LLM 本能的追问通道）会被
    拦下，返回纠正性文案引导改用 request_app_authorization。

    Returns:
        纠正性文案（拦截）或 None（放行）。
    """
    if tool_name != "ask_clarification":
        return None

    messages = _get_state_messages(state)
    for msg in reversed(messages):
        name = getattr(msg, "name", "") or ""
        if name == "request_app_authorization":
            # 最近一次授权请求之后无新标记 → 已消化，放行
            return None
        if name and getattr(msg, "type", "") == "tool":
            content = _message_text(msg)
            if UNBOUND_MARKER_KEY in content:
                return (
                    "检测到有待授权的应用（工具返回了 mcp_credential_error "
                    "标记）。请改用 request_app_authorization 工具请求用户"
                    "完成授权；禁止通过对话向用户索要任何应用的账号或密码。"
                )
    return None


def _get_state_messages(state: Any) -> list[Any]:
    """兼容 dict / AgentState 两种形态取 messages。"""
    if state is None:
        return []
    if isinstance(state, dict):
        return list(state.get("messages") or [])
    return list(getattr(state, "messages", None) or [])


def _message_text(msg: Any) -> str:
    """取消息的文本内容（content 为 str 或 block 列表两种形态）。"""
    content = getattr(msg, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                parts.append(str(block.get("text", "")))
        return "\n".join(parts)
    return str(content)


__all__ = [
    "request_app_authorization",
    "authorization_guard_veto",
    "UNBOUND_MARKER_KEY",
]

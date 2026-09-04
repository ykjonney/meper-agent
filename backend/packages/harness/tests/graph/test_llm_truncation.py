"""输出截断（finish_reason=length / max_tokens）检测与反馈重试测试。

回归「思考/正文被 max_tokens 截断 → tools_condition 路由 END → 对话静默
死亡」：llm_node 必须为这条死路补上反馈通道（invalid 调用合成错误
ToolMessage + 注入反馈后原地重调一次）；invalid_tool_calls 未配对时下一轮
请求必被 provider 400 拒绝，由 ensure_tool_pairing 兜底剥离。
"""

from __future__ import annotations

import pytest
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from agent_flow_harness.context_engineering.pairing import ensure_tool_pairing
from agent_flow_harness.graph.nodes.llm_nodes import llm_node


class _ScriptedLLM:
    """按脚本顺序返回 AIMessage，并记录每次 ainvoke 收到的消息列表。"""

    def __init__(self, responses: list[AIMessage]) -> None:
        self._responses = list(responses)
        self.calls: list[list] = []

    @property
    def model_name(self) -> str:
        return "test-model"

    def bind_tools(self, _tools):  # noqa: ANN001, ANN202
        return self

    async def ainvoke(self, messages, _config=None):  # noqa: ANN001
        self.calls.append(list(messages))
        if not self._responses:
            msg = "ScriptedLLM exhausted: no more responses."
            raise RuntimeError(msg)
        return self._responses.pop(0)


def _config(llm) -> dict:
    return {"configurable": {"llm": llm}}


def _truncated(reason: str = "length") -> AIMessage:
    """一条被 max_tokens 截断、无任何有效产出的 AIMessage（典型思考截断）。"""
    return AIMessage(content="", response_metadata={"finish_reason": reason})


# ---------------------------------------------------------------------------
# llm_node — 截断检测 + 反馈重试
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_truncated_empty_output_retries_with_feedback(base_state) -> None:
    """思考/正文截断（content 空、无 tool_calls）→ 注入反馈重调一次。"""
    first = _truncated()
    retry = AIMessage(content="完整回答")
    llm = _ScriptedLLM([first, retry])
    base_state["messages"] = [HumanMessage(content="写一份长报告")]

    patch = await llm_node(base_state, _config(llm))

    # 恰好两次 LLM 调用（上限 1 次重试）。
    assert len(llm.calls) == 2
    # 第二次调用以反馈消息收尾；空内容的截断响应有意不进重试上下文
    # （空 content 的 AIMessage 会被部分 provider 400 拒绝）。
    retry_ctx = llm.calls[1]
    assert isinstance(retry_ctx[-1], HumanMessage)
    assert "截断" in retry_ctx[-1].content
    assert first not in retry_ctx
    # patch 消息序列：[截断响应, 反馈, 重试响应]。
    messages = patch["messages"]
    assert messages == [first, retry_ctx[-1], retry]
    # step_count 只按图节点计一次。
    assert patch["step_count"] == 1


@pytest.mark.asyncio
async def test_anthropic_stop_reason_max_tokens_detected(base_state) -> None:
    """Anthropic 的 stop_reason=max_tokens 同样触发重试。"""
    first = AIMessage(content="", response_metadata={"stop_reason": "max_tokens"})
    llm = _ScriptedLLM([first, AIMessage(content="ok")])
    base_state["messages"] = [HumanMessage(content="hi")]

    patch = await llm_node(base_state, _config(llm))

    assert len(llm.calls) == 2
    assert patch["messages"][-1].content == "ok"


@pytest.mark.asyncio
async def test_truncated_with_valid_tool_calls_passes_through(base_state) -> None:
    """截断但带有效 tool_calls → 放行执行（ToolMessage 反馈通道已存在），不重试。"""
    response = AIMessage(
        content="",
        tool_calls=[{"name": "write", "args": {"path": "a.md"}, "id": "call_v"}],
        response_metadata={"finish_reason": "length"},
    )
    llm = _ScriptedLLM([response])
    base_state["messages"] = [HumanMessage(content="写文件")]

    patch = await llm_node(base_state, _config(llm))

    assert len(llm.calls) == 1
    assert patch["messages"] == [response]


@pytest.mark.asyncio
async def test_invalid_tool_calls_get_toolmessage_and_retry(base_state) -> None:
    """参数截断落进 invalid_tool_calls → 合成错误 ToolMessage（补配对）+ 重试。"""
    first = AIMessage(
        content="",
        invalid_tool_calls=[
            {
                "name": "write",
                "args": '{"path": "a.md", "content": "半截',
                "id": "call_bad",
                "error": "Expecting delimiter",
            }
        ],
        response_metadata={"finish_reason": "length"},
    )
    retry = AIMessage(content="已重写")
    llm = _ScriptedLLM([first, retry])
    base_state["messages"] = [HumanMessage(content="写文件")]

    patch = await llm_node(base_state, _config(llm))

    assert len(llm.calls) == 2
    messages = patch["messages"]
    # 序列：[截断响应, 错误 ToolMessage, 反馈 HumanMessage, 重试响应]。
    tool_msg = messages[1]
    assert isinstance(tool_msg, ToolMessage)
    assert tool_msg.tool_call_id == "call_bad"
    assert isinstance(messages[2], HumanMessage)
    assert messages[3] is retry
    # 重试上下文里 ToolMessage 紧跟在截断响应之后（配对完整，请求合法）。
    retry_ctx = llm.calls[1]
    assert retry_ctx[-3] is first
    assert retry_ctx[-2] is tool_msg


@pytest.mark.asyncio
async def test_retry_still_truncated_returns_as_is(base_state) -> None:
    """重试后仍截断 → 原样返回，不再无限重试。"""
    first = _truncated()
    second = _truncated()
    llm = _ScriptedLLM([first, second])
    base_state["messages"] = [HumanMessage(content="hi")]

    patch = await llm_node(base_state, _config(llm))

    assert len(llm.calls) == 2
    assert patch["messages"][-1] is second


@pytest.mark.asyncio
async def test_normal_response_no_retry(base_state) -> None:
    """正常响应零改动：单次调用，patch 只含响应本身。"""
    response = AIMessage(content="正常回答")
    llm = _ScriptedLLM([response])
    base_state["messages"] = [HumanMessage(content="hi")]

    patch = await llm_node(base_state, _config(llm))

    assert len(llm.calls) == 1
    assert patch["messages"] == [response]
    assert patch["step_count"] == 1


# ---------------------------------------------------------------------------
# ensure_tool_pairing — invalid_tool_calls 配对兜底（防下轮 400）
# ---------------------------------------------------------------------------


def test_pairing_drops_unpaired_invalid_only_message() -> None:
    """只含未配对 invalid 调用、无正文的 AIMessage → 整条丢弃。"""
    msgs: list = [
        SystemMessage(content="sys"),
        HumanMessage(content="写文件"),
        AIMessage(
            content="",
            invalid_tool_calls=[
                {
                    "name": "write",
                    "args": '{"path": "a',
                    "id": "call_bad",
                    "error": "truncated",
                }
            ],
        ),
    ]
    out = ensure_tool_pairing(msgs)
    assert len(out) == 2
    assert not any(isinstance(m, AIMessage) for m in out)


def test_pairing_keeps_paired_invalid_with_toolmessage() -> None:
    """invalid 调用已有配对 ToolMessage（llm_node 合成的错误结果）→ 保留配对。"""
    msgs: list = [
        HumanMessage(content="写文件"),
        AIMessage(
            content="",
            invalid_tool_calls=[
                {
                    "name": "write",
                    "args": '{"path": "a',
                    "id": "call_bad",
                    "error": "truncated",
                }
            ],
        ),
        ToolMessage(content="Error: 截断", tool_call_id="call_bad"),
    ]
    out = ensure_tool_pairing(msgs)
    assert len(out) == 3
    ai = next(m for m in out if isinstance(m, AIMessage))
    assert len(ai.invalid_tool_calls) == 1


def test_pairing_strips_unpaired_invalid_keeps_content() -> None:
    """未配对 invalid + 有正文 → 保留正文，剥离 invalid 调用。"""
    msgs: list = [
        HumanMessage(content="hi"),
        AIMessage(
            content="部分回答",
            invalid_tool_calls=[
                {
                    "name": "write",
                    "args": '{"path": "a',
                    "id": "call_bad",
                    "error": "truncated",
                }
            ],
        ),
    ]
    out = ensure_tool_pairing(msgs)
    assert len(out) == 2
    ai = out[1]
    assert ai.content == "部分回答"
    assert ai.tool_calls == []
    assert ai.invalid_tool_calls == []


def test_pairing_valid_tool_calls_unchanged() -> None:
    """回归：有效 tool_call 的既有语义不变（全配对原样保留，孤儿照旧剥离）。"""
    paired = AIMessage(
        content="",
        tool_calls=[{"name": "write", "args": {"path": "a"}, "id": "call_ok"}],
    )
    orphan = AIMessage(
        content="",
        tool_calls=[{"name": "write", "args": {"path": "b"}, "id": "call_orphan"}],
    )
    msgs: list = [
        HumanMessage(content="hi"),
        paired,
        ToolMessage(content="ok", tool_call_id="call_ok"),
        orphan,
        ToolMessage(content="orphan-result", tool_call_id="call_orphan_x"),
    ]
    out = ensure_tool_pairing(msgs)
    # 孤儿 call 所在 AIMessage 无正文 → 丢弃；不匹配 id 的 ToolMessage → 丢弃。
    assert paired in out
    assert orphan not in out
    assert not any(isinstance(m, ToolMessage) and m.tool_call_id == "call_orphan_x" for m in out)


def test_pairing_mixed_valid_and_invalid() -> None:
    """有效调用全配对 + 未配对 invalid → 重建只留有效调用。"""
    msgs: list = [
        HumanMessage(content="hi"),
        AIMessage(
            content="",
            tool_calls=[{"name": "read", "args": {"path": "a"}, "id": "call_v"}],
            invalid_tool_calls=[
                {
                    "name": "write",
                    "args": '{"path": "a',
                    "id": "call_bad",
                    "error": "truncated",
                }
            ],
        ),
        ToolMessage(content="file body", tool_call_id="call_v"),
    ]
    out = ensure_tool_pairing(msgs)
    ai = next(m for m in out if isinstance(m, AIMessage))
    assert len(ai.tool_calls) == 1
    assert ai.tool_calls[0]["id"] == "call_v"
    assert ai.invalid_tool_calls == []

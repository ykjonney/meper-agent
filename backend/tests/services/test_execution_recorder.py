"""ExecutionRecorder / RecorderMiddleware 测试 — 过程事件、cap 策略、钩子采集。

ExecutionRecorder 是 execution_log.events 的事实源：request 边界/工具元数据/
压缩/中断/错误全部经它产出,finalize 施加 cap（保首尾丢中段 + 自声明）。
"""
from __future__ import annotations

from app.engine.harness_integration.recorder_middleware import RecorderMiddleware
from app.services.execution_recorder import (
    CAP_EVENTS,
    PREVIEW_CHARS,
    ExecutionRecorder,
)


def _event_types(events: list[dict]) -> list[str]:
    return [e["e"] for e in events]


# ---------------------------------------------------------------------------
# 事件序列与语义
# ---------------------------------------------------------------------------


def test_event_sequence_and_request_numbering() -> None:
    """装配 → 请求边界 → 工具 → 收尾,顺序与编号正确,t 单调不减。"""
    rec = ExecutionRecorder()
    rec.tools_resolved("chat", "claude-x", ["bash", "read"], [])
    rec.request_begin()
    rec.request_end(in_tok=100, out_tok=20)
    rec.tool_call("call_1", "bash", {"cmd": "ls"})
    rec.tool_result("call_1", "bash", "file_a\nfile_b")
    rec.request_begin()
    rec.request_end(in_tok=50, out_tok=10)
    rec.compaction("tool_output", id="call_1", before=8210)
    rec.interrupt("clarification")
    rec.error("llm", "rate limited", code="")

    events = rec.finalize()
    assert _event_types(events) == [
        "tools_resolved", "request_begin", "request_end",
        "tool_call", "tool_result",
        "request_begin", "request_end",
        "compaction", "interrupt", "error",
    ]
    # request 编号递增,token 记在 request_end 上
    reqs = [e for e in events if e["e"] == "request_end"]
    assert [r["i"] for r in reqs] == [1, 2]
    assert reqs[0]["in_tok"] == 100 and reqs[0]["out_tok"] == 20
    # t 单调不减
    ts = [e["t"] for e in events]
    assert ts == sorted(ts)
    # tools_resolved 带装配上下文
    tr = events[0]
    assert tr["ctx"] == "chat" and tr["model"] == "claude-x"
    assert tr["tools"] == ["bash", "read"]


def test_tool_event_metadata() -> None:
    """tool_call 只留参数预览;tool_result 记 dur/ok/size,不记正文。"""
    rec = ExecutionRecorder()
    long_args = {"cmd": "x" * 500}
    rec.tool_call("call_1", "bash", long_args)
    rec.tool_result("call_1", "bash", "A" * 4210)

    events = rec.finalize()
    tc, tr = events
    assert tc["id"] == "call_1" and tc["n"] == "bash"
    assert len(tc["args"]) <= PREVIEW_CHARS  # 预览截断
    assert tr["size"] == 4210
    assert tr["ok"] is True
    assert "A" * 100 not in str(tr)  # 正文不进事件


def test_tool_result_error_prefix_sniffed() -> None:
    """通用异常的错误文案（固定前缀）→ ok=False（best-effort 嗅探）。"""
    rec = ExecutionRecorder()
    rec.tool_call("call_1", "bash", {})
    rec.tool_result("call_1", "bash", "Error executing tool: boom")

    assert rec.finalize()[1]["ok"] is False


def test_finalize_idempotent_and_mark_after_ignored() -> None:
    """finalize 幂等;定格后再 mark 静默忽略（终态不漂移）。"""
    rec = ExecutionRecorder()
    rec.request_begin()
    first = rec.finalize()
    rec.request_begin()  # finalize 后的 mark
    second = rec.finalize()
    assert first is second
    assert _event_types(first) == ["request_begin"]


# ---------------------------------------------------------------------------
# cap 策略：保首尾丢中段 + events_truncated 自声明
# ---------------------------------------------------------------------------


def test_cap_drops_middle_tool_events_keeps_head_tail() -> None:
    """超 16KB：中段 tool_call/tool_result 被丢,首尾与自声明标记保留。"""
    rec = ExecutionRecorder()
    rec.tools_resolved("chat", "m", ["bash"], [])
    rec.request_begin()
    # 大量工具对把序列化推过 16KB（每对 ~370B，70 对 ≈ 26KB）
    for i in range(70):
        tcid = f"call_{i}"
        rec.tool_call(tcid, "bash", {"cmd": "c" * 300})
        rec.tool_result(tcid, "bash", "r" * 300)
    rec.request_end(in_tok=1, out_tok=1)
    rec.error("llm", "done")

    events = rec.finalize()
    types = _event_types(events)
    # 首尾保住：装配/首请求在前,收尾 error 在末（截断标记之前）
    assert types[0] == "tools_resolved"
    assert "error" in types[-2:]
    # 自声明截断
    trunc = [e for e in events if e["e"] == "events_truncated"]
    assert len(trunc) == 1
    assert trunc[0]["dropped"] > 0
    # 中段确有丢弃：留下的 tool 事件少于产生的一半（70 对 = 140 条）
    tool_events = [e for e in events if e["e"] in ("tool_call", "tool_result")]
    assert len(tool_events) < 140
    # 序列化在预算内
    import json

    assert len(json.dumps(events, ensure_ascii=False).encode()) <= 16 * 1024 + 512


def test_cap_events_count_limit() -> None:
    """事件条数超上限同样触发丢中段（防极端高频）。"""
    rec = ExecutionRecorder()
    rec.mark("tools_resolved")  # 非工具事件,永不被丢
    for i in range(CAP_EVENTS + 100):
        rec.mark("tool_call", id=f"c{i}", n="t", args="")
    events = rec.finalize()
    assert len(events) <= CAP_EVENTS + 2  # 保底非工具事件 + 截断标记
    assert any(e["e"] == "events_truncated" for e in events)


def test_small_run_untouched() -> None:
    """未超限的事件列表原样返回（不注入任何额外标记）。"""
    rec = ExecutionRecorder()
    rec.request_begin()
    rec.request_end(1, 1)
    assert rec.finalize() == rec.events


# ---------------------------------------------------------------------------
# RecorderMiddleware — graph 内钩子采集（stream/invoke 双路径共用）
# ---------------------------------------------------------------------------


class _FakeAIMessage:
    """带 usage_metadata 的假 AIMessage（LangChain 标准属性）。"""

    def __init__(self, usage: dict | None = None, response_metadata: dict | None = None):
        self.usage_metadata = usage
        self.response_metadata = response_metadata or {}


async def test_middleware_records_request_with_usage_metadata() -> None:
    """before/after_llm → request_begin/end,token 取自 usage_metadata。"""
    rec = ExecutionRecorder()
    mw = RecorderMiddleware(rec)

    await mw.before_llm({"messages": []})
    resp = _FakeAIMessage(usage={"input_tokens": 120, "output_tokens": 30, "total_tokens": 150})
    await mw.after_llm({"messages": []}, resp)

    events = rec.finalize()
    assert _event_types(events) == ["request_begin", "request_end"]
    assert events[1]["in_tok"] == 120 and events[1]["out_tok"] == 30
    assert events[1]["dur"] >= 0


async def test_middleware_usage_metadata_fallback_to_response_metadata() -> None:
    """usage_metadata 缺失时兼容 response_metadata 的 OpenAI 格式。"""
    rec = ExecutionRecorder()
    mw = RecorderMiddleware(rec)

    await mw.before_llm({"messages": []})
    resp = _FakeAIMessage(
        response_metadata={"token_usage": {"prompt_tokens": 10, "completion_tokens": 5}},
    )
    await mw.after_llm({"messages": []}, resp)

    events = rec.finalize()
    assert events[1]["in_tok"] == 10 and events[1]["out_tok"] == 5


async def test_middleware_records_tool_pair() -> None:
    """before/after_tool → tool_call/tool_result 配对（dur/size 元数据）。"""
    rec = ExecutionRecorder()
    mw = RecorderMiddleware(rec)

    state = {"messages": []}
    tc = {"id": "call_9", "name": "bash", "args": {"cmd": "ls"}}
    out = await mw.before_tool(state, tc)
    assert out is tc  # 只观察不改写
    await mw.after_tool(state, tc, "a\nb\nc")

    tc_ev, tr_ev = rec.finalize()
    assert tc_ev["id"] == "call_9" and tc_ev["n"] == "bash"
    assert tr_ev["size"] == 5 and tr_ev["ok"] is True


async def test_middleware_never_rewrites() -> None:
    """四个钩子全部原样返回入参（纯观察,不影响执行）。"""
    rec = ExecutionRecorder()
    mw = RecorderMiddleware(rec)

    state = {"messages": []}
    assert await mw.before_llm(state) is state
    assert await mw.after_llm(state, _FakeAIMessage()) is state
    tc = {"id": "c1", "name": "t"}
    assert await mw.before_tool(state, tc) is tc
    assert await mw.after_tool(state, tc, "r") is state

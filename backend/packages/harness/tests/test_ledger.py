"""SideEffectLedger 协议与 tool_wrapper 织入测试（E5，harness 套件）。

覆盖（提案 §3.8 / PR #73）：
- 状态迁移：prepared → in_progress → succeeded/failed/unknown；
- 异常分类：ToolException→failed，连接错误→unknown，成功→succeeded；
- 回放三匹配：幂等键 + digest + 已持久化摘要 → 不重执行；
- 无执行身份 → 账本旁路；
- 账本自身故障不阻断工具执行。
"""
from __future__ import annotations

import pytest
from langchain_core.messages import ToolMessage

from agent_flow_harness.execution_context import (
    ExecutionIdentity,
    set_execution_identity,
)
from agent_flow_harness.ledger import (
    LedgerStatus,
    ToolInvocationDraft,
    digest_args,
    ledger_protected_call,
    set_ledger,
)


class MemoryLedger:
    def __init__(self) -> None:
        self.records: dict[str, dict] = {}
        self.order: list[str] = []
        self.broken = False

    async def prepare(self, draft: ToolInvocationDraft) -> None:
        if self.broken:
            raise RuntimeError("ledger down")
        self.order.append("prepared")
        self.records.setdefault(draft.idempotency_key, {
            "draft": draft, "status": LedgerStatus.PREPARED, "summary": None,
        })

    async def claim(self, key: str) -> bool:
        if self.broken:
            raise RuntimeError("ledger down")
        rec = self.records.get(key)
        if rec is None or rec["status"] != LedgerStatus.PREPARED:
            return False
        self.order.append("in_progress")
        rec["status"] = LedgerStatus.IN_PROGRESS
        return True

    async def mark(self, key, status, *, result_summary=None, error=None):
        if self.broken:
            raise RuntimeError("ledger down")
        rec = self.records.get(key)
        if rec is None or rec["status"] != LedgerStatus.IN_PROGRESS:
            return
        self.order.append(status.value)
        rec.update(status=status, summary=result_summary, error=error)

    async def lookup(self, key):
        rec = self.records.get(key)
        if rec is None:
            return None
        from agent_flow_harness.ledger import LedgerRecord

        return LedgerRecord(
            idempotency_key=key,
            status=rec["status"],
            tool_call_id=rec["draft"].tool_call_id,
            tool_name=rec["draft"].tool_name,
            request_digest=rec["draft"].request_digest,
            result_summary=rec["summary"],
        )


@pytest.fixture(autouse=True)
def _clean_ledger_and_identity():
    from agent_flow_harness.ledger import NoLedger

    set_ledger(NoLedger())
    set_execution_identity(None)
    yield
    set_ledger(NoLedger())
    set_execution_identity(None)


def _draft(key="exec_1:step_1:call_1"):
    return ToolInvocationDraft(
        tool_call_id="call_1",
        tool_name="send_email",
        args={"to": "a@b.c"},
        idempotency_key=key,
        request_digest=digest_args({"to": "a@b.c"}),
    )


async def test_transitions_on_success():
    ledger = MemoryLedger()
    set_ledger(ledger)

    async def ok():
        return ToolMessage(content="sent", tool_call_id="call_1")

    result = await ledger_protected_call(_draft(), ok)
    assert result.content == "sent"
    assert ledger.order == ["prepared", "in_progress", "succeeded"]
    assert ledger.records["exec_1:step_1:call_1"]["summary"] == "sent"


async def test_tool_exception_marks_unknown_without_proof_of_no_side_effect():
    ledger = MemoryLedger()
    set_ledger(ledger)

    async def boom():
        raise RuntimeError("tool adapter failed after request dispatch")

    with pytest.raises(ToolException):
        await ledger_protected_call(_draft(), boom)
    assert ledger.records["exec_1:step_1:call_1"]["status"] == LedgerStatus.UNKNOWN


async def test_connection_error_marks_unknown():
    """连接中断/超时——副作用可能已发生，禁止默认重试 → unknown。"""
    ledger = MemoryLedger()
    set_ledger(ledger)

    async def timeout():
        raise TimeoutError("smtp timeout")

    with pytest.raises(TimeoutError):
        await ledger_protected_call(_draft(), timeout)
    assert ledger.records["exec_1:step_1:call_1"]["status"] == LedgerStatus.UNKNOWN


async def test_broken_ledger_fails_closed_before_execution():
    ledger = MemoryLedger()
    ledger.broken = True
    set_ledger(ledger)

    async def ok():
        return ToolMessage(content="still works", tool_call_id="call_1")

    with pytest.raises(RuntimeError, match="ledger down"):
        await ledger_protected_call(_draft(), ok)
    assert ledger.order == []


# ── tool_wrapper 织入（身份 + 回放） ──────────────────────────────────


def _make_request_and_execute(tracked: list[str], exc: BaseException | None = None):
    """最小 fake：ToolCallRequest 仅需 override()/tool_call/state 可用。"""

    class _Req:
        tool_call = {"id": "call_1", "name": "send_email", "args": {"to": "a@b.c"}}
        state: dict = {}

        def override(self, **kw):
            r = _Req()
            r.tool_call = kw.get("tool_call", self.tool_call)
            return r

    async def execute(request):  # noqa: ARG001
        tracked.append("executed")
        if exc is not None:
            raise exc
        return ToolMessage(content="sent ok", tool_call_id="call_1")

    return _Req(), execute


async def test_wrapper_replays_succeeded_invocation():
    """命中 succeeded + digest 匹配 → 回放摘要，不执行工具。"""
    from agent_flow_harness.graph.nodes.tool_wrapper import make_tool_wrapper
    from agent_flow_harness.middleware.chain import MiddlewareChain

    ledger = MemoryLedger()
    set_ledger(ledger)
    set_execution_identity(ExecutionIdentity(execution_id="exec_1", step_id="step_1"))
    key = "exec_1:step_1:call_1"
    ledger.records[key] = {
        "draft": _draft(key),
        "status": LedgerStatus.SUCCEEDED,
        "summary": "replayed result",
    }

    tracked: list[str] = []
    req, execute = _make_request_and_execute(tracked)
    awrap = make_tool_wrapper(MiddlewareChain([]))
    result = await awrap(req, execute)

    assert tracked == []  # 未重执行
    assert isinstance(result, ToolMessage)
    assert result.content == "replayed result"


async def test_wrapper_digest_mismatch_executes():
    """digest 不匹配（参数已变）→ 视为新调用，正常执行。"""
    from agent_flow_harness.graph.nodes.tool_wrapper import make_tool_wrapper
    from agent_flow_harness.middleware.chain import MiddlewareChain

    ledger = MemoryLedger()
    set_ledger(ledger)
    set_execution_identity(ExecutionIdentity(execution_id="exec_1", step_id="step_1"))
    key = "exec_1:step_1:call_1"
    stale = _draft(key)
    stale.request_digest = "sha256:different"
    ledger.records[key] = {
        "draft": stale, "status": LedgerStatus.SUCCEEDED, "summary": "old",
    }

    tracked: list[str] = []
    req, execute = _make_request_and_execute(tracked)
    awrap = make_tool_wrapper(MiddlewareChain([]))
    result = await awrap(req, execute)

    assert tracked == []
    assert isinstance(result, ToolMessage)
    assert result.status == "error"
    assert "identity conflict" in str(result.content).lower()
    assert ledger.records[key]["status"] == LedgerStatus.SUCCEEDED
    assert ledger.records[key]["summary"] == "old"


async def test_wrapper_without_identity_bypasses_ledger():
    from agent_flow_harness.graph.nodes.tool_wrapper import make_tool_wrapper
    from agent_flow_harness.middleware.chain import MiddlewareChain

    ledger = MemoryLedger()
    set_ledger(ledger)

    tracked: list[str] = []
    req, execute = _make_request_and_execute(tracked)
    awrap = make_tool_wrapper(MiddlewareChain([]))
    await awrap(req, execute)

    assert tracked == ["executed"]
    assert ledger.records == {}  # 无身份 → 账本旁路


async def test_wrapper_connection_error_marks_unknown():
    from agent_flow_harness.graph.nodes.tool_wrapper import make_tool_wrapper
    from agent_flow_harness.middleware.chain import MiddlewareChain

    ledger = MemoryLedger()
    set_ledger(ledger)
    set_execution_identity(ExecutionIdentity(execution_id="exec_1", step_id="step_1"))

    tracked: list[str] = []
    req, execute = _make_request_and_execute(tracked, exc=TimeoutError("net down"))
    awrap = make_tool_wrapper(MiddlewareChain([]))
    result = await awrap(req, execute)  # wrapper 把异常转 error ToolMessage

    assert isinstance(result, ToolMessage)
    assert result.status == "error"
    assert ledger.records["exec_1:step_1:call_1"]["status"] == LedgerStatus.UNKNOWN

"""压缩 formatter 归档调度测试 — 双参签名、fire-and-forget、失败静默。

harness ReferenceFormatter 协议 (tool_call_id, original_content) -> str 的
app 侧落地:harness_integration.context._make_tool_output_reference_formatter。
"""
from __future__ import annotations

import asyncio

from app.engine.agent.recall_tool import (
    reset_thread_id_context,
    set_thread_id_context,
)
from app.engine.harness_integration.context import (
    _make_tool_output_reference_formatter,
    _schedule_archive,
)


def test_formatter_marker_text(monkeypatch) -> None:
    """formatter 返回压缩标记(工具名 + tool_call_id),并调度归档。"""
    scheduled: list[tuple[str, str]] = []
    monkeypatch.setattr(
        "app.engine.harness_integration.context._schedule_archive",
        lambda tcid, original: scheduled.append((tcid, original)),
    )
    fmt = _make_tool_output_reference_formatter()

    out = fmt("call_9", "完整原文内容")

    assert "recall_tool_result" in out
    assert 'tool_call_id="call_9"' in out
    assert scheduled == [("call_9", "完整原文内容")]


def test_formatter_marks_compaction_event(monkeypatch) -> None:
    """recorder 非空时,压缩同步记一条 compaction 过程事件(execution_log.events)。"""
    from app.services.execution_recorder import ExecutionRecorder

    monkeypatch.setattr(
        "app.engine.harness_integration.context._schedule_archive",
        lambda tcid, original: None,
    )
    rec = ExecutionRecorder()
    fmt = _make_tool_output_reference_formatter(recorder=rec)

    fmt("call_7", "x" * 8210)

    events = rec.finalize()
    assert len(events) == 1
    ev = events[0]
    assert ev["e"] == "compaction"
    assert ev["level"] == "tool_output"
    assert ev["id"] == "call_7"
    assert ev["before"] == 8210


async def test_schedule_archive_creates_task(monkeypatch) -> None:
    """有 running loop + thread 上下文 → 异步归档任务被调度并执行。"""
    archived: list[tuple[str, str, str]] = []
    from app.services.tool_output_archive_service import ToolOutputArchiveService

    async def fake_archive(thread_id: str, tool_call_id: str, content: str):
        archived.append((thread_id, tool_call_id, content))

    monkeypatch.setattr(
        ToolOutputArchiveService, "archive", staticmethod(fake_archive)
    )
    token = set_thread_id_context("sess_01TEST")
    try:
        _schedule_archive("call_1", "原文")
        await asyncio.sleep(0)  # 让 create_task 跑完
    finally:
        reset_thread_id_context(token)

    assert archived == [("sess_01TEST", "call_1", "原文")]


async def test_schedule_archive_no_thread(monkeypatch) -> None:
    """无 thread 上下文 → 静默跳过(不触 DB)。"""
    from app.services.tool_output_archive_service import ToolOutputArchiveService

    called = False

    async def fail_archive(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(ToolOutputArchiveService, "archive", staticmethod(fail_archive))
    token = set_thread_id_context("")
    try:
        _schedule_archive("call_1", "原文")  # 不应抛异常
        await asyncio.sleep(0)
    finally:
        reset_thread_id_context(token)
    assert not called


def test_schedule_archive_outside_loop() -> None:
    """同步上下文(无 running loop)调用 → 静默返回,不抛异常。"""
    _schedule_archive("call_1", "原文")  # 不应抛 RuntimeError


async def test_schedule_archive_archive_failure_swallowed(monkeypatch) -> None:
    """归档写库抛异常 → 只记日志,不影响压缩主流程。"""
    from app.services.tool_output_archive_service import ToolOutputArchiveService

    async def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr(ToolOutputArchiveService, "archive", staticmethod(boom))
    token = set_thread_id_context("sess_01TEST")
    try:
        _schedule_archive("call_1", "原文")  # 不应上抛
        await asyncio.sleep(0)
    finally:
        reset_thread_id_context(token)

"""recall_tool_result 工具测试 — 取数链(归档→timeline 兜底)、分页、错误分支。"""
from __future__ import annotations

import pytest
from app.engine.agent.recall_tool import (
    RECALL_TOOL_BY_NAME,
    recall_tool_result,
    reset_thread_id_context,
    set_thread_id_context,
)


@pytest.fixture
def thread_ctx():
    token = set_thread_id_context("sess_01TEST")
    yield "sess_01TEST"
    reset_thread_id_context(token)


def _patch_sources(monkeypatch, *, archived: str | None, timeline: str | None) -> None:
    from app.services.session_service import MessageService
    from app.services.tool_output_archive_service import ToolOutputArchiveService

    async def fake_archive_get(thread_id: str, tool_call_id: str):
        assert thread_id == "sess_01TEST"
        return archived

    async def fake_timeline_get(session_id: str, tool_call_id: str):
        assert session_id == "sess_01TEST"
        return timeline

    monkeypatch.setattr(ToolOutputArchiveService, "get", staticmethod(fake_archive_get))
    monkeypatch.setattr(
        MessageService, "get_tool_result_content", staticmethod(fake_timeline_get)
    )


async def test_archive_hit(thread_ctx, monkeypatch) -> None:
    """归档命中:返回原文 + 来源标注 archive。"""
    _patch_sources(monkeypatch, archived='{"rows": [1, 2, 3]}', timeline=None)

    result = await recall_tool_result.ainvoke({"tool_call_id": "call_1"})
    assert '"rows"' in result
    assert "来源：archive" in result


async def test_timeline_fallback(thread_ctx, monkeypatch) -> None:
    """归档 miss(存量会话)→ messages timeline 兜底。"""
    _patch_sources(monkeypatch, archived=None, timeline="历史工具结果原文")

    result = await recall_tool_result.ainvoke({"tool_call_id": "call_1"})
    assert "历史工具结果原文" in result
    assert "来源：messages" in result


async def test_both_miss_graceful(thread_ctx, monkeypatch) -> None:
    """双 miss:友好错误文本(不抛异常,agent 能读懂并放弃)。"""
    _patch_sources(monkeypatch, archived=None, timeline=None)

    result = await recall_tool_result.ainvoke({"tool_call_id": "call_gone"})
    assert result.startswith("[recall_tool_result]")
    assert "未找到" in result


async def test_no_thread_context(monkeypatch) -> None:
    """无 thread 上下文:直接友好提示,不触 DB。"""
    from app.services.tool_output_archive_service import ToolOutputArchiveService

    called = False

    async def fail_get(thread_id: str, tool_call_id: str):
        nonlocal called
        called = True
        return None

    monkeypatch.setattr(ToolOutputArchiveService, "get", staticmethod(fail_get))

    # 不 set thread ctx(default="")
    reset = set_thread_id_context("")
    try:
        result = await recall_tool_result.ainvoke({"tool_call_id": "call_1"})
    finally:
        reset_thread_id_context(reset)
    assert "无会话上下文" in result
    assert not called


async def test_pagination(thread_ctx, monkeypatch) -> None:
    """长文分页:offset/limit 生效,尾部给续读提示。"""
    _patch_sources(monkeypatch, archived="x" * 100, timeline=None)

    result = await recall_tool_result.ainvoke(
        {"tool_call_id": "call_1", "offset": 90, "limit": 5}
    )
    assert "x" * 5 in result  # 90-95 的切片
    assert "共 100 字符" in result
    assert "offset=95" in result  # 续读提示
    # 末页:不出现续读提示
    result2 = await recall_tool_result.ainvoke(
        {"tool_call_id": "call_1", "offset": 95, "limit": 5}
    )
    assert "共 100 字符" in result2
    assert "续读" not in result2


async def test_limit_clamped(thread_ctx, monkeypatch) -> None:
    """limit 超上限截到 _MAX_LIMIT,offset 越界钳到 total。"""
    _patch_sources(monkeypatch, archived="y" * 50, timeline=None)

    result = await recall_tool_result.ainvoke(
        {"tool_call_id": "call_1", "offset": 9999, "limit": 999999}
    )
    # offset 越界 → 钳到 50,返回空 chunk + footer
    assert "共 50 字符" in result


def test_registry() -> None:
    """注册表与 _INJECTED_BUILTIN_TOOL_NAMES 单一事实源一致。"""
    from app.engine.harness_integration.context import _INJECTED_BUILTIN_TOOL_NAMES

    assert "recall_tool_result" in RECALL_TOOL_BY_NAME
    assert "recall_tool_result" in _INJECTED_BUILTIN_TOOL_NAMES

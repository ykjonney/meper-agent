"""文档水位线压缩测试 — 两级水位线 / 影子账本 / 单条截断。

数据模型背景：message 文档一次性写入定型（写前同步压缩）；
session.compaction_bytes 影子账本 = thread 压缩累计掉的原文体量
= session 永久保留的全文体量（同一数据两份拷贝）。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.core.config import settings
from app.services import doc_compaction_service as dcs


def _tool_result(tcid: str, content: str) -> dict:
    return {
        "type": "tool_result",
        "tool_name": "bash",
        "tool_call_id": tcid,
        "status": "success",
        "content": content,
    }


@pytest.fixture
def small_watermarks(monkeypatch: pytest.MonkeyPatch):
    """把水位线缩到测试友好的量级（默认 10/14MB 太大）。"""
    monkeypatch.setattr(settings, "DOC_COMPACT_HIGH_MB", 1)      # 1MB
    monkeypatch.setattr(settings, "DOC_COMPACT_DISCARD_MB", 2)   # 2MB


# ---------------------------------------------------------------------------
# estimate_doc_size
# ---------------------------------------------------------------------------


def test_estimate_doc_size_scales_with_content() -> None:
    small = dcs.estimate_doc_size({"timeline_entries": [{"content": "x" * 100}]})
    big = dcs.estimate_doc_size({"timeline_entries": [{"content": "x" * 100_000}]})
    assert 0 < small < big
    # BSON 结构开销系数（~1.1×json 长度）。
    assert big > 100_000


# ---------------------------------------------------------------------------
# compact_timeline_entries — 阶段 1（preview + extern，可逆）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compact_noop_under_watermark(small_watermarks) -> None:
    """未超高水位：零改动（没达到数量就没必要瘦身）。"""
    entries = [_tool_result("t1", "x" * 500), {"type": "text", "content": "hi"}]
    result, changed = await dcs.compact_timeline_entries(
        list(entries), owner_user_id="u1", origin_id="m1",
    )
    assert changed is False
    assert result == entries


@pytest.mark.asyncio
async def test_compact_previews_oldest_until_target(small_watermarks) -> None:
    """超高水位：从最老的大 tool_result 开始 preview+extern，压到目标线停。"""
    # 3 条 500KB → 估算 ~1.65MB > 1MB 高水位。压 1 条剩 ~1.1MB 仍超 →
    # 压第 2 条剩 ~0.55MB ≤ 1MB 停：外置 2 条、保真最新的 1 条。
    entries = [
        _tool_result("t1", "a" * 500_000),
        _tool_result("t2", "b" * 500_000),
        _tool_result("t3", "c" * 500_000),
        {"type": "text", "content": "结论"},
    ]
    extern_ref = {"file_id": "f1", "storage_key": "k1", "size": 500_000}
    with patch.object(
        dcs, "externalize_content", new=AsyncMock(return_value=extern_ref),
    ) as mock_ext:
        result, changed = await dcs.compact_timeline_entries(
            list(entries), owner_user_id="u1", origin_id="m1",
        )
    assert changed is True
    # 最老的 t1/t2 被外置（preview + extern 引用），最新的 t3 保真。
    assert result[0]["content_extern"] == extern_ref
    assert len(result[0]["content"]) < 1000
    assert "已外置" in result[0]["content"]
    assert result[1].get("content_extern") == extern_ref
    assert result[2].get("content_extern") is None
    assert result[2]["content"] == "c" * 500_000
    # text 结论条目不动。
    assert result[3] == {"type": "text", "content": "结论"}
    # 恰好外置到目标线的条数（2 条），不过度外置。
    assert mock_ext.call_count == 2


@pytest.mark.asyncio
async def test_compact_skips_small_and_idempotent(small_watermarks) -> None:
    """小于门槛(<2000 字符)的 tool_result 不外置；已外置的幂等跳过。"""
    big = "x" * 500_000
    entries = [
        {**_tool_result("t1", big), "content_extern": {"file_id": "f0"}},  # 已外置
        _tool_result("t2", "y" * 100),  # 太小
        _tool_result("t3", "z" * 500_000),
    ]
    with patch.object(
        dcs, "externalize_content", new=AsyncMock(
            return_value={"file_id": "f3", "storage_key": "k", "size": 1},
        ),
    ) as mock_ext:
        result, changed = await dcs.compact_timeline_entries(
            list(entries), owner_user_id="u1", origin_id="m1",
        )
    assert changed is True
    assert mock_ext.call_count == 1  # 只外置 t3
    assert len(result[2]["content"]) < 1000
    assert result[1]["content"] == "y" * 100


@pytest.mark.asyncio
async def test_compact_externalize_failure_keeps_original(small_watermarks) -> None:
    """外置失败：原文保留不动（宁膨胀不丢数据），下次重试。"""
    entries = [_tool_result("t1", "a" * 500_000)]
    with patch.object(dcs, "externalize_content", new=AsyncMock(return_value=None)):
        result, changed = await dcs.compact_timeline_entries(
            list(entries), owner_user_id="u1", origin_id="m1",
        )
    assert result[0]["content"] == "a" * 500_000
    assert changed is False


# ---------------------------------------------------------------------------
# compact_timeline_entries — 阶段 2（丢弃，不可逆）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_discard_phase_drops_payload_keeps_skeleton(small_watermarks) -> None:
    """超丢弃线：丢最早载荷条目（tool_call/tool_result/thinking），
    text/interrupt 骨架豁免。

    构造：阶段 1 无可压对象（tool_result 均小于门槛），膨胀来自
    thinking 大载荷（阶段 1 不碰）→ 直接进阶段 2 丢弃。
    """
    big_think = "t" * 500_000
    entries = [
        _tool_result("t1", "x" * 100),          # 小载荷（阶段1跳过）
        {"type": "thinking", "content": big_think},   # 最老的大载荷
        {"type": "text", "content": "第一轮结论"},     # 骨架，永不丢
        {"type": "thinking", "content": big_think},
        {"type": "thinking", "content": big_think},
        _tool_result("t2", "y" * 100),
        {"type": "text", "content": "最终结论"},       # 骨架
    ]
    # ~1.65MB thinking > 丢弃线 2MB？不够 —— thinking×3=1.5MB×1.1≈1.65MB
    # 仍低于 2MB。再加两条使阶段 2 触发。
    entries.insert(4, {"type": "thinking", "content": big_think})
    entries.insert(5, {"type": "thinking", "content": big_think})

    with (
        patch.object(dcs, "externalize_content", new=AsyncMock()) as mock_ext,
        patch.object(dcs, "delete_extern_content", new=AsyncMock()) as mock_del,
    ):
        result, changed = await dcs.compact_timeline_entries(
            list(entries), owner_user_id="u1", origin_id="m1",
        )
    assert changed is True
    # text 骨架全保留。
    contents = [str(e.get("content", ""))[:20] for e in result]
    assert any("第一轮结论" in c for c in contents)
    assert any("最终结论" in c for c in contents)
    # 最老的 thinking 载荷被丢弃（条数减少），阶段 1 未外置（无可压对象）。
    assert len(result) < len(entries)
    assert mock_ext.call_count == 0
    assert mock_del.call_count == 0  # 无 extern 引用被丢 → 无级联删除


# ---------------------------------------------------------------------------
# 影子账本 record_compaction_bytes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shadow_ledger_triggers_compaction_and_resets(monkeypatch: pytest.MonkeyPatch) -> None:
    """累计超触发线 → 异步压缩 + 重置；未超线只记账。"""
    monkeypatch.setattr(settings, "DOC_COMPACT_SHADOW_TRIGGER_MB", 1)

    def _mock_db(total_after_inc: int):
        col = MagicMock()
        col.find_one_and_update = AsyncMock(
            return_value={"compaction_bytes": total_after_inc},
        )
        col.update_one = AsyncMock()
        db = MagicMock()
        db.__getitem__.side_effect = lambda key: col if key == "sessions" else MagicMock()
        return col, db

    compact_calls = []

    async def _fake_compact(session_id: str) -> int:
        compact_calls.append(session_id)
        return 1

    # 未超线：只 $inc，不触发压缩。
    col, db = _mock_db(total_after_inc=100)
    with (
        patch("app.db.mongodb.get_database", return_value=db),
        patch.object(dcs, "compact_session_messages", new=_fake_compact),
    ):
        await dcs.record_compaction_bytes("s1", 100)
    assert compact_calls == []
    col.find_one_and_update.assert_awaited_once()

    # 超线（>1MB）：触发压缩 + 重置为 0。
    dcs._EXTERNALIZE_LOCK.clear()
    col2, db2 = _mock_db(total_after_inc=2_000_000)
    with (
        patch("app.db.mongodb.get_database", return_value=db2),
        patch.object(dcs, "compact_session_messages", new=_fake_compact),
    ):
        await dcs.record_compaction_bytes("s1", 2_000_000)
        # create_task 已调度，等它跑完。
        import asyncio

        await asyncio.sleep(0)
    assert compact_calls == ["s1"]
    # 重置 $set compaction_bytes=0 被调用。
    reset_calls = [
        c for c in col2.update_one.await_args_list
        if c.args and isinstance(c.args[1], dict) and c.args[1].get("$set", {}).get("compaction_bytes") == 0
    ]
    assert reset_calls, "触发压缩后应重置影子账本"


# ---------------------------------------------------------------------------
# 单条截断（session_service._truncate_tool_result_entries）
# ---------------------------------------------------------------------------


def test_truncate_tool_result_entries() -> None:
    from app.services.session_service import _truncate_tool_result_entries

    limit = settings.TOOL_RESULT_MAX_CHARS
    entries = [
        _tool_result("t1", "x" * (limit + 5000)),  # 超限 → 截断
        _tool_result("t2", "ok"),                   # 未超 → 原样
        {"type": "text", "content": "y" * (limit + 1)},  # 非 tool_result → 不动
    ]
    result = _truncate_tool_result_entries(entries)
    assert len(result[0]["content"]) <= limit + 100
    assert result[0]["content_truncated"] is True
    assert result[1]["content"] == "ok"
    assert len(result[2]["content"]) == limit + 1


# ---------------------------------------------------------------------------
# engine 侧：_output_digest / _externalize_large_value
# ---------------------------------------------------------------------------


def test_output_digest_truncates_each_node() -> None:
    from app.engine.workflow.engine import _output_digest

    output = {
        "node_a": {"response": "r" * 5000},
        "node_b": {"response": "短回复"},
    }
    digest = _output_digest(output)
    assert len(digest["node_a"]) <= 210
    assert digest["node_b"] == "短回复"


@pytest.mark.asyncio
async def test_externalize_large_value_threshold() -> None:
    from app.engine.workflow.engine import _externalize_large_value

    # 阈值内零开销原样返回（不触碰 file_library）。
    small = await _externalize_large_value("x" * 100, user_id="u", origin_id="t")
    assert small == "x" * 100

    # 超阈值外置为引用 dict；失败回退原值。
    big = "y" * 60_000
    ref = {"file_id": "f1", "storage_key": "k", "size": 60_000}
    with patch(
        "app.services.doc_compaction_service.externalize_content",
        new=AsyncMock(return_value=ref),
    ):
        out = await _externalize_large_value(big, user_id="u", origin_id="t")
    assert out["extern"] == ref
    assert out["preview"] == "y" * 500

    with patch(
        "app.services.doc_compaction_service.externalize_content",
        new=AsyncMock(return_value=None),
    ):
        out2 = await _externalize_large_value(big, user_id="u", origin_id="t")
    assert out2 == big  # 外置失败宁膨胀不丢数据

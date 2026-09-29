"""ToolOutputArchiveService / MessageService.get_tool_result_content 测试。

全部 mock motor collection(不真连 Mongo,CI 无 27017 也能跑)。
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from app.services.session_service import MessageService
from app.services.tool_output_archive_service import ToolOutputArchiveService
from pymongo.errors import DuplicateKeyError


def _mock_collection(monkeypatch, col=None) -> MagicMock:
    """把 service 的 _collection() 替换为 mock collection 并返回它。"""
    col = col or MagicMock()
    col.insert_one = AsyncMock()
    col.find_one = AsyncMock(return_value=None)
    col.delete_many = AsyncMock(return_value=MagicMock(deleted_count=2))
    monkeypatch.setattr(ToolOutputArchiveService, "_collection", staticmethod(lambda: col))
    return col


# ---------------------------------------------------------------------------
# ToolOutputArchiveService
# ---------------------------------------------------------------------------


async def test_archive_inserts_doc(monkeypatch) -> None:
    """正常归档:插入文档,键为 (thread_id, tool_call_id)。"""
    col = _mock_collection(monkeypatch)

    await ToolOutputArchiveService.archive("t_1", "call_1", "原文", tool_name="bash")

    col.insert_one.assert_awaited_once()
    doc = col.insert_one.await_args.args[0]
    assert doc["thread_id"] == "t_1"
    assert doc["tool_call_id"] == "call_1"
    assert doc["tool_name"] == "bash"
    assert doc["content"] == "原文"
    assert "created_at" in doc  # BSON date(TTL 依赖)


async def test_archive_duplicate_swallowed(monkeypatch) -> None:
    """渐进式压缩的后续回调(唯一键冲突)→ 吞掉,不覆盖首次归档的原文。"""
    col = _mock_collection(monkeypatch)
    col.insert_one = AsyncMock(side_effect=DuplicateKeyError("dup"))

    await ToolOutputArchiveService.archive("t_1", "call_1", "缩短版")  # 不应抛


async def test_archive_db_error_swallowed(monkeypatch) -> None:
    """写库失败 → 静默(归档是 best-effort,不影响压缩主流程)。"""
    col = _mock_collection(monkeypatch)
    col.insert_one = AsyncMock(side_effect=RuntimeError("db down"))

    await ToolOutputArchiveService.archive("t_1", "call_1", "原文")  # 不应抛


async def test_archive_empty_keys_noop(monkeypatch) -> None:
    """空 thread_id / tool_call_id → 直接跳过,不触 collection。"""
    col = _mock_collection(monkeypatch)

    await ToolOutputArchiveService.archive("", "call_1", "x")
    await ToolOutputArchiveService.archive("t_1", "", "x")

    col.insert_one.assert_not_awaited()


async def test_archive_caps_content(monkeypatch) -> None:
    """超 1MB(字符)的原文截断并加标记。"""
    from app.services.tool_output_archive_service import _MAX_ARCHIVE_CHARS

    col = _mock_collection(monkeypatch)
    huge = "x" * (_MAX_ARCHIVE_CHARS + 100)

    await ToolOutputArchiveService.archive("t_1", "call_1", huge)

    doc = col.insert_one.await_args.args[0]
    assert len(doc["content"]) <= _MAX_ARCHIVE_CHARS + 100  # 截断 + 标记行
    assert "已截断" in doc["content"]


async def test_get_hit_and_miss(monkeypatch) -> None:
    """get 命中返回 content 字符串;miss 返回 None;非字符串容错。"""
    col = _mock_collection(monkeypatch)

    col.find_one = AsyncMock(return_value={"content": "归档原文"})
    assert await ToolOutputArchiveService.get("t_1", "call_1") == "归档原文"

    col.find_one = AsyncMock(return_value=None)
    assert await ToolOutputArchiveService.get("t_1", "call_x") is None

    col.find_one = AsyncMock(return_value={"content": 123})  # 脏数据容错
    assert await ToolOutputArchiveService.get("t_1", "call_1") is None


async def test_delete_for_thread(monkeypatch) -> None:
    """会话级联清理预留:按 thread 删除。"""
    col = _mock_collection(monkeypatch)

    count = await ToolOutputArchiveService.delete_for_thread("t_1")

    col.delete_many.assert_awaited_once_with({"thread_id": "t_1"})
    assert count == 2


# ---------------------------------------------------------------------------
# MessageService.get_tool_result_content(recall 的 timeline 兜底)
# ---------------------------------------------------------------------------


def _mock_messages_collection(monkeypatch) -> MagicMock:
    col = MagicMock()
    col.find_one = AsyncMock(return_value=None)
    monkeypatch.setattr(MessageService, "_collection", staticmethod(lambda: col))
    return col


async def test_timeline_tool_result_hit(monkeypatch) -> None:
    """elemMatch + 投影命中:返回该条 tool_result 的 content。"""
    col = _mock_messages_collection(monkeypatch)
    col.find_one = AsyncMock(
        return_value={"timeline_entries": [{"type": "tool_result", "content": "明细原文"}]}
    )

    content = await MessageService.get_tool_result_content("sess_1", "call_1")

    assert content == "明细原文"
    query = col.find_one.await_args.args[0]
    assert query["session_id"] == "sess_1"
    assert query["timeline_entries"]["$elemMatch"]["tool_call_id"] == "call_1"
    assert query["timeline_entries"]["$elemMatch"]["type"] == "tool_result"


async def test_timeline_tool_result_miss(monkeypatch) -> None:
    """未命中(渠道会话不落 messages 等)→ None。"""
    col = _mock_messages_collection(monkeypatch)
    col.find_one = AsyncMock(return_value=None)

    assert await MessageService.get_tool_result_content("sess_1", "call_x") is None


async def test_timeline_tool_result_dirty_doc(monkeypatch) -> None:
    """脏文档(空 entries / content 非字符串)→ None,不抛异常。"""
    col = _mock_messages_collection(monkeypatch)
    col.find_one = AsyncMock(return_value={"timeline_entries": []})
    assert await MessageService.get_tool_result_content("sess_1", "call_1") is None

    col.find_one = AsyncMock(return_value={"timeline_entries": [{"content": None}]})
    assert await MessageService.get_tool_result_content("sess_1", "call_1") is None

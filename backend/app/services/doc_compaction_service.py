"""文档水位线压缩服务 — message / Task 文档的两级水位线治理。

设计（长程任务治理第二批，与 thread 侧压缩对称）：
    thread 侧以 token 计量（estimate_context_tokens）触发上下文压缩；
    session 侧以字节计量（compaction_bytes 影子账本 / $bsonSize）触发
    文档压缩。原理：thread 里被压缩掉的数据 = session 里永久保留的
    全文（同一数据两份拷贝），累计流量精确同步。

两级水位线（16MB 为 Mongo BSON 硬墙，14→16 留扫描间隙增长缓冲）：
    阶段 1（≥10MB，可逆）: 从最老的 tool_result 开始 preview 化 ——
        content > COMPACT_MIN_CHARS 的替换为 preview + content_extern
        外置引用（file_library），recall/前端可按需加载全文。
        压到 <10MB 停（保近期全文）。
    阶段 2（压后 >14MB，不可逆）: 丢弃最早的载荷类条目（tool_result/
        tool_call 成对、thinking），text 与状态骨架事件永不丢。
    层 3（写前防御）: 调用方在写入前发现 size > 丢弃线时先丢再写，
        保证写入永不撞 16MB。

并发安全：
    message 文档一次性写入后不可变 → 压缩无竞态；
    Task timeline 按索引逐条 $set（不覆盖并发 $push 的新事件）。
"""
from __future__ import annotations

import json
from typing import Any

from loguru import logger

from app.core.config import settings
from app.models.base import utc_now
from app.models.file_library import FileConsumerKind

# ---------------------------------------------------------------------------
# 阈值（字节；settings 可配，默认值见 config.py）
# ---------------------------------------------------------------------------

BYTES_PER_MB = 1024 * 1024


def _high_watermark() -> int:
    """阶段 1 触发线（高水位）。"""
    return settings.DOC_COMPACT_HIGH_MB * BYTES_PER_MB


def _discard_watermark() -> int:
    """阶段 2 触发线（丢弃线）。"""
    return settings.DOC_COMPACT_DISCARD_MB * BYTES_PER_MB


def _target_watermark() -> int:
    """压缩目标线（压到该线以下停）。"""
    return settings.DOC_COMPACT_HIGH_MB * BYTES_PER_MB


# tool_result 压缩的最小收益门槛：低于此长度的 preview(500)+extern 结构
# 反而更大，不值得外置。
_COMPACT_MIN_CHARS = 2000
_PREVIEW_CHARS = 500

# 阶段 2 丢弃豁免：这些 timeline_entries 类型是用户可读的骨架/结论，
# 永不丢弃（丢弃只针对载荷类：tool_call/tool_result/thinking）。
_ENTRY_NEVER_DROP = frozenset({"text", "interrupt"})


def estimate_doc_size(doc: dict[str, Any]) -> int:
    """估算文档 BSON 大小（json.dumps × 1.1 结构开销系数）。

    只用于触发判断（与水位线比较），不需要精确——水位线距 16MB 硬墙
    有充足缓冲。精确值由 Mongo $bsonSize（Task 写入路径）兜底。
    """
    try:
        return int(len(json.dumps(doc, ensure_ascii=False, default=str)) * 1.1)
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------------------
# extern 外置 / 加载（file_library）
# ---------------------------------------------------------------------------

_EXTERNALIZE_LOCK: dict[str, bool] = {}
"""session 级节流：同一会话的异步压缩去重（防重复触发重复外置）。"""


async def externalize_content(
    text: str, *, owner_user_id: str, origin_id: str,
) -> dict[str, Any] | None:
    """把全文外置到 file_library，返回 extern 引用结构。

    失败返回 None（压缩主流程绝不因外置失败而中断——原文保留不动，
    下次触发重试）。origin_kind 用 doc_compaction（独立生命周期，
    级联删除挂 delete_session/delete_task）。
    """
    from app.services.file_service import FileService
    from app.services.file_storage import LocalFileStorage

    try:
        svc = FileService(storage=LocalFileStorage())
        ref = await svc.create(
            data=text.encode("utf-8"),
            filename=f"compacted-tool-result-{utc_now().strftime('%Y%m%d%H%M%S')}.txt",
            mime_type="text/plain",
            owner_user_id=owner_user_id,
            origin_kind=FileConsumerKind.DOC_COMPACTION,
            origin_id=origin_id,
        )
        return {
            "file_id": ref.id,
            "storage_key": ref.storage_key,
            # 字符数（不是字节）：口径与 len(text) 一致；FileRef.size 是
            # 文件字节数（UTF-8 中文 3 字节/字），两者同名不同义，勿混用。
            "chars": len(text),
        }
    except Exception as exc:
        logger.warning(
            "doc_compact_externalize_failed", origin_id=origin_id, error=str(exc),
        )
        return None


async def load_extern_content(ref: dict[str, Any]) -> str | None:
    """按 extern 引用加载全文（recall 兜底 / 详情 API 用）。"""
    from app.services.file_service import FileService
    from app.services.file_storage import LocalFileStorage

    try:
        svc = FileService(storage=LocalFileStorage())
        loaded = await svc.load_content(str(ref.get("file_id", "")))
        if loaded is None:
            return None
        _file_ref, data = loaded
        return data.decode("utf-8", errors="replace")
    except Exception as exc:
        logger.warning("doc_compact_extern_load_failed", error=str(exc))
        return None


async def delete_extern_content(ref: dict[str, Any]) -> None:
    """删除外置文件（丢弃条目时级联，防 file_library 孤儿堆积）。"""
    from app.services.file_service import FileService
    from app.services.file_storage import LocalFileStorage

    try:
        svc = FileService(storage=LocalFileStorage())
        await svc.delete(str(ref.get("file_id", "")))
    except Exception as exc:
        logger.debug("doc_compact_extern_delete_failed", error=str(exc))


# ---------------------------------------------------------------------------
# timeline_entries 两阶段压缩（message 文档 / 详情视图共用）
# ---------------------------------------------------------------------------

_PREVIEW_NOTE = "[完整原文已外置存储，可通过工具结果详情按需查看]"


def _make_preview(content: str) -> str:
    size = len(content)
    head = content[:_PREVIEW_CHARS]
    return f"{head}\n…[{_PREVIEW_NOTE}（原 {size} 字符）]"


async def compact_timeline_entries(
    entries: list[dict[str, Any]],
    *,
    owner_user_id: str,
    origin_id: str,
    other_fields: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], bool]:
    """对 timeline_entries 就地执行两级水位线压缩。

    Args:
        entries: 消息的 timeline_entries（将被就地修改的拷贝）。
        owner_user_id / origin_id: 外置文件的归属。
        other_fields: 文档的其余字段（参与大小估算）。

    Returns:
        (压缩后的 entries, 是否发生改动)。改动含 preview 外置与条目丢弃；
        未超高水位时原样返回（零改动）。
    """
    doc_size = estimate_doc_size({"timeline_entries": entries, **(other_fields or {})})
    if doc_size <= _high_watermark():
        return entries, False

    changed = False
    # ── 阶段 1：从最老的大 tool_result 开始 preview 化，压到高水位下停 ──
    for entry in entries:
        if doc_size <= _target_watermark():
            break
        if entry.get("type") != "tool_result":
            continue
        content = entry.get("content")
        if not isinstance(content, str) or len(content) < _COMPACT_MIN_CHARS:
            continue
        if entry.get("content_extern"):
            continue  # 已外置过（幂等）
        ref = await externalize_content(
            content, owner_user_id=owner_user_id, origin_id=origin_id,
        )
        if ref is None:
            continue  # 外置失败：原文保留，下次重试
        entry["content_extern"] = ref
        entry["content"] = _make_preview(content)
        doc_size = estimate_doc_size(
            {"timeline_entries": entries, **(other_fields or {})}
        )
        changed = True

    # ── 阶段 2：仍超丢弃线 → 丢弃最早的载荷条目（成对、豁免骨架）──
    if doc_size > _discard_watermark():
        kept: list[dict[str, Any]] = []
        dropped_refs: list[dict[str, Any]] = []
        dropped_count = 0
        for entry in entries:
            if doc_size <= _target_watermark():
                kept.append(entry)
                continue
            etype = entry.get("type", "")
            if etype in _ENTRY_NEVER_DROP or etype not in (
                "tool_call", "tool_result", "thinking",
            ):
                kept.append(entry)
                continue
            dropped_count += 1
            if entry.get("content_extern"):
                dropped_refs.append(entry["content_extern"])
            changed = True
            # 差量减：粗略按条目 json 长度估算。
            doc_size -= int(len(json.dumps(entry, ensure_ascii=False, default=str)) * 1.1)
        entries = kept
        if dropped_count:
            logger.warning(
                "doc_compact_entries_dropped",
                origin_id=origin_id, dropped=dropped_count,
                note="丢弃线兜底：最早的载荷条目被丢弃（骨架/文本豁免）",
            )
            # 级联删外置文件（防孤儿）。
            for ref in dropped_refs:
                await delete_extern_content(ref)

    return entries, changed


# ---------------------------------------------------------------------------
# 影子账本：compaction_bytes 记账
# ---------------------------------------------------------------------------

async def record_compaction_bytes(session_id: str, nbytes: int) -> None:
    """影子账本记账：thread 每压缩掉一笔，session 永久保留同体量全文。

    挂在 formatter 回调（_schedule_archive 旁）：len(original) 恰是
    "thread 丢掉、session 留下"的体量。累计超触发线 → 异步压缩该会话
    的 message 文档（session 级节流防重）。
    """
    if nbytes <= 0 or not session_id:
        return
    from app.db.mongodb import get_database

    trigger = settings.DOC_COMPACT_SHADOW_TRIGGER_MB * BYTES_PER_MB
    try:
        result = await get_database()["sessions"].find_one_and_update(
            {"_id": session_id},
            {"$inc": {"compaction_bytes": nbytes}},
            projection={"compaction_bytes": 1},
        )
        total = int((result or {}).get("compaction_bytes") or 0)
    except Exception as exc:
        logger.debug("compaction_bytes_inc_failed", session_id=session_id, error=str(exc))
        return
    if total < trigger:
        return

    if _EXTERNALIZE_LOCK.get(session_id):
        return  # 该会话压缩已在跑
    _EXTERNALIZE_LOCK[session_id] = True
    import asyncio

    task = asyncio.create_task(
        _compact_session_and_reset(session_id, total),
    )
    task.add_done_callback(lambda _t: _EXTERNALIZE_LOCK.pop(session_id, None))


async def _compact_session_and_reset(session_id: str, bytes_at_trigger: int) -> None:
    """压缩该会话的 message 文档（从最老开始），完成后重置影子账本。"""
    try:
        await compact_session_messages(session_id)
    except Exception:
        logger.exception("doc_compact_session_failed", session_id=session_id)
    finally:
        from app.db.mongodb import get_database

        # 重置为 0（压缩完成后的新累计重新计）。失败也重置——避免死循环
        # 触发（下次压缩事件重新累计，损失只是一次触发延迟）。
        try:
            await get_database()["sessions"].update_one(
                {"_id": session_id}, {"$set": {"compaction_bytes": 0}},
            )
        except Exception as exc:
            logger.debug(
                "compaction_bytes_reset_failed", session_id=session_id, error=str(exc),
            )


async def compact_session_messages(session_id: str) -> int:
    """按从老到新压缩该会话超水位的 message 文档。返回处理条数。"""
    from app.db.mongodb import get_database

    session = await get_database()["sessions"].find_one(
        {"_id": session_id}, {"user_id": 1},
    )
    if session is None:
        return 0
    user_id = str(session.get("user_id") or "")

    processed = 0
    cursor = (
        get_database()["messages"].find(
            {"session_id": session_id, "role": "agent"},
            {"timeline_entries": 1},
        )
        .sort("created_at", 1)  # 从最老开始
    )
    async for doc in cursor:
        entries = doc.get("timeline_entries") or []
        if not entries:
            continue
        compacted, changed = await compact_timeline_entries(
            list(entries),
            owner_user_id=user_id,
            origin_id=str(doc["_id"]),
        )
        if not changed:
            continue
        # message 文档不可变语义 → 直接 $set 整个数组（无并发写竞争）。
        await get_database()["messages"].update_one(
            {"_id": doc["_id"]},
            {"$set": {"timeline_entries": compacted}},
        )
        processed += 1
    if processed:
        logger.info(
            "doc_compact_session_done", session_id=session_id, messages=processed,
        )
    return processed


__all__ = [
    "compact_session_messages",
    "compact_timeline_entries",
    "delete_extern_content",
    "estimate_doc_size",
    "externalize_content",
    "load_extern_content",
    "record_compaction_bytes",
]

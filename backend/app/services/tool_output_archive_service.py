"""Tool output archive — 压缩发生时归档的工具结果原文。

harness 压缩层（compress_tool_outputs / LLM 摘要）把已消费的大工具结果缩短
前，会经 app 注入的 reference_formatter 回调 (tool_call_id, original)——
formatter 借此把原文写入本 collection，使压缩"可逆"：模型随后可用
``recall_tool_result`` 工具按 (thread_id, tool_call_id) 取回。

为什么必须有独立归档（messages 明细不够）：
- IM 渠道会话默认不落 messages（CHANNEL_PERSIST_MESSAGES=False）；
- workflow agent 节点根本不写 messages；
- checkpointer 里的 ToolMessage 已被压缩改写，原文不存在。
归档是唯一覆盖 chat/渠道/workflow 三场景的原文来源。

写入语义（关键）：
- **insert-if-absent**（唯一复合索引 + DuplicateKeyError 吞掉）：压缩是渐进
  的，同一条结果可能被多次压缩回调——第一次归档的是完整原文，后续回调拿到
  的是"缩短提示 + 标记"，绝不能覆盖。
- 写失败静默（best-effort）：归档是增强能力，绝不能影响压缩主流程。
"""
from __future__ import annotations

from typing import Any

from loguru import logger

from app.db.mongodb import get_database
from app.models.base import utc_now

# 单条归档上限（字符）。上游 sandbox 已把 shell 输出截到 50KB；MCP 等外部
# 工具结果无上游截断，这里兜底防超大文档。
_MAX_ARCHIVE_CHARS = 1_000_000

# TTL：归档是"可回溯"增强而非审计数据，30 天足够覆盖长会话的回溯窗口。
TTL_SECONDS = 30 * 86400


class ToolOutputArchiveService:
    """CRUD for ``tool_output_archives``（静态方法风格，对齐 MessageService）。"""

    COLLECTION = "tool_output_archives"

    @staticmethod
    def _collection():
        return get_database()[ToolOutputArchiveService.COLLECTION]

    @staticmethod
    async def ensure_indexes() -> None:
        col = ToolOutputArchiveService._collection()
        # 唯一复合索引：insert-if-absent 的并发防线（重复压缩回调不覆盖）。
        await col.create_index(
            [("thread_id", 1), ("tool_call_id", 1)],
            unique=True,
            name="idx_tool_archive_thread_tcid",
        )
        # TTL: created_at MUST be a BSON date for the TTL monitor to expire docs.
        await col.create_index(
            "created_at",
            expireAfterSeconds=ToolOutputArchiveService.TTL_SECONDS,
            name="idx_tool_archive_ttl",
        )
        logger.info("ToolOutputArchive indexes ensured")

    @staticmethod
    async def archive(
        thread_id: str,
        tool_call_id: str,
        content: str,
        *,
        tool_name: str = "",
    ) -> None:
        """归档一条工具结果原文（insert-if-absent，已存在则忽略）。

        唯一调用方是 harness_integration.context 的压缩 formatter 调度；
        任何失败只记日志，不上抛（压缩主流程不受影响）。
        """
        from pymongo.errors import DuplicateKeyError

        if not thread_id or not tool_call_id:
            return
        doc: dict[str, Any] = {
            "thread_id": thread_id,
            "tool_call_id": tool_call_id,
            "tool_name": tool_name,
            "content": content[:_MAX_ARCHIVE_CHARS],
            "created_at": utc_now(),  # BSON date（TTL 依赖）
        }
        if len(content) > _MAX_ARCHIVE_CHARS:
            doc["content"] += f"\n[归档上限 {_MAX_ARCHIVE_CHARS} 字符，已截断]"
        try:
            await ToolOutputArchiveService._collection().insert_one(doc)
        except DuplicateKeyError:
            pass  # 渐进式压缩的后续回调：首次归档的完整原文优先，不覆盖
        except Exception:
            logger.debug(
                "tool_output_archive_failed",
                thread_id=thread_id,
                tool_call_id=tool_call_id,
            )

    @staticmethod
    async def get(thread_id: str, tool_call_id: str) -> str | None:
        """按 (thread_id, tool_call_id) 取归档原文；未命中返回 None。"""
        doc = await ToolOutputArchiveService._collection().find_one(
            {"thread_id": thread_id, "tool_call_id": tool_call_id},
            {"content": 1},
        )
        if doc is None:
            return None
        content = doc.get("content")
        return content if isinstance(content, str) else None

    @staticmethod
    async def delete_for_thread(thread_id: str) -> int:
        """删除一个 thread 的全部归档（会话级联清理预留）。"""
        result = await ToolOutputArchiveService._collection().delete_many(
            {"thread_id": thread_id}
        )
        return result.deleted_count or 0

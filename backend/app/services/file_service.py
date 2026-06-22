"""File management service — CRUD operations and usage tracking.

FileService 提供文件的统一管理接口，包括创建、查询、删除等操作。
文件作为一等公民，所有使用方通过 FileUsage 引用。
"""
import hashlib
from typing import Any

from loguru import logger

from app.db.mongodb import get_database
from app.models.base import generate_id, utc_now
from app.models.file_library import FileConsumerKind, FileRef, FileUsage
from app.services.file_storage import FileStorage


class FileService:
    """文件管理服务层。

    提供文件的 CRUD 操作和使用记录管理。
    FileRef 是独立聚合，FileUsage 跟踪所有引用方。
    """

    FILE_REFS_COLLECTION = "file_refs"
    FILE_USAGES_COLLECTION = "file_usages"

    def __init__(self, storage: FileStorage):
        """初始化文件服务。

        Args:
            storage: 文件存储后端实例
        """
        self._storage = storage

    def _file_refs(self):
        """获取 file_refs 集合。"""
        return get_database().file_refs

    def _file_usages(self):
        """获取 file_usages 集合。"""
        return get_database().file_usages

    # ------------------------------------------------------------------
    # CRUD 操作
    # ------------------------------------------------------------------

    async def create(
        self,
        data: bytes,
        filename: str,
        mime_type: str,
        owner_user_id: str,
        origin_kind: FileConsumerKind,
        origin_id: str,
    ) -> FileRef:
        """创建文件引用。

        计算 sha256、生成 file_id、构建 storage_key、调用 FileStorage.save + MongoDB 插入。

        Args:
            data: 文件字节流
            filename: 原始文件名
            mime_type: MIME 类型
            owner_user_id: 所属用户 ID
            origin_kind: 最初来源类型
            origin_id: 来源 ID（如 msg_xxx / cron_xxx / user_xxx）

        Returns:
            创建的 FileRef 实例
        """
        file_id = generate_id("file")
        sha256 = hashlib.sha256(data).hexdigest()
        storage_key = f"{owner_user_id}/files/{file_id}"

        # 保存到存储后端
        await self._storage.save(storage_key, data)

        # 创建 FileRef
        file_ref = FileRef(
            id=file_id,
            owner_user_id=owner_user_id,
            storage_key=storage_key,
            name=filename,
            size=len(data),
            mime_type=mime_type,
            sha256=sha256,
            origin_kind=origin_kind,
            origin_id=origin_id,
        )

        # 插入 MongoDB
        await self._file_refs().insert_one(file_ref.model_dump(by_alias=True))

        logger.info(
            "file_created",
            file_id=file_id,
            owner_user_id=owner_user_id,
            filename=filename,
            size=len(data),
        )

        return file_ref

    async def get(self, file_id: str) -> FileRef | None:
        """按 ID 查询文件。

        Args:
            file_id: 文件 ID

        Returns:
            FileRef 实例，不存在返回 None
        """
        doc = await self._file_refs().find_one({"_id": file_id})
        if doc is None:
            return None
        return FileRef(**doc)

    async def list_by_owner(
        self, owner_user_id: str, page: int = 1, page_size: int = 20,
        status: str | None = None,
    ) -> tuple[list[FileRef], int]:
        """按 owner 分页查询文件列表。

        Args:
            owner_user_id: 所属用户 ID
            page: 页码（从 1 开始）
            page_size: 每页大小
            status: 可选状态过滤（如 "active"、"trashed"）

        Returns:
            (文件列表, 总数) 元组
        """
        query: dict[str, Any] = {"owner_user_id": owner_user_id}
        if status is not None:
            query["status"] = status

        # 查询总数
        total = await self._file_refs().count_documents(query)

        # 分页查询
        cursor = (
            self._file_refs()
            .find(query)
            .sort("created_at", -1)
            .skip((page - 1) * page_size)
            .limit(page_size)
        )
        docs = await cursor.to_list()

        files = [FileRef(**doc) for doc in docs]
        return files, total

    async def delete(self, file_id: str, force: bool = False) -> bool:
        """删除文件。

        force=False 时执行软删除（status → trashed）；
        force=True 时级联删除所有 usage + 物理文件 + DB 记录。

        Args:
            file_id: 文件 ID
            force: 是否强制删除（级联删除所有 usage）

        Returns:
            True 如果删除成功，False 如果文件不存在
        """
        file_ref = await self.get(file_id)
        if file_ref is None:
            return False

        if not force:
            # 软删除：仅标记状态为 trashed
            await self.update_status(file_id, "trashed")
            logger.info("file_soft_deleted", file_id=file_id)
            return True

        # force=True：级联删除所有 usage
        usage_count = await self._file_usages().count_documents({"file_id": file_id})
        if usage_count > 0:
            await self._file_usages().delete_many({"file_id": file_id})
            logger.info(
                "file_usages_cascade_deleted",
                file_id=file_id,
                deleted_count=usage_count,
            )

        # 删除物理文件
        await self._storage.delete(file_ref.storage_key)

        # 删除 MongoDB 记录
        await self._file_refs().delete_one({"_id": file_id})

        logger.info("file_hard_deleted", file_id=file_id)
        return True

    async def update_status(self, file_id: str, status: str) -> bool:
        """更新文件状态。

        Args:
            file_id: 文件 ID
            status: 新状态（active / trashed）

        Returns:
            True 如果更新成功，False 如果文件不存在
        """
        result = await self._file_refs().update_one(
            {"_id": file_id},
            {"$set": {"status": status, "updated_at": utc_now().isoformat()}},
        )
        return result.modified_count > 0

    # ------------------------------------------------------------------
    # Usage 管理
    # ------------------------------------------------------------------

    async def add_usage(
        self,
        file_id: str,
        consumer_kind: FileConsumerKind,
        consumer_id: str,
        expires_at: str | None = None,
    ) -> FileUsage:
        """添加使用记录。

        唯一约束冲突时返回已有记录（幂等操作）。

        Args:
            file_id: 文件 ID
            consumer_kind: 消费者类型
            consumer_id: 消费者 ID
            expires_at: 到期时间（None 表示长期持有）

        Returns:
            FileUsage 实例
        """
        from pymongo.errors import DuplicateKeyError

        usage = FileUsage(
            file_id=file_id,
            consumer_kind=consumer_kind,
            consumer_id=consumer_id,
            expires_at=expires_at,
        )

        try:
            await self._file_usages().insert_one(usage.model_dump(by_alias=True))
            logger.info(
                "file_usage_added",
                file_id=file_id,
                consumer_kind=consumer_kind.value,
                consumer_id=consumer_id,
            )
            return usage
        except DuplicateKeyError:
            # 唯一约束冲突，返回已有记录
            existing = await self._file_usages().find_one(
                {
                    "file_id": file_id,
                    "consumer_kind": consumer_kind,
                    "consumer_id": consumer_id,
                }
            )
            if existing:
                return FileUsage(**existing)
            # 理论上不会走到这里
            raise

    async def remove_usage(
        self,
        file_id: str,
        consumer_kind: FileConsumerKind,
        consumer_id: str,
    ) -> bool:
        """移除使用记录。

        Args:
            file_id: 文件 ID
            consumer_kind: 消费者类型
            consumer_id: 消费者 ID

        Returns:
            True 如果移除成功，False 如果记录不存在
        """
        result = await self._file_usages().delete_one(
            {
                "file_id": file_id,
                "consumer_kind": consumer_kind,
                "consumer_id": consumer_id,
            }
        )

        if result.deleted_count > 0:
            logger.info(
                "file_usage_removed",
                file_id=file_id,
                consumer_kind=consumer_kind.value,
                consumer_id=consumer_id,
            )
            return True
        return False

    async def list_usages(self, file_id: str) -> list[FileUsage]:
        """查询文件的所有使用记录。

        Args:
            file_id: 文件 ID

        Returns:
            FileUsage 列表
        """
        cursor = self._file_usages().find({"file_id": file_id})
        docs = await cursor.to_list()
        return [FileUsage(**doc) for doc in docs]

    async def has_usages(self, file_id: str) -> bool:
        """检查文件是否还有引用。

        Args:
            file_id: 文件 ID

        Returns:
            True 如果还有引用，否则 False
        """
        count = await self._file_usages().count_documents({"file_id": file_id})
        return count > 0

    async def cleanup_expired_usages(self) -> int:
        """清理过期的 FileUsage 记录，并删除无引用且已 trashed 的文件。

        Returns:
            清理的 expired usage 数量
        """
        now = utc_now().isoformat()

        # 删除所有已过期的 usage
        result = await self._file_usages().delete_many(
            {"expires_at": {"$ne": None, "$lt": now}}
        )
        deleted_count = result.deleted_count

        if deleted_count > 0:
            logger.info("expired_usages_cleaned", count=deleted_count)

        # 清理后，查找无引用且 status=trashed 的文件，硬删除
        trashed_files = await self._file_refs().find(
            {"status": "trashed"}
        ).to_list()

        hard_deleted = 0
        for doc in trashed_files:
            file_id = doc["_id"]
            remaining = await self._file_usages().count_documents({"file_id": file_id})
            if remaining == 0:
                storage_key = doc.get("storage_key", "")
                if storage_key:
                    await self._storage.delete(storage_key)
                await self._file_refs().delete_one({"_id": file_id})
                hard_deleted += 1

        if hard_deleted > 0:
            logger.info("trashed_files_hard_deleted", count=hard_deleted)

        return deleted_count

    async def remove_usages_by_consumer(
        self, consumer_kind: FileConsumerKind, consumer_id: str,
    ) -> int:
        """按消费者删除所有 FileUsage 记录。

        当 Session/Workflow/CronJob 被删除时调用，清理对应消费者的引用。

        Args:
            consumer_kind: 消费者类型
            consumer_id: 消费者 ID

        Returns:
            删除的 usage 数量
        """
        result = await self._file_usages().delete_many(
            {"consumer_kind": consumer_kind, "consumer_id": consumer_id}
        )
        deleted_count = result.deleted_count

        if deleted_count > 0:
            logger.info(
                "consumer_usages_removed",
                consumer_kind=consumer_kind.value,
                consumer_id=consumer_id,
                count=deleted_count,
            )

        return deleted_count

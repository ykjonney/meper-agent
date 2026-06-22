"""Tests for FileService CRUD operations."""
import hashlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.file_library import FileConsumerKind, FileRef
from app.services.file_storage import FileStorage


class TestFileServiceCreate:
    """FileService.create 测试。"""

    @pytest.mark.asyncio
    async def test_create_file_ref_successfully(self) -> None:
        """成功创建文件引用。"""
        mock_storage = AsyncMock(spec=FileStorage)
        mock_db = MagicMock()
        mock_file_refs = MagicMock()
        mock_file_refs.insert_one = AsyncMock()
        mock_db.file_refs = mock_file_refs

        from app.services.file_service import FileService

        service = FileService(storage=mock_storage)
        data = b"test file content"
        filename = "report.xlsx"
        mime_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        owner_user_id = "user_01HXYZ"
        origin_kind = FileConsumerKind.SESSION_MESSAGE
        origin_id = "msg_01DEF"

        with patch("app.services.file_service.get_database", return_value=mock_db):
            file_ref = await service.create(
                data=data,
                filename=filename,
                mime_type=mime_type,
                owner_user_id=owner_user_id,
                origin_kind=origin_kind,
                origin_id=origin_id,
            )

        assert isinstance(file_ref, FileRef)
        assert file_ref.name == filename
        assert file_ref.size == len(data)
        assert file_ref.mime_type == mime_type
        assert file_ref.owner_user_id == owner_user_id
        assert file_ref.origin_kind == origin_kind
        assert file_ref.origin_id == origin_id
        assert file_ref.sha256 == hashlib.sha256(data).hexdigest()
        assert file_ref.storage_key == f"{owner_user_id}/files/{file_ref.id}"

        # 验证存储层被调用
        mock_storage.save.assert_called_once_with(file_ref.storage_key, data)
        # 验证 MongoDB 插入被调用
        mock_file_refs.insert_one.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_calculates_sha256(self) -> None:
        """创建时计算 sha256 哈希。"""
        mock_storage = AsyncMock(spec=FileStorage)
        mock_db = MagicMock()
        mock_file_refs = MagicMock()
        mock_file_refs.insert_one = AsyncMock()
        mock_db.file_refs = mock_file_refs

        from app.services.file_service import FileService

        service = FileService(storage=mock_storage)
        data = b"Hello, World!"
        expected_hash = hashlib.sha256(data).hexdigest()

        with patch("app.services.file_service.get_database", return_value=mock_db):
            file_ref = await service.create(
                data=data,
                filename="test.txt",
                mime_type="text/plain",
                owner_user_id="user_01HXYZ",
                origin_kind=FileConsumerKind.USER_LIBRARY,
                origin_id="user_01HXYZ",
            )

        assert file_ref.sha256 == expected_hash


class TestFileServiceGet:
    """FileService.get 测试。"""

    @pytest.mark.asyncio
    async def test_get_existing_file(self) -> None:
        """获取存在的文件。"""
        mock_storage = AsyncMock(spec=FileStorage)
        mock_db = MagicMock()
        mock_file_refs = MagicMock()

        file_ref = FileRef(
            id="file_01ABC",
            owner_user_id="user_01HXYZ",
            storage_key="user_01HXYZ/files/file_01ABC",
            name="test.pdf",
            size=1000,
            sha256="sha256hash",
            origin_kind=FileConsumerKind.WORKFLOW_RUN,
            origin_id="run_01GHI",
        )
        mock_file_refs.find_one = AsyncMock(
            return_value=file_ref.model_dump(by_alias=True)
        )
        mock_db.file_refs = mock_file_refs

        from app.services.file_service import FileService

        service = FileService(storage=mock_storage)

        with patch("app.services.file_service.get_database", return_value=mock_db):
            result = await service.get("file_01ABC")

        assert result is not None
        assert result.id == file_ref.id
        assert result.name == "test.pdf"

    @pytest.mark.asyncio
    async def test_get_nonexistent_file(self) -> None:
        """获取不存在的文件返回 None。"""
        mock_storage = AsyncMock(spec=FileStorage)
        mock_db = MagicMock()
        mock_file_refs = MagicMock()
        mock_file_refs.find_one = AsyncMock(return_value=None)
        mock_db.file_refs = mock_file_refs

        from app.services.file_service import FileService

        service = FileService(storage=mock_storage)

        with patch("app.services.file_service.get_database", return_value=mock_db):
            result = await service.get("nonexistent")

        assert result is None


class TestFileServiceListByOwner:
    """FileService.list_by_owner 测试。"""

    @pytest.mark.asyncio
    async def test_list_files_by_owner(self) -> None:
        """按 owner 分页查询文件。"""
        mock_storage = AsyncMock(spec=FileStorage)
        mock_db = MagicMock()
        mock_file_refs = MagicMock()

        # Mock cursor
        files = [
            FileRef(
                id="file_01ABC",
                owner_user_id="user_01HXYZ",
                storage_key="user_01HXYZ/files/file_01ABC",
                name="file1.pdf",
                size=100,
                sha256="hash1",
                origin_kind=FileConsumerKind.USER_LIBRARY,
                origin_id="user_01HXYZ",
            ).model_dump(by_alias=True),
            FileRef(
                id="file_01DEF",
                owner_user_id="user_01HXYZ",
                storage_key="user_01HXYZ/files/file_01DEF",
                name="file2.pdf",
                size=200,
                sha256="hash2",
                origin_kind=FileConsumerKind.SESSION_MESSAGE,
                origin_id="msg_01GHI",
            ).model_dump(by_alias=True),
        ]
        cursor = MagicMock()
        cursor.to_list = AsyncMock(return_value=files)
        cursor.skip = MagicMock(return_value=cursor)
        cursor.limit = MagicMock(return_value=cursor)
        cursor.sort = MagicMock(return_value=cursor)
        mock_file_refs.find = MagicMock(return_value=cursor)
        mock_file_refs.count_documents = AsyncMock(return_value=2)
        mock_db.file_refs = mock_file_refs

        from app.services.file_service import FileService

        service = FileService(storage=mock_storage)

        with patch("app.services.file_service.get_database", return_value=mock_db):
            result, total = await service.list_by_owner("user_01HXYZ", page=1, page_size=10)

        assert len(result) == 2
        assert total == 2
        assert all(isinstance(f, FileRef) for f in result)


class TestFileServiceDelete:
    """FileService.delete 测试。"""

    @pytest.mark.asyncio
    async def test_delete_file_without_usage_soft_deletes(self) -> None:
        """force=False 时执行软删除（update_status trashed），不删物理文件。"""
        mock_storage = AsyncMock(spec=FileStorage)
        mock_db = MagicMock()
        mock_file_refs = MagicMock()
        mock_file_usages = MagicMock()

        file_ref = FileRef(
            id="file_01ABC",
            owner_user_id="user_01HXYZ",
            storage_key="user_01HXYZ/files/file_01ABC",
            name="test.pdf",
            size=1000,
            sha256="sha256hash",
            origin_kind=FileConsumerKind.USER_LIBRARY,
            origin_id="user_01HXYZ",
        )
        mock_file_refs.find_one = AsyncMock(
            return_value=file_ref.model_dump(by_alias=True)
        )
        mock_file_refs.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
        mock_db.file_refs = mock_file_refs
        mock_db.file_usages = mock_file_usages

        from app.services.file_service import FileService

        service = FileService(storage=mock_storage)

        with patch("app.services.file_service.get_database", return_value=mock_db):
            result = await service.delete("file_01ABC", force=False)

        assert result is True
        # 软删除不删除物理文件，只更新状态
        mock_storage.delete.assert_not_called()
        mock_file_refs.update_one.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_file_with_usage_soft_deletes(self) -> None:
        """有引用的文件 force=False 时仍软删除（不删物理文件、不删 usage）。"""
        mock_storage = AsyncMock(spec=FileStorage)
        mock_db = MagicMock()
        mock_file_refs = MagicMock()
        mock_file_usages = MagicMock()

        file_ref = FileRef(
            id="file_01ABC",
            owner_user_id="user_01HXYZ",
            storage_key="user_01HXYZ/files/file_01ABC",
            name="test.pdf",
            size=1000,
            sha256="sha256hash",
            origin_kind=FileConsumerKind.SESSION_MESSAGE,
            origin_id="msg_01DEF",
        )
        mock_file_refs.find_one = AsyncMock(
            return_value=file_ref.model_dump(by_alias=True)
        )
        mock_file_refs.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
        mock_db.file_refs = mock_file_refs
        mock_db.file_usages = mock_file_usages

        from app.services.file_service import FileService

        service = FileService(storage=mock_storage)

        with patch("app.services.file_service.get_database", return_value=mock_db):
            result = await service.delete("file_01ABC", force=False)

        assert result is True
        # 软删除不删物理文件
        mock_storage.delete.assert_not_called()
        # 软删除不删 usage
        mock_file_usages.delete_many.assert_not_called()
        mock_file_refs.update_one.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_file_with_usage_force_deletes(self) -> None:
        """有引用的文件 force=True 时级联删除。"""
        mock_storage = AsyncMock(spec=FileStorage)
        mock_db = MagicMock()
        mock_file_refs = MagicMock()
        mock_file_usages = MagicMock()

        file_ref = FileRef(
            id="file_01ABC",
            owner_user_id="user_01HXYZ",
            storage_key="user_01HXYZ/files/file_01ABC",
            name="test.pdf",
            size=1000,
            sha256="sha256hash",
            origin_kind=FileConsumerKind.SESSION_MESSAGE,
            origin_id="msg_01DEF",
        )
        mock_file_refs.find_one = AsyncMock(
            return_value=file_ref.model_dump(by_alias=True)
        )
        mock_file_refs.delete_one = AsyncMock()
        mock_file_usages.count_documents = AsyncMock(return_value=1)
        mock_file_usages.delete_many = AsyncMock()
        mock_db.file_refs = mock_file_refs
        mock_db.file_usages = mock_file_usages

        from app.services.file_service import FileService

        service = FileService(storage=mock_storage)

        with patch("app.services.file_service.get_database", return_value=mock_db):
            result = await service.delete("file_01ABC", force=True)

        assert result is True
        mock_file_usages.delete_many.assert_called_once_with({"file_id": "file_01ABC"})
        mock_storage.delete.assert_called_once()
        mock_file_refs.delete_one.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_file(self) -> None:
        """删除不存在的文件返回 False。"""
        mock_storage = AsyncMock(spec=FileStorage)
        mock_db = MagicMock()
        mock_file_refs = MagicMock()
        mock_file_refs.find_one = AsyncMock(return_value=None)
        mock_db.file_refs = mock_file_refs

        from app.services.file_service import FileService

        service = FileService(storage=mock_storage)

        with patch("app.services.file_service.get_database", return_value=mock_db):
            result = await service.delete("nonexistent", force=False)

        assert result is False


class TestFileServiceUpdateStatus:
    """FileService.update_status 测试。"""

    @pytest.mark.asyncio
    async def test_update_status_to_trashed(self) -> None:
        """更新状态为 trashed。"""
        mock_storage = AsyncMock(spec=FileStorage)
        mock_db = MagicMock()
        mock_file_refs = MagicMock()
        mock_file_refs.update_one = AsyncMock(return_value=MagicMock(modified_count=1))
        mock_db.file_refs = mock_file_refs

        from app.services.file_service import FileService

        service = FileService(storage=mock_storage)

        with patch("app.services.file_service.get_database", return_value=mock_db):
            result = await service.update_status("file_01ABC", "trashed")

        assert result is True
        mock_file_refs.update_one.assert_called_once()


class TestFileServiceCleanupExpiredUsages:
    """FileService.cleanup_expired_usages 测试。"""

    @pytest.mark.asyncio
    async def test_cleanup_expired_usages_deletes_and_hard_deletes_trashed(self) -> None:
        """清理过期 usage，无引用且 trashed 的文件被硬删除。"""
        mock_storage = AsyncMock(spec=FileStorage)
        mock_db = MagicMock()
        mock_file_refs = MagicMock()
        mock_file_usages = MagicMock()

        trashed_file = FileRef(
            id="file_TRASH",
            owner_user_id="user_01HXYZ",
            storage_key="user_01HXYZ/files/file_TRASH",
            name="old.pdf",
            size=500,
            sha256="hash",
            origin_kind=FileConsumerKind.USER_LIBRARY,
            origin_id="user_01HXYZ",
            status="trashed",
        )
        # find 返回 trashed 文件列表
        cursor = MagicMock()
        cursor.to_list = AsyncMock(return_value=[trashed_file.model_dump(by_alias=True)])
        mock_file_refs.find = MagicMock(return_value=cursor)
        mock_file_refs.delete_one = AsyncMock()
        mock_file_usages.delete_many = AsyncMock(return_value=MagicMock(deleted_count=2))
        # 清理后无剩余 usage
        mock_file_usages.count_documents = AsyncMock(return_value=0)
        mock_db.file_refs = mock_file_refs
        mock_db.file_usages = mock_file_usages

        from app.services.file_service import FileService

        service = FileService(storage=mock_storage)

        with patch("app.services.file_service.get_database", return_value=mock_db):
            count = await service.cleanup_expired_usages()

        assert count == 2
        # trashed 文件无引用 → 硬删除
        mock_storage.delete.assert_called_once_with(trashed_file.storage_key)
        mock_file_refs.delete_one.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_keeps_trashed_file_with_remaining_usages(self) -> None:
        """trashed 文件仍有未过期 usage 时保留。"""
        mock_storage = AsyncMock(spec=FileStorage)
        mock_db = MagicMock()
        mock_file_refs = MagicMock()
        mock_file_usages = MagicMock()

        trashed_file = FileRef(
            id="file_TRASH2",
            owner_user_id="user_01HXYZ",
            storage_key="user_01HXYZ/files/file_TRASH2",
            name="still_used.pdf",
            size=500,
            sha256="hash",
            origin_kind=FileConsumerKind.USER_LIBRARY,
            origin_id="user_01HXYZ",
            status="trashed",
        )
        cursor = MagicMock()
        cursor.to_list = AsyncMock(return_value=[trashed_file.model_dump(by_alias=True)])
        mock_file_refs.find = MagicMock(return_value=cursor)
        mock_file_usages.delete_many = AsyncMock(return_value=MagicMock(deleted_count=1))
        # 仍有剩余 usage
        mock_file_usages.count_documents = AsyncMock(return_value=1)
        mock_db.file_refs = mock_file_refs
        mock_db.file_usages = mock_file_usages

        from app.services.file_service import FileService

        service = FileService(storage=mock_storage)

        with patch("app.services.file_service.get_database", return_value=mock_db):
            count = await service.cleanup_expired_usages()

        assert count == 1
        # 有引用，不硬删除
        mock_storage.delete.assert_not_called()


class TestFileServiceRemoveUsagesByConsumer:
    """FileService.remove_usages_by_consumer 测试。"""

    @pytest.mark.asyncio
    async def test_remove_usages_by_consumer(self) -> None:
        """按消费者删除所有 usage 记录。"""
        mock_storage = AsyncMock(spec=FileStorage)
        mock_db = MagicMock()
        mock_file_usages = MagicMock()
        mock_file_usages.delete_many = AsyncMock(return_value=MagicMock(deleted_count=3))
        mock_db.file_usages = mock_file_usages

        from app.services.file_service import FileService

        service = FileService(storage=mock_storage)

        with patch("app.services.file_service.get_database", return_value=mock_db):
            count = await service.remove_usages_by_consumer(
                FileConsumerKind.SESSION_MESSAGE, "sess_01ABC"
            )

        assert count == 3
        mock_file_usages.delete_many.assert_called_once_with(
            {
                "consumer_kind": FileConsumerKind.SESSION_MESSAGE,
                "consumer_id": "sess_01ABC",
            }
        )

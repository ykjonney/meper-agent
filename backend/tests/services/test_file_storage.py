"""Tests for FileStorage abstraction and LocalFileStorage implementation."""
import pytest
from app.services.file_storage import FileStorage, LocalFileStorage


class TestLocalFileStorage:
    """LocalFileStorage 本地实现测试。"""

    @pytest.fixture
    def storage(self, tmp_path):
        """创建使用临时目录的 LocalFileStorage 实例。"""
        return LocalFileStorage(base_dir=tmp_path)

    @pytest.mark.asyncio
    async def test_save_and_load(self, storage: LocalFileStorage) -> None:
        """保存后能正确加载。"""
        data = b"Hello, World!"
        await storage.save("user_01HXYZ/files/file_01ABC", data)
        loaded = await storage.load("user_01HXYZ/files/file_01ABC")
        assert loaded == data

    @pytest.mark.asyncio
    async def test_save_creates_parent_directories(
        self, storage: LocalFileStorage
    ) -> None:
        """save 自动创建父目录。"""
        data = b"test data"
        await storage.save("user_01HXYZ/files/deep/nested/file_01ABC", data)
        loaded = await storage.load("user_01HXYZ/files/deep/nested/file_01ABC")
        assert loaded == data

    @pytest.mark.asyncio
    async def test_load_nonexistent_file_raises_error(
        self, storage: LocalFileStorage
    ) -> None:
        """加载不存在的文件抛出 FileNotFoundError。"""
        with pytest.raises(FileNotFoundError):
            await storage.load("user_01HXYZ/files/nonexistent")

    @pytest.mark.asyncio
    async def test_delete_existing_file(self, storage: LocalFileStorage) -> None:
        """删除已存在的文件返回 True。"""
        data = b"test"
        await storage.save("user_01HXYZ/files/file_01ABC", data)
        result = await storage.delete("user_01HXYZ/files/file_01ABC")
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_nonexistent_file(self, storage: LocalFileStorage) -> None:
        """删除不存在的文件返回 False。"""
        result = await storage.delete("user_01HXYZ/files/nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_exists_returns_true_for_existing_file(
        self, storage: LocalFileStorage
    ) -> None:
        """存在的文件 exists 返回 True。"""
        data = b"test"
        await storage.save("user_01HXYZ/files/file_01ABC", data)
        assert await storage.exists("user_01HXYZ/files/file_01ABC") is True

    @pytest.mark.asyncio
    async def test_exists_returns_false_for_nonexistent_file(
        self, storage: LocalFileStorage
    ) -> None:
        """不存在的文件 exists 返回 False。"""
        assert await storage.exists("user_01HXYZ/files/nonexistent") is False

    @pytest.mark.asyncio
    async def test_get_size_of_existing_file(
        self, storage: LocalFileStorage
    ) -> None:
        """获取已存在文件的大小。"""
        data = b"Hello, World!"  # 13 bytes
        await storage.save("user_01HXYZ/files/file_01ABC", data)
        size = await storage.get_size("user_01HXYZ/files/file_01ABC")
        assert size == 13

    @pytest.mark.asyncio
    async def test_get_size_of_nonexistent_file_raises_error(
        self, storage: LocalFileStorage
    ) -> None:
        """获取不存在文件的大小抛出 FileNotFoundError。"""
        with pytest.raises(FileNotFoundError):
            await storage.get_size("user_01HXYZ/files/nonexistent")

    @pytest.mark.asyncio
    async def test_path_traversal_prevention(self, storage: LocalFileStorage) -> None:
        """路径穿越攻击被阻止。"""
        with pytest.raises(ValueError, match="Path traversal"):
            await storage.save("../../../etc/passwd", b"malicious")

    @pytest.mark.asyncio
    async def test_absolute_path_outside_base_rejected(
        self, storage: LocalFileStorage
    ) -> None:
        """指向 base 外的绝对路径被拒绝。"""
        with pytest.raises(ValueError, match="Path traversal"):
            await storage.save("/etc/passwd", b"malicious")

    @pytest.mark.asyncio
    async def test_large_file_handling(self, storage: LocalFileStorage) -> None:
        """大文件（1MB）处理正常。"""
        data = b"x" * (1024 * 1024)  # 1MB
        await storage.save("user_01HXYZ/files/large_file", data)
        loaded = await storage.load("user_01HXYZ/files/large_file")
        assert loaded == data
        size = await storage.get_size("user_01HXYZ/files/large_file")
        assert size == 1024 * 1024

    @pytest.mark.asyncio
    async def test_binary_data_handling(self, storage: LocalFileStorage) -> None:
        """二进制数据（含 null 字节）处理正常。"""
        data = bytes(range(256))  # 所有字节值
        await storage.save("user_01HXYZ/files/binary_file", data)
        loaded = await storage.load("user_01HXYZ/files/binary_file")
        assert loaded == data

    @pytest.mark.asyncio
    async def test_overwrite_existing_file(self, storage: LocalFileStorage) -> None:
        """覆盖已存在的文件。"""
        original = b"original content"
        new_data = b"new content"
        await storage.save("user_01HXYZ/files/file_01ABC", original)
        await storage.save("user_01HXYZ/files/file_01ABC", new_data)
        loaded = await storage.load("user_01HXYZ/files/file_01ABC")
        assert loaded == new_data


class TestFileStorageAbstraction:
    """FileStorage 抽象类测试。"""

    def test_file_storage_is_abstract(self) -> None:
        """FileStorage 是抽象类，不能直接实例化。"""
        with pytest.raises(TypeError):
            FileStorage()  # type: ignore[abstract]

    def test_local_file_storage_inherits_from_file_storage(self) -> None:
        """LocalFileStorage 继承自 FileStorage。"""
        assert issubclass(LocalFileStorage, FileStorage)

    @pytest.mark.asyncio
    async def test_local_file_storage_implements_all_methods(
        self, tmp_path
    ) -> None:
        """LocalFileStorage 实现了所有抽象方法。"""
        storage = LocalFileStorage(base_dir=tmp_path)
        # 验证所有方法存在且可调用
        assert callable(storage.save)
        assert callable(storage.load)
        assert callable(storage.delete)
        assert callable(storage.exists)
        assert callable(storage.get_size)

"""File storage abstraction and local filesystem implementation.

FileStorage 抽象类定义文件存储的标准接口，支持不同的存储后端。
LocalFileStorage 是本地文件系统的实现，复用现有 Workspace 基础设施。
"""
from abc import ABC, abstractmethod
from pathlib import Path


class FileStorage(ABC):
    """文件存储抽象基类。

    定义文件存储的标准接口，支持不同的存储后端（本地、OSS、MinIO 等）。
    所有方法均为异步方法，支持高并发场景。
    """

    @abstractmethod
    async def save(self, storage_key: str, data: bytes) -> None:
        """保存文件字节流。

        Args:
            storage_key: 存储路径（相对路径，如 "{user_id}/files/{file_id}"）
            data: 文件字节流

        Raises:
            ValueError: 路径穿越攻击
            OSError: 文件系统错误
        """

    @abstractmethod
    async def load(self, storage_key: str) -> bytes:
        """加载文件字节流。

        Args:
            storage_key: 存储路径

        Returns:
            文件字节流

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 路径穿越攻击
        """

    @abstractmethod
    async def delete(self, storage_key: str) -> bool:
        """删除物理文件。

        Args:
            storage_key: 存储路径

        Returns:
            True 如果文件存在并被删除，False 如果文件不存在

        Raises:
            ValueError: 路径穿越攻击
        """

    @abstractmethod
    async def exists(self, storage_key: str) -> bool:
        """检查文件是否存在。

        Args:
            storage_key: 存储路径

        Returns:
            True 如果文件存在，否则 False

        Raises:
            ValueError: 路径穿越攻击
        """

    @abstractmethod
    async def get_size(self, storage_key: str) -> int:
        """获取文件大小（字节）。

        Args:
            storage_key: 存储路径

        Returns:
            文件大小（字节）

        Raises:
            FileNotFoundError: 文件不存在
            ValueError: 路径穿越攻击
        """


class LocalFileStorage(FileStorage):
    """本地文件系统存储实现。

    复用现有 WorkspaceManager._workspaces_root() 作为存储根目录。
    所有路径操作使用 WorkspaceManager.safe_resolve_path 防止路径穿越。
    """

    def __init__(self, base_dir: Path | None = None):
        """初始化本地存储。

        Args:
            base_dir: 存储根目录。如果为 None，使用 WorkspaceManager._workspaces_root()
        """
        if base_dir is None:
            from app.engine.tool.workspace import WorkspaceManager

            self._base_dir = WorkspaceManager._workspaces_root()
        else:
            self._base_dir = base_dir

    def _resolve(self, storage_key: str) -> Path:
        """安全解析路径，防止路径穿越攻击。

        Args:
            storage_key: 存储路径

        Returns:
            解析后的绝对路径

        Raises:
            ValueError: 路径穿越攻击
        """
        from app.engine.tool.workspace import WorkspaceManager

        resolved = WorkspaceManager.safe_resolve_path(self._base_dir, storage_key)
        if resolved is None:
            raise ValueError(f"Path traversal detected: {storage_key}")
        return resolved

    async def save(self, storage_key: str, data: bytes) -> None:
        """保存文件字节流到本地文件系统。"""
        path = self._resolve(storage_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    async def load(self, storage_key: str) -> bytes:
        """从本地文件系统加载文件字节流。"""
        path = self._resolve(storage_key)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {storage_key}")
        return path.read_bytes()

    async def delete(self, storage_key: str) -> bool:
        """删除本地文件系统中的文件。"""
        path = self._resolve(storage_key)
        if not path.exists():
            return False
        path.unlink()
        return True

    async def exists(self, storage_key: str) -> bool:
        """检查本地文件是否存在。"""
        return self._resolve(storage_key).exists()

    async def get_size(self, storage_key: str) -> int:
        """获取本地文件大小。"""
        path = self._resolve(storage_key)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {storage_key}")
        return path.stat().st_size

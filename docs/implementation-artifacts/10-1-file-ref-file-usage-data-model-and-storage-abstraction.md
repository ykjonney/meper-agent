---
baseline_commit: d25537c798d51080e68ae21db677129aea4bdca0
---

# Story 10.1: File 领域模型与存储抽象

**Epic:** Epic 10 — 文件管理
**Status:** review
**Story ID:** 10-1
**Story Key:** 10-1-file-ref-file-usage-data-model-and-storage-abstraction

## Story

As a 开发者，
I want 建立文件管理的领域模型与存储抽象层，让文件成为独立的一等公民，
So that 聊天附件、Workflow 输入、定时任务配置等多种场景都能通过统一的 file_id 引用文件，不再被 session 绑定。

> ⚠️ **关键背景**：
> - 当前项目已有 `WorkspaceManager`（`backend/app/engine/tool/workspace.py`）管理 `{user_id}/{session_id}/{input,output,tmp}/` 目录树，用于 session 工作区
> - 但 Workspace 强绑 session，无法支撑定时任务、用户文件库、Workflow 长期引用等场景
> - 本 Story 引入 File 作为**独立聚合**，不归属任何 consumer，所有使用方通过 FileUsage 引用
> - 文件物理存储复用现有 `WorkspaceManager._workspaces_root()` 下的 `{user_id}/files/` 目录
>
> 🔧 **范围说明**：
> 1. **本 Story 只做领域模型 + 存储抽象 + 基础 CRUD**
> 2. 不做上传/下载 API（Story 10-2）
> 3. 不做聊天集成（Story 10-3）
> 4. 不做自动清理/TTL/孤儿回收（主人决策：仅支持手动删除）
> 5. 不做 OSS 等远程存储抽象（仅本地文件系统）

## 核心设计原则

### File 是一等公民

```
┌─────────────────────────────────────────────┐
│  FileRef (独立聚合)                          │
│  ──────────────────────────────              │
│  file_id: "file_xxx"                        │
│  owner_user_id: "user_xxx"                  │
│  storage_key: "{user_id}/files/{file_id}"   │
│  name, size, mime_type, sha256              │
│  status: active / trashed                   │
│  origin_kind + origin_id（最初来源）          │
└─────────────────────────────────────────────┘
              │
              │ 1 : N
              ▼
┌─────────────────────────────────────────────┐
│  FileUsage（使用记录）                       │
│  ──────────────────────────────              │
│  file_id → FileRef                          │
│  consumer_kind: USER_LIBRARY /              │
│                 SESSION_MESSAGE /            │
│                 WORKFLOW_RUN /               │
│                 CRON_JOB                     │
│  consumer_id: 具体消费者 ID                  │
└─────────────────────────────────────────────┘
```

### 为什么不直接绑 session？

- ✅ 定时任务的模板文件：session 没了文件还在
- ✅ Workflow 多节点共享同一文件：不重复上传
- ✅ 用户文件库：跨 session 复用
- ✅ 删除安全：某方删引用不影响其他使用方

### consumer_kind 枚举

```python
class FileConsumerKind(StrEnum):
    USER_LIBRARY = "user_library"           # 用户文件库（长期持有）
    SESSION_MESSAGE = "session_message"     # 聊天消息附件
    WORKFLOW_RUN = "workflow_run"           # Workflow 运行时引用
    CRON_JOB = "cron_job"                   # 定时任务配置（长期持有）
```

后续新增消费者（如 API Token、共享链接）**只需加枚举值**，模型零改动。

## Acceptance Criteria

### AC1: FileConsumerKind 枚举定义
**Given** 系统需要跟踪文件被哪些场景使用
**When** 审查 `backend/app/models/file_library.py`
**Then** 定义 `FileConsumerKind(StrEnum)` 枚举，包含：
  - `USER_LIBRARY = "user_library"`
  - `SESSION_MESSAGE = "session_message"`
  - `WORKFLOW_RUN = "workflow_run"`
  - `CRON_JOB = "cron_job"`

### AC2: FileRef 数据模型定义
**Given** 文件是一等公民，需要独立存储
**When** 审查 `backend/app/models/file_library.py`
**Then** 定义 `FileRef` Pydantic 模型包含字段：
  - `id: str`（格式 `file_{ULID}`，alias `_id`）
  - `owner_user_id: str`（所属用户，权限根）
  - `storage_key: str`（存储路径，格式 `{user_id}/files/{file_id}`）
  - `name: str`（原始文件名）
  - `size: int`（字节数，≥0）
  - `mime_type: str`（MIME 类型，默认 `application/octet-stream`）
  - `sha256: str`（文件内容哈希，用于去重校验）
  - `origin_kind: FileConsumerKind`（最初来源类型）
  - `origin_id: str`（来源 ID，如 msg_xxx / cron_xxx / user_xxx）
  - `status: str`（默认 `"active"`，可取值 `active` / `trashed`）
  - `created_at: str`（ISO 时间戳）
  - `updated_at: str`（ISO 时间戳）
**And** 使用 `ConfigDict(populate_by_name=True)`，`id` 字段 `alias="_id"`
**And** `id` 默认值通过 `generate_id("file")` 生成
**And** `created_at` / `updated_at` 默认值通过 `utc_now().isoformat()` 生成

### AC3: FileUsage 数据模型定义
**Given** 文件使用记录需要跟踪所有引用方
**When** 审查 `backend/app/models/file_library.py`
**Then** 定义 `FileUsage` Pydantic 模型包含字段：
  - `id: str`（格式 `fu_{ULID}`，alias `_id`）
  - `file_id: str`（指向 FileRef.id）
  - `consumer_kind: FileConsumerKind`（消费者类型）
  - `consumer_id: str`（消费者 ID）
  - `granted_at: str`（引用授予时间，ISO 时间戳）
  - `expires_at: str | None`（到期时间，None 表示长期持有）
**And** 联合唯一约束：`(file_id, consumer_kind, consumer_id)` 不可重复
**And** 使用 `ConfigDict(populate_by_name=True)`，`id` 字段 `alias="_id"`

### AC4: FileStorage 存储抽象类
**Given** 文件存储需要抽象层（即使当前只有本地实现）
**When** 审查 `backend/app/services/file_storage.py`
**Then** 定义 `FileStorage` 抽象类（ABC），包含方法：
  - `async save(storage_key: str, data: bytes) -> None` — 保存文件字节流
  - `async load(storage_key: str) -> bytes` — 加载文件字节流
  - `async delete(storage_key: str) -> bool` — 删除物理文件，返回是否存在
  - `async exists(storage_key: str) -> bool` — 文件是否存在
  - `async get_size(storage_key: str) -> int` — 获取文件大小（字节）
**And** 抽象类不关心具体存储后端，只定义接口契约

### AC5: LocalFileStorage 本地实现
**Given** 当前阶段使用本地文件系统存储
**When** 审查 `backend/app/services/file_storage.py`
**Then** 定义 `LocalFileStorage(FileStorage)` 实现类
**And** 构造函数接受 `base_dir: Path` 参数（默认使用 `WorkspaceManager._workspaces_root()`）
**And** `save` 方法：将字节流写入 `{base_dir}/{storage_key}`，自动创建父目录
**And** `load` 方法：读取文件字节流，文件不存在抛出 `FileNotFoundError`
**And** `delete` 方法：调用 `Path.unlink(missing_ok=True)`，返回是否成功
**And** `exists` 方法：调用 `Path.exists()`
**And** `get_size` 方法：调用 `Path.stat().st_size`
**And** 所有路径操作使用 `Path.resolve()` 防止路径穿越
**And** 复用现有 `WorkspaceManager.safe_resolve_path` 进行安全校验

### AC6: FileService 基础 CRUD
**Given** 文件管理需要统一的服务层
**When** 审查 `backend/app/services/file_service.py`
**Then** 定义 `FileService` 类，包含以下静态方法：
  - `create(data: bytes, filename: str, mime_type: str, owner_user_id: str, origin_kind: FileConsumerKind, origin_id: str) -> FileRef` — 计算 sha256、生成 file_id、构建 storage_key、调用 FileStorage.save + MongoDB 插入
  - `get(file_id: str) -> FileRef | None` — 按 ID 查询
  - `list_by_owner(owner_user_id: str, page: int, page_size: int) -> tuple[list[FileRef], int]` — 按 owner 分页查询
  - `delete(file_id: str, force: bool = False) -> bool` — force=False 标记为 trashed；force=True 检查 FileUsage 数量，有引用返回 False，无引用则删除物理文件 + MongoDB 记录
  - `update_status(file_id: str, status: str) -> bool` — 更新状态
**And** 使用 `FileStorage` 实例（通过依赖注入或全局单例）进行物理文件操作
**And** 使用 MongoDB `file_refs` 集合存储 FileRef
**And** 使用 MongoDB `file_usages` 集合存储 FileUsage

### AC7: FileService Usage 管理
**Given** 文件使用记录需要动态管理
**When** 审查 `backend/app/services/file_service.py`
**Then** 定义 `FileService` 包含以下静态方法：
  - `add_usage(file_id: str, consumer_kind: FileConsumerKind, consumer_id: str, expires_at: str | None = None) -> FileUsage` — 添加使用记录（唯一约束冲突时返回已有记录）
  - `remove_usage(file_id: str, consumer_kind: FileConsumerKind, consumer_id: str) -> bool` — 移除使用记录，返回是否存在
  - `list_usages(file_id: str) -> list[FileUsage]` — 查询文件的所有使用记录
  - `has_usages(file_id: str) -> bool` — 文件是否还有引用
**And** `add_usage` 支持 `expires_at` 参数（None 表示长期持有）
**And** 所有方法均通过 MongoDB 操作 `file_usages` 集合

### AC8: 数据库索引
**Given** file_refs 和 file_usages 集合写入 MongoDB
**When** 审查 `backend/app/db/indexes.py`
**Then** `file_refs` 集合创建索引：
  - `owner_user_id` + `created_at` DESC 复合索引（`idx_file_refs_owner_created`）— 按用户查询文件列表
  - `sha256` 普通索引（`idx_file_refs_sha256`）— 去重查询
  - `status` 普通索引（`idx_file_refs_status`）— 状态过滤
**And** `file_usages` 集合创建索引：
  - `file_id` 普通索引（`idx_file_usages_file_id`）— 查询文件的所有引用
  - `(consumer_kind, consumer_id)` 复合索引（`idx_file_usages_consumer`）— 按消费者查询
  - `(file_id, consumer_kind, consumer_id)` 唯一索引（`uq_file_usages_unique`）— 防重复引用

### AC9: 单元测试覆盖
**Given** 本 Story 的所有功能
**When** 运行测试套件
**Then** 覆盖以下场景：
  - FileRef 模型字段验证（必填字段、默认值、枚举值）
  - FileUsage 模型字段验证
  - FileConsumerKind 枚举完整性
  - LocalFileStorage 的 save/load/delete/exists/get_size（使用临时目录）
  - LocalFileStorage 路径穿越防护（`../../../etc/passwd` 被拒绝）
  - FileService.create 完整流程（sha256 计算、ID 生成、物理存储、MongoDB 插入）
  - FileService.get 命中 / 未命中
  - FileService.list_by_owner 分页
  - FileService.delete 无引用 / 有引用 / force 模式
  - FileService.add_usage 新增 / 重复幂等
  - FileService.remove_usage 存在 / 不存在
  - FileService.list_usages 多引用场景
  - FileService.has_usages 有引用 / 无引用
  - 运行 `cd backend && uv run pytest tests/models/test_file_library.py tests/services/test_file_storage.py tests/services/test_file_service.py -v`

## Tasks / Subtasks

### 后端（Backend）

- [x] **T1: File 领域模型定义** (AC: #1, #2, #3)
  - [x] 新建 `backend/app/models/file_library.py`
  - [x] 定义 `FileConsumerKind(StrEnum)` 枚举（4 个值）
  - [x] 定义 `FileRef` Pydantic 模型（参考 `models/agent.py` / `models/tool.py` 模式）
  - [x] 定义 `FileUsage` Pydantic 模型
  - [x] 使用 `ConfigDict(populate_by_name=True)`，`id` 字段 `alias="_id"`
  - [x] ID 默认值使用 `generate_id("file")` / `generate_id("fu")`
  - [x] 时间戳默认值使用 `utc_now().isoformat()`

- [x] **T2: FileStorage 存储抽象与本地实现** (AC: #4, #5)
  - [x] 新建 `backend/app/services/file_storage.py`
  - [x] 定义 `FileStorage(ABC)` 抽象类，5 个异步方法
  - [x] 定义 `LocalFileStorage(FileStorage)` 实现类
  - [x] 构造函数接受 `base_dir: Path`，默认 `WorkspaceManager._workspaces_root()`
  - [x] 实现 save / load / delete / exists / get_size
  - [x] 所有路径操作使用 `WorkspaceManager.safe_resolve_path` 防穿越
  - [x] 目录不存在时自动 `mkdir(parents=True, exist_ok=True)`

- [x] **T3: FileService CRUD 方法** (AC: #6)
  - [x] 新建 `backend/app/services/file_service.py`
  - [x] 定义 `FileService` 类（实例方法模式，接受 `storage: FileStorage` 依赖）
  - [x] 实现 `create(data, filename, mime_type, owner_user_id, origin_kind, origin_id) -> FileRef`
  - [x] 实现 `get(file_id) -> FileRef | None`
  - [x] 实现 `list_by_owner(owner_user_id, page, page_size) -> tuple[list, int]`
  - [x] 实现 `delete(file_id, force) -> bool`
  - [x] 实现 `update_status(file_id, status) -> bool`
  - [x] sha256 使用 `hashlib.sha256(data).hexdigest()`
  - [x] 修复：FileRef 构造时传入 `id=file_id`，避免生成两个不同 ULID

- [x] **T4: FileService Usage 管理方法** (AC: #7)
  - [x] 在 `backend/app/services/file_service.py` 中继续
  - [x] 实现 `add_usage(file_id, consumer_kind, consumer_id, expires_at) -> FileUsage`
  - [x] 实现 `remove_usage(file_id, consumer_kind, consumer_id) -> bool`
  - [x] 实现 `list_usages(file_id) -> list[FileUsage]`
  - [x] 实现 `has_usages(file_id) -> bool`
  - [x] `add_usage` 处理唯一约束冲突（DuplicateKeyError）时返回已有记录

- [x] **T5: 数据库索引注册** (AC: #8)
  - [x] 修改 `backend/app/db/indexes.py`
  - [x] 在 `create_indexes()` 中添加 `file_refs` 集合索引（3 个）
  - [x] 在 `create_indexes()` 中添加 `file_usages` 集合索引（3 个，含 1 个唯一）

- [x] **T6: Schema 定义（响应体）** (AC: #6)
  - [x] 新建 `backend/app/schemas/file_library.py`
  - [x] 定义 `FileRefResponse` — FileRef 响应体
  - [x] 定义 `FileRefListResponse` — 分页列表响应
  - [x] 定义 `FileUsageResponse` — FileUsage 响应体

- [x] **T7: 单元测试** (AC: #9)
  - [x] 新建 `backend/tests/models/test_file_library.py` — 模型字段验证（16 tests）
  - [x] 新建 `backend/tests/services/test_file_storage.py` — LocalFileStorage 测试（17 tests）
  - [x] 新建 `backend/tests/services/test_file_service.py` — FileService CRUD + Usage 管理测试（10 tests）
  - [x] 运行 `cd backend && uv run pytest tests/models/test_file_library.py tests/services/test_file_storage.py tests/services/test_file_service.py -v`
  - [x] 确保全部 43 个测试通过 ✅

## Dev Notes

### 🔧 技术栈与约定

**后端（FastAPI + Motor + Pydantic）：**
- Python 包管理：**uv**（非 pip/poetry），`uv run pytest`
- Pydantic v2 BaseModel（参考 `models/tool.py` / `models/agent.py`）
- Motor 异步 MongoDB（参考 `services/tool_service.py`）
- 日志：`loguru.logger`，结构化日志
- 测试：pytest + pytest-asyncio（mode=auto）
- 文件存储：当前仅本地文件系统，不引入 OSS / MinIO

### 📐 关键架构约束

**数据模型参考 `models/tool.py` 模式：**
```python
# backend/app/models/file_library.py
from enum import StrEnum
from pydantic import BaseModel, ConfigDict, Field

from app.models.base import generate_id, utc_now


class FileConsumerKind(StrEnum):
    USER_LIBRARY = "user_library"
    SESSION_MESSAGE = "session_message"
    WORKFLOW_RUN = "workflow_run"
    CRON_JOB = "cron_job"


class FileRef(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(default_factory=lambda: generate_id("file"), alias="_id")
    owner_user_id: str
    storage_key: str                          # 格式: {user_id}/files/{file_id}
    name: str                                 # 原始文件名
    size: int = Field(ge=0)                   # 字节数
    mime_type: str = "application/octet-stream"
    sha256: str                               # 文件内容哈希
    origin_kind: FileConsumerKind             # 最初来源类型
    origin_id: str                            # 来源 ID
    status: str = "active"                    # active | trashed
    created_at: str = Field(default_factory=lambda: utc_now().isoformat())
    updated_at: str = Field(default_factory=lambda: utc_now().isoformat())


class FileUsage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(default_factory=lambda: generate_id("fu"), alias="_id")
    file_id: str
    consumer_kind: FileConsumerKind
    consumer_id: str
    granted_at: str = Field(default_factory=lambda: utc_now().isoformat())
    expires_at: str | None = None
```

**FileStorage 抽象类示例：**
```python
# backend/app/services/file_storage.py
from abc import ABC, abstractmethod
from pathlib import Path


class FileStorage(ABC):
    @abstractmethod
    async def save(self, storage_key: str, data: bytes) -> None: ...

    @abstractmethod
    async def load(self, storage_key: str) -> bytes: ...

    @abstractmethod
    async def delete(self, storage_key: str) -> bool: ...

    @abstractmethod
    async def exists(self, storage_key: str) -> bool: ...

    @abstractmethod
    async def get_size(self, storage_key: str) -> int: ...


class LocalFileStorage(FileStorage):
    def __init__(self, base_dir: Path | None = None):
        from app.engine.tool.workspace import WorkspaceManager
        self._base_dir = base_dir or WorkspaceManager._workspaces_root()

    def _resolve(self, storage_key: str) -> Path:
        """Resolve path safely to prevent traversal attacks."""
        from app.engine.tool.workspace import WorkspaceManager
        resolved = WorkspaceManager.safe_resolve_path(self._base_dir, storage_key)
        if resolved is None:
            raise ValueError(f"Path traversal detected: {storage_key}")
        return resolved

    async def save(self, storage_key: str, data: bytes) -> None:
        path = self._resolve(storage_key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    async def load(self, storage_key: str) -> bytes:
        path = self._resolve(storage_key)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {storage_key}")
        return path.read_bytes()

    async def delete(self, storage_key: str) -> bool:
        path = self._resolve(storage_key)
        if not path.exists():
            return False
        path.unlink()
        return True

    async def exists(self, storage_key: str) -> bool:
        return self._resolve(storage_key).exists()

    async def get_size(self, storage_key: str) -> int:
        path = self._resolve(storage_key)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {storage_key}")
        return path.stat().st_size
```

**FileService 参考 `services/tool_service.py` 模式：**
```python
# backend/app/services/file_service.py
import hashlib
from app.db.mongodb import get_database
from app.models.base import generate_id, utc_now
from app.models.file_library import FileRef, FileUsage, FileConsumerKind
from app.services.file_storage import FileStorage


class FileService:
    FILE_REFS_COLLECTION = "file_refs"
    FILE_USAGES_COLLECTION = "file_usages"

    def __init__(self, storage: FileStorage):
        self._storage = storage

    def _file_refs(self):
        return get_database()[self.FILE_REFS_COLLECTION]

    def _file_usages(self):
        return get_database()[self.FILE_USAGES_COLLECTION]

    async def create(
        self,
        data: bytes,
        filename: str,
        mime_type: str,
        owner_user_id: str,
        origin_kind: FileConsumerKind,
        origin_id: str,
    ) -> FileRef:
        file_id = generate_id("file")
        sha256 = hashlib.sha256(data).hexdigest()
        storage_key = f"{owner_user_id}/files/{file_id}"

        await self._storage.save(storage_key, data)

        doc = FileRef(
            owner_user_id=owner_user_id,
            storage_key=storage_key,
            name=filename,
            size=len(data),
            mime_type=mime_type,
            sha256=sha256,
            origin_kind=origin_kind,
            origin_id=origin_id,
        )
        await self._file_refs().insert_one(doc.model_dump(by_alias=True))
        return doc

    async def get(self, file_id: str) -> FileRef | None:
        doc = await self._file_refs().find_one({"_id": file_id})
        return FileRef(**doc) if doc else None

    async def delete(self, file_id: str, force: bool = False) -> bool:
        file_ref = await self.get(file_id)
        if not file_ref:
            return False

        if await self.has_usages(file_id):
            if not force:
                return False  # 有引用，拒绝删除
            # force=True 时级联删除所有 usage
            await self._file_usages().delete_many({"file_id": file_id})

        await self._storage.delete(file_ref.storage_key)
        await self._file_refs().delete_one({"_id": file_id})
        return True
```

**数据库索引注册（参考 `db/indexes.py`）：**
```python
# backend/app/db/indexes.py — 追加到 create_indexes() 函数

# FileRefs 索引
await db.file_refs.create_index(
    [("owner_user_id", 1), ("created_at", -1)],
    name="idx_file_refs_owner_created",
)
await db.file_refs.create_index(
    [("sha256", 1)],
    name="idx_file_refs_sha256",
)
await db.file_refs.create_index(
    [("status", 1)],
    name="idx_file_refs_status",
)

# FileUsages 索引
await db.file_usages.create_index(
    [("file_id", 1)],
    name="idx_file_usages_file_id",
)
await db.file_usages.create_index(
    [("consumer_kind", 1), ("consumer_id", 1)],
    name="idx_file_usages_consumer",
)
await db.file_usages.create_index(
    [("file_id", 1), ("consumer_kind", 1), ("consumer_id", 1)],
    name="uq_file_usages_unique",
    unique=True,
)
```

### ⚠️ 回归防护

**不能破坏的现有行为：**
1. 现有 `WorkspaceManager` 的所有方法保持不变
2. 现有 session files API（`GET /sessions/{id}/files`）继续工作
3. 现有数据库索引创建逻辑
4. 现有测试套件全部通过

**不修改的文件：**
- `backend/app/engine/tool/workspace.py` — Workspace 管理逻辑完全不变
- `backend/app/api/v1/sessions.py` — Session files API 不变
- `backend/app/models/session.py` — Message 模型不变（attachments 在 Story 10-3 添加）

### 📁 文件清单

**后端新建的文件：**
- `backend/app/models/file_library.py` — FileRef / FileUsage 数据模型 + FileConsumerKind 枚举
- `backend/app/schemas/file_library.py` — 响应 Schema 定义
- `backend/app/services/file_storage.py` — FileStorage 抽象类 + LocalFileStorage 实现
- `backend/app/services/file_service.py` — FileService CRUD + Usage 管理
- `backend/tests/models/test_file_library.py` — 模型测试
- `backend/tests/services/test_file_storage.py` — 存储层测试
- `backend/tests/services/test_file_service.py` — Service 层测试

**后端修改的文件：**
- `backend/app/db/indexes.py` — 添加 file_refs + file_usages 集合索引

### 🚫 本 Story 不做的事

- **不做上传/下载 API** — REST API 在 Story 10-2
- **不做聊天附件集成** — 在 Story 10-3
- **不做 Agent 工具** — `list_attachments` / `invoke_workflow` 扩展在 Story 10-4
- **不做 Workflow Start 节点 file 类型** — 在 Story 10-5
- **不做前端上传组件** — 在 Story 10-6
- **不做自动清理/TTL/孤儿回收** — 主人决策仅支持手动删除，不做定时扫描任务
- **不做 OSS / MinIO 远程存储** — 仅本地文件系统
- **不做路径穿越以外的安全防护** — 不引入病毒扫描、文件类型黑名单

### Dependencies to Add

无新依赖。所有所需库（FastAPI、Motor、Pydantic、pytest）均已存在。

### Project Structure Notes

- 后端测试目录：
  - `tests/api/` — API 端点测试（本 Story 不涉及）
  - `tests/services/` — Service 层测试
  - `tests/models/` — 模型测试
- 测试使用 pytest-asyncio，mode=auto
- LocalFileStorage 测试使用 `tmp_path` fixture 创建临时目录

### References

- [Source: backend/app/engine/tool/workspace.py] — WorkspaceManager 现有实现（复用 `_workspaces_root()`、`safe_resolve_path()`）
- [Source: backend/app/models/tool.py] — Tool 数据模型模式参考
- [Source: backend/app/services/tool_service.py] — Service 层模式参考
- [Source: backend/app/db/indexes.py] — 索引注册模式参考
- [Source: backend/app/models/base.py] — `generate_id()` / `utc_now()` 工具函数
- [Source: docs/planning-artifacts/architecture.md] — 整体架构参考

## Dev Agent Record

### Agent Model Used

{{agent_model_name_version}}

### Debug Log References

- **T3 FileService 测试失败修复**：
  - 问题 1：`FileRef` 构造时未传入 `id=file_id`，导致生成两个不同 ULID
  - 问题 2：测试使用 `mongodb.get_database = ...` patch 方式错误，应在 `app.services.file_service.get_database` 上 patch
  - 问题 3：`mock_db["file_refs"]` 字典访问与 `mock_db.file_refs` 属性访问不匹配，改用属性访问
  - 问题 4：`update_one` 需要返回 `MagicMock(modified_count=1)` 而非默认 AsyncMock

### Completion Notes List

✅ **T1**: File 领域模型定义完成 — FileConsumerKind 枚举（4 值）、FileRef、FileUsage Pydantic 模型
✅ **T2**: FileStorage 存储抽象完成 — FileStorage ABC + LocalFileStorage 实现，复用 WorkspaceManager
✅ **T3**: FileService CRUD 方法完成 — create/get/list_by_owner/delete/update_status
✅ **T4**: FileService Usage 管理完成 — add_usage/remove_usage/list_usages/has_usages
✅ **T5**: 数据库索引注册完成 — file_refs 3 个索引 + file_usages 3 个索引（含唯一约束）
✅ **T6**: Schema 定义完成 — FileRefResponse/FileRefListResponse/FileUsageResponse
✅ **T7**: 单元测试完成 — 43 个测试全部通过（16 + 17 + 10）

**测试覆盖**：
- 模型字段验证、序列化、默认值
- LocalFileStorage 文件操作、路径穿越防护、大文件处理
- FileService CRUD、Usage 管理、级联删除、引用检查

**关键修复**：
- FileRef 构造时必须显式传入 `id=file_id`，避免 default_factory 生成新 ULID
- 测试 mock 需在 `app.services.file_service.get_database` 上 patch，而非 `app.db.mongodb.get_database`
- MongoDB 集合访问使用属性访问（`db.file_refs`）而非字典访问（`db["file_refs"]`）

### File List

**新建文件**：
- backend/app/models/file_library.py
- backend/app/services/file_storage.py
- backend/app/services/file_service.py
- backend/app/schemas/file_library.py
- backend/tests/models/test_file_library.py
- backend/tests/services/test_file_storage.py
- backend/tests/services/test_file_service.py

**修改文件**：
- backend/app/db/indexes.py

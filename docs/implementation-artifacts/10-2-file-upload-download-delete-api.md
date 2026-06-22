---
baseline_commit: 72b68c4
---

# Story 10.2: 文件上传/下载/删除 API

**Epic:** Epic 10 — 文件管理
**Status:** review
**Story ID:** 10-2
**Story Key:** 10-2-file-upload-download-delete-api

## Story

As a 前端开发者 / API 调用者，
I want 通过 REST API 上传、下载、列出、删除文件，
So that 用户可以在文件库中管理自己的文件，为后续聊天附件、Workflow 输入等场景提供基础。

> ⚠️ **关键背景**：
> - Story 10-1 已完成：`FileRef` / `FileUsage` 数据模型、`FileStorage` 抽象 + `LocalFileStorage`、`FileService` CRUD + Usage 管理
> - `FileService` 接受 `FileStorage` 实例作为构造依赖（`__init__(self, storage: FileStorage)`）
> - 当前仅支持本地文件系统存储，不做 OSS / MinIO
> - 文件大小限制：≤ 50MB（architecture NFR）
> - 文件 MIME 类型由客户端通过 multipart 头提供
> - 本 Story 不做前端组件（10-6），只做后端 API

## Acceptance Criteria

### AC1: FileService 依赖注入
**Given** API 端点需要 `FileService` 实例
**When** 审查 `backend/app/api/v1/files.py` 或依赖模块
**Then** 提供 `get_file_service() -> FileService` 依赖函数
**And** 内部实例化 `LocalFileStorage()` 并注入到 `FileService(storage)`
**And** 所有 API 端点通过 `Depends(get_file_service)` 获取服务实例

### AC2: 文件上传 API
**Given** 已认证用户需要上传文件
**When** `POST /api/v1/files` 发送 multipart/form-data 请求
**Then** 接受 `file: UploadFile` 参数
**And** 接受可选 `origin_kind` 参数（默认 `"user_library"`）
**And** 接受可选 `origin_id` 参数（默认使用当前用户 ID）
**And** 调用 `FileService.create()` 保存文件
**And** 自动创建 `USER_LIBRARY` 类型的 `FileUsage` 记录
**And** 返回 `201 Created` + `FileRefResponse` JSON
**And** 文件大小超过 50MB 时返回 `413 Payload Too Large`
**And** 未认证返回 `401`

### AC3: 文件列表查询 API
**Given** 已认证用户需要查看自己的文件
**When** `GET /api/v1/files?page=1&page_size=20`
**Then** 返回 `FileRefListResponse`（分页结构：items, total, page, page_size）
**And** 只返回当前用户的文件（`owner_user_id = current_user.id`）
**And** 默认按 `created_at` DESC 排序
**And** 支持可选 `status` 过滤参数（默认只返回 `active` 状态）

### AC4: 文件详情查询 API
**Given** 已认证用户需要查看文件详情
**When** `GET /api/v1/files/{file_id}`
**Then** 返回 `FileRefResponse` JSON
**And** 只允许查看自己的文件（`owner_user_id = current_user.id`），否则 `404`
**And** 文件不存在时返回 `404 FILE_NOT_FOUND`

### AC5: 文件下载 API
**Given** 已认证用户需要下载文件内容
**When** `GET /api/v1/files/{file_id}/download`
**Then** 返回 `StreamingResponse` 或 `Response`，`Content-Type` 为文件的 `mime_type`
**And** 设置 `Content-Disposition: attachment; filename="{name}"`
**And** 只允许下载自己的文件，否则 `404`
**And** 文件不存在时返回 `404`
**And** 物理文件丢失时返回 `404 FILE_CONTENT_NOT_FOUND`

### AC6: 文件删除 API
**Given** 已认证用户需要删除文件
**When** `DELETE /api/v1/files/{file_id}`
**Then** 默认行为：将文件状态标记为 `trashed`（软删除）
**And** 支持 `?force=true` 参数：硬删除（检查引用，无引用则物理删除）
**And** 只允许删除自己的文件，否则 `404`
**And** 有引用且 `force=false` 时返回 `409 FILE_HAS_REFERENCES`
**And** 硬删除成功返回 `204 No Content`
**And** 软删除成功返回 `200` + 更新后的 `FileRefResponse`

### AC7: 文件使用记录查询 API
**Given** 已认证用户需要查看文件被谁引用
**When** `GET /api/v1/files/{file_id}/usages`
**Then** 返回 `list[FileUsageResponse]`
**And** 只允许查看自己文件的使用记录，否则 `404`

### AC8: 请求 Schema 定义
**Given** API 需要请求体校验
**When** 审查 `backend/app/schemas/file_library.py`
**Then** 定义 `FileUploadResponse` — 可选，如与 `FileRefResponse` 相同则复用
**And** 确保 `FileRefResponse`、`FileRefListResponse`、`FileUsageResponse` 已存在（10-1 已创建）
**And** 如需新增请求 Schema 则在此文件追加

### AC9: 单元测试 + API 测试覆盖
**Given** 本 Story 的所有 API 端点
**When** 运行测试套件
**Then** 覆盖以下场景：
  - 上传：正常文件上传、超大文件拒绝（>50MB）、未认证拒绝
  - 列表：分页查询、状态过滤、空列表
  - 详情：正常查询、不存在返回 404、非 owner 返回 404
  - 下载：正常下载、文件不存在、Content-Disposition 验证
  - 删除：软删除（状态变 trashed）、硬删除（有引用 409、无引用 204）、非 owner 404
  - Usage 查询：正常查询、空列表
  - `cd backend && uv run pytest tests/api/test_files.py -v`

## Tasks / Subtasks

### 后端（Backend）

- [x] **T1: FileService 依赖注入** (AC: #1)
  - [x] 在 `backend/app/api/v1/files.py` 中定义 `get_file_service() -> FileService` 函数
  - [x] 内部实例化 `LocalFileStorage()` + `FileService(storage=storage)`
  - [x] 所有 API 端点通过 `Depends(get_file_service)` 获取

- [x] **T2: 文件上传端点** (AC: #2)
  - [x] 在 `backend/app/api/v1/files.py` 中实现 `POST /files`
  - [x] 接受 `file: UploadFile = File(...)` 参数
  - [x] 接受可选 `origin_kind: str = Query("user_library")` 参数
  - [x] 接受可选 `origin_id: str = Query(None)` 参数
  - [x] 读取文件内容，检查大小 ≤ 50MB
  - [x] 调用 `FileService.create(data, filename, mime_type, owner_user_id, origin_kind, origin_id)`
  - [x] 自动调用 `FileService.add_usage(file_id, USER_LIBRARY, owner_user_id)`
  - [x] 返回 `201` + `FileRefResponse`
  - [x] 超过 50MB 抛出 `HTTPException(413)`

- [x] **T3: 文件列表查询端点** (AC: #3)
  - [x] 实现 `GET /files`
  - [x] 接受 `page`, `page_size`, `status` 查询参数
  - [x] 调用 `FileService.list_by_owner(owner_user_id, page, page_size, status)`
  - [x] status 参数传入查询过滤
  - [x] 返回 `FileRefListResponse`

- [x] **T4: 文件详情查询端点** (AC: #4)
  - [x] 实现 `GET /files/{file_id}`
  - [x] 调用 `FileService.get(file_id)`
  - [x] 验证 `owner_user_id == current_user.id`，否则 `404`
  - [x] 返回 `FileRefResponse`

- [x] **T5: 文件下载端点** (AC: #5)
  - [x] 实现 `GET /files/{file_id}/download`
  - [x] 验证文件存在且属于当前用户
  - [x] 调用 `FileService._storage.load(file_ref.storage_key)` 获取字节流
  - [x] 返回 `Response(content=data, media_type=file_ref.mime_type)` + Content-Disposition 头
  - [x] 物理文件不存在时返回 `404 FILE_CONTENT_NOT_FOUND`

- [x] **T6: 文件删除端点** (AC: #6)
  - [x] 实现 `DELETE /files/{file_id}`
  - [x] 验证文件存在且属于当前用户
  - [x] 接受 `force: bool = Query(False)` 参数
  - [x] `force=False`：调用 `FileService.update_status(file_id, "trashed")`，返回 200 + `FileRefResponse`
  - [x] `force=True`：检查引用数，有引用返回 409，无引用调用 `FileService.delete`，成功返回 204
  - [x] 非 owner 返回 `404`

- [x] **T7: 文件使用记录查询端点** (AC: #7)
  - [x] 实现 `GET /files/{file_id}/usages`
  - [x] 验证文件存在且属于当前用户
  - [x] 调用 `FileService.list_usages(file_id)`
  - [x] 返回 `list[FileUsageResponse]`

- [x] **T8: Router 注册** (AC: #1)
  - [x] 修改 `backend/app/api/v1/router.py`
  - [x] 添加 `from app.api.v1.files import router as files_router`
  - [x] 添加 `api_v1_router.include_router(files_router)`

- [x] **T9: Schema 补充** (AC: #8)
  - [x] 检查 `backend/app/schemas/file_library.py`，所有需要的 Schema 已在 10-1 创建
  - [x] 无需新增 Schema，复用 FileRefResponse、FileRefListResponse、FileUsageResponse

- [x] **T10: API 测试** (AC: #9)
  - [x] 新建 `backend/tests/api/test_files.py`
  - [x] 测试上传（正常、超大文件、未认证）
  - [x] 测试列表（分页、状态过滤、空列表）
  - [x] 测试详情（正常、不存在、非 owner）
  - [x] 测试下载（正常、不存在、Content-Disposition）
  - [x] 测试删除（软删除、硬删除有引用 409、硬删除无引用 204、非 owner 404）
  - [x] 测试 Usage 查询
  - [x] 20 个新测试全部通过 ✅，完整套件 795 tests 通过 ✅

## Dev Notes

### 🔧 技术栈与约定

**后端（FastAPI + Motor + Pydantic）：**
- Python 包管理：**uv**（非 pip/poetry），`uv run pytest`
- FastAPI `UploadFile` + `File()` 处理 multipart 上传
- `Response` + `StreamingResponse` 处理文件下载
- Motor 异步 MongoDB
- 测试：pytest + pytest-asyncio（mode=auto）+ httpx `AsyncClient`（API 测试）

### 📐 关键架构约束

**Router 模式（参考 `api/v1/tools.py`）：**
```python
# backend/app/api/v1/files.py
from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import Response

from app.core.security import get_current_user, require_any_role
from app.schemas.file_library import FileRefResponse, FileRefListResponse, FileUsageResponse
from app.schemas.user import UserResponse
from app.services.file_service import FileService
from app.services.file_storage import LocalFileStorage

router = APIRouter(
    prefix="/files",
    tags=["files"],
    dependencies=[Depends(get_current_user)],
)


def get_file_service() -> FileService:
    """FileService 依赖注入。"""
    storage = LocalFileStorage()
    return FileService(storage=storage)
```

**文件上传端点模式：**
```python
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

@router.post(
    "",
    response_model=FileRefResponse,
    status_code=201,
    summary="Upload a file",
    responses={413: {"description": "File too large"}},
)
async def upload_file(
    file: UploadFile = File(...),
    origin_kind: str = Query("user_library", description="Origin consumer kind"),
    origin_id: str | None = Query(None, description="Origin consumer ID"),
    svc: FileService = Depends(get_file_service),
    current_user: UserResponse = Depends(require_any_role("admin", "developer", "operator", "viewer")),
) -> FileRefResponse:
    data = await file.read()
    if len(data) > MAX_FILE_SIZE:
        raise ValidationError(
            code="FILE_TOO_LARGE",
            message=f"文件大小超过限制（最大 {MAX_FILE_SIZE // 1024 // 1024}MB）",
        )
    # ...
```

**文件下载端点模式：**
```python
@router.get(
    "/{file_id}/download",
    summary="Download file content",
    responses={404: {"description": "File not found"}},
)
async def download_file(
    file_id: str,
    svc: FileService = Depends(get_file_service),
    current_user: UserResponse = Depends(get_current_user),
) -> Response:
    file_ref = await svc.get(file_id)
    if file_ref is None or file_ref.owner_user_id != current_user.id:
        raise NotFoundError(code="FILE_NOT_FOUND", message=f"文件 {file_id} 不存在")
    try:
        data = await svc._storage.load(file_ref.storage_key)
    except FileNotFoundError:
        raise NotFoundError(code="FILE_CONTENT_NOT_FOUND", message="文件内容不存在")
    return Response(
        content=data,
        media_type=file_ref.mime_type,
        headers={"Content-Disposition": f'attachment; filename="{file_ref.name}"'},
    )
```

**权限校验辅助函数（owner 校验）：**
```python
async def _get_owner_file(svc: FileService, file_id: str, owner_user_id: str) -> FileRef:
    """获取文件并验证所有权，不存在或非 owner 返回 404。"""
    file_ref = await svc.get(file_id)
    if file_ref is None or file_ref.owner_user_id != owner_user_id:
        raise NotFoundError(code="FILE_NOT_FOUND", message=f"文件 {file_id} 不存在")
    return file_ref
```

**Error 处理（参考 `core/errors.py`）：**
```python
from app.core.errors import NotFoundError, ValidationError, ConflictError

# 404 — 文件不存在
raise NotFoundError(code="FILE_NOT_FOUND", message="文件不存在")

# 413 → 用 ValidationError (422) 或自定义
# 实际上 413 需要 HTTPException:
from fastapi import HTTPException
raise HTTPException(status_code=413, detail="File too large")

# 409 — 有引用
raise ConflictError(code="FILE_HAS_REFERENCES", message="文件仍被引用，无法删除")
```

### 📝 FileService.list_by_owner 扩展需求

当前 `FileService.list_by_owner()` 只按 `owner_user_id` 查询，本 Story 可能需要增加 `status` 过滤。
两种方案：
1. 在 API 层过滤（简单但浪费查询）
2. 给 `list_by_owner` 添加可选 `status` 参数（推荐）

推荐方案 2，在 `FileService.list_by_owner` 中添加可选 `status: str | None = None` 参数：
```python
async def list_by_owner(
    self, owner_user_id: str, page: int = 1, page_size: int = 20,
    status: str | None = None,
) -> tuple[list[FileRef], int]:
    query: dict[str, Any] = {"owner_user_id": owner_user_id}
    if status is not None:
        query["status"] = status
    # ...
```

### ⚠️ 回归防护

**不能破坏的现有行为：**
1. 现有 `FileService` 的所有方法签名保持不变（`list_by_owner` 新增可选参数，向后兼容）
2. 现有 API 路由不受影响
3. 现有测试套件全部通过（775 tests）

**不修改的文件：**
- `backend/app/services/file_storage.py` — 存储层不变
- `backend/app/models/file_library.py` — 数据模型不变
- `backend/app/services/file_service.py` — 仅新增可选参数（`list_by_owner` 的 `status` 参数）
- `backend/app/db/indexes.py` — 索引不变

### 📁 文件清单

**后端新建的文件：**
- `backend/app/api/v1/files.py` — 文件管理 API 端点
- `backend/tests/api/test_files.py` — API 测试

**后端修改的文件：**
- `backend/app/api/v1/router.py` — 注册 files router
- `backend/app/schemas/file_library.py` — 如需补充 Schema
- `backend/app/services/file_service.py` — `list_by_owner` 新增 `status` 可选参数

### 🚫 本 Story 不做的事

- **不做前端上传组件** — Story 10-6
- **不做聊天附件集成** — Story 10-3
- **不做 Agent 文件工具** — Story 10-4
- **不做 Workflow Start 节点 file 类型** — Story 10-5
- **不做文件去重**（sha256 相同不合并） — 当前不做
- **不做预签名 URL** — 当前阶段直接通过 API 传输
- **不做文件版本管理** — 当前不做
- **不做文件分享/权限委托** — 当前不做

### Dependencies to Add

无新依赖。FastAPI `UploadFile`、`File`、`Response`、`HTTPException` 均已内置。

### Project Structure Notes

- API 测试需要 `httpx.AsyncClient` + FastAPI `TestClient`
- 测试 mock 模式：patch `get_database` + `LocalFileStorage` 方法
- 文件上传测试使用 `httpx` 的 `files` 参数

### References

- [Source: backend/app/api/v1/tools.py] — API Router 模式参考（prefix、tags、auth、UploadFile）
- [Source: backend/app/api/v1/router.py] — Router 注册模式
- [Source: backend/app/services/file_service.py] — FileService 现有方法
- [Source: backend/app/services/file_storage.py] — FileStorage 抽象
- [Source: backend/app/schemas/file_library.py] — 已有 Schema 定义
- [Source: backend/app/core/errors.py] — 业务异常类
- [Source: backend/app/core/security.py] — get_current_user / require_any_role
- [Completed: docs/implementation-artifacts/10-1-file-ref-file-usage-data-model-and-storage-abstraction.md] — Story 10-1 完成产物

## Dev Agent Record

### Debug Log References

- **DELETE endpoint response_model 错误**：FastAPI 不支持 `Response | FileRefResponse` 联合类型作为 response_model。修复：设置 `response_model=None`，由端点自行管理响应。
- **upload test mock 冲突**：`patch` 和 `app.dependency_overrides` 不能同时使用。修复：只用 `dependency_overrides` 方式。
- **download content-type 断言**：FastAPI Response 会自动附加 `charset=utf-8`。修复：使用 `startswith("text/plain")` 而非精确匹配。

### Completion Notes List

✅ **T1**: FileService 依赖注入完成 — `get_file_service()` 函数 + `Depends()` 模式
✅ **T2**: 文件上传端点完成 — POST /files，50MB 限制，自动创建 USER_LIBRARY usage
✅ **T3**: 文件列表查询完成 — GET /files，分页 + status 过滤
✅ **T4**: 文件详情查询完成 — GET /files/{file_id}，owner 校验
✅ **T5**: 文件下载完成 — GET /files/{file_id}/download，Content-Disposition 头
✅ **T6**: 文件删除完成 — DELETE /files/{file_id}，软删除 + 硬删除（force）
✅ **T7**: 使用记录查询完成 — GET /files/{file_id}/usages
✅ **T8**: Router 注册完成 — router.py 已添加 files_router
✅ **T9**: Schema 确认完成 — 10-1 已创建所有需要的 Schema，无需补充
✅ **T10**: API 测试完成 — 20 个测试全部通过，完整套件 795 tests 0 failures

### File List

**新建文件**：
- backend/app/api/v1/files.py
- backend/tests/api/test_files.py

**修改文件**：
- backend/app/api/v1/router.py
- backend/app/services/file_service.py

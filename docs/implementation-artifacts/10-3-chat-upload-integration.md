---
baseline_commit: 57c9ece
---

# Story 10.3: 聊天附件上传集成

**Epic:** Epic 10 — 文件管理
**Status:** review
**Story ID:** 10-3
**Story Key:** 10-3-chat-upload-integration

## Story

As a 用户，
I want 在聊天中上传文件作为消息附件，
So that Agent 可以读取我上传的文件内容来辅助对话和任务执行。

> ⚠️ **关键背景**：
> - Story 10-1 完成：FileRef / FileUsage 数据模型、FileStorage / FileService
> - Story 10-2 完成：文件上传/下载/列表 REST API（`POST /api/v1/files`）
> - Session workspace 已有 `input/` 目录（创建 session 时自动创建）
> - Sandbox 已将 `input/` 以只读方式挂载（Agent 可读取）
> - 当前 `Message` 模型没有附件字段，`add_message` 不接受文件参数
> - 本 Story 连接文件系统和聊天系统

## Acceptance Criteria

### AC1: Message 模型增加附件字段
**Given** 聊天消息需要关联上传的文件
**When** 审查 `backend/app/models/session.py`
**Then** `Message` 模型新增字段 `file_ids: list[str] = Field(default_factory=list)`
**And** 该字段存储与此消息关联的 FileRef ID 列表
**And** 默认值为空列表（向后兼容现有消息）

### AC2: Session 聊天文件上传端点
**Given** 已认证用户需要在聊天中上传文件
**When** `POST /api/v1/sessions/{session_id}/files/upload`
**Then** 接受 `file: UploadFile = File(...)` 参数
**Then** 接受可选 `content: str = Form("")` 参数（消息文本）
**And** 验证 session 存在且属于当前用户
**And** 调用 FileService.create() 创建 FileRef（`origin_kind=SESSION_MESSAGE`, `origin_id=session_id`）
**And** 调用 FileService.add_usage() 创建 SESSION_MESSAGE 使用记录
**And** 将物理文件复制到 session 的 workspace `input/` 目录
**And** 如果提供了 content，调用 MessageService.add_message() 创建包含 file_ids 的用户消息
**And** 返回 `201` + 包含 `file_ref` 和可选 `message` 的响应
**And** 文件超过 50MB 返回 `413`

### AC3: 消息响应包含附件信息
**Given** 聊天消息可能包含文件附件
**When** 审查 `backend/app/schemas/session.py`
**Then** `MessageResponse` 新增 `file_ids: list[str] = []` 字段
**And** 新增 `files: list[FileRefResponse] = []` 字段（完整文件信息，可选填充）
**And** 查询消息详情时填充 `files` 字段

### AC4: 消息创建支持附件
**Given** 用户发送带附件的消息
**When** 调用 `MessageService.add_message()`
**Then** 新增可选参数 `file_ids: list[str] | None = None`
**And** 将 file_ids 写入 Message 文档
**And** 默认 `None` 或空列表时向后兼容

### AC5: 文件复制到 Session Workspace
**Given** 上传的文件需要被 Agent sandbox 访问
**When** 文件通过聊天上传
**Then** 物理文件被复制到 `{workspace_root}/{user_id}/{session_id}/input/{filename}`
**And** 使用 `FileStorage.load()` 读取源文件 + 写入 `input/` 目录
**And** 文件名冲突时自动添加后缀（如 `report_1.txt`）
**And** 复制失败不影响 FileRef 创建（文件库中仍存在）

### AC6: 上传响应 Schema
**Given** API 需要清晰的响应结构
**When** 审查 `backend/app/schemas/session.py`
**Then** 定义 `ChatFileUploadResponse`：
  - `file: FileRefResponse` — 创建的文件引用
  - `message: MessageResponse | None` — 如果同时创建了消息
  - `workspace_path: str` — 文件在 workspace input/ 中的路径

### AC7: 测试覆盖
**Given** 本 Story 的所有功能
**When** 运行测试套件
**Then** 覆盖以下场景：
  - Message 模型 file_ids 字段默认值、序列化
  - 上传文件到 session（正常、无 content、session 不存在、非 owner）
  - 文件复制到 workspace input/ 目录
  - MessageService.add_message 带 file_ids
  - 消息响应包含 file_ids 和 files 字段
  - 文件名冲突处理
  - `cd backend && uv run pytest tests/services/test_session_service.py tests/api/test_sessions.py -v`

## Tasks / Subtasks

### 后端（Backend）

- [x] **T1: Message 模型扩展** (AC: #1)
  - [x] 修改 `backend/app/models/session.py`
  - [x] `Message` 新增 `file_ids: list[str] = Field(default_factory=list)`
  - [x] 确保向后兼容（现有文档无此字段时默认空列表）

- [x] **T2: MessageService.add_message 扩展** (AC: #4)
  - [x] 修改 `backend/app/services/session_service.py`
  - [x] `add_message` 新增可选参数 `file_ids: list[str] | None = None`
  - [x] 将 file_ids 写入 Message 文档

- [x] **T3: Schema 扩展** (AC: #3, #6)
  - [x] 修改 `backend/app/schemas/session.py`
  - [x] `MessageResponse` 新增 `file_ids: list[str] = []` 和 `files: list[FileRefResponse] = []`
  - [x] 新增 `ChatFileUploadResponse` schema

- [x] **T4: Session 聊天文件上传端点** (AC: #2, #5)
  - [x] 在 `backend/app/api/v1/sessions.py` 中实现 `POST /sessions/{session_id}/files/upload`
  - [x] 接受 `file: UploadFile`, 可选 `content: str = Form("")`
  - [x] 验证 session 所有权
  - [x] 创建 FileRef（origin_kind=SESSION_MESSAGE）
  - [x] 创建 FileUsage（SESSION_MESSAGE）
  - [x] 复制物理文件到 workspace input/ 目录（处理文件名冲突）
  - [x] 如有 content，创建带 file_ids 的消息
  - [x] 返回 ChatFileUploadResponse

- [x] **T5: 消息查询填充文件详情** (AC: #3)
  - [x] 修改 `_msg_to_response` 辅助函数
  - [x] 查询 file_ids 对应的 FileRef 填充 `files` 字段
  - [x] 无 file_ids 时 files 为空列表

- [x] **T6: 测试** (AC: #7)
  - [x] 补充 `tests/services/test_session_service.py` — add_message 带 file_ids
  - [x] 补充 `tests/api/test_sessions.py` — 上传端点测试
  - [x] 运行全部测试确保通过

## Dev Notes

### 🔧 技术栈与约定

**后端（FastAPI + Motor + Pydantic）：**
- Python 包管理：**uv**
- FastAPI `UploadFile` + `File()` + `Form()` 处理 multipart 混合上传
- Motor 异步 MongoDB
- 测试：pytest + pytest-asyncio（mode=auto）

### 📐 关键设计决策

**文件存储双写策略：**
1. FileRef + 物理文件存储到用户文件库（`{user_id}/files/{file_id}`）
2. 同时复制到 session workspace `input/` 目录
3. 原因：sandbox 只读取 `input/` 目录，FileRef 用于管理和引用跟踪

**文件名冲突处理：**
```python
def _resolve_input_filename(input_dir: Path, filename: str) -> Path:
    """解决文件名冲突，添加数字后缀。"""
    target = input_dir / filename
    if not target.exists():
        return target
    stem = target.stem
    suffix = target.suffix
    counter = 1
    while target.exists():
        target = input_dir / f"{stem}_{counter}{suffix}"
        counter += 1
    return target
```

**FileService 复用：**
- 使用 `FileService.create()` 创建 FileRef
- 使用 `FileService.add_usage()` 创建 SESSION_MESSAGE 引用
- 使用 `FileService._storage.load()` 读取物理文件用于复制到 workspace

### ⚠️ 回归防护

**不能破坏的现有行为：**
1. 现有 Message 模型（`file_ids` 新增可选字段，默认空列表，向后兼容）
2. 现有 Session API（新端点不修改现有端点）
3. 现有 MessageService.add_message（`file_ids` 可选参数，默认 None）
4. 现有测试套件全部通过（795 tests）

### 📁 文件清单

**后端新建的文件：** 无
**后端修改的文件：**
- `backend/app/models/session.py` — Message 增加 file_ids
- `backend/app/services/session_service.py` — add_message 增加 file_ids
- `backend/app/schemas/session.py` — MessageResponse + ChatFileUploadResponse
- `backend/app/api/v1/sessions.py` — 新增上传端点 + 消息查询填充

### 🚫 本 Story 不做的事

- **不做前端聊天上传 UI** — Story 10-6 统一处理
- **不做 Agent 文件工具** — Story 10-4
- **不做文件去重** — 当前不做
- **不做消息编辑时修改附件** — 当前不支持
- **不做多文件单次上传** — 当前每次上传一个文件

### Dependencies to Add

无新依赖。

### References

- [Source: backend/app/models/session.py] — Message / Session 模型
- [Source: backend/app/services/session_service.py] — MessageService.add_message
- [Source: backend/app/api/v1/sessions.py] — Session API 端点
- [Source: backend/app/api/v1/files.py] — Story 10-2 文件 API
- [Source: backend/app/services/file_service.py] — FileService
- [Source: backend/app/engine/tool/workspace.py] — WorkspaceManager

## Dev Agent Record

### Implementation Plan
- T1: Message model 增加 file_ids 字段（默认空列表，向后兼容）
- T2: MessageService.add_message 增加 file_ids 可选参数
- T3: MessageResponse 增加 file_ids + files 字段；新增 ChatFileUploadResponse schema
- T4: 实现 POST /sessions/{session_id}/files/upload 端点（双写：FileRef + workspace input/）
- T5: get_session 端点查询时填充消息的文件详情
- T6: 6 个 API 测试（TestUploadChatFile × 4 + TestSessionDetailWithFiles × 2）

### Debug Log
- FastAPI `Depends(_get_file_service)` 在模块加载时捕获函数引用，`patch("..._get_file_service")` 无法覆盖
  - 解决：改用 `app.dependency_overrides[_get_file_service] = lambda: mock_svc`
  - 注意：`get_session` 端点中 `_get_file_service()` 是直接函数调用（非 Depends），`patch` 仍然有效

### Completion Notes
✅ 全部 6 个 AC 满足
✅ 801 tests passed, 0 failures（795 原有 + 6 新增）
✅ 聊天上传端点：FileRef 创建 + FileUsage 记录 + workspace input/ 复制 + 可选消息创建
✅ 消息详情端点：自动填充 file_ids 对应的 FileRef 到 files 字段
✅ 文件名冲突自动添加数字后缀（_resolve_input_filename）

## File List

**新建:**
- `backend/tests/api/test_sessions.py` — 6 个聊天文件上传 API 测试

**修改:**
- `backend/app/models/session.py` — Message 新增 file_ids 字段
- `backend/app/services/session_service.py` — add_message 新增 file_ids 参数
- `backend/app/schemas/session.py` — MessageResponse 扩展 + ChatFileUploadResponse
- `backend/app/api/v1/sessions.py` — 上传端点 + 消息文件填充

## Change Log
- 2026-06-22: Story 10-3 实现完成 — 聊天附件上传集成（Message 扩展 + 上传端点 + 文件填充）

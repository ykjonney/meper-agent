---
baseline_commit: cd3e65c
---

# Story 10.4: Agent 文件工具 — 扩展内置工具集

**Epic:** Epic 10 — 文件管理
**Status:** done (skipped — bash 已覆盖文件管理，专用工具 ROI 不足)
**Story ID:** 10-4
**Story Key:** 10-4-agent-file-tools-extend-existing-workflow-with-file-support

## Story

As a Agent，
I want 拥有结构化文件管理工具（列表、删除、元数据查看），
So that 我可以在对话中主动管理 workspace 中的文件，而不必依赖 bash 命令。

> ⚠️ **关键背景**：
> - Story 10-1 完成：FileRef / FileUsage 数据模型、FileStorage / FileService
> - Story 10-2 完成：文件上传/下载/列表 REST API（`POST /api/v1/files`）
> - Story 10-3 完成：聊天附件上传集成（Message.file_ids + 上传端点）
> - 当前 Agent 内置工具：`bash`、`read`、`write`、`write_to_output`
> - Agent 可以通过 `bash ls` 列出文件，但没有结构化文件管理工具
> - Workspace 结构：`{user_id}/{session_id}/{input,output,tmp}/`
> - 安全：所有路径必须通过 `WorkspaceManager.safe_resolve_path()` 防穿越
> - 本 Story 扩展 Agent 内置工具集，添加文件管理能力

## Acceptance Criteria

### AC1: list_files 工具
**Given** Agent 需要查看 workspace 目录内容
**When** Agent 调用 `list_files(path: str)` 工具
**Then** 返回指定路径下的文件和目录列表
**And** 每个条目包含 `name`、`type`（file/directory）、`size` 字段
**And** 路径解析受 workspace 安全约束（不可穿越）
**And** `path` 为空或 `.` 时列出当前 workspace 根目录内容
**And** 支持 `subdir` 参数指定列出 `input/`、`output/`、`tmp/` 子目录

### AC2: delete_file 工具
**Given** Agent 需要清理不需要的文件
**When** Agent 调用 `delete_file(path: str)` 工具
**Then** 删除 workspace 内的指定文件
**And** 路径必须在 workspace 范围内（安全检查）
**And** 不允许删除 `input/` 目录中的文件（用户上传，只读）
**And** 可以删除 `tmp/` 和 `output/` 中的文件
**And** 返回删除结果消息（成功/失败原因）

### AC3: file_info 工具
**Given** Agent 需要了解文件元数据
**When** Agent 调用 `file_info(path: str)` 工具
**Then** 返回文件元数据：`size`、`modified_at`、`mime_type`、`is_file`/`is_dir`
**And** 路径必须在 workspace 范围内（安全检查）
**And** 文件不存在时返回错误消息

### AC4: 工具注册与配置
**Given** 新工具需要被 Agent 使用
**When** 审查工具注册逻辑
**Then** 三个新工具加入 `_BUILTIN_BASE_TOOLS` 列表
**And** 加入 `_bash_tool_set`（bash 启用时自动包含）
**And** 加入 `_build_builtin_tool_declaration` 的工具声明映射
**And** 工具在 `_BUILTIN_TOOL_REGISTRY` 中可查

### AC5: 安全约束
**Given** Agent 运行在受限环境中
**When** 新工具执行路径操作
**Then** 所有路径必须通过 `WorkspaceManager.safe_resolve_path()` 验证
**And** 路径穿越攻击被阻止（返回错误消息）
**And** 无 workspace context 时工具返回错误（不允许 fallback 到全局路径）

### AC6: 测试覆盖
**Given** 本 Story 的所有功能
**When** 运行测试套件
**Then** 覆盖以下场景：
  - list_files：正常列出、子目录、路径穿越拒绝、空目录
  - delete_file：正常删除、input/ 拒绝、路径穿越拒绝、文件不存在
  - file_info：正常获取、目录信息、文件不存在、路径穿越拒绝
  - 工具注册验证：三个工具在 registry 中

### AC7: 回归兼容
**Given** 现有 Agent 执行流程
**When** 新工具加入
**Then** 现有 `bash`、`read`、`write`、`write_to_output` 工具不受影响
**Then** 现有 `builtin_config` 白名单逻辑不受影响
**And** 未配置 bash 的 Agent 不会自动获得新工具

## Tasks / Subtasks

### 后端（Backend）

- [ ] **T1: list_files 工具实现** (AC: #1, #5)
  - [ ] 在 `backend/app/engine/agent/builtin_tools.py` 中新增 `list_files` 工具
  - [ ] 参数：`path: str = "."`，`subdir: str = ""`（可选 input/output/tmp）
  - [ ] 使用 `_safe_path_for_read()` 解析路径（复用现有安全逻辑）
  - [ ] 遍历目录返回 `[{name, type, size}]` 列表
  - [ ] 路径穿越时返回错误消息

- [ ] **T2: delete_file 工具实现** (AC: #2, #5)
  - [ ] 在 `builtin_tools.py` 中新增 `delete_file` 工具
  - [ ] 参数：`path: str`
  - [ ] 使用 `_safe_path_for_write()` 解析路径
  - [ ] 检查路径不在 `input/` 目录中（input 只读）
  - [ ] 执行删除并返回结果消息

- [ ] **T3: file_info 工具实现** (AC: #3, #5)
  - [ ] 在 `builtin_tools.py` 中新增 `file_info` 工具
  - [ ] 参数：`path: str`
  - [ ] 使用 `_safe_path_for_read()` 解析路径
  - [ ] 返回 size、modified_at、mime_type、is_file/is_dir

- [ ] **T4: 工具注册与声明** (AC: #4)
  - [ ] 将三个工具加入 `_BUILTIN_BASE_TOOLS`
  - [ ] 更新 `builder.py` 的 `_bash_tool_set` 包含新工具名
  - [ ] 更新 `_build_builtin_tool_declaration` 的 `tool_desc_map`

- [ ] **T5: 测试** (AC: #6, #7)
  - [ ] 新建 `tests/engine/test_file_tools.py`
  - [ ] 测试 list_files / delete_file / file_info 正常路径
  - [ ] 测试路径穿越拒绝
  - [ ] 测试 delete_file 的 input/ 保护
  - [ ] 测试工具注册完整性
  - [ ] 运行全量回归确保无破坏

## Dev Notes

### 🔧 技术栈与约定

**后端（LangChain + FastAPI）：**
- Python 包管理：**uv**
- 工具装饰器：`from langchain_core.tools import tool`（`@tool` 装饰函数）
- 工具注册：`_BUILTIN_BASE_TOOLS` 列表 + `_BUILTIN_TOOL_REGISTRY` 字典
- 测试：pytest + pytest-asyncio（mode=auto）

### 📐 关键设计决策

**工具实现模式（复用现有模式）：**
```python
@tool
def list_files(path: str = ".", subdir: str = "") -> str:
    """List files in a workspace directory..."""
    ws = _get_workspace()
    if ws is None:
        return "Error: No workspace context available"
    # 路径解析 + 安全检查
    # 遍历目录 + 格式化输出
    return formatted_output
```

**路径安全：**
- 读操作：`_safe_path_for_read()` — 允许 workspace + SKILLS_DIR
- 写操作：`_safe_path_for_write()` — 限制在 workspace 内
- 新工具优先使用 `_safe_path_for_read()` 作为基础检查
- `delete_file` 需要额外检查不在 `input/` 目录

**input/ 保护逻辑：**
```python
def _is_in_input_dir(ws: Workspace, resolved_path: str) -> bool:
    """Check if path is within the input/ directory (read-only for agent)."""
    return str(resolved_path).startswith(str(ws.input_dir))
```

**工具声明映射：**
```python
tool_desc_map = {
    ...existing...
    "list_files": "List files in a directory (path: str = '.', subdir: str = '')",
    "delete_file": "Delete a file from workspace (path: str). Cannot delete input/ files.",
    "file_info": "Get file metadata (path: str) — size, modified time, type",
}
```

### ⚠️ 回归防护

**不能破坏的现有行为：**
1. 现有 4 个内置工具（bash, read, write, write_to_output）完全不受影响
2. `_resolve_builtin_tools()` 的白名单逻辑不变
3. `_bash_tool_set` 扩展但不修改已有成员
4. 现有测试套件全部通过（801 tests）
5. 无 workspace context 时的 fallback 行为不变

**`_safe_path_for_read` vs `_safe_path_for_write` 选择：**
- `list_files` / `file_info`：使用 `_safe_path_for_read`（只读操作，允许 SKILLS_DIR）
- `delete_file`：使用 `_safe_path_for_write`（写操作，不允许 SKILLS_DIR）+ input/ 保护

### 📁 文件清单

**新建：**
- `backend/tests/engine/test_file_tools.py` — 文件工具测试

**修改：**
- `backend/app/engine/agent/builtin_tools.py` — 新增 3 个工具 + 注册
- `backend/app/engine/agent/builder.py` — 工具声明更新

### 🚫 本 Story 不做的事

- **不做前端文件管理 UI** — Story 10-6
- **不做 FileRef 与 Agent 工具集成** — 当前工具直接操作 workspace 文件系统，不涉及 FileRef 数据库记录
- **不做文件上传到 input/ 的工具** — 文件通过聊天上传（Story 10-3 已完成）
- **不做跨 session 文件操作** — 每个 session workspace 隔离
- **不做文件内容搜索（grep）** — Agent 可以用 bash grep

### Dependencies to Add

无新依赖。

### References

- [Source: backend/app/engine/agent/builtin_tools.py] — 现有内置工具实现
- [Source: backend/app/engine/agent/builder.py] — 工具声明与注册
- [Source: backend/app/engine/tool/workspace.py] — WorkspaceManager 路径安全
- [Source: backend/tests/api/test_files.py] — Story 10-2 测试模式参考

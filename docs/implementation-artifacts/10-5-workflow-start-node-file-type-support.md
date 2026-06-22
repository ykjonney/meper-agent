---
baseline_commit: e48a07f
---

# Story 10.5: 工作流启动节点文件类型支持

**Epic:** Epic 10 — 文件管理
**Status:** review
**Story ID:** 10-5
**Story Key:** 10-5-workflow-start-node-file-type-support

## Story

As a 工作流设计者，
I want 启动节点能声明文件类型的输入变量，
So that 工作流可以接收用户上传的文件作为输入参数（如：上传 PDF 进行解析）。

> ⚠️ **关键背景**：
> - Story 10-1 完成：FileRef / FileUsage 数据模型、FileService
> - Story 10-2 完成：文件上传/下载 API（`POST /api/v1/files`）
> - 前端 `variable-types.ts` 已定义 `file` 类型（含 allowed_extensions、max_size_mb、multiple 约束）
> - 前端 `VariableTypeSelector` 已可选择 `file` 类型
> - 后端 `StartNodeExecutor` 当前对所有类型统一处理（直接传递值，无类型校验）
> - 工作流触发流程：`dispatch_workflow(params)` → `Task.input` → `VariablePool` → `StartNodeExecutor`
> - 本 Story 补齐后端对 `file` 类型变量的验证与解析能力

## Acceptance Criteria

### AC1: 启动节点文件变量验证
**Given** 工作流启动节点声明了 `type: "file"` 的输出变量
**When** `StartNodeExecutor.execute()` 处理该变量
**Then** 验证输入值是否为有效的 FileRef ID（字符串格式）
**And** 通过 FileService 查询 FileRef 记录是否存在
**And** 验证 `allowed_extensions`（如有配置）
**And** 验证 `max_size_mb`（如有配置）
**And** 验证 `required` 约束（文件变量必填时不能为空）
**And** 验证失败时返回清晰的错误消息

### AC2: 文件引用解析
**Given** 启动节点接收到的文件输入为 FileRef ID
**When** StartNodeExecutor 完成变量解析
**Then** 输出中包含文件元信息 `{file_id, name, size, mime_type, storage_key}`
**And** 下游节点可通过 `{{start_node.file_var_name}}` 引用文件信息
**And** 下游 Agent 节点可通过 `read` 工具读取文件内容（通过 FileService 加载）

### AC3: 多文件支持
**Given** 文件变量配置 `multiple: true`
**When** 启动节点处理该变量
**Then** 接受 FileRef ID 列表（`list[str]`）
**And** 对列表中每个文件执行约束验证
**And** 输出为文件元信息列表

### AC4: 工作流触发时的文件传递
**Given** Agent 通过 `dispatch_workflow` 触发带文件输入的工作流
**When** Agent 构造 params
**Then** 文件类型变量值应为 FileRef ID 字符串（或 ID 列表）
**And** 系统提示中说明文件变量需传递 FileRef ID
**And** Task 的 `input` 字段正确存储 FileRef ID

### AC5: 文件变量在工作流执行中可用
**Given** 工作流包含文件类型输入
**When** 下游 Agent 节点执行
**Then** VariablePool 中包含解析后的文件元信息
**And** Agent 可通过表达式引用 `{{start_node.var_name.name}}` 获取文件名
**And** Agent 可通过 FileService 加载文件内容

### AC6: 测试覆盖
**Given** 本 Story 的所有功能
**When** 运行测试套件
**Then** 覆盖以下场景：
  - 文件变量正常解析（单文件、多文件）
  - FileRef 不存在 → 验证错误
  - 扩展名不匹配 → 验证错误
  - 文件超限 → 验证错误
  - required 文件变量为空 → 验证错误
  - 多文件中部分无效 → 明确报错位置
  - 非文件类型不受影响（回归兼容）

### AC7: 回归兼容
**Given** 现有工作流执行流程
**When** 添加文件类型支持
**Then** 非 `file` 类型变量的处理逻辑完全不变
**Then** 现有测试套件全部通过
**And** 无 `file` 类型变量的工作流行为不变

## Tasks / Subtasks

### 后端（Backend）

- [x] **T1: 文件变量验证器** (AC: #1, #3)
  - [x] 在 `backend/app/engine/workflow/` 新建 `file_validator.py`
  - [x] 实现 `validate_file_variable(value, var_def)` 函数
  - [x] 支持单文件（`str`）和多文件（`list[str]`）输入
  - [x] 通过 FileService 查询 FileRef 存在性
  - [x] 验证 allowed_extensions、max_size_mb、required

- [x] **T2: StartNodeExecutor 集成** (AC: #1, #2, #5)
  - [x] 修改 `backend/app/engine/workflow/node_executor.py`
  - [x] `StartNodeExecutor.execute()` 中对 `type == "file"` 变量调用验证器
  - [x] 验证通过后解析 FileRef 为文件元信息 dict
  - [x] 输出包含 `{file_id, name, size, mime_type, storage_key}`

- [x] **T3: 工作流工具声明更新** (AC: #4)
  - [x] 修改 `backend/app/engine/agent/builder.py` 的 `_build_workflow_tool_declaration`
  - [x] 当工作流有 `type: "file"` 变量时，在参数说明中标注需传递 FileRef ID
  - [x] 保持非文件变量的声明格式不变

- [x] **T4: 测试** (AC: #6, #7)
  - [x] 新建 `backend/tests/engine/workflow/test_file_validator.py`
  - [x] 测试文件验证器：正常、不存在、扩展名错误、超限、必填为空
  - [x] 新建/修改 `backend/tests/engine/workflow/test_start_node.py`（如存在）
  - [x] 测试 StartNodeExecutor 对文件类型变量的处理
  - [x] 运行全量回归

## Dev Notes

### 🔧 技术栈与约定

**后端（FastAPI + Motor + Jinja2）：**
- Python 包管理：**uv**
- FileService：`from app.services.file_service import FileService`
- FileStorage：`from app.services.file_storage import LocalFileStorage`
- 测试：pytest + pytest-asyncio（mode=auto）

### 📐 关键设计决策

**文件引用格式：**
- 工作流输入中，文件变量值为 FileRef ID 字符串（如 `"file_01HXYZ"`）
- 多文件为 ID 列表（如 `["file_01HXYZ", "file_01HABC"]`）
- StartNodeExecutor 解析后输出文件元信息 dict

**验证器设计：**
```python
# backend/app/engine/workflow/file_validator.py

async def validate_file_variable(
    value: str | list[str],
    var_def: dict,
) -> tuple[list[dict] | None, str | None]:
    """验证文件变量并返回解析后的文件元信息。

    Args:
        value: FileRef ID 或 ID 列表
        var_def: 变量定义（含 constraints）

    Returns:
        (resolved_files, error) — resolved_files 为 None 表示验证失败
    """
    constraints = var_def.get("constraints", {})
    allowed_ext = constraints.get("allowed_extensions", [])
    max_size_mb = constraints.get("max_size_mb")
    multiple = constraints.get("multiple", False)

    # 规范化为列表
    if isinstance(value, str):
        ids = [value]
    elif isinstance(value, list):
        ids = value
    else:
        return None, f"文件变量值应为 FileRef ID 字符串或列表，收到 {type(value).__name__}"

    if not multiple and len(ids) > 1:
        return None, "此变量不允许多文件"

    file_svc = FileService(storage=LocalFileStorage())
    resolved = []
    for fid in ids:
        fref = await file_svc.get(fid)
        if fref is None:
            return None, f"文件 {fid} 不存在"
        # 扩展名检查
        if allowed_ext:
            ext = "." + fref.name.rsplit(".", 1)[-1].lower() if "." in fref.name else ""
            if ext not in [e.lower() for e in allowed_ext]:
                return None, f"文件 {fref.name} 扩展名 {ext} 不在允许列表 {allowed_ext}"
        # 大小检查
        if max_size_mb and fref.size > max_size_mb * 1024 * 1024:
            return None, f"文件 {fref.name} 大小 {fref.size} 超过限制 {max_size_mb}MB"
        resolved.append({
            "file_id": fref.id,
            "name": fref.name,
            "size": fref.size,
            "mime_type": fref.mime_type,
            "storage_key": fref.storage_key,
        })

    if multiple:
        return resolved, None
    return resolved[0] if resolved else None, None
```

**StartNodeExecutor 集成点：**
```python
# 在 node_executor.py 的 execute() 方法中
for var_def in output_variables:
    var_type = var_def.get("type", "text")
    var_name = var_def["name"]

    if var_type == "file":
        raw_value = task_input.get(var_name)
        if raw_value is None:
            # 处理 required / default
            ...
        resolved, error = await validate_file_variable(raw_value, var_def)
        if error:
            raise ValueError(f"文件变量 '{var_name}' 验证失败: {error}")
        output[var_name] = resolved
    else:
        # 现有逻辑不变
        ...
```

### ⚠️ 回归防护

**不能破坏的现有行为：**
1. 非 `file` 类型变量的处理完全不变
2. 无 `output_variables` 的工作流向后兼容
3. `ExpressionEngine` 解析逻辑不变
4. `VariablePool` 结构不变
5. 现有测试套件全部通过（801 tests）

### 📁 文件清单

**新建：**
- `backend/app/engine/workflow/file_validator.py` — 文件变量验证器
- `backend/tests/engine/workflow/test_file_validator.py` — 验证器测试

**修改：**
- `backend/app/engine/workflow/node_executor.py` — StartNodeExecutor 集成文件类型
- `backend/app/engine/agent/builder.py` — 工作流声明中文件参数说明

### 🚫 本 Story 不做的事

- **不做前端工作流运行器文件上传 UI** — 当前工作流通过 Agent `dispatch_workflow` 触发，前端运行器（test-run）暂不处理文件上传
- **不做文件内容自动注入 Agent** — Agent 需通过 FileService/read 工具主动读取
- **不做文件类型变量在工作流画布中的可视化增强** — 前端已有 file 类型显示
- **不做 Agent 自动上传文件** — Agent 需先通过聊天上传获取 FileRef ID，再传入工作流

### Dependencies to Add

无新依赖。

### References

- [Source: backend/app/engine/workflow/node_executor.py] — StartNodeExecutor
- [Source: backend/app/engine/workflow/variable_pool.py] — VariablePool
- [Source: backend/app/engine/agent/builder.py] — 工作流工具声明
- [Source: backend/app/services/file_service.py] — FileService
- [Source: frontend/src/features/workflow-editor/utils/variable-types.ts] — 前端 file 类型定义

## Dev Agent Record

### Implementation Plan
- T1: 新建 `file_validator.py` — 纯函数 `validate_file_variable()`，mock FileService.get 做存在性检查
- T2: 修改 `StartNodeExecutor.execute()` — 在 `output_variables` 循环中识别 `type == "file"` 并调用验证器
- T3: 修改 `_build_workflow_tool_declaration` — file 类型参数追加 "pass FileRef ID string" 提示
- T4: 13 个 file_validator 单元测试 + 4 个 StartNodeExecutor 文件类型集成测试

### Debug Log
- `_get_file_service()` 使用延迟导入模式（函数内 `from app.services...`），避免模块加载时循环依赖
- `validate_file_variable` 返回 `(resolved, error)` 元组，None+str 表示失败，dict/list+None 表示成功
- 扩展名检查对大小写不敏感（`.PDF` 匹配 `.pdf`）
- 文件无扩展名时 ext 为空字符串，不在允许列表中 → 报错

### Completion Notes
✅ 全部 7 个 AC 满足
✅ 818 tests passed, 0 failures（801 原有 + 17 新增）
✅ file_validator：单文件/多文件正常解析、不存在、扩展名错误、超限、类型错误、部分无效报错位置
✅ StartNodeExecutor：file 类型验证集成，非 file 类型完全不变（回归兼容）
✅ 工作流工具声明：file 参数追加 FileRef ID 提示，非 file 格式不变
✅ required 缺失仍走原有 `missing_required` 路径（与 test_file_type_no_required_field 兼容）

## File List

**新建:**
- `backend/app/engine/workflow/file_validator.py` — 文件变量验证器
- `backend/tests/engine/workflow/test_file_validator.py` — 13 个验证器单元测试

**修改:**
- `backend/app/engine/workflow/node_executor.py` — StartNodeExecutor 集成 file 类型验证
- `backend/tests/engine/workflow/test_node_executors.py` — 4 个 StartNode 文件类型集成测试
- `backend/app/engine/agent/builder.py` — 工作流声明中 file 参数追加 FileRef ID 提示

## Change Log
- 2026-06-23: Story 10-5 实现完成 — 工作流启动节点文件类型支持（验证器 + StartNode 集成 + 工具声明）

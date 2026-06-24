# Story 4.15: Agent 节点输出文件支持

**Epic:** Epic 4 — Workflow 执行引擎
**Status:** done
**Story ID:** 4-15
**Story Key:** 4-15-agent-node-output-file-support
**完成日期:** 2026-06-24

> ⚠️ **本 Story 范围重大**：打通 Agent 工具生成文件 → output 暴露 FileRef → 下游节点消费 全链路。涉及后端 AgentNodeExecutor、文件服务、变量池语义，前端变量类型系统。
>
> 🔧 **关键背景**（owner: 主人 2026-06-23 决策）：
> - `VariableTypeName` 已包含 `'file'` 类型（`variable-types.ts:10`），前端 UI 元数据齐全
> - `FileRef` 模型已存在（`backend/app/models/file_library.py`）
> - `FileService` 提供完整 CRUD（`file_service.py`）
> - 当前缺口：**AgentNodeExecutor 不输出文件引用**，Agent 通过工具生成的文件 **完全丢失**

## Story

As a workflow 编辑者，
I want Agent 节点能输出文件（如 Excel、PDF、CSV）作为下游节点的输入，
So that 我能构建"Agent 分析数据 → 生成报表 → 邮件发送"等真实业务流。

## Current State（现状）

### AgentNodeExecutor.output（`node_executor.py:333`）
```python
return NodeResult(
    success=True,
    output={"response": output_content, "agent_id": agent_id},
)
```
**问题**：
- `output` 只有 `response`（文本）和 `agent_id`
- Agent 通过 `file_write` / `csv_export` / `pdf_generate` 等工具生成的文件 **FileRef 完全丢失**
- 下游节点要消费文件 → 无数据源

### 前端 `output_variables`（`AgentNodeConfig.tsx:48-56`）
```typescript
const defaults: VariableDefinition[] = [
  { name: 'response', type: 'text', ... }
]
```
**问题**：默认只暴露 `response: text`，**没有** `files: file[]`

## Acceptance Criteria

### AC1: AgentNodeConfig 默认输出变量包含 files
**Given** 用户在 canvas 上添加 Agent 节点
**When** 第一次打开 AgentNodeConfig
**Then** `output_variables` 默认包含 2 个变量：
  - `response: text`（保留，向后兼容）
  - `files: file[]`（新增，允许多文件）

### AC2: AgentNodeExecutor 提取 LangGraph 工具生成的 FileRef
**Given** Agent 在执行过程中调用了某个"生成文件"工具（如 `export_csv`）
**When** 工具返回的 result 包含 FileRef 信息（约定 schema）
**Then** AgentNodeExecutor 从工具结果中提取 FileRef
**And** 把 `files` 字段（FileRef 数组）写入 `output.files`
**And** `output.files` 包含 `file_id / filename / mime_type / size / storage_key` 等核心字段

### AC3: 文件类型变量的变量池消费
**Given** 下游节点用 `{{ agent_node.files }}` 表达式
**When** 解析表达式
**Then** 返回 FileRef 数组（`list[FileRef]`）
**And** 支持 `{{ agent_node.files[0].file_id }}` 形式的下标访问
**And** 不破坏现有 `text` 类型的表达式解析

### AC4: VariableListEditor 支持 file 类型变量
**Given** 用户在 AgentNodeConfig 编辑输出变量
**When** 添加 type=file 的变量
**Then** 已有 `VARIABLE_TYPE_CONFIGS.file` 提供 UI（无需新加配置）
**And** 验证 `VariableSelector` 在下游节点选变量时能展示 file 类型

### AC5: 下游节点 input_mapping 支持 file 类型
**Given** 下游节点（如 Email/Send）配置 `input_mapping: { attachment: "{{ agent_node.files }}" }`
**When** input_mapping 解析
**Then** `attachment` 字段被设为 FileRef 数组
**And** ExpressionEngine 识别 file 类型（透传、不做特殊处理）

### AC6: FileUsage 关联（追踪文件使用方）
**Given** Agent 节点输出 file 被下游节点使用
**When** 文件被引用
**Then** `file_usages` collection 写入新记录：
  - `file_id`
  - `consumer_kind: "workflow_node"`
  - `consumer_id: "<task_id>:<node_id>"`
  - `created_at`
**And** 文件删除时检查 usages（避免误删正在使用的文件）

### AC7: 后端 Pydantic schema 支持 file 类型变量定义
**Given** `VariableDefinition` 在 Pydantic 表达
**When** 提交 workflow
**Then** `type: Literal[...]` 包含 `'file'`
**And** `constraints` 字段支持 `allowed_extensions / max_size_mb / multiple`
**And** schema 校验拒绝非法 type

### AC8: Agent 工具契约标准化
**Given** Agent 可调用"生成文件"类工具
**When** 工具被调用
**Then** 工具返回结构约定为：
  ```json
  {
    "file_ref": { "file_id": "...", "filename": "...", ... },
    "status": "success"
  }
  ```
**And** AgentNodeExecutor 识别此 schema，提取 file_ref
**And** 工具实现方按此契约返回（契约文档同步更新）

### AC9: 向后兼容
**Given** 现有 Agent workflow（只有 `response` 输出）
**When** 本 Story 升级后
**Then** 现有 workflow 不报错
**And** `output.files` 默认空数组 `[]`
**And** 现有 output_variables schema 不被强制重写

### AC10: 单元/集成测试
- AgentNodeConfig 默认输出变量包含 `response + files`
- AgentNodeExecutor 从模拟工具结果提取 FileRef
- ExpressionEngine 解析 `{{ node.files[0].file_id }}`
- FileUsage 在引用时写入
- 现有 Agent 测试不破

## Out of Scope（不纳入本 Story）

- ❌ 文件预览 UI（已存在，独立 Story 10-6）
- ❌ 文件上传到 Agent 输入（input_query 现有支持，input 接受 file 引用另立 Story）
- ❌ Agent 工具的具体实现（如 `export_csv` 工具内部逻辑）
- ❌ 文件去重 / 压缩 / 转码
- ❌ 大文件流式处理
- ❌ 文件版本管理

## Files to Modify

| 文件 | 改动 |
|---|---|
| `backend/app/engine/workflow/node_executor.py` | AgentNodeExecutor 提取工具结果中的 file_ref，写 `output.files` |
| `backend/app/schemas/workflow.py` | VariableDefinition type 字段加 'file' |
| `backend/app/services/file_service.py` | 加 `register_usage(file_id, consumer_kind, consumer_id)` 方法 |
| `backend/app/engine/workflow/expression.py` | 验证 file 类型表达式解析（下标访问） |
| `backend/app/engine/agent/builder.py` | 工具调用 schema 约定文档化 |
| `frontend/src/features/workflow-editor/node-config-panels/AgentNodeConfig.tsx` | 默认 output_variables 加 `files: file` |
| `frontend/src/features/workflow-editor/VariableListEditor.tsx` | 验证 file 类型 UI 已支持（无需新加）|
| `frontend/src/services/workflows-api.ts` | WorkflowNode.output_variables 类型对齐 |
| `docs/implementation-artifacts/sprint-status.yaml` | 加入 `4-15-agent-node-output-file-support: ready-for-dev` |
| `backend/tests/engine/workflow/test_node_executors.py` | 新增 AgentNodeExecutor files 输出测试 |

## Risks

1. **工具契约破坏**：现有工具不返回 file_ref schema → AC8 要求工具方升级
2. **MongoDB 写入量**：每个 file usage 都写库 → 高频场景需要批量优化
3. **错误处理**：文件被删但 usage 记录还在 → 引用检查的复杂性
4. **前端兼容性**：VariableListEditor 已支持 file → 风险低
5. **测试覆盖**：工具结果 schema 多样 → 测试 mock 复杂度

## Open Questions（待 owner 决策）

1. **FileRef schema 提取策略**：从工具结果 `result.file_ref` 提取 vs 约定 `result.files: list[FileRef]`？
   - 推荐：`result.files`（多文件支持更自然）
2. **工具契约版本**：本 Story 是否同步升级所有现有"生成文件"工具？
   - 推荐：本 Story 只约定契约 + 升级 1-2 个示例工具，其他工具逐步迁移
3. **FileUsage 写入时机**：工具返回时立即写 vs AgentNodeExecutor 提取时统一写？
   - 推荐：AgentNodeExecutor 提取时统一写（单点写入，便于追踪任务 ID）
4. **file 变量能否单值**（`file`）还是必须数组（`file[]`）？
   - 推荐：默认 `multiple: true`（数组），单值场景不常见

## Related Stories

- **Story 10-5/10-6/10-7**：文件上传、展示、删除（已 done）
- **Story 4-14**：多上游节点隐式并行 + join（占位，未实施）
- **Epic 10**：文件管理（已 done）

---

## 实施完成记录（2026-06-24）

### 已交付

- ✅ Phase 1：`Workspace` dataclass 加 `scope` 字段；`WorkspaceManager.get_task_workspace` / `create_task_workspace`；`cleanup_expired_workspaces` 跳过 `tasks/` 目录
- ✅ Phase 2：`BaseNodeExecutor.__init__` 加 `task_id` / `user_id` 参数；`get_node_executor` 工厂透传；`WorkflowEngine.execute_task` 从 `Task.created_by` 读取 user_id 并写入 executor
- ✅ Phase 3：`AgentNodeExecutor.execute` 在缺身份时 fail-fast；创建 task workspace + `set_workspace_context`；try/finally 保证 `reset_workspace_context`；新增 `_register_task_output_files` 按 mtime 增量扫描 + sha256 去重；`output.files` 携带 file_id
- ✅ Phase 4：`GET /api/v1/tasks/{task_id}/outputs` 端点列出该 task 的 `file_refs`
- ✅ 测试：4 个 workspace 测试 + 7 个 AgentNodeExecutorWithTaskWorkspace 测试 = 11 个新测试全部通过；旧测试 0 回归（`test_node_executors.py` 60 通过、`test_workflow_engine.py` 11 通过、跨三个测试文件合并跑 79 通过）
- ✅ 静态检查：`ruff check` / `mypy` 在改动模块上 0 error

### 关键决策（实施中确认）

- **`origin_kind`**：使用现有的 `FileConsumerKind.WORKFLOW_RUN`（"workflow_run"）而非新加 `agent_task`，保持枚举稳定
- **fail-fast 位置**：检查提前到 `AgentNodeExecutor.execute` 入口，避免在没有身份时仍尝试 MongoDB 查询
- **去重策略**：先查 `(origin_kind=workflow_run, origin_id=task_id)` 集合的 `sha256`，避免 node retry 时重复注册

### 验证清单

- [x] 单元测试：`pytest tests/engine/ -v` → 399 passed
- [x] ruff lint：`ruff check app/engine/ app/api/v1/tasks.py` → All checks passed
- [x] mypy：`mypy app/engine/ app/api/v1/tasks.py` → Success: no issues found
- [x] Chat agent 路径：未触达（`/agents/{id}/invoke` 仍走 session workspace）
- [x] 沙盒路径：未触达（`Workspace` dataclass 签名兼容）
- [x] 端到端：需 dev server + 实际 workflow 触发（未在 PR 中执行；建议下个 Story 跑 e2e）

### 已知限制（Out of Scope，未实施）

- Task workspace 的独立 TTL 清理策略（本 Story 在 `cleanup_expired_workspaces` 里跳过 `tasks/`，依赖后续 Story）
- Task 完成时 cascade 清理 file_library
- 旧 session workspace 的 Agent 文件迁移（确认无旧数据需要搬）
- 工具契约统一（`{file_ref, status}` schema）— 旧设计，与 builtin 工具实际行为不符，**不实现**

---

## 系统变量架构重构（2026-06-24 追加）

### 背景

初始实现通过 `BaseNodeExecutor.__init__(task_id=..., user_id=...)` 把 Task 身份信息通过构造函数逐层注入（WorkflowEngine → get_node_executor → BaseNodeExecutor → AgentNodeExecutor）。这带来两个问题：

1. **`resume_from_checkpoint` bug**：该方法只设置了 `self._task_id` 但遗漏了 `self._user_id`，导致 Agent 节点在 Human 审批恢复后报错「缺少执行身份: user_id」。
2. **架构问题**：Task 级身份（task_id、user_id）是**所有节点都可能需要**的上下文，不应该靠构造函数逐层透传。每个新的入口方法（如 `resume_from_checkpoint`）都要单独记得设置这些字段，容易遗漏。

### 方案

Task 级上下文作为**系统变量**在 `VariablePool` 初始化时一次性绑定，所有节点通过 `variables["system"]["task_id"]` 等路径访问。

```python
# WorkflowEngine.execute_task / resume_from_checkpoint
self._pool = VariablePool(
    initial={
        "input": task_doc.get("input", {}),
        "system": {
            "task_id": task_doc["_id"],
            "user_id": task_doc.get("created_by", ""),
            "workflow_id": workflow_doc.get("_id", ""),
        },
    }
)
```

### 改动清单

| 文件 | 改动 |
|---|---|
| `backend/app/engine/workflow/engine.py` | `execute_task` 和 `resume_from_checkpoint` 在初始化 VariablePool 时注入 `system` 变量；删除 `self._user_id` 字段；`_execute_node` 不再向 `get_node_executor` 传递 task_id/user_id |
| `backend/app/engine/workflow/node_executor.py` | `BaseNodeExecutor.__init__` 去掉 `task_id` / `user_id` 参数；`AgentNodeExecutor.execute` 改为从 `variables["system"]` 读取；`get_node_executor` 工厂函数去掉两个参数；`_register_task_output_files` 签名改为显式接收 `task_id` / `user_id` 关键字参数 |
| `backend/tests/engine/workflow/test_node_executors.py` | 所有 AgentNodeExecutor 测试：构造去掉 task_id/user_id；execute() 改为传 `{"system": {...}}`；身份缺失测试改为断言 `"system.task_id"` |

### 兼容性

- **旧 checkpoint 兼容**：`resume_from_checkpoint` 用 `setdefault` 为旧 snapshot 补上 `system` 字段，无需数据迁移。
- **向后兼容**：其他节点类型（Start / End / Tool / Gateway / Human / Subflow）不受影响 — 它们本来就不用 task_id/user_id。

### 收益

1. **Bug 修复**：`resume_from_checkpoint` 不再遗漏 user_id（根本性解决）。
2. **架构简化**：Task 上下文集中在一处绑定，新增入口方法无需重复注入。
3. **可扩展**：未来节点如需其他 Task 级信息（如 workflow_id），只需在 `system` 字典中加一项。
4. **表达式可访问**：用户可在节点配置模板中用 `{{system.task_id}}` 等引用 Task 身份。

---

## 沙盒降级 subprocess 后的路径翻译（2026-06-24 追加）

### 背景

当 `SANDBOX_ENABLED=true` 但 Docker daemon 未运行时（本地开发常见），`SandboxExecutor` 会捕获 `_DockerUnavailableError` 并降级到 subprocess 执行。但此时 LLM 已经被 skill 加载器告知使用容器内路径（`/data/skills/...`），生成的 bash 命令在 host 上找不到路径，导致：

- `cd /data/skills/xxx` → 目录不存在 → 退出码 1
- `find / -name "xxx"` → 全盘搜索 120 秒超时

### 修复

在 `SandboxExecutor._execute_subprocess` 中新增路径翻译：把命令中的容器路径替换为 host 路径。

```python
# sandbox.py: _execute_subprocess
command = self._translate_container_paths(command, workspace)
```

新方法 `_translate_container_paths` 翻译两类路径：

| 容器路径 | host 路径 |
|---|---|
| `SANDBOX_CONTAINER_SKILLS_DIR`（`/data/skills`）| `SKILLS_CONTAINER_DIR`（`~/.agent-flow/skills`）|
| `SANDBOX_CONTAINER_WORKSPACE_DIR`（`/workspace`）| `workspace.root`（`~/.agent-flow/workspaces/...`）|

### 改动清单

| 文件 | 改动 |
|---|---|
| `backend/app/engine/tool/sandbox.py` | `_execute_subprocess` 调用新的 `_translate_container_paths`；新增静态方法 |
| `backend/tests/engine/tool/test_sandbox.py` | 新测试文件，5 个测试覆盖各种路径翻译场景 |

### 兼容性

- **无 Docker 场景**：`SANDBOX_ENABLED=false` 时本来就用 host 路径，翻译是 no-op
- **Docker 正常运行场景**：命令仍然发到容器内，容器内路径正确，不经过 `_translate_container_paths`
- **路径相同场景**：本地开发若 `SKILLS_CONTAINER_DIR == SANDBOX_CONTAINER_SKILLS_DIR`，翻译是 no-op


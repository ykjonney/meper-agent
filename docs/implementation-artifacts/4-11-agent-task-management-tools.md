# Story 4.11: Agent Task 管理工具

**Epic:** Epic 4 — DAG 工作流编排 + Task 运行时
**Status:** ready-for-dev
**Story ID:** 4-11
**Story Key:** 4-11-agent-task-management-tools

## Story

As a 开发者，
I want Agent 拥有一组系统级工具在运行时管理和查询 Task，
So that Agent 能自主搜索工作流、创建 Task、跟踪进度、介入调整、收集结果。

> ⚠️ **关键背景**：这组工具是 Agent 与 Workflow 系统的桥梁。Agent 通过工具感知可用工作流、创建 Task、查询进度、干预执行。
> **重要约束**：Agent 创建 Task 前必须先询问用户确认（Story 4-10 AC4）。
> Workflow Registry 在 Agent 启动时注入到 System Prompt，Agent 通过工具进一步查询。

## Acceptance Criteria

### AC1: Agent 启动时注入 Workflow Registry
**Given** Agent 已配置并绑定工作流
**When** Agent 启动构建 System Prompt
**Then** 绑定的工作流注册信息注入 System Prompt（不注入全量列表，仅注册摘要）
**And** 注册信息包含：`workflow_id`, `name`, `when_to_use`（简短描述）, `input_schema`（摘要）, `has_human_node`（布尔）, `side_effects`（列表）

### AC2: 9 种 Agent Task 工具
**Given** Agent 已启动
**When** 检查 Agent 可用的系统级工具列表
**Then** 以下 9 种工具自动注入：

| 工具名 | 输入 | 输出 | 说明 |
|--------|------|------|------|
| `search_workflow` | `query: str` | `list[WorkflowSummary]` | 搜索匹配的工作流模板 |
| `get_workflow_schema` | `workflow_id: str` | `WorkflowSchema` | 获取工作流的完整 input_schema |
| `create_task` | `workflow_id, input, scheduled_at?` | `TaskCreated` | 创建 Task（**必须先询问用户**） |
| `task_query` | `task_id: str` | `TaskDetail` | 查询 Task 状态、变量、输出 |
| `task_intervene` | `task_id, action, reason?, version` | `TaskStatus` | 干预 Task（cancel/retry/update_variables） |
| `task_list` | `filter?` | `list[TaskSummary]` | 列出当前会话/Agent 的 Task |
| `cancel_task` | `task_id: str, reason?` | `TaskStatus` | 取消指定 Task |
| `get_task_timeline` | `task_id: str` | `list[TimelineEvent]` | 获取 Task 执行时间线 |
| `update_task_variables` | `task_id, variables, version` | `TaskDetail` | 修改变量池 |

### AC3: create_task 工具行为
**Given** Agent 调用 `create_task`
**When** 参数校验通过
**Then** 后端创建 Task，设置 `created_by` 为 Agent ID，`created_by_type` 为 "agent"
**And** 返回 `{task_id, status: "pending", version: 1}`
**And** Agent 可通过 `task_query` 轮询进度
**And** 如果工作流包含 human 节点，创建时在 Task 中标记

**Given** Agent 调用 create_task 前
**When** Agent 已向用户确认
**Then** 工具不额外弹出确认框（Agent 层面已确认）

### AC4: search_workflow 工具行为
**Given** Agent 调用 `search_workflow`
**When** 传入查询关键词
**Then** 在已发布工作流中搜索名称和描述匹配的
**And** 返回前 10 条匹配结果（含 `workflow_id`, `name`, `description`, `has_human_node`, `side_effects`）
**And** 无匹配时返回空列表（不报错）

### AC5: task_intervene 工具行为
**Given** Agent 调用 `task_intervene`
**When** 传入 `task_id`, `action`, `version`
**Then** 校验 version 乐观锁
**And** 仅 Agent 自己创建的 Task 可被干预
**And** 非本 Agent 创建的 Task 返回权限错误

### AC6: Workflow Registry 存储
**Given** 开发者发布工作流
**When** 发布成功
**Then** 工作流注册信息写入 `workflow_registry` 集合
**And** 注册信息包含：`workflow_id`, `name`, `description`, `input_schema`, `has_human_node`, `side_effects`, `tags[]`, `published_at`

**Given** 工作流下架
**When** 下架操作
**Then** Registry 中标记为 `status: inactive`
**And** Agent 搜索时不再返回

## Key Files

| 文件 | 操作 |
|------|------|
| `backend/app/services/workflow_registry_service.py` | **新建** — Workflow Registry 管理 |
| `backend/app/models/workflow_registry.py` | **新建** — Registry Model |
| `backend/app/engine/agent/tools/system_tools/task_tools.py` | **新建** — 9 种 Task 工具的 StructuredTool 定义 |
| `backend/app/engine/agent/builder.py` | **改造** — 注入系统级 Task 工具 + Registry 摘要 |
| `backend/app/engine/agent/react_executor.py` | **改造** — 处理 create_task 前的用户询问逻辑 |
| `backend/tests/engine/agent/test_task_tools.py` | **新建** — Task 工具测试 |
| `backend/tests/services/test_workflow_registry.py` | **新建** — Registry 测试 |

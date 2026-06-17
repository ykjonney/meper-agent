# Story 4.9: Workflow 引擎节点执行器

**Epic:** Epic 4 — DAG 工作流编排 + Task 运行时
**Status:** ready-for-dev
**Story ID:** 4-9
**Story Key:** 4-9-workflow-engine-node-executor

## Story

As a 开发者，
I want Workflow 引擎能按 DAG 拓扑顺序执行节点，管理变量池，支持表达式注入，
So that Task 发布后可按模板定义自动执行，节点间数据通过变量池流转。

> ⚠️ **关键背景**：本 Story 实现 Workflow Engine 的核心执行能力，包括 Node Executor Strategy 模式、Variable Pool、Expression Engine。
> 不包含 Human-in-the-loop（Story 4-10）、事件总线（Story 4-14）、定时调度（Story 4-13）。
>
> Node Executor 采用 Strategy 模式：`BaseNodeExecutor` 抽象类 + 各节点类型实现。
> 变量池使用 MongoDB 嵌入文档，表达式引擎使用 jinja2 sandbox 安全求值。

## Acceptance Criteria

### AC1: Node Executor Strategy 模式
**Given** Workflow Engine 定义了节点执行抽象
**When** 检查架构
**Then** 提供 `BaseNodeExecutor` 抽象类，包含 `async execute(node_config, variables) -> NodeResult`
**And** 实现以下节点执行器：

| 节点类型 | 执行器 | 说明 |
|---------|--------|------|
| start | StartNodeExecutor | 初始化变量池，传入 input |
| end | EndNodeExecutor | 汇总输出，标记 Task 完成 |
| agent | AgentNodeExecutor | 调用 Agent 推理（使用 Agent builder 创建临时 Agent） |
| tool | ToolNodeExecutor | 调用工具池中的工具，含参数注入 |
| gateway | GatewayNodeExecutor | 按顺序评估条件表达式，选择分支 |
| parallel | ParallelNodeExecutor | 并行执行多分支，按 join_strategy 合并 |
| subflow | SubflowNodeExecutor | 创建子 Task，等待完成后返回结果 |

### AC2: DAG 拓扑执行
**Given** Workflow 模板定义了 nodes 和 edges
**When** Task 开始执行
**Then** 引擎计算 DAG 拓扑排序，从 start 节点开始
**And** 每个节点完成后，根据出边选择下一个可执行节点
**And** gateway 节点根据条件表达式选择目标分支
**And** parallel 节点同时执行所有子分支
**And** 所有路径最终汇聚到 end 节点

### AC3: Variable Pool 变量池
**Given** Task 有独立变量池
**When** 节点执行
**Then** 每个节点执行完成后，其输出写入变量池：`variables[node_id] = output`
**And** 变量池初始包含 `input` 键（Task 创建时传入的 input）
**And** 变量池支持嵌套字段访问（如 `node1.result.status`）
**And** 变量池中的变量在下游节点通过表达式引用

### AC4: 表达式引擎（{{node.field}}）
**Given** 节点配置或条件表达式中包含 `{{node.field}}` 语法
**When** 引擎执行时遇到该表达式
**Then** 使用 jinja2 sandbox 安全求值
**And** `task_agent` 替换为 `agent` 查询结果
**And** 未定义的变量求值为 `null`（不抛出异常）
**And** 注入参数时，未定义变量对应的参数值为 `null`
**And** gateway 条件中未定义变量视为 `false`，走 `fallback_on_error` 分支

### AC5: Workflow Engine 核心 API
**Given** 引擎已实现
**When** 调用 `WorkflowEngine.execute_task(task)`
**Then** 引擎加载 Task 绑定的 workflow_version 快照
**And** 按 DAG 拓扑顺序执行节点
**And** 每个节点执行结果写入变量池
**And** 最终输出写入 Task 的 output 字段
**And** 执行完成后 Task 状态转为 completed 或 failed
**And** 所有执行步骤记录到执行时间线

**Given** 节点执行失败
**When** 节点抛出异常
**Then** 引擎捕获异常，Task 进入 failed 状态
**And** error 字段包含：`{node_id, node_type, error_message, timestamp}`
**And** 已执行的节点输出保留在变量池中（用于调试）

### AC6: 执行上下文注入
**Given** Node Executor 执行节点
**When** 节点配置中引用变量
**Then** 在传递给节点执行器之前，先解析配置中的 `{{node.field}}` 表达式
**And** 解析后的配置包含实际值而非模板语法
**And** 表达式解析失败时节点进入 failed 状态

## Key Files

| 文件 | 操作 |
|------|------|
| `backend/app/engine/workflow/__init__.py` | **新建** — Workflow engine 包 |
| `backend/app/engine/workflow/engine.py` | **新建** — WorkflowEngine 核心（DAG 拓扑 + 执行循环） |
| `backend/app/engine/workflow/node_executor.py` | **新建** — BaseNodeExecutor 抽象类 |
| `backend/app/engine/workflow/nodes/start.py` | **新建** — Start 节点执行器 |
| `backend/app/engine/workflow/nodes/end.py` | **新建** — End 节点执行器 |
| `backend/app/engine/workflow/nodes/agent.py` | **新建** — Agent 节点执行器 |
| `backend/app/engine/workflow/nodes/tool.py` | **新建** — Tool 节点执行器 |
| `backend/app/engine/workflow/nodes/gateway.py` | **新建** — Gateway 条件分支执行器 |
| `backend/app/engine/workflow/nodes/parallel.py` | **新建** — Parallel 并行执行器 |
| `backend/app/engine/workflow/nodes/subflow.py` | **新建** — Subflow 子 Task 执行器 |
| `backend/app/engine/workflow/variable_pool.py` | **新建** — VariablePool 管理器 |
| `backend/app/engine/workflow/expression.py` | **新建** — jinja2 sandbox 表达式引擎 |
| `backend/tests/engine/workflow/test_engine.py` | **新建** — 引擎测试 |
| `backend/tests/engine/workflow/test_variable_pool.py` | **新建** — 变量池测试 |
| `backend/tests/engine/workflow/test_expression.py` | **新建** — 表达式引擎测试 |

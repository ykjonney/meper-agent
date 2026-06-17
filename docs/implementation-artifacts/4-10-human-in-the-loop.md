# Story 4.10: Human-in-the-loop（人工审批）

**Epic:** Epic 4 — DAG 工作流编排 + Task 运行时
**Status:** ready-for-dev
**Story ID:** 4-10
**Story Key:** 4-10-human-in-the-loop

## Story

As a 操作员，
I want 工作流执行到人工节点时收到通知，可在对话或管理页面中完成审批/驳回/跳过操作，
So that 需要人工判断的环节不会遗漏，超时也有自动降级处理，Agent 在创建 Task 前会先询问用户。

> ⚠️ **关键背景**：Human-in-the-loop 涉及三个层面：
> 1. **Workflow 内的 Human 节点** — 工作流执行到人工节点时暂停等待用户操作
> 2. **Agent 创建 Task 前询问** — Agent 在调用 create_task 前先向用户确认
> 3. **干预 API** — 通过 REST API/对话对运行中的 Task 进行干预
>
> 前后台模式已移除。所有 Task 创建后异步执行，用户通过 Task 管理面板或对话界面查看进度和干预。

## Acceptance Criteria

### AC1: Human 节点执行
**Given** Workflow 执行到 Human 节点
**When** Task 进入 `waiting_human` 状态
**Then** 节点暂停执行，Task 状态变为 `waiting_human`
**And** 执行时间线记录：`{event_type: "waiting_human", node_id, timestamp}`
**And** Human 节点配置中包含：`title`, `description`, `options[]`, `timeout_ms`, `timeout_action`, `assignee`

### AC2: Human 节点超时处理
**Given** Human 节点配置了 `timeout_ms`
**When** 超过指定时间仍未收到人工操作
**Then** 按 `timeout_action` 执行：
- `auto_approve` — 自动审批，继续执行
- `auto_reject` — 自动驳回，Task 进入 failed
- `auto_skip` — 跳过该节点，继续执行
- `fail` — Task 进入 failed 状态
**And** 审计日志记录"Human 节点超时，执行 timeout_action"

### AC3: 干预 REST API
**Given** Task 处于可干预状态
**When** 调用 `POST /api/v1/tasks/{task_id}/intervene`
**Then** 请求体包含 `{action, reason?, version}`
**And** 支持以下干预操作：

| 操作 | 可用状态 | 效果 |
|------|---------|------|
| `approve` | waiting_human | 审批通过，Human 节点继续 |
| `reject` | waiting_human | 驳回，Task 进入 failed |
| `skip` | waiting_human | 跳过 Human 节点继续 |
| `retry` | failed | 重试失败的节点 |
| `pause` | running | 暂停执行 |
| `resume` | paused | 恢复执行 |
| `cancel` | pending/running/waiting_human/paused | 取消 Task |
| `update_variables` | any | 修改变量池（含 diff 记录） |

**And** 干预请求携带 `version` 乐观锁，冲突返回 409
**And** 所有干预操作记录审计日志

### AC4: Agent 创建 Task 前询问用户
**Given** Agent 判断需要创建 Task
**When** Agent 在工作流执行模式中准备调用 `create_task`
**Then** Agent 先向用户发送确认消息，说明：
- 将使用哪个工作流模板
- 输入参数概览
- 预计执行时长（如有）
- 是否包含人工审批节点
**And** 用户确认后 Agent 才调用 `create_task`
**And** 用户拒绝则 Agent 返回替代方案或结束
**And** 如果工作流模板标记了 `has_human_node: true`，Agent 需特别提示用户

### AC5: 对话界面的审批卡片
**Given** Task 进入 `waiting_human` 状态
**When** 用户当前有活跃对话
**Then** 对话界面展示审批卡片（包含：标题、描述、审批/驳回/跳过按钮）
**And** 用户点击按钮后调用干预 API
**And** 审批结果在对话中展示（"已审批"/"已驳回"/"已跳过"）

### AC6: Agent 重试机制
**Given** Task 执行失败进入 `failed` 状态
**When** Agent 检测到 Task 失败
**Then** Agent 向用户报告失败原因
**And** 询问用户是否重试
**And** 用户确认后 Agent 调用 `task_intervene(task_id, "retry")`
**And** 重试后 Task 状态回到 `running`

## Key Files

| 文件 | 操作 |
|------|------|
| `backend/app/engine/workflow/nodes/human.py` | **新建** — HumanNodeExecutor（含超时处理） |
| `backend/app/engine/workflow/intervention.py` | **新建** — 干预操作引擎 |
| `backend/app/api/v1/tasks.py` | **改造** — 添加 intervene 路由 |
| `backend/app/services/task_service.py` | **改造** — 添加干预逻辑 |
| `backend/app/engine/agent/builder.py` | **改造** — Agent create_task 前注入询问提示 |
| `backend/tests/engine/workflow/test_human_node.py` | **新建** — Human 节点测试 |
| `backend/tests/api/test_task_intervention.py` | **新建** — 干预 API 测试 |

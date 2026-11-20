# Agent 后台任务执行链路设计

> 日期：2026-11-10 ｜ 状态：已获批准（主人逐节确认）
> 范围：Task 支持 workflow / agent 两种执行目标，打通 Agent 后台执行

## 1. 背景与目标

当前 Task 只能以工作流为目标执行（`task.workflow_id`）。前端 `TaskBoard.tsx`
已预留 `target.kind: 'workflow' | 'agent'` 选择器，但 agent 提交被 stub toast
拦截（"需要后端支持"）。本设计打通：

- 创建任务时可直接选择一个**已发布 Agent**，以其为执行目标
- 后端经 Celery 后台执行 Agent REACT 循环，任务状态机复用现有 6 态
- 前端任务看板/详情完整支持 agent 任务展示

## 2. 已确认的关键决策

| 决策点 | 结论 |
|---|---|
| 结果落地 | **独立会话 + task.output 摘要**：每次任务自动建独立会话，完整 REACT 过程留会话页可回看；`task.output` 存最终答案 + session_id 关联 |
| 调度范围 | **立即执行 + 手动定时**（scheduled_at 到期扫描）；触发器（webhook/cron 绑定）不做，前端选 agent 时隐藏周期调度 |
| 会话可见性 | 任务会话**不出现在会话列表**，从任务详情「查看执行过程」跳转进入 |
| 架构方案 | **方案 A：单 Celery 入口分流**（run_workflow_task 内按 task 类型分流），复用状态机/调度扫描/取消/并发限制/token 统计 |

## 3. 数据模型

### 3.1 Task（`backend/app/models/task.py`）

```python
workflow_id: str = Field(default="", max_length=100)   # 从必填改为默认空
agent_id: str = Field(default="", max_length=100)      # 新增
```

不变量：**两者恰好其一非空**（schema 层校验，都空或都非空 → ValidationError）。

### 3.2 Session（`backend/app/models/session.py`）

```python
task_id: str = Field(default="", max_length=100)  # 新增：非空 = 任务自动建的会话
```

一个字段两个用途：会话列表查询过滤（隐藏任务会话）+ 任务详情反查执行过程会话。

### 3.3 Schemas

- `TaskCreate`：加 `agent_id: str = ""`，`workflow_id` 变可选
- `TaskSummary` / `TaskResponse`：加 `agent_id` 透传
- `ExecutionResponse`：加 `total_tokens: int = 0`（Runner 写回 `task.total_tokens` 需要带出）
- Agent 任务输入形态：`input = {"instruction": "<用户指令文本>"}`

## 4. 执行流

```
POST /tasks（agent 分支）
  ├─ 校验 agent 存在且 published（fail fast，对齐 workflow 校验，不产生僵尸 task）
  └─ TaskService.create_task(agent_id=...) → pending → run_workflow_task.delay()

run_workflow_task(task_id)            ← 单入口分流（名字保持不变，注释说明）
  └─ 读 task 文档：agent_id 非空 → _run_agent_async()，否则现有 workflow 路径

_run_agent_async(task_id)             ← 新 AgentTaskRunner
  ├─ transition pending→running（复用 transition_task，并发限制免费生效）
  ├─ AgentExecutionService.invoke(agent_id, ExecutionRequest(input=指令), user_id)
  │    └─ 内部自动新建独立会话（session.task_id 回写）
  ├─ 成功 → output={"output": 文本, "session_id", "step_count"} + total_tokens 写回
  │          → transition running→completed
  └─ 失败 → transition running→failed + task.error
```

**取消语义（协作式中断，实施期升级）**：Runner 传 `cancel_checker`
（每轮 REACT 边界查 task DB status 是否 cancelled）——harness 原生支持
该检查点；Celery revoke 仍作兜底；结果回写守卫丢弃迟到的成功结果。

**无人值守语义（实施期确认）**：Runner 调 invoke 时传
`execution_context="workflow"`——harness 现成的无人值守通道：剥离交互式
工具、注入 abort_workflow，后台任务绝不挂起等人。

**重试**：天然复用 intervene retry（清 error → 再 delay → 入口再分流）。

**定时**：`task_scheduler_service` 扫描条件不含任务类型，agent 定时任务自动
被扫到并 delay，零改动。

## 5. 前端改动

### 5.1 创建流程（`TaskBoard.tsx`）

- 删除 stub toast 拦截（393-396 行）
- `createTask` mutation 按 `target.kind` 分流：workflow 传 `workflow_id` +
  变量表单值（现状）；agent 传 `agent_id` + `input = {instruction}`
- 输入表单：选 agent 时渲染指令 textarea（替代 `WorkflowInputForm`）
- 调度选项：agent 目标时只保留「一次性定时」，隐藏周期 cron

### 5.2 任务展示

- `tasks-api.ts`：`TaskSummary` / `TaskDetail` 加 `agent_id`
- 列表/详情目标名：`workflowNameMap` 旁加 `agentNameMap`（published agent 列表解析）
- 详情页：agent 任务不渲染 `TaskFlowGraph`，渲染「指令 → 最终答案 → token
  用量」+「查看执行过程」按钮（跳聊天页定位 session_id 对应会话）

### 5.3 会话主页

session list API 默认过滤 `task_id: ""`（后端过滤，前端零改动）。

## 6. 测试策略

后端 pytest：

| # | 用例 | 验证 |
|---|---|---|
| 1 | Task schema 校验 | workflow_id/agent_id 都空或都非空 → ValidationError |
| 2 | create_task agent 分支 | agent 不存在/非 published → 校验错误，不产生僵尸 task |
| 3 | Celery 入口分流 | agent_id 非空 → 走 agent runner（mock invoke） |
| 4 | Runner 状态流转 | 成功→completed+output+total_tokens；异常→failed+error；回写时已 cancelled→丢弃 |
| 5 | 会话列表过滤 | task_id 非空会话不出现在列表 |

前端：`npm run build` 类型检查 + 手动验收清单（创建/立即跑/定时跑/取消/重试/详情跳转/列表隐藏）。

## 7. 明确不做（YAGNI）

- Agent 触发器（webhook/cron 绑定 agent）
- 协作式中断（worker 内 REACT 循环取消检查点）
- 附件输入（ExecutionRequest 的 file_ids/file_paths，第一版纯指令文本）
- plan_mode 后台执行（后台任务 REACT 直跑到底，无 human-in-loop）
- 用户自选会话执行

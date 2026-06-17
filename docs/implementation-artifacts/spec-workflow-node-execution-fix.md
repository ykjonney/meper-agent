---
title: '修复工作流引擎执行链路 & 节点配置对齐'
type: 'bugfix'
created: '2026-06-12'
status: 'ready-for-dev'
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** WorkflowEngine 从未被调用导致 Task 永远停在 pending；Agent 节点引用不存在的 `build_agent` 函数必定 ImportError；Start/End/Human 节点前后端配置字段名和类型双重不匹配。工作流"测试运行"功能完全断裂。

**Approach:** 修复 Agent 节点执行器调用正确的 `build_agent_graph()`；在 TaskService 创建任务后触发 WorkflowEngine 执行；统一前后端 Start/End/Human 节点的配置字段名和类型。

## Boundaries & Constraints

**Always:** 前端 config 字段名必须与后端 NodeExecutor 实际读取的字段名完全一致；WorkflowEngine 执行结果必须写回 Task.output；保持现有的 VariablePool + ExpressionEngine 架构不变。

**Ask First:** 引入 Celery 异步执行 vs 先用 asyncio.create_task 简单方案；Parallel 节点 join_strategy 的 any/race 是否需要现在实现。

**Never:** 不重构 NodeExecutor 为独立文件；不新增 Subflow 节点的真实实现；不修改 DAG 编辑器的 UI 布局。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| 测试运行完整工作流 | 已发布 Workflow + 有效 input JSON | Task 状态变为 completed，output 包含最终变量池 | 节点执行失败时 Task 状态变为 failed，output 包含错误信息 |
| Agent 节点执行 | config.agent_id 指向有效 Agent | 调用 build_agent_graph 并执行，输出 {response, agent_id} | agent_id 不存在时返回节点执行错误 |
| Start 节点无输入映射 | config.input_mapping 为空 | 透传 variables.input 到变量池 | N/A |
| End 节点输出映射 | config.output_mapping = {"result": "{{response}}"} | 解析表达式后输出 {"result": 实际值} | 表达式引用不存在的变量时返回空字符串 |
| Human 节点超时 | config.timeout_ms = 3600000 (1小时) | 引擎暂停，等待人工审批 | 超时后执行 timeout_action |

</frozen-after-approval>

## Code Map

- `backend/app/engine/workflow/node_executor.py` -- 所有 NodeExecutor 实现（Start/End/Agent/Tool/Gateway/Parallel/Human/Subflow）
- `backend/app/engine/workflow/engine.py` -- WorkflowEngine 核心，_find_start_nodes / _execute_node / _run_dag
- `backend/app/engine/agent/builder.py` -- build_agent_graph() 函数（Agent 节点应调用此函数）
- `backend/app/services/task_service.py` -- TaskService.create_task()，需要在此触发引擎执行
- `backend/app/models/task.py` -- Task 数据模型
- `backend/app/schemas/task.py` -- Task schemas
- `frontend/src/features/workflow-editor/node-config-panels/StartNodeConfig.tsx` -- Start 节点前端配置面板
- `frontend/src/features/workflow-editor/node-config-panels/EndNodeConfig.tsx` -- End 节点前端配置面板
- `frontend/src/features/workflow-editor/node-config-panels/HumanNodeConfig.tsx` -- Human 节点前端配置面板
- `frontend/src/features/workflow-editor/utils/node-defaults.ts` -- 各节点类型默认配置
- `frontend/src/pages/workflow-detail-page.tsx` -- TestRunModal 测试运行弹窗

## Tasks & Acceptance

**Execution:**

- [ ] `backend/app/engine/workflow/node_executor.py` -- 修复 AgentNodeExecutor：`build_agent` → `build_agent_graph`，参数从 Pydantic 模型改为 dict，修复 system_prompt 双重注入逻辑，去除对不存在字段的依赖 -- Agent 节点能正确调用 Agent 执行
- [ ] `backend/app/engine/workflow/node_executor.py` -- 对齐 Start/End/Human 节点执行器读取的字段名：Start 读取 `output_variables`（与前端一致），End 读取 `output_mapping` 为 dict（前端需改），Human 读取 `timeout_minutes` 并转换为 ms -- 前后端配置字段统一
- [ ] `frontend/src/features/workflow-editor/node-config-panels/StartNodeConfig.tsx` -- 添加 `input_mapping` 编辑 UI（ExpressionEditor 或简单的 key-value 编辑），保留现有 output_variables 编辑 -- Start 节点可配置输入映射
- [ ] `frontend/src/features/workflow-editor/node-config-panels/EndNodeConfig.tsx` -- 将 `output_mapping_prompt` 改为 `output_mapping` dict 编辑器（key=输出字段名，value=表达式模板） -- End 节点配置与后端对齐
- [ ] `frontend/src/features/workflow-editor/node-config-panels/HumanNodeConfig.tsx` -- 将 `timeout_minutes` 改为 `timeout_ms`（或后端改为读取 timeout_minutes） -- 超时字段统一
- [ ] `backend/app/services/task_service.py` -- 在 create_task() 成功创建 Task 后，用 asyncio.create_task 调用 WorkflowEngine 执行工作流，执行完成后更新 Task 状态和 output 字段 -- Task 创建后能自动执行
- [ ] `backend/app/engine/workflow/engine.py` -- 确保执行完成后将最终变量池快照写入 Task.output，执行失败时写入错误信息到 Task.output -- 执行结果可查询
- [ ] `frontend/src/pages/workflow-detail-page.tsx` -- TestRunModal 添加 Task 创建后轮询状态变化（每 2 秒查询一次直到终态），显示执行结果 -- 测试运行有反馈

**Acceptance Criteria:**
- Given 已发布的工作流包含 Start → Agent → End 三个节点，当点击"测试运行"并输入有效参数，then Task 状态从 pending → running → completed，output 包含最终输出
- Given Agent 节点配置了有效的 agent_id，当工作流执行到 Agent 节点，then 成功调用 build_agent_graph 并获取 response，不抛出 ImportError
- Given Start 节点配置了 output_variables 定义变量列表，当工作流执行 Start 节点，then 变量池中包含对应变量及其默认值
- Given End 节点配置了 output_mapping，当工作流执行 End 节点，then output 包含表达式解析后的结果
- Given Human 节点配置了 timeout_minutes=30，当工作流执行到 Human 节点，then 引擎暂停执行，超时时间为 30 分钟（1800000ms）

## Spec Change Log

## Design Notes

**Agent 节点修复要点：**
```python
# Before (broken):
from app.engine.agent.builder import build_agent  # 不存在
graph = await build_agent(agent_model)  # Pydantic model

# After (fixed):
from app.engine.agent.builder import build_agent_graph
agent_doc = await db.agents.find_one({"id": config["agent_id"]})
graph = await build_agent_graph(agent_doc)  # dict
result = await graph.ainvoke({"messages": [{"role": "user", "content": resolved_prompt}]})
```

**Task 执行触发方案（简单版）：**
```python
# task_service.py create_task() 末尾
import asyncio
from app.engine.workflow.engine import WorkflowEngine

asyncio.create_task(
    WorkflowEngine(db).run_and_persist(task_id=str(task.id))
)
```

**WorkflowEngine.run_and_persist() 新增方法：**
执行 DAG → 捕获结果或异常 → 更新 Task 状态为 completed/failed → 写入 Task.output

## Verification

**Commands:**
- `cd backend && uv run python -m pytest tests/ -x -q` -- expected: 所有现有测试通过，不引入回归
- `cd backend && uv run python -c "from app.engine.workflow.node_executor import AgentNodeExecutor; print('import ok')"` -- expected: 无 ImportError

**Manual checks:**
- 在前端打开工作流编辑器，配置 Start → Agent → End 的简单工作流，点击"测试运行"，确认 Task 状态变化和输出结果
- 确认前端 Start/End/Human 节点配置面板保存的字段名与后端 NodeExecutor 读取的字段名一致

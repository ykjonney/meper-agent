---
baseline_commit: NO_VCS
---

# Story 3.1: 任务评估与执行路径选择

**Epic:** Epic 3 — Agent 自主执行引擎
**Status:** review

## Story

As a 开发者，
I want Agent 执行引擎提供统一的 StateGraph 构建和三种执行模式的骨架，
So that Agent 可以根据 Job 类型选择不同的执行策略。

## Acceptance Criteria

- **AC1:** 引擎构建 StateGraph 时，注入 Agent 的 system_prompt、工具列表(tool_ids→tools)、Workflow Registry 元数据
- **AC2:** 引擎根据输入评估自动选择执行路径（direct/react/planner），结果记录在执行日志中
- **AC3:** 执行状态通过 MongoDBSaver 持久化到 MongoDB
- **AC4:** 提供 `POST /api/v1/agents/{id}/invoke`（同步）和 `POST /api/v1/agents/{id}/stream`（流式 SSE）两个端点
- **AC5:** 所有执行步骤记录到执行日志（含 request_id 全链路串联）
- **AC6:** 三种执行器（direct/react/planner）以 skeleton 形式存在，具体实现在 Story 3.2~3.4 完成
- **AC7:** 同步模式下 30s 超时返回 504，流式模式通过 SSE 逐步推送推理内容
- **AC8:** 权限控制：需要 `viewer+` 角色

## Tasks / Subtasks

- [x] **Story 文件** — 创建 `3-1-task-evaluator-and-execution-path-selection.md` Story 文件
- [x] **AgentState** — 完善 `engine/state.py`，从 `dict[str, Any]` 替换为 LangGraph `TypedDict`
- [x] **MongoDBSaver** — 实现 `engine/checkpointer.py` 的 `get_checkpointer()`，返回真实的 MongoDBSaver 实例
- [x] **LLM Factory** — 实现 `engine/llm_factory.py` 的 `get_llm_client()`，支持从 Agent 的 llm_config 初始化 LLM 客户端
- [x] **执行路径评估器** — 创建 `engine/agent/evaluator.py`，实现任务复杂度评估和路径选择逻辑
- [x] **StateGraph 构建器** — 创建 `engine/agent/builder.py`，构建包含三种路径分支的 StateGraph
- [x] **三种执行器骨架** — 创建 `direct_executor.py`、`react_executor.py`、`planner_executor.py` 的 skeleton 文件
- [x] **深度保护骨架** — 创建 `engine/agent/depth_guard.py` skeleton（嵌套深度限制）
- [x] **API 端点** — 添加 `POST /agents/{id}/invoke` 和 `POST /agents/{id}/stream` 端点
- [x] **注册路由** — 在 `api/v1/router.py` 注册 execution router
- [x] **Tests (API/Mock)** — 创建 mock 测试覆盖 invoke/stream 端点的正常、超时、404、401/403
- [x] **Tests (Integration)** — 可选，真实 MongoDB 集成测试（跳过，依赖真实 MongoDB 实例）
- [x] **Run & Verify** — 运行完整测试套件（182 tests passing）

## Dev Notes

### 架构上下文

- 本 Story 是 Epic 3 的**基础骨架 Story**，后续 3-2~3-8 都依赖此 Story 创建的文件结构和 StateGraph 构建能力
- **执行路径选择由模型自主判断**（不是外部规则引擎），通过 Agent 的 system_prompt 引导模型选择路径（PRD §4.2 决策日志）
- 三种路径：direct（简单 Job）→ 3-2 实现、react（REACT 推理）→ 3-2 实现、planner（规划执行）→ 3-3 实现、workflow（工作流执行）→ 3-4 实现
- 本 Story 只做 evaluator 和 builder，实际执行逻辑在后续 Story 中填充

### 核心组件设计

```
engine/
├── state.py              # [修改] AgentState → LangGraph TypedDict
├── checkpointer.py       # [修改] get_checkpointer() → MongoDBSaver
├── llm_factory.py        # [修改] get_llm_client() → 真实 LLM 客户端
├── prompt.py             # [保留] 提示词模板（已有占位，后续 Story 丰富）
├── context.py            # [保留] 上下文压缩（已有占位，后续 Story 3-5 实现）
├── agent/
│   ├── __init__.py
│   ├── builder.py        # [新建] StateGraph 构建
│   ├── evaluator.py      # [新建] 任务评估 + 路径选择
│   ├── direct_executor.py # [新建] 直接执行 skeleton → 3-2
│   ├── react_executor.py  # [新建] REACT 推理 skeleton → 3-2
│   ├── planner_executor.py# [新建] 规划执行 skeleton → 3-3
│   └── depth_guard.py    # [新建] 深度保护 skeleton → 3-6
```

### AgentState 定义

参考 LangGraph 官方模式，定义清晰的 Agent 运行时状态：

```python
from typing import Any, TypedDict, Annotated
from langgraph.graph.message import add_messages

class AgentState(TypedDict):
    messages: Annotated[list, add_messages]  # 对话消息
    agent_id: str                            # 当前 Agent ID
    execution_path: str                      # 选中的执行路径
    request_id: str                          # 全链路追踪 ID
    tool_results: dict[str, Any]             # 工具调用结果缓存
    step_count: int                          # 执行步数
    error: str | None                        # 错误信息
```

### MongoDBSaver 实现

使用 `langgraph-checkpoint-mongodb` 包：

```python
from langgraph_checkpoint_mongodb import MongoDBSaver
from app.db.mongodb import get_database

saver: MongoDBSaver | None = None

def get_checkpointer() -> MongoDBSaver:
    global saver
    if saver is None:
        db = get_database()
        saver = MongoDBSaver(db)
    return saver
```

### LLM Factory 实现

需要支持从 Agent 的 `llm_config` 初始化客户端。MVP 阶段支持 OpenAI-compatible API：

```python
from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic

def get_llm_client(llm_config: dict) -> ChatOpenAI | ChatAnthropic:
    model = llm_config.get("default_model", "")
    provider = _detect_provider(model)
    if provider == "openai":
        return ChatOpenAI(model=model, temperature=llm_config.get("temperature", 0.7))
    elif provider == "anthropic":
        return ChatAnthropic(model=model, temperature=llm_config.get("temperature", 0.7))
    ...
```

### 执行路径评估器（evaluator.py）

**重要设计决策：** 路径选择不单独调用 LLM，而是通过 System Prompt 中的指令引导 Agent 的首轮推理直接做出选择。评估器负责：

1. 解析 Agent 的 system_prompt 和 Workflow Registry
2. 构建 StateGraph 的初始节点
3. 在首轮 LLM 调用中观察 Agent 的路径选择倾向
4. 将路径选择结果写入 state.execution_path 和日志

### API 端点设计

参考架构文档中的端到端调用流程：

```python
# invoke — 同步调用
POST /api/v1/agents/{agent_id}/invoke
Request:  {"input": str, "session_id": str | None}
Response: {"data": {"output": str, "execution_path": str, ...}}
Errors:   404 (Agent 不存在), 504 (30s 超时)

# stream — 流式 SSE 调用
POST /api/v1/agents/{agent_id}/stream
Request:  {"input": str, "session_id": str | None}
Response: SSE 流: data: {"type": "token", "content": "..."}
                            data: {"type": "tool_call", "name": "...", "args": {...}}
                            data: {"type": "path_selection", "path": "direct"}
                            data: {"type": "done", "output": "..."}
Errors:   404 (Agent 不存在)
```

### 执行日志记录

所有执行步骤通过 loguru 记录结构化日志，包含 `request_id`：

```python
logger.bind(
    request_id=request_id,
    agent_id=agent_id,
    execution_path=execution_path,
).info("execution_step", step=step_count, content=summary)
```

后续 Story 9-1 会将日志持久化到 MongoDB，本 Story 仅结构化日志记录。

### 依赖关系（需确认 `pyproject.toml` 已有）

- `langgraph>=1.2.4` ✅ 已配置
- `langgraph-checkpoint-mongodb>=0.4.0` ✅ 已配置
- `langchain-openai` / `langchain-anthropic` — 需确认是否已添加

### 已有 Engine 占位文件

`engine/state.py` 和 `engine/checkpointer.py` 已有占位代码且注释指向本 Story，需要实际实现。

### 项目结构一致性

- 文件命名：`snake_case.py` ✅
- Service 层沿用 `staticmethod` 模式（参考 `AgentService`）
- API 层使用 `Depends(get_current_user)` + `require_any_role()`
- Error 使用 `from app.core.errors import NotFoundError` 模式

## Previous Story Intelligence

### Story 2.1 (Agent 数据模型)

- Agent 文档已包含 `llm_config` 字段（`default_model`/`temperature`/`max_retry`/`routing_rules`）
- `AgentService` 使用 staticmethod 模式，`_collection()` 返回 Motor 集合
- API 使用 `require_any_role("admin", "developer", "operator", "viewer")` 控制权限
- `_doc_to_response()` 模式将 MongoDB 文档转为 Pydantic response

### Story 2.5 (模型配置与动态路由)

- `update_model_config()` 方法已添加到 `AgentService`
- `PATCH /agents/{id}/model-config` 端点已实现
- 版本自增机制确保新旧对话配置隔离

## Dev Agent Record

### 实现计划

1. **AgentState TypedDict** — 替换 `engine/state.py` 占位符，定义 LangGraph TypedDict
2. **MongoDBSaver** — 实现 `engine/checkpointer.py`，通过 Motor.delegate 获取同步 PyMongo 客户端
3. **LLM Factory** — 实现 `engine/llm_factory.py`，支持 OpenAI/Anthropic 模型
4. **执行路径评估器** — 创建 `engine/agent/evaluator.py`，启发式路径选择（workflow→direct→react→planner）
5. **StateGraph 构建器** — 创建 `engine/agent/builder.py`，4 节点+条件边+checkpointer
6. **三种执行器骨架** — direct/react/planner 空 skeleton
7. **深度保护骨架** — `depth_guard.py` check_depth()
8. **API 端点** — invoke (sync) + stream (SSE) in agents.py
9. **Tests** — 10 个 mock 测试覆盖 invoke/stream

### 调试日志

- MongoDBSaver 初始误用 Motor 客户端，修正为 `get_mongodb_client().delegate`
- `build_agent_graph` 在 agents.py 中本地导入，测试 mock path 需要 `app.engine.agent.builder.build_agent_graph`
- AsyncMock `return_value=[]` 不支持 `async for`，改为 async generator function

### 完成备注

- 全部 13 个任务完成（集成测试跳过了，依赖真实 MongoDB）
- 182 个测试全部通过
- 3 个 ruff I001 import 排序问题已修复
- 新增 contract test 模式（`inspect.signature()`）防止 mock blind spot

## File List

**新建的文件:**
- `backend/app/engine/agent/__init__.py`
- `backend/app/engine/agent/builder.py`
- `backend/app/engine/agent/evaluator.py`
- `backend/app/engine/agent/direct_executor.py`
- `backend/app/engine/agent/react_executor.py`
- `backend/app/engine/agent/planner_executor.py`
- `backend/app/engine/agent/depth_guard.py`
- `backend/app/schemas/execution.py`
- `backend/tests/api/test_agent_execution.py`

**修改的文件:**
- `backend/app/engine/state.py` — AgentState TypedDict
- `backend/app/engine/checkpointer.py` — MongoDBSaver 实现
- `backend/app/engine/llm_factory.py` — LLM 客户端工厂实现
- `backend/app/api/v1/agents.py` — 添加 invoke/stream 端点
- `backend/app/api/v1/router.py` — 注册 agent router
- `backend/tests/api/test_agents.py` — 添加 contract tests

## Change Log

- 实现 AgentState TypedDict（engine/state.py）
- 实现 MongoDBSaver 单例（engine/checkpointer.py）
- 实现 LLM 客户端工厂（engine/llm_factory.py）
- 创建执行路径评估器（engine/agent/evaluator.py）
- 创建 StateGraph 构建器（engine/agent/builder.py）
- 创建三种执行器骨架（direct/react/planner/depth_guard）
- 添加 invoke/stream API 端点
- 修复 `model_config=body.llm_config` 参数名 bug
- 添加 contract tests 防止 mock blind spot
- 创建 10 个 mock 测试覆盖 execute/stream 端点

## Status

**Status:** review

---
baseline_commit: v0.0-baseline
---

# Story v0.1-1: harness 包骨架与目录结构

**Epic:** v0.1 — Harness 拆包与基础
**Status:** done (实施完成，commit `b9d0a41`；harness 包 278 测试全绿)

## Story

As a Agent Flow 维护者，
I want 把 `backend/app/engine/` 抽离成独立 `agent-flow-harness` Git 依赖，建立 src 布局与公开 API 骨架，
So that 后续 v0.1 Story（react 节点 / Guard / Middleware / Adapter）有清晰的扩展基线。

## Acceptance Criteria

- **AC1:** 仓库根目录新增 `packages/harness/` 目录，使用 `src/` 布局（`src/agent_flow_harness/`）
- **AC2:** `packages/harness/pyproject.toml` 声明 `name = "agent-flow-harness"`、`requires-python = ">=3.12"`、`[tool.hatch.build.targets.wheel] packages = ["src/agent_flow_harness"]`
- **AC3:** `packages/harness/pyproject.toml` 依赖 `langgraph>=1.0.8`、`langchain-core`、`pydantic>=2.0`、`structlog`；**不可**依赖 `fastapi` / `motor` / `mongoengine` / `celery` / `redis`（**核心约束**）
- **AC4:** `src/agent_flow_harness/__init__.py` 只做 re-export，不实现任何业务逻辑
- **AC5:** 创建 6 个核心模块的**空壳包**（含 `__init__.py`）：
  - `engine/`（含 `prompts/`）
  - `graph/`（含 `nodes/`）
  - `adapters/`
  - `guards/`
  - `tools/`
  - `slots/`
  - `llm/`（含 `providers/`）
  - `middleware/`（含 `builtin/`）
- **AC6:** 创建顶层 `state.py` 和 `checkpointer.py` 文件，含 `AgentState` TypedDict 与 `get_checkpointer() -> BaseCheckpointSaver` 函数签名（**函数体可抛 NotImplementedError**）
- **AC7:** `build_agent_graph(agent_doc, *, checkpointer=None, guards=None, middleware=None) -> CompiledStateGraph` 函数存在，**当前实现仅返回 `react -> END` 单节点图**（不接 evaluator / direct / planner）
- **AC8:** 顶层 `app/api/v1/sessions.py` 迁移 `Session` 模型到 `packages/app/app/models/session.py` 后仍能通过 `import` 引用 harness
- **AC9:** 应用层通过 `uv add git+https://.../agent-flow-harness.git@main` 方式声明依赖（**Git 直接依赖**，主人选 A）
- **AC10:** 包含**最小测试套件**（10 个），覆盖：导入路径、build_agent_graph 返回值类型、checkpointer 注入、guards/middleware 缺省值

## Tasks / Subtasks

- [ ] **Story 文件** — 创建本文档
- [ ] **目录骨架** — 创建 `packages/harness/` + `src/agent_flow_harness/` 及 6 个核心模块的 `__init__.py`
- [ ] **pyproject.toml** — 创建 `packages/harness/pyproject.toml`，声明依赖与 wheel 配置
- [ ] **顶层模块** — 创建 `state.py`（AgentState）+ `checkpointer.py`（get_checkpointer stub）
- [ ] **build_agent_graph stub** — 在 `graph/builder.py` 中实现 `react -> END` 单节点图构造函数
- [ ] **公开 API** — 在 `__init__.py` 中 re-export 6 个核心模块的入口
- [ ] **Git 依赖** — 在 `packages/app/pyproject.toml` 中添加 `agent-flow-harness @ git+...`
- [ ] **测试** — 编写 10 个测试覆盖：导入、`build_agent_graph` 行为、checkpointer 注入、guards/middleware 缺省
- [ ] **CI** — 在 `.github/workflows/ci.yml` 中新增 `packages/harness` 的 lint/test job
- [ ] **Run & Verify** — 运行完整测试套件（应用层 + harness 层），无回归

## Dev Notes

### 核心约束（绝不能违反）

**harness 不可依赖以下**（应用层基础设施）：

```
❌ fastapi / uvicorn / starlette
❌ motor / pymongo / mongoengine / beanie
❌ celery / redis / kombu
❌ app.models.* / app.services.* / app.api.*
```

**harness 允许依赖**：

```
✅ langgraph >= 1.0.8
✅ langchain-core / langchain-* (官方库)
✅ pydantic >= 2.0
✅ structlog
✅ typing-extensions
```

### 与应用层的边界（关键接口）

```python
# 应用层持有：业务模型 + MongoDB 客户端
# harness 持有：纯算法 + 公开 API

# packages/harness/src/agent_flow_harness/state.py
class AgentState(TypedDict):
    messages: list[BaseMessage]
    agent_id: str
    session_id: str
    call_chain: list[str]
    step_count: int
    error: str | None
    # ... (与当前 backend/app/engine/state.py 字段保持一致)

# packages/harness/src/agent_flow_harness/checkpointer.py
def get_checkpointer(
    mongo_uri: str,
    db_name: str,
    *,
    client: AsyncIOMotorClient | None = None,  # 应用层注入
) -> BaseCheckpointSaver:
    """返回 MongoDBSaver 实例。client 为 None 时自行创建。"""
    raise NotImplementedError  # v0.1-1 stub
```

### build_agent_graph 最小实现

```python
# packages/harness/src/agent_flow_harness/graph/builder.py
from langgraph.graph import END, StateGraph
from langgraph.checkpoint.base import BaseCheckpointSaver
from agent_flow_harness.state import AgentState
from agent_flow_harness.engine.react import react_node

def build_agent_graph(
    agent_doc: dict,
    *,
    checkpointer: BaseCheckpointSaver | None = None,
    guards: list | None = None,
    middleware: list | None = None,
) -> CompiledStateGraph:
    """
    v0.1-1: 最小实现 — 单 react 节点直连 END
    v0.1-N: 扩展为 [guard_in?] -> react -> [guard_out?] -> END
    """
    builder = StateGraph(AgentState)
    builder.add_node("react", react_node)
    builder.set_entry_point("react")
    builder.add_edge("react", END)
    return builder.compile(checkpointer=checkpointer)
```

**`react_node` 最小实现**（v0.1-1 是 stub）：

```python
# packages/harness/src/agent_flow_harness/engine/react.py
from langchain_core.runnables import RunnableConfig
from agent_flow_harness.state import AgentState

async def react_node(state: AgentState, config: RunnableConfig) -> dict:
    """
    v0.1-1: stub — 仅返回当前 state，不调 LLM
    v0.1-2: 完整 REACT 循环（合并原 backend/app/engine/agent/react_executor.run + run_streaming）
    """
    return state
```

### 公开 API 清单（v0.1-1）

```python
# packages/harness/src/agent_flow_harness/__init__.py
from agent_flow_harness.state import AgentState
from agent_flow_harness.checkpointer import get_checkpointer
from agent_flow_harness.graph import build_agent_graph  # 最小实现

__version__ = "0.1.0a1"
```

### 命名规范

- 包名：`agent_flow_harness`（下划线）
- 目录名：`agent-flow-harness`（连字符，PyPI 友好）
- 公开 API 一律走 `agent_flow_harness.xxx`

### 测试组织

```
packages/harness/tests/
├── conftest.py                # fake_llm, in_memory_checkpointer
├── test_state.py              # AgentState 字段
├── test_checkpointer.py       # get_checkpointer 签名 + 注入
├── graph/
│   └── test_builder.py        # build_agent_graph 4 个用例
├── engine/
│   └── test_react.py          # react_node stub 2 个用例
└── test_imports.py            # 公开 API 导入路径 4 个用例
```

## Dev Agent Record

### Implementation Plan

1. 创建 `packages/harness/` 目录结构（含 src 布局）
2. 写 `pyproject.toml`（uv-build, name=agent-flow-harness, Python>=3.12）
3. 创建 6 个核心模块空壳 + `state.py` + `checkpointer.py`
4. 实现 `build_agent_graph` 最小版本（react -> END）
5. 在 `packages/app/pyproject.toml` 中添加 Git 依赖
6. 编写 10 个测试
7. 在 CI 中添加 harness 独立 job
8. 运行验证

### Debug Log



### Completion Notes



## File List

**新增文件:**
- `packages/harness/pyproject.toml`
- `packages/harness/README.md`
- `packages/harness/src/agent_flow_harness/__init__.py`
- `packages/harness/src/agent_flow_harness/py.typed`
- `packages/harness/src/agent_flow_harness/state.py`
- `packages/harness/src/agent_flow_harness/checkpointer.py`
- `packages/harness/src/agent_flow_harness/engine/__init__.py`
- `packages/harness/src/agent_flow_harness/engine/react.py`
- `packages/harness/src/agent_flow_harness/engine/context.py`
- `packages/harness/src/agent_flow_harness/engine/prompts/__init__.py`
- `packages/harness/src/agent_flow_harness/graph/__init__.py`
- `packages/harness/src/agent_flow_harness/graph/builder.py`
- `packages/harness/src/agent_flow_harness/graph/runner.py`
- `packages/harness/src/agent_flow_harness/graph/nodes/__init__.py`
- `packages/harness/src/agent_flow_harness/graph/nodes/react.py`
- `packages/harness/src/agent_flow_harness/graph/nodes/guard_nodes.py`
- `packages/harness/src/agent_flow_harness/adapters/__init__.py`
- `packages/harness/src/agent_flow_harness/adapters/stream_events.py`
- `packages/harness/src/agent_flow_harness/adapters/app_event.py`
- `packages/harness/src/agent_flow_harness/adapters/content_blocks.py`
- `packages/harness/src/agent_flow_harness/guards/__init__.py`
- `packages/harness/src/agent_flow_harness/guards/base.py`
- `packages/harness/src/agent_flow_harness/guards/nodes.py`
- `packages/harness/src/agent_flow_harness/tools/__init__.py`
- `packages/harness/src/agent_flow_harness/tools/registry.py`
- `packages/harness/src/agent_flow_harness/tools/builtin.py`
- `packages/harness/src/agent_flow_harness/slots/__init__.py`
- `packages/harness/src/agent_flow_harness/slots/schema.py`
- `packages/harness/src/agent_flow_harness/slots/renderer.py`
- `packages/harness/src/agent_flow_harness/llm/__init__.py`
- `packages/harness/src/agent_flow_harness/llm/factory.py`
- `packages/harness/src/agent_flow_harness/llm/providers/__init__.py`
- `packages/harness/src/agent_flow_harness/middleware/__init__.py`
- `packages/harness/src/agent_flow_harness/middleware/base.py`
- `packages/harness/src/agent_flow_harness/middleware/chain.py`
- `packages/harness/src/agent_flow_harness/middleware/builtin/__init__.py`
- `packages/harness/tests/conftest.py`
- `packages/harness/tests/test_imports.py`
- `packages/harness/tests/test_state.py`
- `packages/harness/tests/test_checkpointer.py`
- `packages/harness/tests/graph/test_builder.py`
- `packages/harness/tests/engine/test_react.py`

**修改文件:**
- `packages/app/pyproject.toml` — 添加 `agent-flow-harness @ git+https://...`
- `.github/workflows/ci.yml` — 新增 `packages/harness` 独立 job

## Change Log

- 2026-06-23: Story v0.1-1 创建 — harness 包骨架与目录结构（ready-for-dev）

## Status

**Status:** ready-for-dev

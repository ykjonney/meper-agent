---
baseline_commit: v0.1-1
---

# Story v0.1-2: 单一 react 节点与 REACT 循环合并

**Epic:** v0.1 — Harness 拆包与基础
**Status:** done (实施完成，commit `01462c0`；删除 react_executor 等 dead code)
**Depends on:** v0.1-1

## Story

As a Agent Flow 维护者，
I want 把现有 `react_executor.run` 与 `react_executor.run_streaming` 合并为单一 `react_node` LangGraph Node，并删除 `evaluator` / `direct_executor` / `planner_executor` 三个未使用的执行器，
So that harness 内部只有一个 REACT 入口，所有执行走 LangGraph 原生 StateGraph 调度，checkpointer 自然生效。

## Acceptance Criteria

- **AC1:** `packages/harness/src/agent_flow_harness/engine/react.py` 实现 `react_node(state, config) -> dict` LangGraph Node 函数
- **AC2:** `react_node` 内部实现完整 REACT 循环：bind_tools → LLM call → 检查 tool_calls → 执行工具 → append ToolMessage → 循环（**最大 25 轮**，与现状一致）
- **AC3:** 工具执行前通过 `contextlib` 设置 workspace 上下文（与现状 `_setup_workspace_context` 行为一致），执行后清理
- **AC4:** 每次 LLM 调用前调用 `check_depth(state)`，超限 / 循环时短路返回（保留原 `circular_call_detected` / `depth_limit_exceeded` 事件）
- **AC5:** Context 压缩：调用前 `should_compress(messages, model_name, context_window)`，超阈值时 `compress_messages`（保留原 70% 阈值 / 4K 预留 / 10 条尾巴）
- **AC6:** 工具执行结果回填到 `state["messages"]`，step_count 每次 LLM 调用 +1（与现状一致）
- **AC7:** `evaluator.py` 整个文件**删除**（v0.1-2 不再有执行路径选择）
- **AC8:** `direct_executor.py` 和 `planner_executor.py` 整个文件**删除**（代码存在但未使用）
- **AC9:** `graph/builder.py` 中的 `build_agent_graph` 不再注册 `evaluate` 节点，**最终图结构 = `react -> END`**
- **AC10:** 提取 `agent/engine/context.py` 中的 `compress_messages` / `should_compress` / `extract_model_name` 到 `packages/harness/src/agent_flow_harness/engine/context.py`（**harness 内自包含**）
- **AC11:** 提取 `agent/engine/depth_guard.py` 的 `check_depth` 到 `packages/harness/src/agent_flow_harness/engine/depth_guard.py`（**harness 内自包含**）
- **AC12:** 保留 streaming 行为的"事件 schema"（5 种事件），但**由 v0.1-3 Adapter 通过 graph.astream_events 触发**（不在 react_node 内推 SSE）
- **AC13:** 提供 15+ 单元测试覆盖：REACT 循环退出条件、tool_call 路径、深度短路、压缩触发、step_count 累加

## Tasks / Subtasks

- [ ] **Story 文件** — 创建本文档
- [ ] **提取 context 模块** — 把 `compress_messages` / `should_compress` / `extract_model_name` 复制到 `harness/engine/context.py`
- [ ] **提取 depth_guard** — 把 `check_depth` 复制到 `harness/engine/depth_guard.py`
- [ ] **实现 react_node** — 在 `harness/engine/react.py` 实现单层 REACT 循环（不写流式）
- [ ] **删除 evaluator** — 删除应用层 `backend/app/engine/agent/evaluator.py`
- [ ] **删除 direct_executor** — 删除应用层 `backend/app/engine/agent/direct_executor.py`
- [ ] **删除 planner_executor** — 删除应用层 `backend/app/engine/agent/planner_executor.py`
- [ ] **更新 builder** — `build_agent_graph` 移除 evaluator 节点引用，保留 react 单节点
- [ ] **删除旧 react_executor** — 替换为 import harness.engine.react
- [ ] **测试** — 15+ 单元测试覆盖 REACT 循环各分支
- [ ] **Run & Verify** — 应用层全部 169+ 测试通过，harness 15+ 测试通过，无回归

## Dev Notes

### 当前 `react_executor.py` 的结构（参考）

```python
# backend/app/engine/agent/react_executor.py (现状)
async def run(state, llm, tools, context_window=None) -> dict:
    """非流式入口 — 由 builder 在 evaluate 节点之后调用"""
    ws_token = _setup_workspace_context(state)
    try:
        return await _run_react_inner(state, llm, tools, context_window)
    finally:
        if ws_token is not None:
            reset_workspace_context(ws_token)

async def _run_react_inner(state, llm, tools, context_window=None) -> dict:
    """内部 REACT 循环"""
    # bind_tools / depth_guard / compress / 25 轮循环 / step_count
    ...

# 300+ 行: 另一个 run_streaming 函数（绕过 graph，自己推 SSE 事件）
```

### v0.1-2 的合并策略

**关键判断**：把 `run` + `_run_react_inner` 合并为**一个 LangGraph Node**。**流式（run_streaming）由 v0.1-3 Adapter 通过 graph.astream_events 实现**，不在 react_node 内推事件。

### react_node 的 LangGraph Node 形态

```python
# packages/harness/src/agent_flow_harness/engine/react.py
from langchain_core.runnables import RunnableConfig
from agent_flow_harness.engine.context import (
    compress_messages,
    extract_model_name,
    should_compress,
)
from agent_flow_harness.engine.depth_guard import check_depth
from agent_flow_harness.state import AgentState

_MAX_ITERATIONS = 25  # 与现状一致

async def react_node(state: AgentState, config: RunnableConfig) -> dict:
    """
    单一 REACT 入口（v0.1-2 锁定）。

    不写流式 — 由 graph.astream_events + v0.1-3 Adapter 提供。
    不写 SSE — 应用层在 on_event 回调中处理。
    """
    # 1. 提取 llm / tools / model_name (从 config["configurable"])
    llm = config["configurable"]["llm"]
    tools = config["configurable"]["tools"]  # dict[str, StructuredTool]
    context_window = config["configurable"].get("context_window")

    # 2. workspace context 设置 (与现状一致)
    ws_token = _setup_workspace_context(state)

    try:
        # 3. bind_tools
        tool_map = tools  # 已由 graph/builder 装配好
        llm_with_tools = llm.bind_tools(list(tool_map.values())) if tool_map else llm

        # 4. REACT 循环
        current_messages = list(state.get("messages", []))
        step_count = state.get("step_count", 0)
        model_name = extract_model_name(llm)

        for iteration in range(_MAX_ITERATIONS):
            # 4.1 depth guard
            depth_result = check_depth(state)
            if not depth_result.allowed:
                return {**state, "error": depth_result.reason, "step_count": step_count}

            # 4.2 context 压缩
            if should_compress(current_messages, model_name, context_window=context_window):
                current_messages = compress_messages(
                    current_messages, model_name, context_window=context_window
                )

            # 4.3 LLM call
            response = await llm_with_tools.ainvoke(current_messages)
            current_messages.append(response)
            step_count += 1

            # 4.4 tool_calls 分支
            if response.tool_calls:
                # 4.4.1 持久中间文本 (与现状 run_streaming 一致)
                if response.content:
                    # AIMessage 已包含 content，append 后下游可还原
                    pass

                # 4.4.2 执行所有 tool_call
                for tool_call in response.tool_calls:
                    tool_name = tool_call["name"]
                    tool_args = tool_call["args"]
                    tool_id = tool_call["id"]

                    tool = tool_map.get(tool_name)
                    if tool is None:
                        tool_result_content = f"Error: tool '{tool_name}' not found."
                    else:
                        try:
                            tool_result_content = await tool.ainvoke(tool_args)
                        except Exception as e:
                            tool_result_content = f"Error: {e}"

                    tool_message = ToolMessage(
                        content=str(tool_result_content),
                        tool_call_id=tool_id,
                    )
                    current_messages.append(tool_message)

                # 4.4.3 继续循环，让 LLM 看到工具结果
                continue

            # 4.5 无 tool_call — 终止
            break

        return {
            **state,
            "messages": current_messages,
            "step_count": step_count,
        }
    finally:
        if ws_token is not None:
            reset_workspace_context(ws_token)
```

**关键设计点**：

1. **不写流式 chunks** — `await llm_with_tools.ainvoke` 返回**完整** `AIMessage`（含 `content` + `tool_calls` + `reasoning_content`），由 LangGraph 调度 `astream_events` 时自动产生原生事件
2. **不推 SSE** — `on_event` 由 v0.1-3 Adapter 负责
3. **workspace context** — 保留与现状一致（`set_workspace_context` / `reset_workspace_context`）
4. **depth_guard / compress** — 行为与现状完全一致（仅文件位置迁移到 harness）

### 删除范围（v0.1-2 删除的 3 个文件）

| 删除文件 | 当前内容 | 为什么不保留 |
|---------|---------|------------|
| `backend/app/engine/agent/evaluator.py` | `evaluate` 节点：返回 `execution_path` 字段 | evaluator 写死 `"react"`，**无实际分支** |
| `backend/app/engine/agent/direct_executor.py` | `direct_executor.run` 函数 | **从未被 StateGraph 接入**（builder 只注册 `evaluate -> react`）|
| `backend/app/engine/agent/planner_executor.py` | `_PLAN_SYSTEM_PROMPT` + `planner_executor.run` | **从未被 StateGraph 接入** |

**验证方法**：`grep -r "direct_executor\|planner_executor\|evaluator" backend/app/api backend/app/services` 确认无引用

### `build_agent_graph` v0.1-2 形态

```python
# packages/harness/src/agent_flow_harness/graph/builder.py
def build_agent_graph(
    agent_doc: dict,
    *,
    checkpointer: BaseCheckpointSaver | None = None,
    guards: list | None = None,
    middleware: list | None = None,
) -> CompiledStateGraph:
    """
    v0.1-2: 单一 react 节点直连 END
    v0.1-4: 扩展为 [guard_in?] -> react -> [guard_out?] -> END
    v0.1-5: middleware 注入 react_node
    """
    builder = StateGraph(AgentState)
    builder.add_node("react", react_node)
    builder.set_entry_point("react")
    builder.add_edge("react", END)
    return builder.compile(checkpointer=checkpointer)
```

### `runtime/configurable` schema

react_node 通过 `config["configurable"]` 拿 LLM/tools 而非全局变量：

```python
# 注入时机（应用层负责）:
config = {
    "configurable": {
        "thread_id": session.thread_id,
        "llm": llm_client,                        # 来自 agent_doc["llm_config"]
        "tools": tool_map,                        # 来自 ToolRegistry.resolve(agent_doc)
        "context_window": model_context_window,
    },
    "recursion_limit": 50,
}
```

**为何用 configurable 而非 state**：
- `state` 由 LangGraph 持久化（不适合塞 LLM 对象 — 不可序列化）
- `configurable` 不持久化、不序列化、每轮注入

### 测试组织（v0.1-2）

```
packages/harness/tests/
├── engine/
│   ├── test_react.py             # 15+ 用例
│   │   ├── test_basic_completion
│   │   ├── test_single_tool_call
│   │   ├── test_multiple_tool_calls
│   │   ├── test_max_iterations
│   │   ├── test_depth_limit_short_circuit
│   │   ├── test_circular_call_detection
│   │   ├── test_context_compression_triggered
│   │   ├── test_workspace_context_set_and_reset
│   │   ├── test_tool_not_found
│   │   ├── test_tool_exception_caught
│   │   ├── test_step_count_incremented
│   │   ├── test_reasoning_content_preserved
│   │   ├── test_state_messages_appended
│   │   ├── test_configurable_missing_keys
│   │   └── test_no_tools_registered
│   ├── test_context.py
│   └── test_depth_guard.py
```

### 兼容性

- `react_executor.run` 的**对外行为**（输入 state / llm / tools / context_window，输出 messages + step_count）**完全保持**
- 应用层 API（`POST /api/v1/sessions/{id}/messages`）**无变化**
- 前端 SSE 事件 schema 由 v0.1-3 继续保证不变

### 已知风险

| 风险 | 缓解 |
|------|------|
| 删除 direct/planner 后未来想恢复需要重新实现 | 文档记录到 `docs/harness/deferred-execution-paths.md` |
| 旧 `run_streaming` 的"中间文本持久"逻辑丢失 | react_node 内通过 `current_messages.append(response)` 自然持久（content 字段保留） |
| workspace context 跨进程 / 跨 worker 不工作 | 现状即如此，v0.1-2 不修复 |

## Dev Agent Record

### Implementation Plan

1. 提取 `compress_messages` / `should_compress` / `extract_model_name` 到 `harness/engine/context.py`
2. 提取 `check_depth` 到 `harness/engine/depth_guard.py`
3. 在 `harness/engine/react.py` 实现 `react_node` LangGraph Node
4. 更新 `harness/graph/builder.py` — 移除 evaluator 节点
5. 删除 3 个应用层文件（evaluator / direct_executor / planner_executor）
6. 应用层 `react_executor.py` 改 import 路径
7. 编写 15+ 单元测试
8. 运行完整测试套件

### Debug Log



### Completion Notes



## File List

**新增文件:**
- `packages/harness/src/agent_flow_harness/engine/context.py` — 提取自 `app.engine.agent.context`
- `packages/harness/src/agent_flow_harness/engine/depth_guard.py` — 提取自 `app.engine.agent.depth_guard`
- `packages/harness/src/agent_flow_harness/engine/react.py` — 单一 REACT 入口
- `packages/harness/tests/engine/test_react.py` — 15+ 测试
- `packages/harness/tests/engine/test_context.py`
- `packages/harness/tests/engine/test_depth_guard.py`
- `docs/harness/deferred-execution-paths.md` — 记录被删的 evaluator / direct / planner 设计意图

**修改文件:**
- `packages/harness/src/agent_flow_harness/graph/builder.py` — 移除 evaluator 节点
- `packages/harness/src/agent_flow_harness/__init__.py` — re-export `react_node` / `compress_messages` / `check_depth`

**删除文件:**
- `backend/app/engine/agent/evaluator.py`
- `backend/app/engine/agent/direct_executor.py`
- `backend/app/engine/agent/planner_executor.py`
- `backend/app/engine/agent/react_executor.py`（被 react_node 替代）

## Change Log

- 2026-06-23: Story v0.1-2 创建 — 单一 react 节点与 REACT 循环合并（ready-for-dev，依赖 v0.1-1）

## Status

**Status:** ready-for-dev

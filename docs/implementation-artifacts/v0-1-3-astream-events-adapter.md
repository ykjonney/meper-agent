---
baseline_commit: v0.1-2
---

# Story v0.1-3: astream_events → 5 种应用层事件 Adapter

**Epic:** v0.1 — Harness 拆包与基础
**Status:** done (实施完成，commit `7bc4d2f`；含 thread 历史重建 `73fe14c`)
**Depends on:** v0.1-2

## Story

As a Agent Flow 维护者，
I want 在 harness 内实现 `stream_events_to_app_events` Adapter，把 `graph.astream_events(version="v2")` 原生事件转换为现有前端 5 种应用层事件 schema，
So that react_node 走 LangGraph 原生流式后，**前端 SSE 客户端零改动**即可看到与现状一致的事件流。

## Acceptance Criteria

- **AC1:** `packages/harness/src/agent_flow_harness/adapters/stream_events.py` 实现 `stream_events_to_app_events(astream_iter, on_event, *, enable_thinking=False) -> None` 异步函数
- **AC2:** 应用层事件 schema **完全保持** 5 种事件类型：`thinking_delta` / `thinking` / `final_answer_delta` / `final_answer` / `tool_call` / `tool_result` / `tool_call_start`（**7 种**实际，主人之前说 5 种是约数）
- **AC3:** LangGraph 原生事件 → 应用层事件映射规则（详见 Dev Notes §1 映射表）
- **AC4:** 流式时**两个并行累积**：`streaming_text_parts: list[str]` / `streaming_thinking_parts: list[str]`，`on_chat_model_end` 时推完整版 `final_answer` / `thinking`
- **AC5:** **中间文本持久**：当 `AIMessage` 同时含 `content`（非空）和 `tool_calls`（非空），在 `on_chat_model_end` 时推 `final_answer` 事件（保留现状 `run_streaming` 的"中间文本持久化"逻辑）
- **AC6:** `tool_call_chunks` 累积成完整 `tool_call`：跨多个 chunk 累积 `id` / `name` / `args`，`on_chat_model_end` 时推一次 `tool_call` 事件
- **AC7:** `on_tool_start` 推 `tool_call_start` 占位事件（**不**含 name/args — name/args 已在 `tool_call` 事件推过）；`on_tool_end` 推 `tool_result` 事件
- **AC8:** `enable_thinking=False`（默认）时，**不推** `thinking_delta` 和 `thinking` 事件（即使模型返回 `reasoning_content`）
- **AC9:** `enable_thinking=True` 时，**必须**推 `thinking_delta` + `thinking` 完整事件
- **AC10:** 错误处理：`on_llm_error` / `on_tool_error` 推 `error` 事件（新增第 6 种事件 `error: {message, source}`）
- **AC11:** 提供 20+ 单元测试覆盖：每种原生事件 → 应用层事件映射、enable_thinking 开关、tool_call 跨 chunk 累积、中间文本持久、错误事件
- **AC12:** 提供 1 个端到端集成测试：`graph.astream_events → Adapter → 收到完整 5 种事件流`，与现状 `react_executor.run_streaming` 输出**逐事件对比一致**

## Tasks / Subtasks

- [ ] **Story 文件** — 创建本文档
- [ ] **app_event.py** — 定义 `AppEvent` Pydantic discriminated union（7 种事件类型）
- [ ] **stream_events.py 骨架** — 实现 `stream_events_to_app_events` 函数签名
- [ ] **流式累积状态** — 实现 `_StreamingAccumulator` 类（text / thinking / tool_call chunks）
- [ ] **on_chat_model_stream 映射** — 处理 `content` 字段推 `final_answer_delta` / 处理 `tool_call_chunks` 累积
- [ ] **on_chat_model_end 映射** — 推完整 `final_answer` / `thinking` / `tool_call`
- [ ] **on_tool_start / on_tool_end 映射** — 推 `tool_call_start` / `tool_result`
- [ ] **中间文本持久** — AIMessage 同时含 content + tool_calls 时推 `final_answer`
- [ ] **enable_thinking 开关** — 条件推 `thinking_delta` / `thinking`
- [ ] **错误事件** — `on_*_error` 推 `error` 事件
- [ ] **20+ 单元测试** — 参数化覆盖每种原生事件
- [ ] **1 个端到端集成测试** — 与现状 `react_executor.run_streaming` 输出对比
- [ ] **Run & Verify** — harness + 应用层全部测试通过，前端 chat-panel 收到的事件流与现状一致

## Dev Notes

### §1 原生事件 → 应用层事件映射表

| LangGraph 原生事件 | 触发条件 | 推应用层事件 | 字段 |
|------------------|---------|------------|------|
| `on_chain_start` (kind="llm") | LLM 调用开始 | `tool_call_start` | `{}` |
| `on_chat_model_stream` (chunk.content) | 流式 token | `final_answer_delta` | `content: str` |
| `on_chat_model_stream` (chunk.tool_call_chunks) | 流式 tool_call chunk | **累积**（不推） | — |
| `on_chat_model_stream` (chunk.additional_kwargs.reasoning) | 流式 thinking | `thinking_delta` | `content: str`（仅 enable_thinking）|
| `on_chat_model_end` (output.content 非空 + 无 tool_calls) | LLM 完成且直接回答 | `final_answer` | `content: str` |
| `on_chat_model_end` (output.content 非空 + 有 tool_calls) | LLM 完成且要调工具 | `final_answer` | `content: str`（**中间文本持久**）|
| `on_chat_model_end` (output.tool_calls 非空) | LLM 完成 | `tool_call` | `tool_name, args, id` |
| `on_chat_model_end` (output.reasoning_content 非空) | LLM 完成 | `thinking` | `content: str`（仅 enable_thinking）|
| `on_tool_start` | 工具开始 | `tool_call_start` | `{}`（**占位**）|
| `on_tool_end` (output 非空) | 工具完成 | `tool_result` | `tool_name, content` |
| `on_llm_error` | LLM 错误 | `error` | `message, source: "llm"` |
| `on_tool_error` | 工具错误 | `error` | `message, source: "tool"` |

### §2 应用层事件 schema（7 种 Pydantic 模型）

```python
# packages/harness/src/agent_flow_harness/adapters/app_event.py
from typing import Literal, Union
from pydantic import BaseModel, Field

class ThinkingDeltaEvent(BaseModel):
    type: Literal["thinking_delta"] = "thinking_delta"
    content: str

class ThinkingEvent(BaseModel):
    type: Literal["thinking"] = "thinking"
    content: str

class FinalAnswerDeltaEvent(BaseModel):
    type: Literal["final_answer_delta"] = "final_answer_delta"
    content: str

class FinalAnswerEvent(BaseModel):
    type: Literal["final_answer"] = "final_answer"
    content: str

class ToolCallStartEvent(BaseModel):
    type: Literal["tool_call_start"] = "tool_call_start"

class ToolCallEvent(BaseModel):
    type: Literal["tool_call"] = "tool_call"
    tool_name: str
    args: dict
    id: str

class ToolResultEvent(BaseModel):
    type: Literal["tool_result"] = "tool_result"
    tool_name: str
    content: str

class ErrorEvent(BaseModel):
    type: Literal["error"] = "error"
    message: str
    source: Literal["llm", "tool", "graph"]

AppEvent = Union[
    ThinkingDeltaEvent,
    ThinkingEvent,
    FinalAnswerDeltaEvent,
    FinalAnswerEvent,
    ToolCallStartEvent,
    ToolCallEvent,
    ToolResultEvent,
    ErrorEvent,
]
```

### §3 Adapter 主流程

```python
# packages/harness/src/agent_flow_harness/adapters/stream_events.py
from collections.abc import AsyncIterator, Awaitable, Callable
from langchain_core.messages import AIMessageChunk, AIMessage
from agent_flow_harness.adapters.app_event import (
    AppEvent,
    FinalAnswerDeltaEvent,
    FinalAnswerEvent,
    ThinkingDeltaEvent,
    ThinkingEvent,
    ToolCallEvent,
    ToolCallStartEvent,
    ToolResultEvent,
    ErrorEvent,
)

OnEventCallback = Callable[[AppEvent], Awaitable[None]]

async def stream_events_to_app_events(
    astream_iter: AsyncIterator[dict],
    on_event: OnEventCallback,
    *,
    enable_thinking: bool = False,
) -> None:
    """
    把 graph.astream_events(version="v2") 的原生事件流转换为应用层 7 种事件。

    Args:
        astream_iter: graph.astream_events(..., version="v2") 的输出
        on_event: 应用层 SSE 推送回调
        enable_thinking: 是否推 thinking 相关事件
    """
    accumulator = _StreamingAccumulator(enable_thinking=enable_thinking)

    async for event in astream_iter:
        event_kind = event.get("event")
        event_data = event.get("data", {})

        if event_kind == "on_chat_model_start":
            # 工具调用前的占位事件
            await on_event(ToolCallStartEvent())

        elif event_kind == "on_chat_model_stream":
            chunk = event_data.get("chunk")
            if chunk is None:
                continue

            # 1. content 字段
            content = _extract_text_content(chunk)
            if content:
                await on_event(FinalAnswerDeltaEvent(content=content))

            # 2. reasoning_content 字段（仅 enable_thinking）
            if enable_thinking:
                thinking = _extract_thinking_content(chunk)
                if thinking:
                    await on_event(ThinkingDeltaEvent(content=thinking))

            # 3. tool_call_chunks 累积
            accumulator.accumulate_tool_call_chunk(chunk)

        elif event_kind == "on_chat_model_end":
            output = event_data.get("output")
            if not isinstance(output, AIMessage):
                continue

            # 3.1 完整 thinking（仅 enable_thinking）
            if enable_thinking and output.additional_kwargs.get("reasoning_content"):
                await on_event(ThinkingEvent(content=output.additional_kwargs["reasoning_content"]))

            # 3.2 完整 text（无论有无 tool_calls 都推 — 中间文本持久化）
            if output.content:
                await on_event(FinalAnswerEvent(content=output.content))

            # 3.3 完整 tool_call
            for tc in output.tool_calls:
                await on_event(ToolCallEvent(
                    tool_name=tc["name"],
                    args=tc["args"],
                    id=tc["id"],
                ))

            accumulator.reset()

        elif event_kind == "on_tool_start":
            # 占位 — name/args 已在 on_chat_model_end 推过
            await on_event(ToolCallStartEvent())

        elif event_kind == "on_tool_end":
            output = event_data.get("output")
            tool_name = event.get("name", "unknown")
            await on_event(ToolResultEvent(
                tool_name=tool_name,
                content=str(output) if output is not None else "",
            ))

        elif event_kind == "on_llm_error":
            await on_event(ErrorEvent(
                message=str(event_data.get("error", "unknown")),
                source="llm",
            ))

        elif event_kind == "on_tool_error":
            await on_event(ErrorEvent(
                message=str(event_data.get("error", "unknown")),
                source="tool",
            ))

        # 忽略 on_chain_start / on_chain_end / on_prompt_start 等非业务事件
```

### §4 现状 `react_executor.run_streaming` 的核心行为（必须保持）

```python
# backend/app/engine/agent/react_executor.py:401-535 (现状, 主人要求"前端对接正常")
# 流式累积
collected_chunks: list[AIMessageChunk]
streaming_text_parts: list[str]
streaming_thinking_parts: list[str]

# 合并所有 chunk 为完整 AIMessage
response = collected_chunks[0]
for chunk in collected_chunks[1:]:
    response = response + chunk  # LangChain AIMessageChunk 的 + 运算

# 推 final_answer 完整版
if final_text:
    await on_event({"type": "final_answer", "content": final_text})

# 中间文本持久化 (有 tool_call 时也推)
if response.tool_calls and response.content:
    await on_event({"type": "final_answer", "content": response.content})

# 推 tool_call 完整版
for tc in response.tool_calls:
    await on_event({"type": "tool_call", "tool_name": tc["name"], "args": tc["args"]})

# 推 tool_result
await on_event({"type": "tool_result", "tool_name": tool_name, "content": ...})
```

**v0.1-3 与现状**：
- 流式累积机制一致（都是合并 chunks）
- 推 5+ 种事件的触发点一致
- 中间文本持久化逻辑一致

### §5 LangGraph `astream_events` 关键 API

```python
# v0.1-3 调用方式（应用层）
graph = build_agent_graph(agent_doc, checkpointer=cp)
config = {"configurable": {"thread_id": tid, "llm": llm, "tools": tools}}

async for event in graph.astream_events(
    {"messages": [HumanMessage(content=user_input)]},
    config=config,
    version="v2",  # 重要 — v1 已弃用
):
    await stream_events_to_app_events(
        iter([event]),  # 或直接 for-loop 不传 iter
        on_event=sse_callback,
        enable_thinking=True,
    )
```

**重要**：v0.1-3 的 `stream_events_to_app_events` 既可以消费单个 `async for` 循环（包装成 iter），也可以直接被 `astream_events` 的 caller 嵌入。

### §6 错误事件（新增第 8 种）

**与现状对比**：现状 `react_executor.run_streaming` 没有专门推 `error` 事件（异常通过 depth_guard / catch 处理）。v0.1-3 引入 `error` 事件**不破坏前端**（前端没监听就不会触发），但**给前端**未来"显示错误"的能力。

### §7 测试组织

```
packages/harness/tests/
├── adapters/
│   ├── test_stream_events.py          # 20+ 单元测试
│   │   ├── test_on_chat_model_stream_text
│   │   ├── test_on_chat_model_stream_thinking_disabled
│   │   ├── test_on_chat_model_stream_thinking_enabled
│   │   ├── test_on_chat_model_stream_tool_call_chunks
│   │   ├── test_on_chat_model_end_final_answer
│   │   ├── test_on_chat_model_end_with_tool_calls
│   │   ├── test_on_chat_model_end_middle_text_persist
│   │   ├── test_on_chat_model_end_thinking_full
│   │   ├── test_on_tool_start
│   │   ├── test_on_tool_end
│   │   ├── test_on_llm_error
│   │   ├── test_on_tool_error
│   │   ├── test_enable_thinking_false_ignores_thinking
│   │   ├── test_tool_call_chunks_across_multiple
│   │   ├── test_empty_content
│   │   ├── test_empty_tool_calls
│   │   ├── test_multiple_tool_calls_in_one_message
│   │   ├── test_accumulator_reset
│   │   ├── test_unrelated_events_ignored
│   │   └── test_thinking_extraction_from_additional_kwargs
│   ├── test_app_event.py              # 7 种 Pydantic schema 校验
│   └── test_content_blocks.py         # AIMessage → UI blocks (后续 Story)
└── integration/
    └── test_react_streaming_e2e.py    # 1 个端到端对比现状
```

### §8 端到端测试细节

```python
# packages/harness/tests/integration/test_react_streaming_e2e.py
async def test_e2e_react_streaming_equivalent_to_legacy():
    """
    端到端：graph.astream_events + v0.1-3 Adapter 输出的事件流
    必须与 backend/app/engine/agent/react_executor.run_streaming 输出**逐事件一致**。
    """
    # 1. 用相同的 Agent 配置 + 用户输入
    # 2. 跑 v0.1-3: graph.astream_events → stream_events_to_app_events → 收集 AppEvent
    # 3. 跑 legacy: react_executor.run_streaming → 收集 dict 事件
    # 4. 逐事件断言：type / 字段 / 顺序
    pass
```

### 兼容性

- **前端 chat-panel.tsx 完全零改动**（5 种事件类型 + 字段保持）
- 应用层 API（`POST /api/v1/sessions/{id}/messages`）无变化
- `graph.astream_events` 替换 `react_executor.run_streaming` 是**应用层 runner.py 改动**，不暴露给前端

### 已知风险

| 风险 | 缓解 |
|------|------|
| `astream_events` v1 / v2 行为差异 | 显式声明 `version="v2"`；v0.1-3 全程 v2 |
| `AIMessageChunk` 的 content 可能是 list（content blocks） | `_extract_text_content` helper 统一处理 str / list 两种形态 |
| Tool args 跨多个 chunk 累积 | `_StreamingAccumulator.accumulate_tool_call_chunk` 内部 dict 合并 |
| `reasoning_content` 字段在不同 LLM 后端位置不同 | 优先查 `additional_kwargs.reasoning_content`，备选 `content` 中 type="thinking" block |

## Dev Agent Record

### Implementation Plan

1. 定义 `AppEvent` 7 种 Pydantic schema（`app_event.py`）
2. 实现 `_StreamingAccumulator` 类
3. 实现 `stream_events_to_app_events` 主循环
4. 写 20+ 单元测试
5. 写 1 个端到端对比测试
6. 应用层 `runner.py` 切换到 `graph.astream_events` + Adapter
7. 运行完整测试套件
8. 手动验证前端 chat-panel 收到事件与现状一致

### Debug Log



### Completion Notes



## File List

**新增文件:**
- `packages/harness/src/agent_flow_harness/adapters/app_event.py` — 7 种 AppEvent Pydantic schema
- `packages/harness/src/agent_flow_harness/adapters/stream_events.py` — Adapter 主函数
- `packages/harness/src/agent_flow_harness/adapters/_accumulator.py` — 流式累积器
- `packages/harness/tests/adapters/test_stream_events.py` — 20+ 单元测试
- `packages/harness/tests/adapters/test_app_event.py` — Schema 校验
- `packages/harness/tests/integration/test_react_streaming_e2e.py` — 端到端对比测试

**修改文件:**
- `packages/harness/src/agent_flow_harness/__init__.py` — re-export `stream_events_to_app_events` / `AppEvent`
- `packages/harness/src/agent_flow_harness/graph/runner.py` — 切换到 `graph.astream_events` + Adapter
- `backend/app/api/v1/sessions.py`（应用层）— 走 harness 的 run_agent_streaming

**未修改文件（保持兼容）:**
- `frontend/src/components/chat-panel.tsx` — **零改动**
- 全部前端 SSE 监听逻辑

## Change Log

- 2026-06-23: Story v0.1-3 创建 — astream_events → 5 种应用层事件 Adapter（ready-for-dev，依赖 v0.1-2）

## Status

**Status:** ready-for-dev

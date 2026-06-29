# Story v0.2-3: ACP — Agent Communication Protocol 外部接口

**Epic:** v0.2 — P1 增强模块
**Status:** backlog
**Depends on:** v0.1-1, v0.1-3, v0.1-5 (middleware)

---

## Story

As **Agent Flow 平台集成商**,
I want **harness 暴露一个标准化的 Agent 通信协议（ACP），让外部系统能用统一的方式调用任何 Agent**,
So that **第三方系统（IDE 插件、IM 机器人、Web App）能用同一套接口对接所有 Agent，不必为每个 Agent 写专属适配层**。

---

## 背景与动机

当前 harness 的对外接口散落在应用层：

- `POST /api/v1/sessions/{id}/messages` — SSE 流式
- `POST /api/v1/agents/{id}/invoke` — 单次调用
- `GET /api/v1/agents/{id}/tools` — 工具列表

每个应用层路由都是"为这个前端定制的"，**没有跨系统的统一协议**。ACP 目标：

1. **协议中立** — 不绑定 HTTP / WebSocket / gRPC，定义**消息格式层**即可
2. **流式优先** — 一次 invoke 可返回 N 条事件（与 v0.1-3 适配器对齐）
3. **可扩展** — 允许 ACP 消息携带元数据（trace_id / parent_id / caller）

---

## 范围

### Must（必须做）

- `ACPMessage` Pydantic schema（request / response / event 三种类型）
- `ACPRequest`：含 `agent_id` / `session_id` / `input` / `stream: bool` / `metadata: dict`
- `ACPResponse`：含 `output` / `events: list[ACPEvent]` / `metadata: dict`
- `ACPEvent`：对齐 v0.1-3 的 7 种 AppEvent（`MessageStart` / `ContentDelta` / `ToolCallStart` / `ToolResult` / `MessageEnd` / `Error` / `SubAgent*`）
- `acp_invoke(request: ACPRequest) -> AsyncIterator[ACPResponse | ACPEvent]` 入口函数
- JSON 序列化（`model_dump_json()` / `model_validate_json()`）

### Should（应该做）

- `metadata.caller` 字段透传到 `AgentState.metadata`
- `metadata.trace_id` 写入 LangSmith / OpenTelemetry（与 v0.1-5 TraceMiddleware 集成）
- `metadata.parent_id` 支持 v0.2-1 subagent 调用链追踪
- ACP 错误码枚举（`ACP_TIMEOUT` / `ACP_GUARD_BLOCKED` / `ACP_TOOL_NOT_FOUND` 等）

### Won't（不在本 Story 做）

- HTTP / WebSocket 传输层（应用层负责）
- 鉴权 / 限流（应用层负责）
- ACP 服务端注册中心（应用层负责）

---

## Acceptance Criteria

- **AC1:** `packages/harness/src/agent_flow_harness/acp/__init__.py` 导出 `ACPRequest` / `ACPResponse` / `ACPEvent` / `acp_invoke`
- **AC2:** `ACPRequest` 字段：`agent_id: str` / `session_id: str` / `input: str` / `stream: bool = False` / `metadata: dict = {}`
- **AC3:** `ACPResponse` 字段：`output: str` / `events: list[ACPEvent]` / `metadata: dict` / `error: ACPError | None`
- **AC4:** `ACPEvent` 与 v0.1-3 的 7 种 AppEvent 一一对应（type 字段字符串匹配）
- **AC5:** `acp_invoke(request, agent_doc, *, checkpointer, guards, middleware)` 异步生成器，逐事件 yield
- **AC6:** `request.stream=False` 时只 yield 一次 `ACPResponse`（含完整 events）
- **AC7:** `request.stream=True` 时先 yield 多个 `ACPEvent`，最后 yield 一次 `ACPResponse`
- **AC8:** `metadata.trace_id` 自动透传到 `TraceMiddleware.span.trace_id`
- **AC9:** `metadata.parent_id` 自动写入 `state["call_chain"]`（配合 v0.2-1 subagent）
- **AC10:** 25+ 单元测试 + 2 个跨进程集成测试（JSON 序列化往返 / 端到端流式）

---

## Tasks / Subtasks

1. **ACPMessage schema 设计**
   - Pydantic v2 BaseModel
   - 三种类型用 `discriminator` 字段区分（type="request" / "response" / "event"）
2. **ACPRequest 字段定义**
   - 含 `agent_id` / `session_id` / `input` / `stream` / `metadata`
   - 字段校验（`agent_id` 非空、`input` 长度限制）
3. **ACPEvent 类型枚举**
   - 对齐 v0.1-3：`MESSAGE_START` / `CONTENT_DELTA` / `TOOL_CALL_START` / `TOOL_RESULT` / `MESSAGE_END` / `ERROR` / `SUBAGENT_START` / `SUBAGENT_END`
   - 每个 type 对应一个 Pydantic model
4. **ACPResponse 字段定义**
   - `output` / `events` / `metadata` / `error`
   - `error` 用 `ACPError` 子 model（code + message + details）
5. **acp_invoke 实现**
   - 内部用 v0.1-2 的 `run_agent` / `run_agent_streaming`
   - 把 v0.1-3 的 AppEvent 序列化为 ACPEvent
   - `stream=True` 模式 yield `ACPEvent` + 最终 `ACPResponse`
   - `stream=False` 模式 yield 单个 `ACPResponse`
6. **metadata 透传**
   - `request.metadata` 合并到 `AgentState.metadata`
   - `trace_id` 注入 `TraceMiddleware`
   - `parent_id` 追加到 `state["call_chain"]`
7. **错误码枚举**
   - `ACPErrorCode = Literal["TIMEOUT", "GUARD_BLOCKED", "TOOL_NOT_FOUND", "INVALID_REQUEST", ...]`
   - 异常 → `ACPError(code, message)`
8. **测试**
   - 25+ 单元测试：schema 序列化 / 字段校验 / 类型分发
   - 2 个集成测试：JSON 字符串往返 + 端到端 invoke

---

## Dev Notes

### 关键设计点

1. **协议层 ≠ 传输层** — ACP 只定义消息格式，HTTP/WebSocket 由应用层决定（v0.2-3 不实现 HTTP handler）
2. **流式优先** — `stream=True` 是默认行为（应用层决定是否 buffer）
3. **可扩展 metadata** — 用 `dict[str, Any]`，不预定义所有字段（保持协议稳定）
4. **错误用结构化** — `ACPError` 而非 `str`，便于应用层 i18n
5. **复用 v0.1-3 适配器** — 不重新定义事件类型，直接序列化

### 与 v0.1 兼容

- 不修改 v0.1-3 适配器，仅在 ACP 层做**序列化映射**
- 不修改 v0.1-2 react_node，仅在 `acp_invoke` 入口做 metadata 注入
- 应用层 HTTP 路由**可以并存**：老的 `/api/v1/sessions/...` 走原路径，新的 `/acp/v1/invoke` 走 ACP

### ACP 消息示例

```json
// ACPRequest (stream=true)
{
  "type": "request",
  "agent_id": "agent-uuid",
  "session_id": "session-uuid",
  "input": "搜索最新 AI 新闻",
  "stream": true,
  "metadata": {
    "caller": "ide-plugin",
    "trace_id": "trace-123",
    "parent_id": null
  }
}

// ACPEvent (流式)
{
  "type": "event",
  "event_type": "TOOL_CALL_START",
  "tool_name": "tavily_search",
  "tool_args": {"query": "AI news 2026"},
  "timestamp": "2026-06-24T10:00:00Z"
}

// ACPResponse (流式最终)
{
  "type": "response",
  "output": "最新 AI 新闻包括...",
  "events": [...],
  "metadata": {"trace_id": "trace-123", "duration_ms": 5432},
  "error": null
}
```

### 跨系统对接场景

- **IDE 插件** — 发 ACPRequest over WebSocket，监听 ACPEvent 流
- **IM 机器人** — 发 ACPRequest over HTTP，收集 events 后回复文本
- **CI 流水线** — 发 `stream=false` ACPRequest，等待单条 ACPResponse
- **第三方 Agent 平台** — 实现 ACP 服务端，让其他 Agent Flow 接入

---

## File List

**新增文件:**
- `packages/harness/src/agent_flow_harness/acp/__init__.py`
- `packages/harness/src/agent_flow_harness/acp/schemas.py` — ACPRequest / ACPResponse / ACPEvent / ACPError
- `packages/harness/src/agent_flow_harness/acp/invoke.py` — acp_invoke 入口
- `packages/harness/src/agent_flow_harness/acp/serialization.py` — JSON 序列化工具
- `packages/harness/tests/acp/test_schemas.py`
- `packages/harness/tests/acp/test_invoke.py`
- `packages/harness/tests/acp/test_streaming.py`
- `packages/harness/tests/acp/test_integration.py` — 集成测试

**修改文件:**
- `packages/harness/src/agent_flow_harness/__init__.py` — 导出 acp API
- `packages/harness/src/agent_flow_harness/middleware/builtin/trace.py` — 接收 `trace_id` from metadata

---

## References

- [SPEC.md §12.5 acp](../../SPEC.md) — 详细设计
- [v0.1-3 adapter](v0-1-3-astream-events-adapter.md) — AppEvent 类型映射
- [v0.1-5 middleware](v0-1-5-middleware-chain.md) — TraceMiddleware 集成
- [v0.2-1 subagents](v0-2-1-subagents.md) — parent_id 配合 call_chain

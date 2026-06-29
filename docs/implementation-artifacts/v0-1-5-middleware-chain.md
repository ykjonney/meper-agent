---
baseline_commit: v0.1-4
---

# Story v0.1-5: Middleware 协议与 Chain 执行器

**Epic:** v0.1 — Harness 拆包与基础
**Status:** done (实施完成，commit `23ebdf5`；Middleware 协议与 Chain 执行器)
**Depends on:** v0.1-4

## Story

As a Agent Flow 维护者，
I want 在 harness 内实现 `Middleware` Protocol + `MiddlewareChain` 执行器 + 3 类内置 Middleware（audit / prompt_injection / trace），并让 react_node 内部按 `order` 升序串联，
So that Agent 具备"细粒度横切"能力（改写 / 记录 / 透传），与 v0.1-4 的 Guard 形成 A 方案分工（Guard=门粗粒度 / Middleware=滤网细粒度）。

## Acceptance Criteria

- **AC1:** `packages/harness/src/agent_flow_harness/middleware/base.py` 定义 `Middleware` Protocol，含 4 个方法：`before_llm` / `after_llm` / `before_tool` / `after_tool`
- **AC2:** `Middleware` 含两个字段：`name: str`（必填，唯一标识）+ `order: int = 100`（升序执行）
- **AC3:** `packages/harness/src/agent_flow_harness/middleware/chain.py` 实现 `MiddlewareChain` 类：
  - 构造时接收 `middlewares: list[Middleware]`
  - 内部按 `order` 升序排序
  - 提供 `run_before_llm(state)` / `run_after_llm(state, response)` / `run_before_tool(state, tool_call)` / `run_after_tool(state, tool_call, result)` 4 个方法
  - **任一 middleware 抛异常** → 捕获后继续执行后续 middleware（**不阻断**，与 Guard 的"block"语义相反）
- **AC4:** 3 类内置 Middleware 全部实现：
  - `AuditMiddleware` — 每次 LLM/Tool 调用记录结构化审计日志（agent_id / session_id / event_type / timestamp）
  - `PromptInjectionMiddleware` — 每次 LLM 调用前可注入 system reminder 或改写 messages
  - `TraceMiddleware` — 桥接 LangSmith / OpenTelemetry / 自家 trace 协议
- **AC5:** 3 类内置 Middleware 都在 `middleware/builtin/` 子目录，通过 `middleware/builtin/__init__.py` 的 `__all__` 导出
- **AC6:** `react_node`（v0.1-2）内部接入 `MiddlewareChain`：
  - LLM 调用前调 `chain.run_before_llm(state)` → 用返回的 state 调 LLM
  - LLM 返回后调 `chain.run_after_llm(state, response)` → 用返回的 state 更新
  - 工具调用前调 `chain.run_before_tool(state, tc)` → 改写 tool_args
  - 工具返回后调 `chain.run_after_tool(state, tc, result)` → 改写 result
- **AC7:** `build_agent_graph(agent_doc, *, middleware=None, ...)` 接收 `middleware: list[Middleware] | None`：
  - `middleware=None` 时 react_node 内部 `MiddlewareChain([])` 空链（v0.1-4 行为不变）
  - `middleware=[m1, m2]` 时 react_node 内部构造 `MiddlewareChain([m1, m2])`
- **AC8:** Agent 配置字段 `agent_doc["middleware"]` 声明要启用的 Middleware 列表（与 v0.1-4 的 `agent_doc["guards"]` 风格一致）：
  ```python
  agent_doc["middleware"] = [
      {"name": "audit", "config": {"log_level": "info"}},
      {"name": "trace", "config": {"provider": "langsmith"}},
      {"name": "prompt_injection", "config": {"reminders": ["始终使用中文回答"]}},
  ]
  ```
- **AC9:** `build_agent_graph` 解析 `agent_doc["middleware"]`，按 `name` 字段实例化对应 Middleware 类（**注册表机制**）
- **AC10:** 全部 3 类 Middleware 在 `middleware/__init__.py` 中通过 `__all__` 导出，**应用层可继承扩展**
- **AC11:** 提供 25+ 单元测试覆盖：Middleware Protocol / Chain 排序 / Chain 异常隔离 / 3 类 Middleware 各自行为 / react_node 接入
- **AC12:** 提供 1 个集成测试：3 类 Middleware 组合 + Guard 组合（验证 A 方案分工不冲突）

## Tasks / Subtasks

- [ ] **Story 文件** — 创建本文档
- [ ] **Middleware Protocol** — 定义 `Middleware` Protocol + 4 个方法签名
- [ ] **MiddlewareChain** — 实现排序 + 异常隔离 + 4 个 run_* 方法
- [ ] **AuditMiddleware** — 结构化审计日志
- [ ] **PromptInjectionMiddleware** — 改写 system reminder
- [ ] **TraceMiddleware** — 桥接 LangSmith / OTel
- [ ] **Middleware Registry** — 内置 Middleware 名称 → 类 的注册表
- [ ] **react_node 接入** — 在 v0.1-2 react_node 内部插入 4 个调用点
- [ ] **build_agent_graph 扩展** — 接收 `middleware: list[Middleware] | None`
- [ ] **agent_doc["middleware"] 解析** — 配置 → 实例化
- [ ] **25+ 单元测试**
- [ ] **1 个集成测试** (Middleware + Guard 组合)
- [ ] **Run & Verify** — harness + 应用层全部测试通过

## Dev Notes

### §1 Middleware Protocol

```python
# packages/harness/src/agent_flow_harness/middleware/base.py
from typing import Protocol
from langchain_core.messages import BaseMessage
from agent_flow_harness.state import AgentState

class Middleware(Protocol):
    """中间件统一接口。细粒度，环绕 LLM/Tool 调用。"""
    name: str
    order: int = 100  # 升序执行

    async def before_llm(self, state: AgentState) -> AgentState:
        """LLM 调用前。返回修改后的 state。"""
        ...

    async def after_llm(self, state: AgentState, response: BaseMessage) -> AgentState:
        """LLM 调用后。可读 response 改写 state。"""
        ...

    async def before_tool(self, state: AgentState, tool_call: dict) -> dict:
        """工具调用前。返回修改后的 tool_call (含 args)。"""
        ...

    async def after_tool(self, state: AgentState, tool_call: dict, result: str) -> AgentState:
        """工具调用后。可读 result 改写 state。"""
        ...
```

### §2 MiddlewareChain 执行器

```python
# packages/harness/src/agent_flow_harness/middleware/chain.py
import structlog
from agent_flow_harness.middleware.base import Middleware
from agent_flow_harness.state import AgentState

logger = structlog.get_logger(__name__)

class MiddlewareChain:
    """
    中间件链。核心规则：
    1. 按 order 升序执行
    2. 任一 middleware 抛异常 → 捕获后继续执行后续（不阻断）
    3. middleware 之间共享 state (浅引用)
    """

    def __init__(self, middlewares: list[Middleware]):
        self.middlewares = sorted(middlewares, key=lambda m: m.order)

    async def _safe_call(self, method_name: str, middleware: Middleware, *args, **kwargs):
        try:
            method = getattr(middleware, method_name)
            return await method(*args, **kwargs)
        except Exception as e:
            logger.warning(
                "middleware_error",
                middleware=middleware.name,
                method=method_name,
                error=str(e),
                exc_info=True,
            )
            # 异常不阻断 — 返回原值
            return args[0] if args else kwargs.get("state")

    async def run_before_llm(self, state: AgentState) -> AgentState:
        for m in self.middlewares:
            state = await self._safe_call("before_llm", m, state)
        return state

    async def run_after_llm(self, state: AgentState, response: BaseMessage) -> AgentState:
        for m in self.middlewares:
            state = await self._safe_call("after_llm", m, state, response)
        return state

    async def run_before_tool(self, state: AgentState, tool_call: dict) -> dict:
        for m in self.middlewares:
            tool_call = await self._safe_call("before_tool", m, state, tool_call)
        return tool_call

    async def run_after_tool(self, state: AgentState, tool_call: dict, result: str) -> AgentState:
        for m in self.middlewares:
            state = await self._safe_call("after_tool", m, state, tool_call, result)
        return state
```

### §3 AuditMiddleware

```python
# packages/harness/src/agent_flow_harness/middleware/builtin/audit.py
import time
import structlog
from langchain_core.messages import BaseMessage
from agent_flow_harness.middleware.base import Middleware
from agent_flow_harness.state import AgentState

logger = structlog.get_logger("agent_flow_harness.audit")

class AuditMiddleware(Middleware):
    """结构化审计日志。每次 LLM/Tool 调用都记录。"""
    name = "audit"
    order = 100  # 默认排序 — 在最外层

    def __init__(self, log_level: str = "info"):
        self.log_level = log_level

    async def before_llm(self, state: AgentState) -> AgentState:
        logger.log(
            self.log_level,
            "llm_call_start",
            agent_id=state.get("agent_id"),
            session_id=state.get("session_id"),
            step_count=state.get("step_count", 0),
            message_count=len(state.get("messages", [])),
        )
        return state

    async def after_llm(self, state: AgentState, response: BaseMessage) -> AgentState:
        logger.log(
            self.log_level,
            "llm_call_end",
            agent_id=state.get("agent_id"),
            session_id=state.get("session_id"),
            step_count=state.get("step_count", 0),
            has_tool_calls=bool(response.tool_calls),
            content_length=len(response.content) if response.content else 0,
        )
        return state

    async def before_tool(self, state: AgentState, tool_call: dict) -> dict:
        logger.log(
            self.log_level,
            "tool_call_start",
            agent_id=state.get("agent_id"),
            tool_name=tool_call["name"],
            tool_id=tool_call["id"],
        )
        return tool_call

    async def after_tool(self, state: AgentState, tool_call: dict, result: str) -> AgentState:
        logger.log(
            self.log_level,
            "tool_call_end",
            agent_id=state.get("agent_id"),
            tool_name=tool_call["name"],
            tool_id=tool_call["id"],
            result_length=len(result),
        )
        return state
```

### §4 PromptInjectionMiddleware

```python
# packages/harness/src/agent_flow_harness/middleware/builtin/prompt_injection.py
from langchain_core.messages import SystemMessage, BaseMessage
from agent_flow_harness.middleware.base import Middleware
from agent_flow_harness.state import AgentState

class PromptInjectionMiddleware(Middleware):
    """在 LLM 调用前向 messages 注入 system reminder（或改写 messages）。

    注意：与 SlotRenderer (v0.1-6) 不同 —— SlotRenderer 在 Agent 启动时构造 system prompt；
    本 Middleware 在每次 LLM 调用前动态注入额外内容。
    """
    name = "prompt_injection"
    order = 50  # 在 audit (100) 之前 — 改写后让 audit 看到最终 messages

    def __init__(self, reminders: list[str] | None = None):
        self.reminders = reminders or []

    async def before_llm(self, state: AgentState) -> AgentState:
        if not self.reminders:
            return state

        messages = list(state.get("messages", []))
        reminder_text = "\n".join(f"[系统提醒] {r}" for r in self.reminders)
        messages.append(SystemMessage(content=reminder_text))
        return {**state, "messages": messages}

    async def after_llm(self, state: AgentState, response: BaseMessage) -> AgentState:
        return state

    async def before_tool(self, state: AgentState, tool_call: dict) -> dict:
        return tool_call

    async def after_tool(self, state: AgentState, tool_call: dict, result: str) -> AgentState:
        return state
```

### §5 TraceMiddleware

```python
# packages/harness/src/agent_flow_harness/middleware/builtin/trace.py
import time
from langchain_core.messages import BaseMessage
from agent_flow_harness.middleware.base import Middleware
from agent_flow_harness.state import AgentState

class TraceMiddleware(Middleware):
    """Trace 桥接。抽象协议 — 实际导出由 provider 决定。

    支持 provider:
    - "langsmith": LangSmith trace (默认)
    - "otel": OpenTelemetry
    - "noop": 关闭 (测试用)
    """
    name = "trace"
    order = 200  # 在最内层（最后执行）— 拿到最完整信息

    def __init__(self, provider: str = "noop", **provider_config):
        self.provider = provider
        self.span_stack: list[dict] = []
        # v0.1-5 仅做协议；具体 provider 在 v0.1.1+ 实现
        # 当前为 stub — 仅记录 span 边界

    async def before_llm(self, state: AgentState) -> AgentState:
        self.span_stack.append({
            "type": "llm",
            "start": time.time(),
            "step": state.get("step_count", 0),
        })
        return state

    async def after_llm(self, state: AgentState, response: BaseMessage) -> AgentState:
        if not self.span_stack:
            return state
        span = self.span_stack.pop()
        span["end"] = time.time()
        span["duration"] = span["end"] - span["start"]
        # v0.1-5: 仅 structlog 记录；v0.1.1+ 接 LangSmith / OTel
        # 通过 _emit_trace 钩子
        self._emit_trace(span)
        return state

    async def before_tool(self, state: AgentState, tool_call: dict) -> dict:
        self.span_stack.append({
            "type": "tool",
            "tool_name": tool_call["name"],
            "start": time.time(),
        })
        return tool_call

    async def after_tool(self, state: AgentState, tool_call: dict, result: str) -> AgentState:
        if not self.span_stack:
            return state
        span = self.span_stack.pop()
        span["end"] = time.time()
        self._emit_trace(span)
        return state

    def _emit_trace(self, span: dict) -> None:
        """v0.1-5 stub — 后续 Story 替换为 LangSmith / OTel 适配器"""
        pass
```

### §6 Middleware Registry

```python
# packages/harness/src/agent_flow_harness/middleware/__init__.py
from agent_flow_harness.middleware.base import Middleware
from agent_flow_harness.middleware.chain import MiddlewareChain
from agent_flow_harness.middleware.builtin.audit import AuditMiddleware
from agent_flow_harness.middleware.builtin.prompt_injection import PromptInjectionMiddleware
from agent_flow_harness.middleware.builtin.trace import TraceMiddleware

MIDDLEWARE_REGISTRY: dict[str, type[Middleware]] = {
    "audit": AuditMiddleware,
    "prompt_injection": PromptInjectionMiddleware,
    "trace": TraceMiddleware,
}

def resolve_middleware(spec: dict) -> Middleware:
    """从 agent_doc['middleware'] 单条配置解析为 Middleware 实例"""
    name = spec["name"]
    config = spec.get("config", {})
    cls = MIDDLEWARE_REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"Unknown middleware: {name}. Available: {list(MIDDLEWARE_REGISTRY)}")
    return cls(**config)

__all__ = [
    "Middleware", "MiddlewareChain",
    "AuditMiddleware", "PromptInjectionMiddleware", "TraceMiddleware",
    "MIDDLEWARE_REGISTRY", "resolve_middleware",
]
```

### §7 react_node 接入 MiddlewareChain

```python
# packages/harness/src/agent_flow_harness/engine/react.py (v0.1-5 扩展)
from agent_flow_harness.middleware.chain import MiddlewareChain
from agent_flow_harness.middleware import resolve_middleware

async def react_node(state: AgentState, config: RunnableConfig) -> dict:
    llm = config["configurable"]["llm"]
    tools = config["configurable"]["tools"]
    middlewares: list = config["configurable"].get("middlewares", [])
    chain = MiddlewareChain(middlewares)

    # ... 4.3 LLM call
    state_before_llm = await chain.run_before_llm(state)
    response = await llm_with_tools.ainvoke(state_before_llm["messages"])
    state_after_llm = await chain.run_after_llm(state_before_llm, response)

    # ... 4.4 tool_call 分支
    for tool_call in response.tool_calls:
        tool_call_modified = await chain.run_before_tool(state_after_llm, tool_call)
        # 执行工具
        tool_result_content = await tool.ainvoke(tool_call_modified["args"])
        state_after_tool = await chain.run_after_tool(
            state_after_llm, tool_call_modified, str(tool_result_content)
        )
        # 用 state_after_tool 继续后续 LLM 调用
```

### §8 build_agent_graph 扩展

```python
# packages/harness/src/agent_flow_harness/graph/builder.py (v0.1-5 扩展)
def build_agent_graph(
    agent_doc: dict,
    *,
    checkpointer: BaseCheckpointSaver | None = None,
    guards: list | None = None,
    middleware: list[Middleware] | None = None,
) -> CompiledStateGraph:
    """
    v0.1-5: 同时支持 guards + middleware
    - guards 走 graph 拓扑（Node 形式）
    - middleware 通过 configurable 注入 react_node 内部
    """
    if middleware is None and "middleware" in agent_doc:
        middleware = [resolve_middleware(spec) for spec in agent_doc["middleware"]]

    # 后续与 v0.1-4 builder 完全一致
    # middleware 通过 config["configurable"]["middlewares"] 传给 react_node
    ...
```

### §9 Guard vs Middleware 分工（再次强调 — A 方案）

| 维度 | Guard | Middleware |
|------|-------|------------|
| 位置 | LangGraph **Node** | 环绕 LLM/Tool 调用的钩子 |
| 粒度 | 粗 — 每次 react 节点前/后 | 细 — 每次 LLM/Tool 调用前/后 |
| 决策 | block / allow | 改写 / 记录 / 透传（**不阻断**） |
| 作用对象 | 整段 react 节点 | 单次 LLM / Tool 调用 |
| 配置载体 | `agent_doc["guards"]` | `agent_doc["middleware"]` |
| 典型场景 | token 超限、wall-clock 超时、循环检测、危险命令拦截 | audit 日志、trace 推送、prompt 注入、PII 打码 |

**判断口诀**：
- "**要不要让这一步发生**" → Guard（门）
- "**这一步发生时要改/记什么**" → Middleware（滤网）

### §10 3 类内置 Middleware 速查

| Middleware | order | 行为 |
|------------|-------|------|
| `PromptInjectionMiddleware` | 50 | 注入 system reminder 到 messages |
| `AuditMiddleware` | 100 | structlog 记录 LLM/Tool 调用 |
| `TraceMiddleware` | 200 | span 边界追踪（v0.1-5 stub，v0.1.1+ 接 LangSmith）|

**为什么 Audit 排在 100，Trace 排在 200**：
- PromptInjection (50) — **最早改写 messages**（让后续 middleware 看到最终内容）
- Audit (100) — 记录改写后的实际 LLM 调用
- Trace (200) — 包裹最外层，记录完整时间窗口

### §11 测试组织

```
packages/harness/tests/
├── middleware/
│   ├── test_base.py                  # Middleware Protocol
│   ├── test_chain.py                 # 排序 + 异常隔离 (8 个用例)
│   ├── test_audit.py                 # 4 个用例
│   ├── test_prompt_injection.py      # 5 个用例
│   ├── test_trace.py                 # 4 个用例
│   ├── test_registry.py              # resolve_middleware (3 个用例)
│   └── test_react_integration.py     # react_node 接入 (5 个用例)
└── integration/
    └── test_middleware_guard_combined.py  # 1 个集成用例
```

### 兼容性

- `build_agent_graph(agent_doc, checkpointer=cp)` **不传 middleware** 时，行为与 v0.1-4 **完全一致**（react_node 内部 `MiddlewareChain([])` 空链 — 4 个 run_* 方法直接透传）
- `react_node` 内部逻辑**增量扩展**，不修改 v0.1-2 / v0.1-4 的语义
- 3 类内置 Middleware 可单独启用 / 禁用

### 已知风险

| 风险 | 缓解 |
|------|------|
| Middleware 异常影响主流程 | `_safe_call` 捕获 + 记录，**绝不阻断** |
| 多个 middleware 改写 messages 冲突 | order 升序串联，**最后改写生效**；文档明确 |
| `agent_doc["middleware"]` 与应用层字段冲突 | 显式命名空间（v0.1.1 调整） |
| TraceMiddleware 真实 LangSmith 集成延迟 | v0.1-5 仅 stub，v0.1.1+ 单独 Story |

## Dev Agent Record

### Implementation Plan

1. 定义 `Middleware` Protocol
2. 实现 `MiddlewareChain`（排序 + 异常隔离）
3. 实现 3 类内置 Middleware
4. 实现 `MIDDLEWARE_REGISTRY` + `resolve_middleware`
5. 扩展 `react_node` 接入 4 个调用点
6. 扩展 `build_agent_graph` 支持 `middleware` 参数
7. 写 25+ 单元测试
8. 写 1 个集成测试（Middleware + Guard 组合）
9. 运行完整测试套件

### Debug Log



### Completion Notes



## File List

**新增文件:**
- `packages/harness/src/agent_flow_harness/middleware/__init__.py` — REGISTRY + resolve_middleware
- `packages/harness/src/agent_flow_harness/middleware/base.py` — Middleware Protocol
- `packages/harness/src/agent_flow_harness/middleware/chain.py` — MiddlewareChain
- `packages/harness/src/agent_flow_harness/middleware/builtin/__init__.py`
- `packages/harness/src/agent_flow_harness/middleware/builtin/audit.py`
- `packages/harness/src/agent_flow_harness/middleware/builtin/prompt_injection.py`
- `packages/harness/src/agent_flow_harness/middleware/builtin/trace.py`
- `packages/harness/tests/middleware/test_base.py`
- `packages/harness/tests/middleware/test_chain.py`
- `packages/harness/tests/middleware/test_audit.py`
- `packages/harness/tests/middleware/test_prompt_injection.py`
- `packages/harness/tests/middleware/test_trace.py`
- `packages/harness/tests/middleware/test_registry.py`
- `packages/harness/tests/middleware/test_react_integration.py`
- `packages/harness/tests/integration/test_middleware_guard_combined.py`

**修改文件:**
- `packages/harness/src/agent_flow_harness/engine/react.py` — 接入 MiddlewareChain 4 个调用点
- `packages/harness/src/agent_flow_harness/graph/builder.py` — 支持 `middleware` 参数
- `packages/harness/src/agent_flow_harness/__init__.py` — re-export 3 类 Middleware + resolve_middleware

## Change Log

- 2026-06-23: Story v0.1-5 创建 — Middleware 协议与 Chain 执行器（ready-for-dev，依赖 v0.1-4）

## Status

**Status:** ready-for-dev

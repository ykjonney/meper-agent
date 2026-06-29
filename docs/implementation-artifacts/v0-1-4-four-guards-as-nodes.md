---
baseline_commit: v0.1-3
---

# Story v0.1-4: 4 类 Guard 作为 LangGraph Node

**Epic:** v0.1 — Harness 拆包与基础
**Status:** done (实施完成，commit `ae68a73`；4 类 Guard 作为 LangGraph Node)
**Depends on:** v0.1-3

## Story

As a Agent Flow 维护者，
I want 在 harness 内实现 4 类内置 Guard（Token / Time / ToolRateLimit / Content）作为 LangGraph Node，并通过 `build_agent_graph(agent_doc, guards=[...])` 自动插入到 `[guard_in?] -> react -> [guard_out?] -> END` 拓扑中，
So that Agent 默认具备"长任务能力"（所有能力默认开启），通过 Agent 配置精细控制使用多少。

## Acceptance Criteria

- **AC1:** `packages/harness/src/agent_flow_harness/guards/base.py` 定义 `Guard` Protocol + `GuardResult` 判别联合（`Allow` / `Block` / `Warn`）
- **AC2:** 4 类 Guard 全部实现：
  - `TokenBudgetGuard` — 累计 token 计数，超阈值 block
  - `TimeBudgetGuard` — wall-clock 计时，超时 block
  - `ToolRateLimitGuard` — 同 tool N 次 / 同一 args 重复 → block
  - `ContentGuard` — tool input/output 黑名单匹配 → block
- **AC3:** 4 类 Guard 全部支持 `check_in(state) -> GuardResult` 和 `check_out(state, output) -> GuardResult` 异步方法
- **AC4:** `packages/harness/src/agent_flow_harness/guards/nodes.py` 提供 `make_guard_in_node(guard)` 和 `make_guard_out_node(guard)` 函数工厂
- **AC5:** `build_agent_graph(agent_doc, *, guards=None, ...)` 接收 `guards: list[Guard] | None`：
  - `guards=None` → 拓扑保持 `react -> END`（v0.1-2 行为不变）
  - `guards=[t1, t2, ...]` → 拓扑扩展为 `[t1_in, t2_in, ...] -> react -> [t1_out, t2_out, ...] -> END`
- **AC6:** Agent 配置字段 `agent_doc["guards"]` 声明要启用的 Guard 列表（**主人原话**："所有能力我们要有，但是使用多少可以自定义"）：
  ```python
  agent_doc["guards"] = [
      {"name": "token_budget", "config": {"max_total_tokens": 200000}},
      {"name": "time_budget",  "config": {"max_wall_seconds": 1800}},
      {"name": "tool_rate_limit", "config": {"max_calls_per_tool": 30, "max_repeat_args": 3}},
      {"name": "content", "config": {"deny_patterns": ["rm -rf /"], "redact_pii": True}},
  ]
  ```
- **AC7:** `build_agent_graph` 解析 `agent_doc["guards"]`，按 `name` 字段实例化对应 Guard 类（**注册表机制**）
- **AC8:** `Block` 结果时，guard 节点返回 `state["error"] = reason` 并短路（LangGraph 自然终止）；前端 v0.1-3 推 `error` 事件
- **AC9:** `Warn` 结果时，记录到 `state["warnings"]` 列表但**不阻断**（继续执行）
- **AC10:** 全部 4 类 Guard 在 `guards/__init__.py` 中通过 `__all__` 导出，**应用层可继承扩展**（harness 暴露为"内置但可继承"）
- **AC11:** 提供 20+ 单元测试覆盖：4 类 Guard 各自的 allow/block/warn 分支、guard_in / guard_out 节点行为、`build_agent_graph` 拓扑扩展
- **AC12:** 提供 1 个集成测试：4 类 Guard 组合使用，全部 enabled 时阻断各种越界场景

## Tasks / Subtasks

- [ ] **Story 文件** — 创建本文档
- [ ] **Guard Protocol** — 定义 `Guard` Protocol + `GuardResult` 判别联合
- [ ] **TokenBudgetGuard** — 实现累计 token 计数逻辑
- [ ] **TimeBudgetGuard** — 实现 wall-clock 计时逻辑
- [ ] **ToolRateLimitGuard** — 实现同 tool / 同 args 频率检测
- [ ] **ContentGuard** — 实现 deny_patterns + PII redact
- [ ] **Guard Registry** — 内置 Guard 名称 → 类 的注册表
- [ ] **make_guard_in_node / make_guard_out_node** — 节点工厂
- [ ] **build_agent_graph 扩展** — 接收 `guards: list[Guard] | None` 参数
- [ ] **agent_doc["guards"] 解析** — 解析配置 → 实例化 Guard
- [ ] **20+ 单元测试** — 覆盖各 Guard 与节点行为
- [ ] **1 个集成测试** — 4 类 Guard 组合
- [ ] **Run & Verify** — harness + 应用层全部测试通过

## Dev Notes

### §1 Guard 协议定义

```python
# packages/harness/src/agent_flow_harness/guards/base.py
from typing import Literal, Protocol, Union
from pydantic import BaseModel
from agent_flow_harness.state import AgentState

class GuardResult(BaseModel):
    """Guard 检查结果"""
    decision: Literal["allow", "block", "warn"]
    reason: str = ""

# 类型别名
GuardResultUnion = Union[
    Literal["allow"],
    BlockResult,
    WarnResult,
]
# 简化为：
# Allow = 字符串 "allow" (无 reason)
# Block = BlockResult(reason="...")
# Warn  = WarnResult(reason="...")
# —— 实现为 dataclass / Pydantic model, 由 guard 返回

class Guard(Protocol):
    """护栏统一接口。粗粒度，作为 LangGraph Node。"""
    name: str

    async def check_in(self, state: AgentState) -> GuardResult:
        """react node 之前调用 — 决定是否放行 react"""
        ...

    async def check_out(self, state: AgentState, output: dict) -> GuardResult:
        """react node 之后调用 — 决定是否接受 react 输出"""
        ...
```

### §2 TokenBudgetGuard（实现细节）

```python
# packages/harness/src/agent_flow_harness/guards/token_budget.py
from agent_flow_harness.guards.base import Guard, GuardResult
from agent_flow_harness.state import AgentState

class TokenBudgetGuard(Guard):
    name = "token_budget"

    def __init__(self, max_total_tokens: int):
        self.max_total_tokens = max_total_tokens

    async def check_in(self, state: AgentState) -> GuardResult:
        current = state.get("total_tokens", 0)
        if current >= self.max_total_tokens:
            return Block(reason=f"Token budget exceeded: {current} >= {self.max_total_tokens}")
        if current >= self.max_total_tokens * 0.9:
            return Warn(reason=f"Token budget 90% used: {current}/{self.max_total_tokens}")
        return Allow()

    async def check_out(self, state: AgentState, output: dict) -> GuardResult:
        # output 包含本轮新增的 token 计数
        delta = output.get("step_tokens", 0)
        new_total = state.get("total_tokens", 0) + delta
        if new_total > self.max_total_tokens:
            return Block(reason=f"Token budget exceeded after step: {new_total}")
        return Allow()
```

### §3 TimeBudgetGuard（实现细节）

```python
# packages/harness/src/agent_flow_harness/guards/time_budget.py
import time
from agent_flow_harness.guards.base import Guard, GuardResult

class TimeBudgetGuard(Guard):
    name = "time_budget"

    def __init__(self, max_wall_seconds: int):
        self.max_wall_seconds = max_wall_seconds

    async def check_in(self, state: AgentState) -> GuardResult:
        started_at = state.get("started_at", time.time())
        elapsed = time.time() - started_at
        if elapsed >= self.max_wall_seconds:
            return Block(reason=f"Time budget exceeded: {elapsed:.1f}s >= {self.max_wall_seconds}s")
        if elapsed >= self.max_wall_seconds * 0.9:
            return Warn(reason=f"Time budget 90% used: {elapsed:.1f}s/{self.max_wall_seconds}s")
        return Allow()

    async def check_out(self, state: AgentState, output: dict) -> GuardResult:
        return Allow()  # 计时只在 check_in 评估
```

### §4 ToolRateLimitGuard（实现细节）

```python
# packages/harness/src/agent_flow_harness/guards/tool_rate_limit.py
import json
from collections import defaultdict
from agent_flow_harness.guards.base import Guard, GuardResult

class ToolRateLimitGuard(Guard):
    name = "tool_rate_limit"

    def __init__(self, max_calls_per_tool: int = 30, max_repeat_args: int = 3):
        self.max_calls_per_tool = max_calls_per_tool
        self.max_repeat_args = max_repeat_args

    async def check_in(self, state: AgentState) -> GuardResult:
        tool_call_count: dict[str, int] = state.get("tool_call_count", {})
        for tool_name, count in tool_call_count.items():
            if count >= self.max_calls_per_tool:
                return Block(reason=f"Tool '{tool_name}' called {count} times, limit {self.max_calls_per_tool}")
        return Allow()

    async def check_out(self, state: AgentState, output: dict) -> GuardResult:
        # 工具调用记录在 react_node 的 step 内完成
        # 这里做"同一 args 重复 N 次"检测
        tool_calls: list[dict] = output.get("tool_calls_this_step", [])
        if not tool_calls:
            return Allow()
        # 按 (tool_name, args_hash) 计数
        args_counter: dict[tuple, int] = defaultdict(int)
        for tc in tool_calls:
            key = (tc["name"], json.dumps(tc["args"], sort_keys=True))
            args_counter[key] += 1
        for (name, _), count in args_counter.items():
            if count >= self.max_repeat_args:
                return Block(reason=f"Tool '{name}' called with same args {count} times")
        return Allow()
```

### §5 ContentGuard（实现细节）

```python
# packages/harness/src/agent_flow_harness/guards/content.py
import re
from agent_flow_harness.guards.base import Guard, GuardResult

class ContentGuard(Guard):
    name = "content"

    def __init__(
        self,
        deny_patterns: list[str] | None = None,
        redact_pii: bool = False,
    ):
        self.deny_patterns = [re.compile(p) for p in (deny_patterns or [])]
        self.redact_pii = redact_pii
        self.pii_patterns = [
            re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),  # SSN
            re.compile(r"\b[\w.]+@[\w.]+\b"),       # email
        ] if redact_pii else []

    async def check_in(self, state: AgentState) -> GuardResult:
        # 检查即将发给 LLM 的最后一条 user message
        messages = state.get("messages", [])
        if not messages:
            return Allow()
        last = messages[-1]
        text = getattr(last, "content", "") or ""
        for pattern in self.deny_patterns:
            if pattern.search(text):
                return Block(reason=f"Content denied by pattern: {pattern.pattern}")
        return Allow()

    async def check_out(self, state: AgentState, output: dict) -> GuardResult:
        # 检查本轮 tool_calls 与 tool_results
        tool_calls = output.get("tool_calls_this_step", [])
        for tc in tool_calls:
            args_text = json.dumps(tc.get("args", {}))
            for pattern in self.deny_patterns:
                if pattern.search(args_text):
                    return Block(reason=f"Tool args denied by pattern: {pattern.pattern}")
        return Allow()
```

### §6 节点工厂

```python
# packages/harness/src/agent_flow_harness/guards/nodes.py
from langchain_core.runnables import RunnableConfig
from agent_flow_harness.state import AgentState
from agent_flow_harness.guards.base import Guard, GuardResult, Allow, Block, Warn

def make_guard_in_node(guard: Guard):
    """guard_in: 在 react 之前拦截"""
    async def guard_in_node(state: AgentState, config: RunnableConfig) -> dict:
        result = await guard.check_in(state)
        return _apply_result(state, guard, result, direction="in")
    guard_in_node.__name__ = f"guard_in_{guard.name}"
    return guard_in_node

def make_guard_out_node(guard: Guard):
    """guard_out: 在 react 之后拦截"""
    async def guard_out_node(state: AgentState, config: RunnableConfig) -> dict:
        result = await guard.check_out(state, state)  # state 此时包含本轮 output
        return _apply_result(state, guard, result, direction="out")
    guard_out_node.__name__ = f"guard_out_{guard.name}"
    return guard_out_node

def _apply_result(state: AgentState, guard: Guard, result: GuardResult, direction: str) -> dict:
    """统一处理 Allow / Block / Warn"""
    if result.decision == "allow":
        return state
    if result.decision == "block":
        return {**state, "error": f"[{guard.name}:{direction}] {result.reason}"}
    if result.decision == "warn":
        warnings = list(state.get("warnings", []))
        warnings.append(f"[{guard.name}:{direction}] {result.reason}")
        return {**state, "warnings": warnings}
    return state
```

### §7 Guard Registry

```python
# packages/harness/src/agent_flow_harness/guards/__init__.py
from agent_flow_harness.guards.base import Guard, GuardResult, Allow, Block, Warn
from agent_flow_harness.guards.token_budget import TokenBudgetGuard
from agent_flow_harness.guards.time_budget import TimeBudgetGuard
from agent_flow_harness.guards.tool_rate_limit import ToolRateLimitGuard
from agent_flow_harness.guards.content import ContentGuard
from agent_flow_harness.guards.nodes import make_guard_in_node, make_guard_out_node

GUARD_REGISTRY: dict[str, type[Guard]] = {
    "token_budget": TokenBudgetGuard,
    "time_budget": TimeBudgetGuard,
    "tool_rate_limit": ToolRateLimitGuard,
    "content": ContentGuard,
}

def resolve_guard(spec: dict) -> Guard:
    """从 agent_doc["guards"] 单条配置解析为 Guard 实例"""
    name = spec["name"]
    config = spec.get("config", {})
    cls = GUARD_REGISTRY.get(name)
    if cls is None:
        raise ValueError(f"Unknown guard: {name}. Available: {list(GUARD_REGISTRY)}")
    return cls(**config)

__all__ = [
    "Guard", "GuardResult", "Allow", "Block", "Warn",
    "TokenBudgetGuard", "TimeBudgetGuard", "ToolRateLimitGuard", "ContentGuard",
    "make_guard_in_node", "make_guard_out_node",
    "GUARD_REGISTRY", "resolve_guard",
]
```

### §8 build_agent_graph 扩展

```python
# packages/harness/src/agent_flow_harness/graph/builder.py
def build_agent_graph(
    agent_doc: dict,
    *,
    checkpointer: BaseCheckpointSaver | None = None,
    guards: list[Guard] | None = None,
    middleware: list | None = None,
) -> CompiledStateGraph:
    """
    v0.1-4: 拓扑扩展支持 guards

    guards=None:                    react -> END
    guards=[t1, t2]:
        [t1_in, t2_in] -> react -> [t1_out, t2_out] -> END
    """
    builder = StateGraph(AgentState)
    builder.add_node("react", react_node)

    if not guards:
        # v0.1-2 兼容路径
        builder.set_entry_point("react")
        builder.add_edge("react", END)
    else:
        # v0.1-4 扩展路径
        guard_in_nodes = [make_guard_in_node(g) for g in guards]
        guard_out_nodes = [make_guard_out_node(g) for g in guards]

        for i, node in enumerate(guard_in_nodes):
            name = f"guard_in_{guards[i].name}"
            builder.add_node(name, node)
        for i, node in enumerate(guard_out_nodes):
            name = f"guard_out_{guards[i].name}"
            builder.add_node(name, node)

        # 入口：第一个 guard_in（如果有）
        builder.set_entry_point(guard_in_nodes[0].__name__)

        # guard_in -> guard_in 串联
        for i in range(len(guard_in_nodes) - 1):
            builder.add_edge(
                guard_in_nodes[i].__name__,
                guard_in_nodes[i + 1].__name__,
            )

        # 最后一个 guard_in -> react
        builder.add_edge(guard_in_nodes[-1].__name__, "react")

        # react -> 第一个 guard_out
        builder.add_edge("react", guard_out_nodes[0].__name__)

        # guard_out -> guard_out 串联
        for i in range(len(guard_out_nodes) - 1):
            builder.add_edge(
                guard_out_nodes[i].__name__,
                guard_out_nodes[i + 1].__name__,
            )

        # 最后一个 guard_out -> END
        builder.add_edge(guard_out_nodes[-1].__name__, END)

    return builder.compile(checkpointer=checkpointer)
```

### §9 应用层调用方式（两种）

```python
# 方式 1：直接传 Guard 实例（应用层构造）
from agent_flow_harness.guards import TokenBudgetGuard, TimeBudgetGuard, ContentGuard

graph = build_agent_graph(
    agent_doc,
    checkpointer=cp,
    guards=[
        TokenBudgetGuard(max_total_tokens=200000),
        TimeBudgetGuard(max_wall_seconds=1800),
        ContentGuard(deny_patterns=["rm -rf /"]),
    ],
)

# 方式 2：从 agent_doc["guards"] 配置自动解析（推荐）
graph = build_agent_graph(agent_doc, checkpointer=cp)
# agent_doc["guards"] = [
#     {"name": "token_budget", "config": {"max_total_tokens": 200000}},
#     ...
# ]
# builder 内部自动调用 resolve_guard(spec)
```

**v0.1-4 实现策略**：builder 内部检测 `agent_doc.get("guards")` — 若存在且 `guards` 参数未传，自动调用 `resolve_guard` 解析；若显式传 `guards` 参数则优先使用。

### §10 State 字段扩展

```python
# packages/harness/src/agent_flow_harness/state.py
class AgentState(TypedDict, total=False):
    messages: list[BaseMessage]
    agent_id: str
    session_id: str
    call_chain: list[str]
    step_count: int
    error: str | None
    warnings: list[str]                  # 🆕 v0.1-4
    started_at: float                     # 🆕 v0.1-4 (用于 TimeBudgetGuard)
    total_tokens: int                     # 🆕 v0.1-4 (用于 TokenBudgetGuard)
    tool_call_count: dict[str, int]       # 🆕 v0.1-4 (用于 ToolRateLimitGuard)
    tool_calls_this_step: list[dict]      # 🆕 v0.1-4 (由 react_node 写入)
```

### §11 Guard 与 Middleware 分工（再次强调 — §9 SPEC 锁定 A 方案）

| 维度 | Guard | Middleware |
|------|-------|------------|
| 位置 | LangGraph **Node** | 环绕 LLM/Tool 调用的钩子 |
| 粒度 | 粗 — 每次 react 节点前/后 | 细 — 每次 LLM/Tool 调用前/后 |
| 决策 | block / allow | 改写 / 记录 / 透传 |
| 作用对象 | 整段 react 节点 | 单次 LLM / Tool 调用 |
| 配置载体 | `agent_doc["guards"]` | `agent_doc["middleware"]` |
| 典型场景 | token 超限、wall-clock 超时、循环检测、危险命令拦截 | audit 日志、trace 推送、prompt 注入、PII 打码 |

**判断口诀**：
- "**要不要让这一步发生**" → Guard（门）
- "**这一步发生时要改/记什么**" → Middleware（滤网）

### §12 测试组织

```
packages/harness/tests/
├── guards/
│   ├── test_base.py                  # Guard Protocol + GuardResult
│   ├── test_token_budget.py          # 4 个用例
│   ├── test_time_budget.py           # 4 个用例
│   ├── test_tool_rate_limit.py       # 5 个用例
│   ├── test_content.py               # 5 个用例
│   ├── test_nodes.py                 # guard_in / guard_out 节点 4 个用例
│   ├── test_registry.py              # resolve_guard + 未知 name 异常 3 个用例
│   └── test_builder_integration.py   # 4 个用例 (不同 guard 组合的拓扑)
└── integration/
    └── test_guard_combinations.py    # 1 个用例 (4 类全开)
```

### 兼容性

- `build_agent_graph(agent_doc, checkpointer=cp)` **不传 guards** 时，行为与 v0.1-3 **完全一致**（拓扑 = `react -> END`）
- `AgentState` 字段扩展**向后兼容**（TypedDict `total=False`，旧字段不破坏）
- Guard 可继承：应用层可写 `class CustomGuard(TokenBudgetGuard)` 重写方法

### 已知风险

| 风险 | 缓解 |
|------|------|
| `agent_doc["guards"]` 字段与未来应用层同名冲突 | 显式命名空间：`agent_doc["harness"]["guards"]` (v0.1.1 调整) |
| `started_at` 在多轮对话中是否重置 | 第一个 guard_in 节点判断：`state.get("started_at")` 为空时设置 |
| 多个 guard 串联性能开销 | 每个 guard 只做简单 O(1) 检查，最坏 O(messages × patterns) |
| `ToolRateLimitGuard` 误报（如合法重复调用）| `max_repeat_args` 默认 3，保守；应用层可调 |

## Dev Agent Record

### Implementation Plan

1. 定义 `Guard` Protocol + `GuardResult`
2. 实现 4 类 Guard
3. 实现 `make_guard_in_node` / `make_guard_out_node`
4. 实现 `GUARD_REGISTRY` + `resolve_guard`
5. 扩展 `build_agent_graph` 支持 guards
6. 扩展 `AgentState` 字段
7. 写 20+ 单元测试
8. 写 1 个集成测试
9. 运行完整测试套件

### Debug Log



### Completion Notes



## File List

**新增文件:**
- `packages/harness/src/agent_flow_harness/guards/__init__.py` — GUARD_REGISTRY + resolve_guard
- `packages/harness/src/agent_flow_harness/guards/base.py` — Guard Protocol + GuardResult
- `packages/harness/src/agent_flow_harness/guards/token_budget.py`
- `packages/harness/src/agent_flow_harness/guards/time_budget.py`
- `packages/harness/src/agent_flow_harness/guards/tool_rate_limit.py`
- `packages/harness/src/agent_flow_harness/guards/content.py`
- `packages/harness/src/agent_flow_harness/guards/nodes.py` — 节点工厂
- `packages/harness/tests/guards/test_base.py`
- `packages/harness/tests/guards/test_token_budget.py`
- `packages/harness/tests/guards/test_time_budget.py`
- `packages/harness/tests/guards/test_tool_rate_limit.py`
- `packages/harness/tests/guards/test_content.py`
- `packages/harness/tests/guards/test_nodes.py`
- `packages/harness/tests/guards/test_registry.py`
- `packages/harness/tests/guards/test_builder_integration.py`
- `packages/harness/tests/integration/test_guard_combinations.py`

**修改文件:**
- `packages/harness/src/agent_flow_harness/state.py` — 添加 warnings / started_at / total_tokens / tool_call_count / tool_calls_this_step
- `packages/harness/src/agent_flow_harness/graph/builder.py` — 支持 guards 参数
- `packages/harness/src/agent_flow_harness/engine/react.py` — 写 tool_calls_this_step / total_tokens 到 state
- `packages/harness/src/agent_flow_harness/__init__.py` — re-export 4 类 Guard + resolve_guard

## Change Log

- 2026-06-23: Story v0.1-4 创建 — 4 类 Guard 作为 LangGraph Node（ready-for-dev，依赖 v0.1-3）

## Status

**Status:** ready-for-dev

# Story v0.2-1: Subagents — 多 Agent 协作调度

**Epic:** v0.2 — P0 增强模块
**Status:** done (实施完成 2026-06-25，278 harness 测试 + 814 backend 测试全绿)
**Depends on:** v0.1-1, v0.1-2, v0.1-3, v0.1-7, v0.1-8

---

## Story

As **Agent Flow 架构师**,
I want **在 harness 内实现 Subagent 调度协议，让一个主 Agent 能动态 spawn 子 Agent 执行子任务并汇总结果**,
So that **复杂任务可以被拆解为可组合的多 Agent 协作流程，提升 LLM 单次调用无法完成的长任务表现**。

---

## 背景与动机

当前 harness 的 `react_node` 是单 Agent 循环（v0.1-2）。在以下场景受限：

1. **任务复杂度过高** — 一次 LLM 调用难以装下所有推理步骤
2. **上下文溢出** — 单 Agent 的 messages 列表会超 token 限制
3. **职责分离** — 不同子任务需要不同的 system prompt / tools / 模型

`subagents` 模块要解决：在不破坏 v0.1 单 Agent 模型的前提下，让一个 Agent（"主 Agent"）能在 REACT 循环中**调用一个特殊工具 `delegate_to_subagent`**，触发子 Agent 执行。

### 调研基础（deer-flow）

本设计调研了 [bytedance/deer-flow](https://github.com/bytedance/deer-flow) 的 `subagents/` 实现
（`registry.py` / `executor.py` / `config.py` + `tools/builtins/task_tool.py` +
`middlewares/subagent_limit_middleware.py`），借鉴其核心模式，弃用其复杂部分：

| 借鉴（采用） | 弃用（过重） |
|---|---|
| 工具排除做深度保护（子 agent 无 task 工具） | 后台线程池 + isolated event loop |
| 工具调用形式调度（非多节点路由） | cancel_event + 轮询 |
| 结果只取最后一条 AIMessage 文本 | SubagentResult 状态机 |
| Spec 自带完整配置（system_prompt 纯文本 + tools 列表） | — |

---

## 范围

### Must（必须做）

- 子 Agent 注册协议（声明名字、prompt、可用工具、模型配置）
- `delegate_to_subagent` 内置工具（主 Agent 用它来派发子任务）
- 子 Agent 执行环境**完全隔离**（全新 AgentState，不继承主 Agent 历史）
- 主 Agent 的 messages 中能感知子 Agent 返回的结果（1 条 ToolMessage）
- **工具排除**做递归保护（子 Agent 工具列表不含 delegate，物理无法递归）

### Should（应该做）

- 子 Agent 异常隔离（一个失败不中断主流程，转为错误字符串返回）

### Won't（不在本 Story 做）

- ~~子 Agent 执行进度事件（SubAgentStartEvent / SubAgentEndEvent）~~ — 砍掉，只返回最终文本
- 后台并行子 Agent / 取消 / 超时（deer-flow 式复杂调度，留待后续）
- 跨进程分布式 subagent（v0.3+）
- 子 Agent 之间的对等通信（仅支持主→子单向）
- 动态子 Agent 注册（仅静态声明）
- ~~独立 checkpointer namespace~~ — 子 Agent stateless，无需持久化

---

## 关键设计决策（已与主人确认）

| # | 决策点 | 选择 | 理由 |
|---|---|---|---|
| 1 | 深度保护 | **工具排除**（deer-flow 模式） | 子 agent 无 delegate 工具，物理无法递归，比 call_chain 计数更安全 |
| 2 | 依赖注入 | **ContextVar** | 与 v0.1 `workspace_context` 同模式，不改 ToolRegistry / react_node |
| 3 | 执行方式 | **同步 await 串行** | react_node 零改造，简单可测；v0.2-1 不需要后台并行/取消 |
| 4 | 结果返回 | **只最终文本** | 主 agent 追加 1 条 ToolMessage，上下文不爆炸 |
| 5 | prompt/tools | **SubAgentSpec 自带完整配置** | system_prompt 纯文本（不走 Slot 渲染）+ tools 名称列表 |
| 6 | 构建时机 | **调用时延迟构建** | registry 只存 spec 数据；graph 在 delegate 工具被调用时才构建 |
| 7 | 上下文隔离 | **完全隔离 stateless** | 不继承主 agent 历史，不独立持久化（同步跑完无中断机会） |

---

## 架构

```
主 Agent REACT 循环 (react_node, 零改造)
    │
    │  LLM 决定调用 delegate_to_subagent(subagent_name, task)
    │
    ▼
delegate_to_subagent 工具 (delegate.py)
    │  1. 从 ContextVar 读 SubAgentContext(registry, tool_registry, build_llm, parent_llm)
    │  2. registry.get(name) → SubAgentSpec
    │  3. 延迟构建：spec.tools → TOOL_REGISTRY 解析实例（排除 delegate 自身）
    │  4. 构建独立 AgentState（只有 task 作为 HumanMessage + system_prompt）
    │  5. await build_agent_graph(spec).ainvoke(state)  ← 同步阻塞，跑完才返回
    │  6. 取子 agent 最后一条 AIMessage 文本 → 返回 str
    │
    ▼
主 agent 的 ToolMessage(content=子 agent 最终输出)  ← 只有这一条，上下文不爆炸
```

### 构建时序（延迟构建）

```
register(spec)         ← 启动时只存纯数据（SubAgentSpec），轻量
    ↓
主 Agent 执行          ← 此时无子 agent graph 存在
    ↓
LLM 调用 delegate      ← 此刻才 build_agent_graph + ainvoke（延迟构建）
    ↓
返回最终文本            ← 子 agent stateless，无持久化
```

### 持久化说明

子 Agent **不需要独立 checkpointer**：
- 子 Agent 在主 Agent **单次 tool-call 期间同步跑完**，没有中断/恢复的机会
- 子 Agent 完全隔离 stateless（全新 AgentState，不看主 agent 历史）
- 结果（最终文本）作为 ToolMessage 进主 Agent 的 messages，由**主 Agent 的 checkpointer 统一持久化**
- 与 deer-flow 一致（`SubagentExecutor._create_agent` 里 `checkpointer=False`）

---

## 组件设计

### 1. SubAgentSpec（Pydantic BaseModel）

```python
class SubAgentSpec(BaseModel):
    name: str                        # 唯一标识，delegate 工具按此查找
    description: str                 # 给主 Agent 看的"何时委派给此子 agent"说明
    system_prompt: str               # 子 Agent 的完整 system prompt（直接用，不走 Slot 渲染）
    tools: list[str]                 # 允许的工具名称列表（运行时经 TOOL_REGISTRY 解析）
    llm_config: dict = {}            # LLM 配置；{"model": "inherit"} 表示用主 Agent 的模型
    max_turns: int = 25              # 子 Agent REACT 最大迭代数
```

**设计要点：**
- `system_prompt` 是**完整文本**，不走 6 段式 Slot 渲染 — 子 Agent 通常只需简单 prompt（deer-flow 同款）
- `tools` 是**名称列表**，运行时经 `TOOL_REGISTRY.resolve()` 解析成实例；`delegate_to_subagent` 被自动排除（工具排除防递归）
- `llm_config["model"] = "inherit"` 复用主 Agent 的 LLM（最常见）；否则按 config 构建新 LLM

### 2. SubAgentRegistry（plain class，与 v0.1 ToolRegistry 同构）

```python
class SubAgentRegistry:
    def register(self, spec: SubAgentSpec) -> None       # 重名 raise ValueError
    def get(self, name: str) -> SubAgentSpec             # 不存在 raise KeyError
    def list_names(self) -> list[str]
```

plain in-memory store，无 I/O，宿主启动时注册。子 Agent 必须**预先注册**（防 prompt injection 动态 spawn）。

### 3. delegate_to_subagent 工具（StructuredTool，async）

```python
async def delegate_to_subagent(subagent_name: str, task: str) -> str:
    """委派子任务给子 Agent，返回其最终输出文本。"""
    ctx = get_subagent_context()            # 从 ContextVar 读依赖
    spec = ctx.registry.get(subagent_name)  # KeyError → 转错误字符串返回
    # 解析 tools：spec.tools → TOOL_REGISTRY 实例，排除 delegate 自身
    tools = ctx.resolve_tools(spec)
    # 构建独立 AgentState（只有 task 作为 HumanMessage，无主 agent 历史）
    state = ctx.build_subagent_state(spec, task)
    # 同步 await 子 agent 执行
    result = await ctx.run_subagent(spec, tools, state)
    return result                           # 子 agent 最后一条 AIMessage 的文本
```

**设计要点：**
- 工具签名只暴露 `subagent_name` + `task` 给 LLM；所有运行时依赖从 ContextVar 拿
- 子 Agent 的 `AgentState` 是**全新的**（只含 task 作为初始 HumanMessage + system_prompt）— 状态隔离
- 异常被 catch 并转成错误字符串返回（`"Error: unknown subagent 'xxx'"`），不中断主 Agent 循环

### 4. SubAgentContext + ContextVar（依赖注入协议）

```python
@dataclass
class SubAgentContext:
    """宿主在每次主 Agent 执行前注入的依赖包。"""
    registry: SubAgentRegistry
    tool_registry: ToolRegistry                 # 解析子 agent 的 tools
    build_llm: Callable[[dict], BaseChatModel]  # 按 spec.llm_config 构建 LLM
    parent_llm: BaseChatModel | None            # model="inherit" 时用

    def resolve_tools(self, spec) -> list[BaseTool]: ...       # 解析 + 排除 delegate
    def build_subagent_state(self, spec, task) -> AgentState: ...
    async def run_subagent(self, spec, tools, state) -> str: ...

# ContextVar（与 v0.1 workspace_context 同模式）
_subagent_ctx: ContextVar[SubAgentContext | None] = ContextVar("subagent_ctx", default=None)

def set_subagent_context(ctx: SubAgentContext) -> Token
def get_subagent_context() -> SubAgentContext    # 未设置 raise RuntimeError
def reset_subagent_context(token: Token) -> None
```

**宿主接入方式（backend 侧）：**
```python
# 主 Agent 执行前
token = set_subagent_context(SubAgentContext(
    registry=subagent_registry,
    tool_registry=TOOL_REGISTRY,
    build_llm=lambda cfg: build_client_from_doc({"llm": cfg}),
    parent_llm=main_llm,
))
try:
    result = await run_agent(agent_doc, state, config=config)
finally:
    reset_subagent_context(token)
```

---

## Acceptance Criteria

- **AC1:** `packages/harness/src/agent_flow_harness/subagents/__init__.py` 导出 `SubAgentSpec`、`SubAgentRegistry`、`delegate_to_subagent`、`SubAgentContext`、`set/get/reset_subagent_context`
- **AC2:** `SubAgentSpec` 字段：`name: str` / `description: str` / `system_prompt: str` / `tools: list[str]` / `llm_config: dict = {}` / `max_turns: int = 25`
- **AC3:** `SubAgentRegistry.register(spec)` / `.get(name)` / `.list_names()` 三个方法（重名 ValueError / 不存在 KeyError）
- **AC4:** `delegate_to_subagent(subagent_name: str, task: str) -> str` 工具实现，**返回字符串**（子 Agent 最终输出）
- **AC5:** 子 Agent 复用 v0.1 的 `build_agent_graph`（延迟构建 — 调用时才构建 graph）
- **AC6:** 主 Agent 的 `messages` 在子 Agent 执行结束后**只追加**一条 `ToolMessage`（子 Agent 最终输出），不展开中间过程
- **AC7:** **工具排除防递归** — 子 Agent 解析出的工具列表不含 `delegate_to_subagent`，物理无法递归
- **AC8:** 子 Agent **stateless** — 全新 AgentState（只有 task + system_prompt），不继承主 Agent 历史，无独立 checkpointer
- **AC9:** **ContextVar 依赖注入** — `set/get/reset_subagent_context` 协议实现，未设置时 `get` raise RuntimeError
- **AC10:** **异常隔离** — 子 Agent 抛异常时，delegate 工具 catch 并返回错误字符串，不中断主 Agent 循环
- **AC11:** 20+ 单元测试 + 2 个集成测试（端到端委派执行 / 工具排除验证）通过

---

## Tasks / Subtasks

1. **SubAgentSpec 数据类**（`subagents/spec.py`）
   - Pydantic BaseModel，6 个字段
   - 字段校验（name 非空）
2. **SubAgentRegistry 注册中心**（`subagents/registry.py`）
   - `register` / `get` / `list_names` 三方法
   - 与 v0.1 `ToolRegistry` 同构风格
3. **SubAgentContext + ContextVar**（`subagents/context.py`）
   - dataclass 持有 4 个依赖 + 3 个 helper 方法（resolve_tools / build_subagent_state / run_subagent）
   - `set/get/reset_subagent_context`（参照 `tools/workspace_context.py`）
4. **delegate_to_subagent 工具**（`subagents/delegate.py`）
   - `StructuredTool`，async，签名只有 `subagent_name` + `task`
   - 内部：get_context → registry.get → resolve_tools(排除 delegate) → build_state → run_subagent → 返回最终文本
   - 异常 catch 转错误字符串
5. **resolve_tools 的工具排除逻辑**
   - `SubAgentContext.resolve_tools` 解析 spec.tools 后，过滤掉 name == "delegate_to_subagent"
6. **run_subagent 的最终文本提取**
   - 子 agent 跑完后，从 messages 反向找最后一条 AIMessage，提取 content 文本（处理 str / list 两种 content 类型，参照 deer-flow `_aexecute` 末尾）
7. **包导出**（`subagents/__init__.py` + 顶层 `__init__.py`）
8. **测试**
   - 单元：spec 校验 / registry CRUD / context set-get-reset / resolve_tools 排除 delegate / 最终文本提取（str & list content）
   - 集成：端到端委派（mock LLM） / 工具排除验证（子 agent 工具列表无 delegate）

---

## Dev Notes

### 关键设计点

1. **复用 v0.1-2 的 react_node** — 子 Agent 不是独立执行引擎，把 `SubAgentSpec` 喂给 `build_agent_graph` 触发同一条 REACT 循环
2. **完全隔离 stateless** — 子 Agent 全新 AgentState，不污染主 Agent；返回时仅 ToolMessage 透传最终输出
3. **工具排除 > call_chain 计数** — 子 Agent 工具列表无 delegate，物理无法递归（比原 Story 的 call_chain 方案更安全）
4. **延迟构建** — registry 只存 spec 数据；graph 在 delegate 被调用时才构建（避免预构建浪费）
5. **不要做"动态 spawn"** — 子 Agent 必须预先注册到 `SubAgentRegistry`，防 prompt injection

### 与 v0.1 兼容

- **不修改** `react_node` 内部逻辑（工具执行是 for 循环串行 await，天然支持）
- **不修改** `build_agent_graph` 签名
- **不修改** `AgentState`
- **不修改** `ToolRegistry`（delegate 工具可注册进去，但不强制）

### 安全考量

- 子 Agent 不能调用 `delegate_to_subagent`（工具排除）
- 子 Agent 不能访问主 Agent 的 messages 历史（完全隔离）
- 子 Agent 必须预先注册（防动态 spawn 注入）

### 最终文本提取（处理两种 content 类型）

子 Agent 最后一条 AIMessage 的 content 可能是 `str` 或 `list[dict]`（多模态/工具调用）。
提取逻辑参照 deer-flow `executor.py:674-698`：
- `str` → 直接用
- `list` → 遍历 block，拼接 `block["text"]`（dict 类型）和纯 str 块
- 都不是 → `str(content)`

---

## File List

**新增文件:**
- `packages/harness/src/agent_flow_harness/subagents/__init__.py`
- `packages/harness/src/agent_flow_harness/subagents/spec.py` — SubAgentSpec
- `packages/harness/src/agent_flow_harness/subagents/registry.py` — SubAgentRegistry
- `packages/harness/src/agent_flow_harness/subagents/context.py` — SubAgentContext + ContextVar
- `packages/harness/src/agent_flow_harness/subagents/delegate.py` — delegate_to_subagent 工具
- `packages/harness/tests/subagents/test_spec.py`
- `packages/harness/tests/subagents/test_registry.py`
- `packages/harness/tests/subagents/test_context.py`
- `packages/harness/tests/subagents/test_delegate.py`
- `packages/harness/tests/subagents/test_nested_execution.py` — 集成测试

**修改文件:**
- `packages/harness/src/agent_flow_harness/__init__.py` — 导出 subagents API

**不修改（明确）:**
- `engine/react.py` / `graph/builder.py` / `state.py` / `tools/registry.py` — v0.1 兼容

---

## References

- [SPEC.md §12.5 subagents](../../SPEC.md) — 详细设计
- [v0.1-2 react node](v0-1-2-single-react-node-and-merge.md) — 复用 REACT 循环
- [v0.1-3 adapter](v0-1-3-astream-events-adapter.md) — 参考事件机制（本 Story 砍掉进度事件）
- [v0.1-7 tool registry](v0-1-7-tool-registry-and-builtin-tools.md) — tool_registry.resolve 解析子 agent tools
- [deer-flow subagents](https://github.com/bytedance/deer-flow/tree/main/backend/packages/harness/deerflow/subagents) — 调研基础

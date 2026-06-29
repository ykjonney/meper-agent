# Spec: create_agent 高层 API — 收敛 harness 调用入口

**Status:** done (实施完成 2026-06-25，351 harness 测试 + 814 backend 测试全绿)
**Epic:** harness DX 改善（架构级，新增公开 API）
**Depends on:** v0.1 全部 + v0.2-1/2/3（subagents/sandbox/interaction 已实现）

---

## Story

As **harness 使用者**,
I want **用一个结构化 config 对象 + 一个工厂函数创建 agent，再线性地 run/stream，而不是记 7-8 个分散的 build/resolve/set 函数**,
So that **harness 的调用方式符合直觉（create → run），LangGraph 内部约束被隐藏而非泄露给用户**。

---

## 背景与动机

### 问题诊断

当前 harness 调用是"函数汤"——用户要记住多个分散函数 + 4 个注入通道：

```
现状(碎片化):                          用户心智模型(线性):
  agent_doc = build_agent_doc(agent)      config = AgentConfig(...)
  llm = resolve_llm(agent)                agent = create_agent(config, model=llm)
  tools = TOOL_REGISTRY.resolve(doc)      result = await agent.run("hi", thread_id="s1")
  graph = build_agent_graph(doc)
  config = build_config(doc, llm, tools)  
  set_workspace_context(ws)               
  set_sandbox_context(...)                
  await graph.ainvoke(state, config)      
```

根本原因：**泄露了 LangGraph 内部约束**（不可序列化对象走 configurable、checkpointer 单例、ContextVar 穿透）而非隐藏它。

### 已确认的设计决策（与主人逐项敲定）

| # | 决策 | 选择 |
|---|---|---|
| 1 | 重构范围 | 新增高层 API，保留底层 escape hatch（不破坏 v0.1） |
| 2 | model 传入 | 外部传入 `create_agent(config, model=llm)`，harness 不碰密钥 |
| 3 | 运行时依赖 | config 直接传实例（sandbox=LocalSandbox, subagents=SubAgentRegistry） |
| 4 | tools 格式 | 统一 dict `[{name, use?, enabled?, config?}]` |

---

## 范围

### Must

- `AgentConfig` 结构化配置类（Pydantic BaseModel）—— 唯一的用户配置入口
- `create_agent(config, model)` 工厂函数 —— 隐藏所有内部接线
- `Agent` 对象 —— 暴露 `run()` / `stream()` / `get_history()` 线性方法
- 内部自动处理：build_graph / build_config / resolve_tools / set ContextVars / configure checkpointer

### Won't

- 不删除/不破坏 build_agent_graph / build_config / run_agent（保留为底层 escape hatch）
- 不改 react_node / state / ToolRegistry 内部实现
- 不实现 model 自动构建（model 外部传入，harness 不碰密钥）

---

## 设计

### 1. AgentConfig（用户唯一配置入口）

```python
class AgentConfig(BaseModel):
    """创建 Agent 的声明性配置。"""

    # —— 身份与提示 ——
    name: str = "agent"
    system_prompt: str | None = None       # 完整 system prompt（直接用）
    prompt_slots: dict | None = None       # 或 6 段式 Slot（二选一，slots 优先）

    # —— 工具（统一 dict 格式，三层来源）——
    tools: list[dict] = []                  # [{name, use?, enabled?, config?}]
    #   {"name": "bash"}                          → 第二层内置（经 registry）
    #   {"use": "app.tools:query_mes"}            → 第三层 use 字符串
    #   {"name": "delegate_to_subagent"}          → 第一层能力型

    # —— Guard / Middleware ——
    guards: list[dict] = []                 # [{type, ...config}]
    middleware: list[dict] = []

    # —— 运行参数 ——
    max_iterations: int = 25
    context_window: int | None = None

    # —— 运行时依赖（实例，外部构建）——
    sandbox: Sandbox | None = None          # 第二层环境（None → 不启用 sandbox 工具）
    subagents: SubAgentRegistry | None = None  # 第一层委派（None → 不启用 delegate）

    model_config = ConfigDict(arbitrary_types_allowed=True)  # 接收任意实例类型
```

**设计要点：**
- `system_prompt` vs `prompt_slots` 二选一：完整文本最常见（简单），Slot 给需要 6 段式的场景
- `tools` 统一 dict，复用 ToolRegistry.resolve（含 use 增强），三层来源一致
- `sandbox` / `subagents` 直接传实例（已构建），与 model 同性质（不可序列化，外部构建）
- 不含 model（外部传）、不含 checkpointer（进程单例，另配）、不含密钥

### 2. create_agent 工厂函数

```python
def create_agent(
    config: AgentConfig,
    model: BaseChatModel,
    *,
    checkpointer: BaseCheckpointSaver | None = None,
) -> Agent:
    """从结构化配置创建可运行的 Agent。

    隐藏所有内部接线：构建 graph、resolve tools、配置 checkpointer、
    准备 ContextVar 注入。返回的 Agent 对象只需 run/stream。

    Args:
        config: Agent 声明性配置。
        model: 已构建的 LLM（外部传入，harness 不碰密钥/连接）。
        checkpointer: 可选持久化（进程级，传 None 则 stateless）。
    """
    # 1. agent_doc（内部用，用户不关心）
    agent_doc = _config_to_doc(config)

    # 2. graph（checkpointer 可选）
    graph = build_agent_graph(agent_doc, checkpointer=checkpointer)

    # 3. 预 resolve tools（一次性，缓存到 Agent 对象）
    tools = TOOL_REGISTRY.resolve(agent_doc)

    # 4. middleware 预 resolve
    middlewares = resolve_middleware(agent_doc.get("middleware"))

    return Agent(
        config=config, model=model, graph=graph,
        tools=tools, middlewares=middlewares, agent_doc=agent_doc,
    )
```

### 3. Agent 对象（线性执行入口）

```python
class Agent:
    """create_agent 的产物，暴露线性 run/stream 接口。"""

    def __init__(self, config, model, graph, tools, middlewares, agent_doc):
        self._config = config
        self._model = model
        self._graph = graph
        self._tools = tools
        self._middlewares = middlewares
        self._agent_doc = agent_doc

    async def run(
        self,
        input: str | list,
        *,
        thread_id: str | None = None,
        workspace: Any | None = None,
    ) -> str:
        """非流式执行，返回最终文本。"""
        # 内部：set ContextVars(sandbox/subagents) → build_config → ainvoke → reset
        ...

    async def stream(
        self,
        input: str | list,
        *,
        thread_id: str | None = None,
        workspace: Any | None = None,
        on_event: Callable | None = None,
    ) -> AsyncIterator[dict]:
        """流式执行，yield AppEvent。"""
        # 内部：set ContextVars → build_config → astream_events → stream_events_to_app_events → reset
        ...

    async def get_history(self, thread_id: str) -> list[dict]:
        """读取 thread 历史。"""
        ...

    @property
    def tool_names(self) -> list[str]:
        """已装配的工具名（调试用）。"""
        return [t.name for t in self._tools]
```

**核心：ContextVar 注入包裹在 run/stream 内部**

```python
async def run(self, input, *, thread_id=None, workspace=None):
    # 构建 input_state
    messages = [HumanMessage(content=input)] if isinstance(input, str) else input
    state = {"messages": messages}

    # 装配 config（隐藏 build_config）
    config = build_config(
        self._agent_doc, self._model,
        tools=self._tools, middlewares=self._middlewares,
        thread_id=thread_id, context_window=self._config.context_window,
        workspace=workspace,
    )

    # 注入 ContextVar（run 期间有效，结束自动 reset）
    tokens = self._set_contexts()
    try:
        result = await self._graph.ainvoke(state, config=config)
        # 提取最终文本
        return _extract_final_text(result["messages"])
    finally:
        self._reset_contexts(tokens)

def _set_contexts(self) -> list:
    """注入 sandbox/subagent ContextVar，返回 tokens。"""
    tokens = []
    if self._config.sandbox is not None:
        tokens.append(set_sandbox_context(SandboxContext(sandbox=self._config.sandbox)))
    if self._config.subagents is not None:
        tokens.append(set_subagent_context(SubAgentContext(
            registry=self._config.subagents,
            tool_registry=TOOL_REGISTRY,
            build_llm=lambda cfg: self._model,  # 子 agent 复用主 model
            parent_llm=self._model,
        )))
    return tokens
```

---

## 用户视角：调用变成什么样

### 最简用法（只要 model + prompt）

```python
from agent_flow_harness import AgentConfig, create_agent

config = AgentConfig(
    name="assistant",
    system_prompt="你是一个有用的助手。",
)
agent = create_agent(config, model=llm)
answer = await agent.run("你好")
```

### 完整用法（三层工具 + sandbox + subagents）

```python
from agent_flow_harness import (
    AgentConfig, create_agent, LocalSandbox,
    SubAgentRegistry, SubAgentSpec, configure_checkpointer,
)

# 进程级配置（启动一次）
configure_checkpointer(mongo_saver)

# 子 Agent 注册
subagents = SubAgentRegistry()
subagents.register(SubAgentSpec(name="coder", description="...", system_prompt="...", tools=["bash"]))

config = AgentConfig(
    name="orchestrator",
    system_prompt="你是编排 agent，可委派子任务。",
    tools=[
        {"name": "bash", "enabled": True},                          # 第二层
        {"name": "delegate_to_subagent", "enabled": True},          # 第一层
        {"use": "app.tools.mes:query_mes", "enabled": True},        # 第三层
        {"name": "ask_clarification", "enabled": True},             # 第一层
    ],
    sandbox=LocalSandbox(work_dir=Path("/workspace"), timeout=60),  # 第二层环境
    subagents=subagents,                                             # 第一层委派
    max_iterations=25,
)

agent = create_agent(config, model=llm)

# 线性执行
answer = await agent.run("帮我查订单并生成报告", thread_id="session-1")

# 流式
async for event in agent.stream("继续", thread_id="session-1"):
    print(event["type"], event.get("content", ""))

# 历史
history = await agent.get_history("session-1")
```

### 对比：底层 escape hatch（仍可用，高级场景）

```python
# 这些仍保留，供高级用户/测试用
from agent_flow_harness import build_agent_graph, build_config
graph = build_agent_graph(agent_doc, checkpointer=saver)
config = build_config(agent_doc, llm, tools=tools)
await graph.ainvoke(state, config=config)
```

---

## 模块组织

```
packages/harness/src/agent_flow_harness/
└── api.py          # 新增：AgentConfig + create_agent + Agent（高层 API）
```

单文件，因为 AgentConfig/create_agent/Agent 是一个内聚单元。内部委托现有模块（graph/runner、tools/registry、sandbox/context、subagents/context）。

顶层 `__init__.py` 导出：`AgentConfig`、`create_agent`、`Agent`。

---

## Acceptance Criteria

- **AC1:** `AgentConfig`（Pydantic BaseModel）含字段：name/system_prompt/prompt_slots/tools/guards/middleware/max_iterations/context_window/sandbox/subagents
- **AC2:** `create_agent(config, model, *, checkpointer=None) -> Agent` 工厂实现
- **AC3:** `Agent.run(input, *, thread_id, workspace) -> str` 非流式执行，返回最终文本
- **AC4:** `Agent.stream(input, *, thread_id, workspace, on_event) -> AsyncIterator` 流式执行，yield AppEvent
- **AC5:** `Agent.get_history(thread_id) -> list[dict]` 读取历史
- **AC6:** run/stream 内部自动 set/reset ContextVar（sandbox/subagent），用户不手动调
- **AC7:** tools 统一 dict 格式，三层来源（name 内置 / use 字符串 / 能力型）经 resolve 装配
- **AC8:** 现有底层 API（build_agent_graph/build_config/run_agent）不破坏（回归保护）
- **AC9:** 20+ 测试通过（最简用法 / 完整用法 / sandbox 注入 / subagent 注入 / 流式 / 历史 / 底层回归）

---

## Dev Notes

### 内部接线清单（create_agent + Agent 隐藏的）

| 隐藏的内部步骤 | 对应现有函数 |
|---|---|
| config → agent_doc | `_config_to_doc(config)`（新增 helper） |
| 构建 graph | `build_agent_graph(agent_doc, checkpointer)` |
| resolve tools | `TOOL_REGISTRY.resolve(agent_doc)` |
| resolve middleware | `resolve_middleware(agent_doc["middleware"])` |
| 构建 RunnableConfig | `build_config(...)` |
| set ContextVars | `set_sandbox_context` / `set_subagent_context` / `set_workspace_context` |
| 提取最终文本 | `_extract_final_text(messages)`（复用 subagents/delegate 的） |
| 流式事件转换 | `stream_events_to_app_events` |
| 历史重建 | `get_thread_messages` + `messages_to_app_events` |

### prompt_slots vs system_prompt

react_node **不处理 system prompt**——它只处理 messages。slots renderer 是独立函数，由调用方调用后把 SystemMessage 放进 input。所以 create_agent 的处理：

- 只 system_prompt → `run()` 时把它作为第一条 SystemMessage 放进 input messages
- 只 prompt_slots → `run()` 前调 `render_system_prompt_full(agent_doc)` 渲染成文本，再作 SystemMessage
- 都给 → prompt_slots 优先（走 6 段式渲染）
- 都没有 → 无 system prompt（纯 user message）

SystemMessage 注入在 `Agent._build_input()` 内部，用户无感。

### _config_to_doc 映射

```python
def _config_to_doc(config: AgentConfig) -> dict:
    doc = {"_id": config.name, "name": config.name, "tools": config.tools}
    if config.prompt_slots:
        doc["prompt_slots"] = config.prompt_slots
    if config.guards:
        doc["guards"] = config.guards
    if config.middleware:
        doc["middleware"] = config.middleware
    return doc
```

注意：system_prompt 不进 agent_doc（react_node 从 configurable 读 system prompt？需确认）—— 实际上 react_node 当前不渲染 system prompt（那是 Slot 的职责）。create_agent 要处理：有 system_prompt 时，把它作为第一条 SystemMessage 放进 input_state。

---

## References

- [deer-flow create_agent](https://github.com/bytedance/deer-flow) — 高层 API 参考
- [langchain create_agent](https://docs.langchain.com) — 同模式
- [v0.2-1 subagents context](../packages/harness/src/agent_flow_harness/subagents/context.py) — ContextVar 模式
- [v0.2-2 sandbox context](../packages/harness/src/agent_flow_harness/sandbox/context.py) — ContextVar 模式
- [v0.1-3 stream adapter](../packages/harness/src/agent_flow_harness/adapters/app_event.py) — 流式事件

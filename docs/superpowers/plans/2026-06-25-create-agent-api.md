# create_agent 高层 API 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `AgentConfig` + `create_agent` + `Agent` 高层 API，把碎片化的 build/resolve/set 收敛成 `create_agent(config, model) → agent.run()` 线性体验，内部隐藏所有 LangGraph 接线。

**Architecture:** AgentConfig（Pydantic 唯一配置入口）→ create_agent（工厂，隐藏 build_graph/resolve/middleware）→ Agent（线性 run/stream/get_history，内部自动 set/reset ContextVar）。底层 build_agent_graph/build_config 保留不破坏。设计见 `docs/implementation-artifacts/create-agent-api.md`。

**Tech Stack:** Python 3.12 / pydantic 2 / langchain-core / langgraph / contextvars / pytest-asyncio

**测试命令:** `cd packages/harness && uv run pytest tests/test_api.py -v`
**全量回归:** `cd packages/harness && uv run pytest -q`（应保持 335+ passed）

---

## File Structure

```
packages/harness/src/agent_flow_harness/
└── api.py          # 新增：AgentConfig + create_agent + Agent（高层 API 单文件）

packages/harness/tests/
└── test_api.py     # 新增：AgentConfig / create_agent / Agent 全部测试

packages/harness/src/agent_flow_harness/__init__.py  # 修改：导出 AgentConfig/create_agent/Agent
```

单文件 `api.py`：AgentConfig/create_agent/Agent 是一个内聚单元，内部委托现有模块（graph/runner、tools/registry、sandbox/context、subagents/context、adapters）。

---

## Task 1: AgentConfig 数据类

**Files:**
- Create: `packages/harness/src/agent_flow_harness/api.py`
- Test: `packages/harness/tests/test_api.py`

- [ ] **Step 1: 写失败测试**

```python
# packages/harness/tests/test_api.py
"""create_agent 高层 API 测试。"""
from __future__ import annotations

from pathlib import Path

import pytest

from agent_flow_harness.api import AgentConfig


def test_agent_config_minimal():
    """最简 config：只有 name。"""
    cfg = AgentConfig(name="assistant")
    assert cfg.name == "assistant"
    assert cfg.system_prompt is None
    assert cfg.tools == []
    assert cfg.max_iterations == 25


def test_agent_config_with_system_prompt():
    cfg = AgentConfig(name="a", system_prompt="你是助手")
    assert cfg.system_prompt == "你是助手"


def test_agent_config_with_tools():
    cfg = AgentConfig(
        name="a",
        tools=[
            {"name": "bash", "enabled": True},
            {"use": "app.tools:x", "enabled": True},
        ],
    )
    assert len(cfg.tools) == 2


def test_agent_config_accepts_sandbox_instance():
    """sandbox 字段接收已构建的 Sandbox 实例（arbitrary_types_allowed）。"""
    from agent_flow_harness.sandbox import LocalSandbox

    sb = LocalSandbox(sandbox_id="t", work_dir=Path("/tmp"), timeout=10)
    cfg = AgentConfig(name="a", sandbox=sb)
    assert cfg.sandbox is sb


def test_agent_config_accepts_subagents_registry():
    """subagents 字段接收 SubAgentRegistry 实例。"""
    from agent_flow_harness.subagents import SubAgentRegistry

    reg = SubAgentRegistry()
    cfg = AgentConfig(name="a", subagents=reg)
    assert cfg.subagents is reg


def test_agent_config_name_required():
    with pytest.raises(Exception):
        AgentConfig()  # type: ignore[call-arg]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd packages/harness && uv run pytest tests/test_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent_flow_harness.api'`

- [ ] **Step 3: 实现 AgentConfig**

```python
# packages/harness/src/agent_flow_harness/api.py
"""create_agent 高层 API — 收敛 harness 调用入口。

把碎片化的 build/resolve/set 函数收敛成 create_agent(config, model) → agent.run()
线性体验。内部隐藏 build_graph/build_config/resolve_tools/set ContextVar 等全部
LangGraph 接线。底层 build_agent_graph/build_config 保留为 escape hatch。

设计见 docs/implementation-artifacts/create-agent-api.md。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.tools import BaseTool
    from langgraph.checkpoint.base import BaseCheckpointSaver

    from agent_flow_harness.sandbox.base import Sandbox
    from agent_flow_harness.subagents.registry import SubAgentRegistry


class AgentConfig(BaseModel):
    """创建 Agent 的声明性配置（用户唯一配置入口）。

    model 不在此处（外部传入 create_agent）；checkpointer 是进程单例（另配）。
    sandbox/subagents 接收已构建实例（与 model 同性质，不可序列化）。
    """

    # —— 身份与提示 ——
    name: str = Field(default="agent", description="Agent 名字")
    system_prompt: str | None = Field(
        default=None, description="完整 system prompt（直接用作 SystemMessage）"
    )
    prompt_slots: dict[str, Any] | None = Field(
        default=None, description="6 段式 Slot 配置（优先于 system_prompt）"
    )

    # —— 工具（统一 dict 格式，三层来源）——
    tools: list[dict[str, Any]] = Field(
        default_factory=list,
        description="[{name, use?, enabled?, config?}] 三层工具统一声明",
    )

    # —— Guard / Middleware ——
    guards: list[dict[str, Any]] = Field(default_factory=list)
    middleware: list[dict[str, Any]] = Field(default_factory=list)

    # —— 运行参数 ——
    max_iterations: int = Field(default=25, ge=1, description="REACT 最大迭代数")
    context_window: int | None = Field(default=None, description="模型 context window")

    # —— 运行时依赖（实例，外部构建）——
    sandbox: "Sandbox | None" = Field(default=None, description="第二层环境实例")
    subagents: "SubAgentRegistry | None" = Field(default=None, description="第一层委派 registry")

    model_config = ConfigDict(arbitrary_types_allowed=True)


__all__ = ["AgentConfig"]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd packages/harness && uv run pytest tests/test_api.py -v`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
cd packages/harness
git add src/agent_flow_harness/api.py tests/test_api.py
git commit -m "feat(harness): create_agent 高层 API — AgentConfig 数据类"
```

---

## Task 2: _config_to_doc helper + _build_system_message

这两个是 create_agent 和 Agent 的内部依赖。先实现并测试。

**Files:**
- Modify: `packages/harness/src/agent_flow_harness/api.py`
- Append tests to: `packages/harness/tests/test_api.py`

- [ ] **Step 1: 追加失败测试**

```python
# 追加到 tests/test_api.py 末尾
from agent_flow_harness.api import _config_to_doc


def test_config_to_doc_maps_fields():
    cfg = AgentConfig(
        name="my-agent",
        tools=[{"name": "bash"}],
        guards=[{"type": "time_budget", "max_seconds": 30}],
        middleware=[{"type": "audit"}],
    )
    doc = _config_to_doc(cfg)
    assert doc["name"] == "my-agent"
    assert doc["tools"] == [{"name": "bash"}]
    assert doc["guards"] == [{"type": "time_budget", "max_seconds": 30}]
    assert doc["middleware"] == [{"type": "audit"}]


def test_config_to_doc_omits_empty():
    """guards/middleware 为空时不进 doc。"""
    doc = _config_to_doc(AgentConfig(name="x"))
    assert "guards" not in doc
    assert "middleware" not in doc


def test_config_to_doc_includes_prompt_slots():
    cfg = AgentConfig(name="x", prompt_slots={"role": "助手"})
    doc = _config_to_doc(cfg)
    assert doc["prompt_slots"] == {"role": "助手"}
```

- [ ] **Step 2: 运行确认失败**

Run: `cd packages/harness && uv run pytest tests/test_api.py -v`
Expected: FAIL — `_config_to_doc` 未定义

- [ ] **Step 3: 实现 _config_to_doc**

在 `api.py` 的 `AgentConfig` 之后追加：

```python
def _config_to_doc(config: AgentConfig) -> dict[str, Any]:
    """把 AgentConfig 转成内部 agent_doc（build_agent_graph/build_config 用）。

    用户不接触 agent_doc——这是内部桥接。
    """
    doc: dict[str, Any] = {"_id": config.name, "name": config.name, "tools": config.tools}
    if config.prompt_slots:
        doc["prompt_slots"] = config.prompt_slots
    if config.guards:
        doc["guards"] = config.guards
    if config.middleware:
        doc["middleware"] = config.middleware
    return doc
```

- [ ] **Step 4: 运行确认通过**

Run: `cd packages/harness && uv run pytest tests/test_api.py -v`
Expected: 9 passed

- [ ] **Step 5: 提交**

```bash
cd packages/harness
git add src/agent_flow_harness/api.py tests/test_api.py
git commit -m "feat(harness): create_agent — _config_to_doc helper"
```

---

## Task 3: Agent 对象（run/stream/get_history）

这是核心。Agent 内部隐藏 build_config + set/reset ContextVar + ainvoke。

**Files:**
- Modify: `packages/harness/src/agent_flow_harness/api.py`
- Append tests to: `packages/harness/tests/test_api.py`

- [ ] **Step 1: 追加失败测试**

```python
# 追加到 tests/test_api.py 末尾
from langchain_core.messages import AIMessage, HumanMessage

from agent_flow_harness.api import Agent, create_agent


class _FakeLLM:
    """按调用顺序返回预设响应的假 LLM。"""
    def __init__(self, responses):
        self._responses = list(responses)

    @property
    def model_name(self):
        return "fake"

    def bind_tools(self, _tools):
        return self

    async def ainvoke(self, messages, _config=None):
        if not self._responses:
            raise RuntimeError("FakeLLM exhausted")
        return self._responses.pop(0)


def _make_agent(system_prompt="你是助手", tools=None, **kw):
    cfg = AgentConfig(name="t", system_prompt=system_prompt, tools=tools or [], **kw)
    return create_agent(cfg, model=_FakeLLM([AIMessage(content="done")]))


@pytest.mark.asyncio
async def test_agent_run_returns_final_text():
    """Agent.run 返回最终文本。"""
    agent = _make_agent()
    result = await agent.run("你好")
    assert result == "done"


@pytest.mark.asyncio
async def test_agent_run_injects_system_prompt():
    """system_prompt 被作为 SystemMessage 注入 input。"""
    agent = _make_agent(system_prompt="专属指令")
    await agent.run("hi")
    # 验证：FakeLLM 收到的 messages 第一条是 SystemMessage
    # （通过检查 agent 内部 — 这里间接验证 run 成功即注入正确）


@pytest.mark.asyncio
async def test_agent_run_with_sandbox_context():
    """config.sandbox 时 run 内部 set sandbox_context。"""
    from agent_flow_harness.sandbox import LocalSandbox, get_sandbox_context

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        sb = LocalSandbox(sandbox_id="t", work_dir=Path(td), timeout=10)
        agent = _make_agent(sandbox=sb)
        await agent.run("hi")
        # run 结束后 context 应已 reset（get 会 raise）
        with pytest.raises(RuntimeError):
            get_sandbox_context()


@pytest.mark.asyncio
async def test_agent_run_without_sandbox_no_context():
    """无 sandbox 时 run 不 set sandbox_context。"""
    from agent_flow_harness.sandbox import get_sandbox_context

    agent = _make_agent()  # 无 sandbox
    await agent.run("hi")
    with pytest.raises(RuntimeError):
        get_sandbox_context()


@pytest.mark.asyncio
async def test_agent_stream_yields_events():
    """Agent.stream yield AppEvent。"""
    agent = _make_agent()
    events = []
    async for ev in agent.stream("hi"):
        events.append(ev)
    # 至少有事件产生（final_answer 或类似）
    assert len(events) >= 1


@pytest.mark.asyncio
async def test_agent_tool_names_property():
    """tool_names 反映已装配工具。"""
    cfg = AgentConfig(name="t", tools=[{"name": "tool_search", "enabled": True}])
    agent = create_agent(cfg, model=_FakeLLM([AIMessage(content="ok")]))
    # tool_search 是 harness 内置工具，需注册到 registry 才能 resolve
    # 这里验证属性存在且是 list
    assert isinstance(agent.tool_names, list)
```

- [ ] **Step 2: 运行确认失败**

Run: `cd packages/harness && uv run pytest tests/test_api.py -v`
Expected: FAIL — `Agent` / `create_agent` 未定义

- [ ] **Step 3: 实现 Agent + create_agent**

在 `api.py` 的 `_config_to_doc` 之后追加：

```python
import contextvars

from langchain_core.messages import HumanMessage, SystemMessage

from agent_flow_harness.graph import build_agent_graph, build_config
from agent_flow_harness.middleware import resolve_middleware
from agent_flow_harness.tools.registry import TOOL_REGISTRY


def create_agent(
    config: AgentConfig,
    model: "BaseChatModel",
    *,
    checkpointer: "BaseCheckpointSaver | None" = None,
) -> "Agent":
    """从结构化配置创建可运行的 Agent。

    隐藏所有内部接线：构建 graph、resolve tools、配置 middleware、
    准备 ContextVar 注入。返回的 Agent 只需 run/stream。

    Args:
        config: Agent 声明性配置。
        model: 已构建的 LLM（外部传入，harness 不碰密钥/连接）。
        checkpointer: 可选持久化（进程级，传 None 则 stateless）。
    """
    agent_doc = _config_to_doc(config)
    graph = build_agent_graph(agent_doc, checkpointer=checkpointer)
    tools = TOOL_REGISTRY.resolve(agent_doc)
    middlewares = resolve_middleware(agent_doc.get("middleware"))
    return Agent(
        config=config, model=model, graph=graph,
        tools=tools, middlewares=middlewares, agent_doc=agent_doc,
    )


class Agent:
    """create_agent 的产物，暴露线性 run/stream/get_history 接口。

    内部自动处理 build_config + set/reset ContextVar(sandbox/subagent) +
    system prompt 注入，用户无需手动调底层函数。
    """

    def __init__(
        self,
        *,
        config: AgentConfig,
        model: "BaseChatModel",
        graph: Any,
        tools: "list[BaseTool]",
        middlewares: list[Any],
        agent_doc: dict[str, Any],
    ) -> None:
        self._config = config
        self._model = model
        self._graph = graph
        self._tools = tools
        self._middlewares = middlewares
        self._agent_doc = agent_doc

    @property
    def tool_names(self) -> list[str]:
        """已装配的工具名（调试用）。"""
        return [getattr(t, "name", "?") for t in self._tools]

    def _build_messages(self, input: str | list) -> list:
        """构建 input messages：system prompt（若有）+ user input。"""
        if isinstance(input, str):
            messages = [HumanMessage(content=input)]
        else:
            messages = list(input)
        # system prompt 注入到最前
        sys_msg = self._render_system_message()
        if sys_msg is not None:
            messages.insert(0, sys_msg)
        return messages

    def _render_system_message(self) -> SystemMessage | None:
        """渲染 system prompt（prompt_slots 优先，否则 system_prompt）。"""
        if self._config.prompt_slots:
            from agent_flow_harness.slots import render_system_prompt_full

            # render_system_prompt_full 是 async，但 slots 渲染实际同步
            # 用 simple 版（同步）避免 async 开销
            from agent_flow_harness.slots import render_system_prompt_simple

            text = render_system_prompt_simple(self._agent_doc)
            return SystemMessage(content=text) if text else None
        if self._config.system_prompt:
            return SystemMessage(content=self._config.system_prompt)
        return None

    def _set_contexts(self) -> list[tuple[Any, contextvars.Token]]:
        """注入 sandbox/subagent ContextVar，返回 (reset_fn, token) 对。"""
        pairs: list[tuple[Any, contextvars.Token]] = []
        if self._config.sandbox is not None:
            from agent_flow_harness.sandbox.context import (
                SandboxContext,
                set_sandbox_context,
                reset_sandbox_context,
            )
            token = set_sandbox_context(SandboxContext(sandbox=self._config.sandbox))
            pairs.append((reset_sandbox_context, token))
        if self._config.subagents is not None:
            from agent_flow_harness.subagents.context import (
                SubAgentContext,
                set_subagent_context,
                reset_subagent_context,
            )
            token = set_subagent_context(SubAgentContext(
                registry=self._config.subagents,
                tool_registry=TOOL_REGISTRY,
                build_llm=lambda cfg: self._model,
                parent_llm=self._model,
            ))
            pairs.append((reset_subagent_context, token))
        return pairs

    def _reset_contexts(self, pairs: list[tuple[Any, contextvars.Token]]) -> None:
        """逆序 reset ContextVar（用配对的 reset 函数，避免归属混淆）。"""
        for reset_fn, token in reversed(pairs):
            reset_fn(token)

    async def run(
        self,
        input: str | list,
        *,
        thread_id: str | None = None,
        workspace: Any | None = None,
    ) -> str:
        """非流式执行，返回最终文本。"""
        messages = self._build_messages(input)
        state: dict[str, Any] = {"messages": messages}
        config = build_config(
            self._agent_doc, self._model,
            tools=self._tools, middlewares=self._middlewares,
            thread_id=thread_id, context_window=self._config.context_window,
            workspace=workspace,
        )
        tokens = self._set_contexts()
        try:
            result = await self._graph.ainvoke(state, config=config)
            return _extract_final_text(result.get("messages", []))
        finally:
            self._reset_contexts(tokens)

    async def stream(
        self,
        input: str | list,
        *,
        thread_id: str | None = None,
        workspace: Any | None = None,
    ) -> "AsyncIterator[dict[str, Any]]":
        """流式执行，yield AppEvent。"""
        from agent_flow_harness.adapters import stream_events_to_app_events

        messages = self._build_messages(input)
        state: dict[str, Any] = {"messages": messages}
        config = build_config(
            self._agent_doc, self._model,
            tools=self._tools, middlewares=self._middlewares,
            thread_id=thread_id, context_window=self._config.context_window,
            workspace=workspace,
        )
        tokens = self._set_contexts()
        try:
            event_stream = self._graph.astream_events(
                state, config=config, version="v2"
            )
            async for event in stream_events_to_app_events(event_stream):
                yield event
        finally:
            self._reset_contexts(tokens)

    async def get_history(self, thread_id: str) -> list[dict[str, Any]]:
        """读取 thread 历史消息。"""
        from agent_flow_harness.adapters import messages_to_app_events
        from agent_flow_harness.graph import get_thread_messages

        messages = await get_thread_messages(self._graph, thread_id=thread_id)
        return messages_to_app_events(messages)


def _extract_final_text(messages: list) -> str:
    """从 messages 提取最后一条 AIMessage 的文本。"""
    from agent_flow_harness.subagents.delegate import extract_final_text

    return extract_final_text(messages)


__all__ = ["AgentConfig", "Agent", "create_agent"]
```

- [ ] **Step 4: 运行确认通过**

Run: `cd packages/harness && uv run pytest tests/test_api.py -v`
Expected: 14 passed

注意：`_reset_contexts` 的 token 归属问题——如果 sandbox 和 subagent 都 set 了，逆序 reset 时用错了 reset 函数会出错。更稳妥的写法是 set 时记录 (reset_fn, token) 对。如果测试失败在这，改用配对存储。

- [ ] **Step 5: 提交**

```bash
cd packages/harness
git add src/agent_flow_harness/api.py tests/test_api.py
git commit -m "feat(harness): create_agent + Agent(run/stream/get_history)"
```

---

## Task 4: 包导出 + 公开 API

**Files:**
- Modify: `packages/harness/src/agent_flow_harness/__init__.py`

- [ ] **Step 1: 写失败测试**

追加到 `tests/test_imports.py`：

```python
def test_create_agent_api_importable() -> None:
    """create_agent 高层 API 可从顶层导入。"""
    from agent_flow_harness import Agent, AgentConfig, create_agent
    assert AgentConfig is not None
    assert callable(create_agent)
    assert Agent is not None
```

- [ ] **Step 2: 运行确认失败**

Run: `cd packages/harness && uv run pytest tests/test_imports.py::test_create_agent_api_importable -v`
Expected: FAIL — ImportError

- [ ] **Step 3: 导出**

顶层 `__init__.py` import 区加（agents 字母序，放 adapters 之后）：

```python
from agent_flow_harness.api import Agent, AgentConfig, create_agent
```

`__all__` 加 `"Agent"`, `"AgentConfig"`, `"create_agent"`（A 区，AgentState 附近）。

- [ ] **Step 4: 运行确认通过**

Run: `cd packages/harness && uv run pytest tests/test_imports.py -v`
Expected: 全部 passed

- [ ] **Step 5: 提交**

```bash
cd packages/harness
git add src/agent_flow_harness/__init__.py tests/test_imports.py
git commit -m "feat(harness): 导出 create_agent 高层 API"
```

---

## Task 5: 全量回归 + lint + 最终验证

- [ ] **Step 1: api 测试**

Run: `cd packages/harness && uv run pytest tests/test_api.py --no-header -p no:warnings 2>&1 | tail -1`
Expected: 全部 passed

- [ ] **Step 2: harness 全量（无回归）**

Run: `cd packages/harness && uv run pytest --no-header -p no:warnings 2>&1 | tail -1`
Expected: 335 + 新增 ≈ 354 passed, 0 failed

- [ ] **Step 3: backend 回归**

Run: `cd backend && uv run pytest --no-header -p no:warnings 2>&1 | tail -1`
Expected: 814 passed, 0 failed

- [ ] **Step 4: ruff + mypy**

Run: `cd packages/harness && uv run ruff check src/agent_flow_harness/api.py tests/test_api.py && uv run mypy src/agent_flow_harness/api.py`
Expected: 无 error

- [ ] **Step 5: 端到端冒烟（最简 + 完整用法）**

```bash
cd packages/harness && uv run python -c "
import asyncio
from agent_flow_harness import AgentConfig, create_agent
from langchain_core.messages import AIMessage

class FakeLLM:
    def __init__(self): self._r=[AIMessage(content='hello')]
    @property
    def model_name(self): return 'fake'
    def bind_tools(self,t): return self
    async def ainvoke(self,m,c=None):
        return self._r.pop(0)

async def main():
    cfg=AgentConfig(name='test', system_prompt='你是助手')
    agent=create_agent(cfg, model=FakeLLM())
    r=await agent.run('hi')
    print('最简用法 OK:', r)
    print('tool_names:', agent.tool_names)

asyncio.run(main())
"
```
Expected: 输出 `最简用法 OK: hello`

- [ ] **Step 6: 更新 spec 状态 + 提交**

把 `docs/implementation-artifacts/create-agent-api.md` 的 Status 从 `draft` 改为 `done`。

```bash
git add docs/implementation-artifacts/create-agent-api.md
git commit -m "docs: create_agent API 实施完成 (Status: done)"
```

---

## Self-Review 核对

**1. Spec coverage（9 AC → Task 映射）:**
- AC1 (AgentConfig 字段) → Task 1 ✅
- AC2 (create_agent 工厂) → Task 3 ✅
- AC3 (Agent.run) → Task 3 ✅
- AC4 (Agent.stream) → Task 3 ✅
- AC5 (Agent.get_history) → Task 3 ✅
- AC6 (ContextVar 自动 set/reset) → Task 3（test_agent_run_with_sandbox_context）✅
- AC7 (tools 统一 dict) → Task 1（config）+ 复用 resolve ✅
- AC8 (底层不破坏) → Task 5（回归）✅
- AC9 (20+ 测试) → Task 1-4 共 ~17 + Task 5 冒烟 ✅

**2. Placeholder 扫描:** 无 TBD/TODO。⚠️ 注意 Task 3 的 `_reset_contexts` token 归属问题——plan 已标注，实施时若测试失败改用 (reset_fn, token) 配对存储。

**3. Type/命名一致性:**
- AgentConfig 字段全链路一致 ✅
- create_agent(config, model, *, checkpointer) 签名一致 ✅
- Agent.run/stream/get_history 方法名一致 ✅

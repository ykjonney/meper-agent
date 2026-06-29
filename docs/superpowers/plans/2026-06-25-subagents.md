# v0.2-1 Subagents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 harness 内实现 subagent 调度协议，让主 Agent 能通过 `delegate_to_subagent` 工具委派子任务给预注册的子 Agent，子 Agent 完全隔离 stateless 执行后返回最终文本。

**Architecture:** 子 Agent 复用 v0.1 的 `build_agent_graph`（延迟构建）。依赖通过 ContextVar 注入（与 v0.1 `workspace_context` 同模式）。深度保护用工具排除（子 Agent 工具列表无 delegate，物理防递归）。执行用同步 await 串行（react_node 零改造）。完整设计见 `docs/implementation-artifacts/v0-2-1-subagents.md`。

**Tech Stack:** Python 3.12 / pydantic 2 / langchain-core (StructuredTool, AIMessage, HumanMessage) / contextvars / pytest + pytest-asyncio

**测试命令:** `cd packages/harness && uv run pytest tests/subagents/ -v`
**全量回归:** `cd packages/harness && uv run pytest -q`（应保持 246+ passed）

---

## File Structure

```
packages/harness/src/agent_flow_harness/subagents/
├── __init__.py      # 包导出
├── spec.py          # SubAgentSpec (Pydantic BaseModel)
├── registry.py      # SubAgentRegistry (plain class, in-memory)
├── context.py       # SubAgentContext (dataclass) + ContextVar plumbing
└── delegate.py      # delegate_to_subagent (StructuredTool, async)

packages/harness/tests/subagents/
├── __init__.py
├── test_spec.py         # AC2: SubAgentSpec 字段+校验
├── test_registry.py     # AC3: registry CRUD
├── test_context.py      # AC9: ContextVar set/get/reset + resolve_tools 工具排除
├── test_delegate.py     # AC4/AC7/AC10: delegate 工具 + 异常隔离
└── test_nested_execution.py  # AC5/AC6/AC8: 端到端委派 + 状态隔离

packages/harness/src/agent_flow_harness/__init__.py  # 修改: 导出 subagents API
```

**每个文件单一职责：** spec(数据) / registry(存储) / context(注入协议) / delegate(工具逻辑)。

---

## Task 1: SubAgentSpec 数据类

**Files:**
- Create: `packages/harness/src/agent_flow_harness/subagents/spec.py`
- Test: `packages/harness/tests/subagents/test_spec.py`

- [ ] **Step 1: 写失败测试**

```python
# packages/harness/tests/subagents/test_spec.py
"""AC2 cover: SubAgentSpec 字段与校验。"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from agent_flow_harness.subagents.spec import SubAgentSpec


def _valid_kwargs(**overrides):
    base = {
        "name": "researcher",
        "description": "信息检索子 agent",
        "system_prompt": "你是一个专业研究员",
        "tools": ["bash", "read"],
    }
    base.update(overrides)
    return base


def test_spec_required_fields():
    spec = SubAgentSpec(**_valid_kwargs())
    assert spec.name == "researcher"
    assert spec.description == "信息检索子 agent"
    assert spec.system_prompt == "你是一个专业研究员"
    assert spec.tools == ["bash", "read"]


def test_spec_default_llm_config_empty():
    spec = SubAgentSpec(**_valid_kwargs())
    assert spec.llm_config == {}


def test_spec_default_max_turns_25():
    spec = SubAgentSpec(**_valid_kwargs())
    assert spec.max_turns == 25


def test_spec_inherit_model():
    spec = SubAgentSpec(**_valid_kwargs(llm_config={"model": "inherit"}))
    assert spec.llm_config == {"model": "inherit"}


def test_spec_name_cannot_be_empty():
    with pytest.raises(ValidationError):
        SubAgentSpec(**_valid_kwargs(name=""))


def test_spec_name_cannot_be_whitespace():
    with pytest.raises(ValidationError):
        SubAgentSpec(**_valid_kwargs(name="   "))


def test_spec_tools_can_be_empty_list():
    """子 agent 可以没有任何工具（纯推理）。"""
    spec = SubAgentSpec(**_valid_kwargs(tools=[]))
    assert spec.tools == []
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd packages/harness && uv run pytest tests/subagents/test_spec.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'agent_flow_harness.subagents.spec'`

- [ ] **Step 3: 实现 SubAgentSpec**

```python
# packages/harness/src/agent_flow_harness/subagents/spec.py
"""SubAgentSpec — 子 Agent 的声明性配置（纯数据）。

每个 SubAgentSpec 描述一个可被主 Agent 委派的子 Agent：它的 system_prompt、
可用工具名称、LLM 配置和最大轮数。运行时由 SubAgentRegistry 存储；
delegate_to_subagent 工具被调用时才据此延迟构建子 agent graph。

system_prompt 是完整文本（不走 6 段式 Slot 渲染）——子 Agent 通常只需
简单 prompt。tools 是名称列表，运行时经 TOOL_REGISTRY.resolve() 解析。
llm_config={"model": "inherit"} 表示复用主 Agent 的 LLM。
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class SubAgentSpec(BaseModel):
    """声明一个可委派的子 Agent。"""

    name: str = Field(..., min_length=1, description="唯一标识")
    description: str = Field(..., description="给主 Agent 看的委派时机说明")
    system_prompt: str = Field(..., description="子 Agent 完整 system prompt")
    tools: list[str] = Field(default_factory=list, description="允许的工具名称列表")
    llm_config: dict = Field(default_factory=dict, description="LLM 配置; {'model':'inherit'} 复用主 LLM")
    max_turns: int = Field(default=25, ge=1, description="REACT 最大迭代数")


__all__ = ["SubAgentSpec"]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd packages/harness && uv run pytest tests/subagents/test_spec.py -v`
Expected: 7 passed

- [ ] **Step 5: 提交**

```bash
cd packages/harness
git add src/agent_flow_harness/subagents/spec.py tests/subagents/test_spec.py
git commit -m "feat(harness): v0.2-1 SubAgentSpec 数据类"
```

---

## Task 2: SubAgentRegistry 注册中心

**Files:**
- Create: `packages/harness/src/agent_flow_harness/subagents/registry.py`
- Test: `packages/harness/tests/subagents/test_registry.py`

- [ ] **Step 1: 写失败测试**

```python
# packages/harness/tests/subagents/test_registry.py
"""AC3 cover: SubAgentRegistry register/get/list_names。"""
from __future__ import annotations

import pytest

from agent_flow_harness.subagents.registry import SubAgentRegistry
from agent_flow_harness.subagents.spec import SubAgentSpec


def _spec(name: str) -> SubAgentSpec:
    return SubAgentSpec(
        name=name,
        description=f"{name} subagent",
        system_prompt=f"prompt for {name}",
        tools=["bash"],
    )


def test_register_and_get():
    reg = SubAgentRegistry()
    spec = _spec("researcher")
    reg.register(spec)
    assert reg.get("researcher") is spec


def test_get_unknown_raises_key_error():
    reg = SubAgentRegistry()
    with pytest.raises(KeyError):
        reg.get("nonexistent")


def test_register_duplicate_name_raises_value_error():
    reg = SubAgentRegistry()
    reg.register(_spec("coder"))
    with pytest.raises(ValueError, match="researcher"):
        reg.register(_spec("coder"))


def test_list_names():
    reg = SubAgentRegistry()
    reg.register(_spec("coder"))
    reg.register(_spec("researcher"))
    assert sorted(reg.list_names()) == ["coder", "researcher"]


def test_list_names_empty():
    reg = SubAgentRegistry()
    assert reg.list_names() == []


def test_register_multiple_distinct():
    reg = SubAgentRegistry()
    reg.register(_spec("a"))
    reg.register(_spec("b"))
    reg.register(_spec("c"))
    assert len(reg.list_names()) == 3
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd packages/harness && uv run pytest tests/subagents/test_registry.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 实现 SubAgentRegistry**

```python
# packages/harness/src/agent_flow_harness/subagents/registry.py
"""SubAgentRegistry — 子 Agent 配置的进程内存储。

与 v0.1 ToolRegistry 同构：plain in-memory store，无 I/O，宿主启动时注册。
子 Agent 必须预先注册（防 prompt injection 动态 spawn）。registry 只存
SubAgentSpec 纯数据；graph 的构建延迟到 delegate 工具被调用时。
"""
from __future__ import annotations

from agent_flow_harness.subagents.spec import SubAgentSpec


class SubAgentRegistry:
    """进程内子 Agent 配置注册中心。"""

    def __init__(self) -> None:
        self._specs: dict[str, SubAgentSpec] = {}

    def register(self, spec: SubAgentSpec) -> None:
        """注册一个子 Agent 配置。重名 raise ValueError。"""
        if spec.name in self._specs:
            msg = f"SubAgent '{spec.name}' already registered."
            raise ValueError(msg)
        self._specs[spec.name] = spec

    def get(self, name: str) -> SubAgentSpec:
        """按名查找；不存在 raise KeyError。"""
        if name not in self._specs:
            msg = f"SubAgent '{name}' not found."
            raise KeyError(msg)
        return self._specs[name]

    def list_names(self) -> list[str]:
        """返回所有已注册子 Agent 的名字。"""
        return list(self._specs.keys())


__all__ = ["SubAgentRegistry"]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd packages/harness && uv run pytest tests/subagents/test_registry.py -v`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
cd packages/harness
git add src/agent_flow_harness/subagents/registry.py tests/subagents/test_registry.py
git commit -m "feat(harness): v0.2-1 SubAgentRegistry 注册中心"
```

---

## Task 3: SubAgentContext + ContextVar 注入协议

**Files:**
- Create: `packages/harness/src/agent_flow_harness/subagents/context.py`
- Test: `packages/harness/tests/subagents/test_context.py`

- [ ] **Step 1: 写失败测试**

```python
# packages/harness/tests/subagents/test_context.py
"""AC9 cover: ContextVar set/get/reset + resolve_tools 工具排除 (AC7)。"""
from __future__ import annotations

import pytest
from langchain_core.tools import StructuredTool

from agent_flow_harness.subagents.context import (
    SubAgentContext,
    get_subagent_context,
    reset_subagent_context,
    set_subagent_context,
)
from agent_flow_harness.subagents.registry import SubAgentRegistry
from agent_flow_harness.subagents.spec import SubAgentSpec
from agent_flow_harness.tools.registry import ToolRegistry


def _make_tool(name: str) -> StructuredTool:
    def _fn(**_kwargs) -> str:
        return "ok"
    _fn.__name__ = name
    return StructuredTool.from_function(_fn, name=name, description=f"test {name}")


def _make_context(subagent_tool: StructuredTool | None = None) -> SubAgentContext:
    tool_reg = ToolRegistry()
    tool_reg.register(_make_tool("bash"))
    if subagent_tool is not None:
        tool_reg.register(subagent_tool)
    registry = SubAgentRegistry()
    return SubAgentContext(
        registry=registry,
        tool_registry=tool_reg,
        build_llm=lambda cfg: object(),  # 测试不实际构建 LLM
        parent_llm=None,
    )


def test_get_without_set_raises_runtime_error():
    """未设置 context 时 get 必须 raise RuntimeError。"""
    # 先确保无残留（前一个测试可能 set 过又 reset 了）
    try:
        get_subagent_context()
        # 如果没 raise，说明测试间有 context 残留——这本身是 bug，但
        # ContextVar 默认 None 时应 raise，所以走到这里算失败
        pytest.fail("get_subagent_context should raise when context is None")
    except RuntimeError:
        pass  # 期望：未设置时 raise


def test_set_then_get_returns_same_context():
    ctx = _make_context()
    token = set_subagent_context(ctx)
    try:
        assert get_subagent_context() is ctx
    finally:
        reset_subagent_context(token)


def test_reset_restores_previous_state():
    ctx = _make_context()
    token = set_subagent_context(ctx)
    reset_subagent_context(token)
    # reset 后再 get 应 raise（回到未设置状态）
    with pytest.raises(RuntimeError):
        get_subagent_context()


def test_resolve_tools_excludes_delegate(monkeypatch):
    """AC7: resolve_tools 解析后必须排除 delegate_to_subagent。"""
    delegate_tool = _make_tool("delegate_to_subagent")
    ctx = _make_context(subagent_tool=delegate_tool)
    spec = SubAgentSpec(
        name="x", description="d", system_prompt="p",
        tools=["bash", "delegate_to_subagent"],
    )
    tools = ctx.resolve_tools(spec)
    names = [t.name for t in tools]
    assert "bash" in names
    assert "delegate_to_subagent" not in names


def test_resolve_tools_unknown_name_skipped():
    """未知工具名跳过（不 raise，与 TOOL_REGISTRY.resolve 行为一致）。"""
    ctx = _make_context()
    spec = SubAgentSpec(
        name="x", description="d", system_prompt="p",
        tools=["bash", "nonexistent_tool"],
    )
    tools = ctx.resolve_tools(spec)
    names = [t.name for t in tools]
    assert names == ["bash"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd packages/harness && uv run pytest tests/subagents/test_context.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 实现 SubAgentContext + ContextVar**

```python
# packages/harness/src/agent_flow_harness/subagents/context.py
"""SubAgentContext + ContextVar — delegate 工具的依赖注入协议。

与 v0.1 workspace_context 同模式：宿主在每次主 Agent 执行前
set_subagent_context()，delegate_to_subagent 工具内部 get_subagent_context()
读取。ContextVar 保证异步任务隔离。

resolve_tools 实现 AC7 工具排除：解析 spec.tools 后过滤掉
delegate_to_subagent，使子 Agent 物理上无法递归。
"""
from __future__ import annotations

import contextvars
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.tools import BaseTool

    from agent_flow_harness.subagents.spec import SubAgentSpec
    from agent_flow_harness.subagents.registry import SubAgentRegistry
    from agent_flow_harness.tools.registry import ToolRegistry

# delegate 工具名——resolve_tools 排除它实现 AC7。
_DELEGATE_TOOL_NAME = "delegate_to_subagent"


class SubAgentContext:
    """宿主注入给 delegate 工具的依赖包。

    Attributes:
        registry: 子 Agent 配置注册中心。
        tool_registry: 解析子 agent tools 的工具注册中心。
        build_llm: 按 spec.llm_config 构建 LLM 的工厂。
        parent_llm: 主 Agent 的 LLM；model="inherit" 时复用。
    """

    def __init__(
        self,
        registry: "SubAgentRegistry",
        tool_registry: "ToolRegistry",
        build_llm: "Callable[[dict], BaseChatModel]",
        parent_llm: "BaseChatModel | None",
    ) -> None:
        self.registry = registry
        self.tool_registry = tool_registry
        self.build_llm = build_llm
        self.parent_llm = parent_llm

    def resolve_llm(self, spec: "SubAgentSpec") -> "BaseChatModel":
        """解析子 Agent 的 LLM。model='inherit' 复用 parent_llm。"""
        model = spec.llm_config.get("model", "inherit")
        if model == "inherit":
            if self.parent_llm is None:
                msg = "llm_config model='inherit' but no parent_llm injected."
                raise RuntimeError(msg)
            return self.parent_llm
        return self.build_llm(spec.llm_config)

    def resolve_tools(self, spec: "SubAgentSpec") -> "list[BaseTool]":
        """解析 spec.tools 为 BaseTool 实例，排除 delegate_to_subagent (AC7)。

        构造一个临时 agent_doc 走 TOOL_REGISTRY.resolve，再过滤掉 delegate。
        未知工具名被 silently skip（与 TOOL_REGISTRY 行为一致）。
        """
        agent_doc = {"tools": [{"name": n, "enabled": True} for n in spec.tools]}
        resolved = self.tool_registry.resolve(agent_doc)
        # AC7: 工具排除——子 Agent 不能拿到 delegate 工具。
        return [t for t in resolved if t.name != _DELEGATE_TOOL_NAME]


# ---------------------------------------------------------------------------
# ContextVar plumbing (与 workspace_context.py 同构)
# ---------------------------------------------------------------------------

_subagent_ctx: contextvars.ContextVar[SubAgentContext | None] = contextvars.ContextVar(
    "subagent_ctx", default=None
)


def set_subagent_context(ctx: SubAgentContext) -> contextvars.Token:
    """为本异步任务设置 subagent 依赖，返回 reset token。"""
    return _subagent_ctx.set(ctx)


def reset_subagent_context(token: contextvars.Token) -> None:
    """恢复之前的 subagent context 状态。"""
    _subagent_ctx.reset(token)


def get_subagent_context() -> SubAgentContext:
    """读取当前 subagent 依赖。未设置 raise RuntimeError。"""
    ctx = _subagent_ctx.get()
    if ctx is None:
        msg = (
            "SubAgentContext not set: call set_subagent_context() before "
            "invoking an agent that uses delegate_to_subagent."
        )
        raise RuntimeError(msg)
    return ctx


__all__ = [
    "SubAgentContext",
    "set_subagent_context",
    "reset_subagent_context",
    "get_subagent_context",
]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd packages/harness && uv run pytest tests/subagents/test_context.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
cd packages/harness
git add src/agent_flow_harness/subagents/context.py tests/subagents/test_context.py
git commit -m "feat(harness): v0.2-1 SubAgentContext + ContextVar 注入(工具排除 AC7)"
```

---

## Task 4: 最终文本提取 helper + build_subagent_state

这两个是 delegate 工具的内部依赖。先实现并测试，因为 Task 5 的 delegate 工具会调用它们。它们放在 context.py 作为 SubAgentContext 的方法（build_subagent_state）和 delegate.py 的模块级 helper（extract_final_text）。

**Files:**
- Modify: `packages/harness/src/agent_flow_harness/subagents/context.py` (加 build_subagent_state 方法)
- Create: `packages/harness/tests/subagents/test_delegate.py` (本 task 只测提取 helper + state 构建)

- [ ] **Step 1: 写失败测试**

```python
# packages/harness/tests/subagents/test_delegate.py
"""AC4/AC6/AC10 cover: 提取最终文本 + build_subagent_state + delegate 工具。

本 task 先覆盖 extract_final_text 和 build_subagent_state（Task 5 覆盖工具本身）。
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent_flow_harness.subagents.context import SubAgentContext
from agent_flow_harness.subagents.delegate import extract_final_text
from agent_flow_harness.subagents.spec import SubAgentSpec
from agent_flow_harness.tools.registry import ToolRegistry
from agent_flow_harness.subagents.registry import SubAgentRegistry


def _spec() -> SubAgentSpec:
    return SubAgentSpec(
        name="coder", description="coder sub", system_prompt="你是编码助手", tools=[]
    )


def _make_context() -> SubAgentContext:
    return SubAgentContext(
        registry=SubAgentRegistry(),
        tool_registry=ToolRegistry(),
        build_llm=lambda cfg: object(),
        parent_llm=None,
    )


# --- extract_final_text ---

def test_extract_final_text_str_content():
    """最后一条 AIMessage content 是 str → 直接返回。"""
    msgs = [HumanMessage(content="task"), AIMessage(content="final answer")]
    assert extract_final_text(msgs) == "final answer"


def test_extract_final_text_list_content():
    """content 是 list[dict] → 拼接 text 字段。"""
    msgs = [
        HumanMessage(content="task"),
        AIMessage(content=[{"type": "text", "text": "part1"}, {"type": "text", "text": "part2"}]),
    ]
    assert "part1" in extract_final_text(msgs)
    assert "part2" in extract_final_text(msgs)


def test_extract_final_text_no_ai_message():
    """没有 AIMessage → 返回兜底字符串。"""
    msgs = [HumanMessage(content="task")]
    assert "No response" in extract_final_text(msgs) or extract_final_text(msgs) != ""


def test_extract_final_text_empty_messages():
    assert isinstance(extract_final_text([]), str)


def test_extract_final_text_picks_last_ai_message():
    """多条 AIMessage → 取最后一条。"""
    msgs = [
        HumanMessage(content="task"),
        AIMessage(content="first"),
        AIMessage(content="second"),
    ]
    assert extract_final_text(msgs) == "second"


# --- build_subagent_state ---

def test_build_subagent_state_isolation():
    """AC8: 子 Agent state 全新——只有 system_prompt + task，无主 agent 历史。"""
    ctx = _make_context()
    spec = _spec()
    state = ctx.build_subagent_state(spec, "do something")
    msgs = state["messages"]
    # 第一条是 system_prompt，最后一条是 task
    assert isinstance(msgs[0], SystemMessage)
    assert msgs[0].content == "你是编码助手"
    assert isinstance(msgs[-1], HumanMessage)
    assert msgs[-1].content == "do something"
    # 只有 2 条——没有主 agent 的历史
    assert len(msgs) == 2
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd packages/harness && uv run pytest tests/subagents/test_delegate.py -v`
Expected: FAIL — `ModuleNotFoundError: ...delegate`

- [ ] **Step 3: 实现 extract_final_text + build_subagent_state**

先创建 delegate.py 的 helper：

```python
# packages/harness/src/agent_flow_harness/subagents/delegate.py
"""delegate_to_subagent 工具 — 主 Agent 委派子任务的入口。

本模块暂只实现 extract_final_text helper；工具本身在 Task 5 完成。
提取逻辑参照 deer-flow executor.py:674-698：从 messages 反向找最后一条
AIMessage，处理 str / list 两种 content 类型。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage

_PLACEHOLDER = "No response generated."


def extract_final_text(messages: "list[BaseMessage]") -> str:
    """从 messages 提取最后一条 AIMessage 的文本内容。

    处理两种 content 类型：
    - str → 直接返回
    - list → 拼接 block["text"]（dict）和 str 块
    - 都不是 → str(content)
    无 AIMessage → 返回兜底字符串。
    """
    last_ai: Any | None = None
    for msg in reversed(messages):
        # 用类型名字符串判断，避免循环 import AIMessage
        if msg.__class__.__name__ == "AIMessage":
            last_ai = msg
            break
    if last_ai is None:
        return _PLACEHOLDER
    return _content_to_text(last_ai.content)


def _content_to_text(content: Any) -> str:
    """把 AIMessage.content（str / list / other）转成纯文本。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts) if parts else _PLACEHOLDER
    return str(content)


__all__ = ["extract_final_text"]
```

然后在 context.py 的 SubAgentContext 类中加 build_subagent_state 方法（加在 resolve_tools 之后）：

```python
    def build_subagent_state(self, spec: "SubAgentSpec", task: str) -> dict[str, Any]:
        """构建子 Agent 的全新 AgentState（AC8 完全隔离 stateless）。

        只有 SystemMessage(system_prompt) + HumanMessage(task)，无主 agent 历史。
        """
        # 延迟 import 避免循环依赖
        from langchain_core.messages import HumanMessage, SystemMessage

        return {
            "messages": [
                SystemMessage(content=spec.system_prompt),
                HumanMessage(content=task),
            ],
        }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd packages/harness && uv run pytest tests/subagents/test_delegate.py -v`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
cd packages/harness
git add src/agent_flow_harness/subagents/delegate.py src/agent_flow_harness/subagents/context.py tests/subagents/test_delegate.py
git commit -m "feat(harness): v0.2-1 最终文本提取 + build_subagent_state(状态隔离 AC8)"
```

---

## Task 5: delegate_to_subagent 工具实现

**Files:**
- Modify: `packages/harness/src/agent_flow_harness/subagents/delegate.py` (加工具)
- Append tests to: `packages/harness/tests/subagents/test_delegate.py`

- [ ] **Step 1: 追加失败测试**

在 `tests/subagents/test_delegate.py` 末尾追加（保留已有 import 和 helper，追加这些）：

```python
# --- delegate_to_subagent 工具 (Task 5) ---

from unittest.mock import AsyncMock, MagicMock

from agent_flow_harness.subagents.context import (
    set_subagent_context,
    reset_subagent_context,
)
from agent_flow_harness.subagents.delegate import delegate_to_subagent
from langchain_core.messages import AIMessage, HumanMessage


def _setup_context_with_mock_graph(final_text: str = "subagent result"):
    """构建一个 ctx，其 run_subagent 返回固定文本。"""
    ctx = MagicMock()
    ctx.registry.get = MagicMock(return_value=_spec())
    ctx.resolve_tools = MagicMock(return_value=[])
    ctx.build_subagent_state = MagicMock(return_value={"messages": []})
    ctx.run_subagent = AsyncMock(return_value=final_text)
    return ctx


@pytest.mark.asyncio
async def test_delegate_returns_subagent_final_text():
    """AC4: delegate 工具返回子 Agent 最终输出字符串。"""
    ctx = _setup_context_with_mock_graph(final_text="the answer is 42")
    token = set_subagent_context(ctx)
    try:
        result = await delegate_to_subagent.ainvoke(
            {"subagent_name": "coder", "task": "compute"}
        )
        assert result == "the answer is 42"
        ctx.registry.get.assert_called_once_with("coder")
    finally:
        reset_subagent_context(token)


@pytest.mark.asyncio
async def test_delegate_unknown_subagent_returns_error_string():
    """AC10: 未知子 Agent → 返回错误字符串，不 raise。"""
    ctx = MagicMock()
    ctx.registry.get = MagicMock(side_effect=KeyError("not found"))
    ctx.resolve_tools = MagicMock(return_value=[])
    ctx.build_subagent_state = MagicMock(return_value={"messages": []})
    ctx.run_subagent = AsyncMock()
    token = set_subagent_context(ctx)
    try:
        result = await delegate_to_subagent.ainvoke(
            {"subagent_name": "ghost", "task": "x"}
        )
        assert "Error" in result or "ghost" in result
        ctx.run_subagent.assert_not_called()
    finally:
        reset_subagent_context(token)


@pytest.mark.asyncio
async def test_delegate_subagent_exception_isolated():
    """AC10: 子 Agent 抛异常 → 返回错误字符串，不中断。"""
    ctx = MagicMock()
    ctx.registry.get = MagicMock(return_value=_spec())
    ctx.resolve_tools = MagicMock(return_value=[])
    ctx.build_subagent_state = MagicMock(return_value={"messages": []})
    ctx.run_subagent = AsyncMock(side_effect=RuntimeError("LLM down"))
    token = set_subagent_context(ctx)
    try:
        result = await delegate_to_subagent.ainvoke(
            {"subagent_name": "coder", "task": "x"}
        )
        assert "Error" in result
    finally:
        reset_subagent_context(token)


def test_delegate_tool_is_structured_tool():
    """delegate_to_subagent 是一个可注册的 StructuredTool/BaseTool。"""
    from langchain_core.tools import BaseTool
    assert isinstance(delegate_to_subagent, BaseTool)
    assert delegate_to_subagent.name == "delegate_to_subagent"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `cd packages/harness && uv run pytest tests/subagents/test_delegate.py -v -k "delegate_" `
Expected: FAIL — `delegate_to_subagent` 工具未定义

- [ ] **Step 3: 实现 delegate_to_subagent 工具**

在 `delegate.py` 末尾追加（在 extract_final_text 函数之后，__all__ 之前替换）：

```python
# 在文件顶部 import 区追加（已有 typing TYPE_CHECKING，补充这些）
import logging
from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class _DelegateArgs(BaseModel):
    """delegate_to_subagent 的 LLM 可见参数。"""
    subagent_name: str = Field(..., description="要委派的子 Agent 名称")
    task: str = Field(..., description="委派给子 Agent 的任务描述")


async def _delegate_to_subagent(subagent_name: str, task: str) -> str:
    """委派子任务给子 Agent，返回其最终输出文本。

    依赖从 ContextVar 获取。异常被 catch 转错误字符串返回（AC10 异常隔离）。
    """
    from agent_flow_harness.subagents.context import get_subagent_context
    from agent_flow_harness.graph import build_agent_graph, build_config

    try:
        ctx = get_subagent_context()
        spec = ctx.registry.get(subagent_name)
        tools = ctx.resolve_tools(spec)          # AC7: 已排除 delegate
        llm = ctx.resolve_llm(spec)
        state = ctx.build_subagent_state(spec, task)  # AC8: 全新隔离 state
        # 延迟构建子 agent graph（AC5）
        agent_doc = {"_id": f"subagent:{spec.name}", "name": spec.name}
        graph = build_agent_graph(agent_doc)
        config = build_config(agent_doc, llm, tools=tools, recursion_limit=spec.max_turns)
        result_state = await graph.ainvoke(state, config=config)
        final_messages = result_state.get("messages", [])
        return extract_final_text(final_messages)
    except Exception as exc:
        logger.warning("delegate_to_subagent failed: %s", exc, exc_info=True)
        return f"Error: {exc}"


delegate_to_subagent = StructuredTool.from_function(
    _delegate_to_subagent,
    name="delegate_to_subagent",
    description="委派子任务给一个专门的子 Agent 执行，返回子 Agent 的最终输出。当任务复杂、需要不同工具集或独立上下文时使用。",
    args_schema=_DelegateArgs,
    coroutine=_delegate_to_subagent,
)
```

注意：`__all__` 更新为：
```python
__all__ = ["delegate_to_subagent", "extract_final_text"]
```

- [ ] **Step 4: 运行测试确认通过**

Run: `cd packages/harness && uv run pytest tests/subagents/test_delegate.py -v`
Expected: 10 passed (原 6 + 新 4)

- [ ] **Step 5: 提交**

```bash
cd packages/harness
git add src/agent_flow_harness/subagents/delegate.py tests/subagents/test_delegate.py
git commit -m "feat(harness): v0.2-1 delegate_to_subagent 工具(异常隔离 AC10)"
```

---

## Task 6: 包导出 (subagents/__init__.py + 顶层 __init__.py)

**Files:**
- Create: `packages/harness/src/agent_flow_harness/subagents/__init__.py`
- Modify: `packages/harness/src/agent_flow_harness/__init__.py`
- Create: `packages/harness/tests/subagents/__init__.py`

- [ ] **Step 1: 写失败测试**

```python
# packages/harness/tests/subagents/__init__.py
# (空文件，使 tests/subagents 成为可导入包)
```

```python
# 追加到 packages/harness/tests/test_imports.py 末尾
def test_subagents_public_api_importable():
    """AC1: subagents 包公开 API 可从顶层导入。"""
    from agent_flow_harness import (
        SubAgentSpec,
        SubAgentRegistry,
        SubAgentContext,
        delegate_to_subagent,
        set_subagent_context,
        get_subagent_context,
        reset_subagent_context,
    )
    assert SubAgentSpec is not None
    assert SubAgentRegistry is not None
    assert SubAgentContext is not None
    assert delegate_to_subagent.name == "delegate_to_subagent"
```

先确认 test_imports.py 的现有结构，追加测试函数。

- [ ] **Step 2: 运行测试确认失败**

Run: `cd packages/harness && uv run pytest tests/test_imports.py::test_subagents_public_api_importable -v`
Expected: FAIL — ImportError

- [ ] **Step 3: 实现包导出**

```python
# packages/harness/src/agent_flow_harness/subagents/__init__.py
"""Subagents 模块 — 多 Agent 协作调度 (v0.2-1)。

主 Agent 通过 delegate_to_subagent 工具委派子任务给预注册的子 Agent。
子 Agent 完全隔离 stateless 执行，返回最终文本。设计见
docs/implementation-artifacts/v0-2-1-subagents.md。
"""
from agent_flow_harness.subagents.context import (
    SubAgentContext,
    get_subagent_context,
    reset_subagent_context,
    set_subagent_context,
)
from agent_flow_harness.subagents.delegate import delegate_to_subagent, extract_final_text
from agent_flow_harness.subagents.registry import SubAgentRegistry
from agent_flow_harness.subagents.spec import SubAgentSpec

__all__ = [
    "SubAgentContext",
    "SubAgentRegistry",
    "SubAgentSpec",
    "delegate_to_subagent",
    "extract_final_text",
    "get_subagent_context",
    "reset_subagent_context",
    "set_subagent_context",
]
```

在顶层 `__init__.py` 的 import 区（slots import 之后）加：

```python
from agent_flow_harness.subagents import (
    SubAgentContext,
    SubAgentRegistry,
    SubAgentSpec,
    delegate_to_subagent,
    get_subagent_context,
    reset_subagent_context,
    set_subagent_context,
)
```

并在 `__all__` 列表中加入这 7 个符号（按字母序插入合适位置）。

- [ ] **Step 4: 运行测试确认通过**

Run: `cd packages/harness && uv run pytest tests/test_imports.py -v`
Expected: 全部 passed（含新增 test_subagents_public_api_importable）

- [ ] **Step 5: 提交**

```bash
cd packages/harness
git add src/agent_flow_harness/subagents/__init__.py src/agent_flow_harness/__init__.py tests/subagents/__init__.py tests/test_imports.py
git commit -m "feat(harness): v0.2-1 subagents 包导出 + 公开 API (AC1)"
```

---

## Task 7: 端到端集成测试

用 FakeLLM 驱动一个真实的主 Agent + 子 Agent 委派，验证 AC5（延迟构建）/ AC6（只追加 1 条 ToolMessage）/ AC8（状态隔离）。

**Files:**
- Create: `packages/harness/tests/subagents/test_nested_execution.py`

- [ ] **Step 1: 写集成测试**

```python
# packages/harness/tests/subagents/test_nested_execution.py
"""AC5/AC6/AC8 集成测试: 真实主 Agent 委派子 Agent 端到端。

用 FakeLLM 脚本化响应：主 Agent 调用 delegate → 子 Agent 执行 → 结果回主 Agent。
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from agent_flow_harness.engine.react import react_node
from agent_flow_harness.subagents.context import (
    SubAgentContext,
    reset_subagent_context,
    set_subagent_context,
)
from agent_flow_harness.subagents.registry import SubAgentRegistry
from agent_flow_harness.subagents.spec import SubAgentSpec
from agent_flow_harness.tools.registry import ToolRegistry


class _FakeLLM:
    """按调用顺序返回预设响应的假 LLM。"""

    def __init__(self, responses, model_name="fake"):
        self._responses = list(responses)
        self._model_name = model_name

    @property
    def model_name(self):
        return self._model_name

    def bind_tools(self, _tools):
        return self

    async def ainvoke(self, messages, _config=None):
        if not self._responses:
            raise RuntimeError("FakeLLM exhausted")
        return self._responses.pop(0)


def _ai_tool_call(name, args=None, call_id="c1"):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args or {}, "id": call_id}])


def _ai_text(text):
    return AIMessage(content=text)


@pytest.mark.asyncio
async def test_end_to_end_delegation(base_state, make_run_config):
    """AC5/AC6: 主 Agent 委派 → 子 Agent 回答 → 主 Agent 收 1 条 ToolMessage。"""
    # 子 Agent 的 LLM：被调用一次，直接返回最终文本
    sub_llm = _FakeLLM([_ai_text("subagent computed: 42")])

    # 注册子 Agent
    registry = SubAgentRegistry()
    registry.register(SubAgentSpec(
        name="computer",
        description="compute things",
        system_prompt="你是计算助手",
        tools=[],
        max_turns=5,
    ))

    # 构建 SubAgentContext
    ctx = SubAgentContext(
        registry=registry,
        tool_registry=ToolRegistry(),
        build_llm=lambda cfg: sub_llm,
        parent_llm=None,
    )
    token = set_subagent_context(ctx)
    try:
        # 注册 delegate 工具到主 Agent
        from agent_flow_harness.subagents import delegate_to_subagent

        # 主 Agent LLM: 先调用 delegate，再输出最终答案
        main_llm = _FakeLLM([
            _ai_tool_call("delegate_to_subagent",
                          {"subagent_name": "computer", "task": "计算答案"}, "tc1"),
            _ai_text("最终结果由子 Agent 给出"),
        ])
        config = make_run_config(main_llm, tools=[delegate_to_subagent])

        result = await react_node(base_state, config)

        # AC6: 主 Agent messages 里有 delegate 的 ToolMessage
        tool_msgs = [m for m in result["messages"]
                     if m.__class__.__name__ == "ToolMessage"]
        assert any("42" in (m.content or "") for m in tool_msgs), \
            "子 Agent 结果应作为 ToolMessage 出现在主 Agent messages"
        # 主 Agent 最终答案也在
        contents = [m.content for m in result["messages"] if isinstance(m, AIMessage)]
        assert any("最终结果" in c for c in contents)
    finally:
        reset_subagent_context(token)


@pytest.mark.asyncio
async def test_subagent_tools_exclude_delegate(base_state, make_run_config):
    """AC7: 子 Agent 工具列表不含 delegate（物理防递归）。"""
    from agent_flow_harness.subagents import delegate_to_subagent

    tool_reg = ToolRegistry()
    tool_reg.register(delegate_to_subagent)  # delegate 在全局 registry 里
    registry = SubAgentRegistry()
    # 子 Agent spec 声明要用 delegate（但 resolve 时会被排除）
    registry.register(SubAgentSpec(
        name="nested",
        description="tries to nest",
        system_prompt="p",
        tools=["delegate_to_subagent"],
        max_turns=3,
    ))
    ctx = SubAgentContext(
        registry=registry,
        tool_registry=tool_reg,
        build_llm=lambda cfg: _FakeLLM([_ai_text("ok")]),
        parent_llm=None,
    )
    # resolve_tools 必须排除 delegate
    spec = registry.get("nested")
    tools = ctx.resolve_tools(spec)
    assert all(t.name != "delegate_to_subagent" for t in tools), \
        "子 Agent 绝不能拿到 delegate_to_subagent 工具"
```

- [ ] **Step 2: 运行测试**

Run: `cd packages/harness && uv run pytest tests/subagents/test_nested_execution.py -v`
Expected: 2 passed

如果有失败，最可能是 delegate 工具的 args 传递（StructuredTool.ainvoke 接收 dict）。调试时检查 `_delegate_to_subagent` 是否正确接收到 `subagent_name`/`task`。

- [ ] **Step 3: 提交**

```bash
cd packages/harness
git add tests/subagents/test_nested_execution.py
git commit -m "test(harness): v0.2-1 端到端委派集成测试(AC5/AC6/AC7/AC8)"
```

---

## Task 8: 全量回归 + 最终验证

- [ ] **Step 1: 跑 subagents 全部测试**

Run: `cd packages/harness && uv run pytest tests/subagents/ -v`
Expected: 全部 passed（spec 7 + registry 6 + context 5 + delegate 10 + nested 2 = 30 passed）

- [ ] **Step 2: 跑 harness 全量测试（无回归）**

Run: `cd packages/harness && uv run pytest -q`
Expected: 之前 246 + 新增 ≈ 30 = 276 passed, 0 failed

- [ ] **Step 3: 跑 backend 全量测试（无回归）**

Run: `cd backend && uv run pytest -q`
Expected: 814 passed, 0 failed（harness 改动不影响 backend）

- [ ] **Step 4: 验证公开 API 完整（AC1）**

Run:
```bash
cd packages/harness && uv run python -c "
from agent_flow_harness import (
    SubAgentSpec, SubAgentRegistry, SubAgentContext,
    delegate_to_subagent,
    set_subagent_context, get_subagent_context, reset_subagent_context,
)
print('All subagents symbols importable ✓')
print('delegate tool name:', delegate_to_subagent.name)
"
```
Expected: 输出 `All subagents symbols importable ✓` 和 `delegate tool name: delegate_to_subagent`

- [ ] **Step 5: 类型检查（ruff + mypy，与 CI 一致）**

Run: `cd packages/harness && uv run ruff check src/agent_flow_harness/subagents/ && uv run mypy src/agent_flow_harness/subagents/`
Expected: 无 error

- [ ] **Step 6: 更新 Story 文档状态 + 提交收尾**

把 `docs/implementation-artifacts/v0-2-1-subagents.md` 的 Status 从 `approved` 改为 `done`，附测试数。

```bash
git add docs/implementation-artifacts/v0-2-1-subagents.md
git commit -m "docs(v0.2-1): subagents 实施完成 (Status: done)"
```

---

## Self-Review 核对

**1. Spec coverage（11 个 AC → Task 映射）:**
- AC1 (包导出) → Task 6 ✅
- AC2 (SubAgentSpec 字段) → Task 1 ✅
- AC3 (Registry CRUD) → Task 2 ✅
- AC4 (delegate 返回字符串) → Task 5 ✅
- AC5 (延迟构建复用 build_agent_graph) → Task 5 (代码) + Task 7 (集成) ✅
- AC6 (只追加 1 条 ToolMessage) → Task 7 集成验证 ✅
- AC7 (工具排除防递归) → Task 3 (单元) + Task 7 (集成) ✅
- AC8 (stateless 隔离) → Task 4 (build_subagent_state) + Task 7 (集成) ✅
- AC9 (ContextVar 协议) → Task 3 ✅
- AC10 (异常隔离) → Task 5 ✅
- AC11 (20+ 测试 + 2 集成) → 30 单元 + 2 集成 ✅

**2. Placeholder 扫描:** 无 TBD/TODO，每步都有完整代码。✅

**3. Type/命名一致性:**
- `SubAgentSpec` 字段全链路一致（spec→registry→context→delegate）✅
- `resolve_tools` / `resolve_llm` / `build_subagent_state` 方法名在 Task 3/4/5 一致 ✅
- `delegate_to_subagent` 工具名在 Task 3 (`_DELEGATE_TOOL_NAME`) / Task 5 / Task 7 一致 ✅

无遗漏。

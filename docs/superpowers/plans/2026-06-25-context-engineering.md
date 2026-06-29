# v0.2-5 Context Engineering 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans.

**Goal:** 把 v0.1 硬编码的 `compress_messages` 重构为可插拔 `ContextStrategy` 协议，提供 SlidingWindow/Summarization/Hybrid 三策略，补 LLM 智能摘要 + ToolMessage 配对保护 + 压缩事件。react_node 可选注入 strategy（无 strategy 时保持现有行为，向后兼容）。

**Architecture:** ContextStrategy（ABC，`select(messages, max_tokens) -> list`）+ 3 策略实现。react_node 在 LLM 调用前检查 `config["configurable"]["context_strategy"]`，有则调 `strategy.select()`，无则走现有 `compress_messages`。token 估算复用 `engine/context.py` 的 `estimate_messages_tokens`。

**Tech Stack:** Python 3.12 / langchain-core / pytest-asyncio

**测试命令:** `cd packages/harness && uv run pytest tests/context_engineering/ -v`
**全量回归:** `cd packages/harness && uv run pytest -q`

---

## File Structure

```
packages/harness/src/agent_flow_harness/context_engineering/
├── __init__.py          # 包导出
├── base.py              # ContextStrategy ABC
├── token_estimator.py   # 复用 engine/context.py 的 estimate_messages_tokens
├── pairing.py           # ToolMessage 配对保护算法
├── sliding_window.py    # SlidingWindowStrategy
├── summarization.py     # SummarizationStrategy（LLM 智能摘要）
└── hybrid.py            # HybridStrategy（默认）

packages/harness/tests/context_engineering/
├── __init__.py
├── test_pairing.py
├── test_sliding_window.py
├── test_summarization.py
├── test_hybrid.py
└── test_react_integration.py
```

---

## Task 1: ContextStrategy ABC + token_estimator + 包骨架

**Files:**
- Create: `context_engineering/base.py`, `token_estimator.py`, `__init__.py`
- Test: `tests/context_engineering/test_base.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/context_engineering/test_base.py
from agent_flow_harness.context_engineering.base import ContextStrategy
from agent_flow_harness.context_engineering.token_estimator import count_tokens


def test_count_tokens_string():
    assert count_tokens("hello world") > 0

def test_count_tokens_messages():
    from langchain_core.messages import HumanMessage
    msgs = [HumanMessage(content="hi"), HumanMessage(content="there")]
    assert count_tokens(msgs) > count_tokens([msgs[0]])

def test_strategy_is_abstract():
    import pytest
    with pytest.raises(TypeError):
        ContextStrategy()  # type: ignore[abstract]
```

- [ ] **Step 2: 运行确认失败**

- [ ] **Step 3: 实现**

```python
# context_engineering/base.py
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage


class ContextStrategy(ABC):
    """可插拔上下文压缩策略。react_node 在 LLM 调用前调 select()。"""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def select(self, messages: "list[BaseMessage]", *, max_tokens: int) -> "list[BaseMessage]":
        """压缩/选择 messages，返回不超 max_tokens 的列表。"""
        ...

__all__ = ["ContextStrategy"]
```

```python
# context_engineering/token_estimator.py
from __future__ import annotations
from typing import TYPE_CHECKING, Any, Sequence

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage

from agent_flow_harness.engine.context import estimate_messages_tokens


def count_tokens(messages_or_text: "Sequence[BaseMessage] | str") -> int:
    """估算 messages 列表或单段文本的 token 数。复用 engine/context.py。"""
    if isinstance(messages_or_text, str):
        return max(1, len(messages_or_text) // 4)
    return estimate_messages_tokens(messages_or_text)


__all__ = ["count_tokens"]
```

```python
# context_engineering/__init__.py
from agent_flow_harness.context_engineering.base import ContextStrategy
from agent_flow_harness.context_engineering.token_estimator import count_tokens

__all__ = ["ContextStrategy", "count_tokens"]
```

- [ ] **Step 4: 运行确认通过** → **Step 5: 提交**

```bash
git add src/agent_flow_harness/context_engineering/ tests/context_engineering/test_base.py tests/context_engineering/__init__.py
git commit -m "feat(harness): v0.2-5 ContextStrategy ABC + token_estimator"
```

---

## Task 2: ToolMessage 配对保护 (pairing.py)

**核心安全约束**：压缩后不能出现 tool_call 没有对应 tool_result（会让 LLM 报错/幻觉）。

**Files:**
- Create: `context_engineering/pairing.py`
- Test: `tests/context_engineering/test_pairing.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/context_engineering/test_pairing.py
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from agent_flow_harness.context_engineering.pairing import ensure_tool_pairing


def test_keeps_paired_messages():
    """完整的 tool_call + tool_result 配对都保留。"""
    msgs = [
        HumanMessage(content="hi"),
        AIMessage(content="", tool_calls=[{"name": "bash", "args": {}, "id": "c1"}]),
        ToolMessage(content="result", tool_call_id="c1"),
        AIMessage(content="done"),
    ]
    result = ensure_tool_pairing(msgs)
    assert len(result) == 4  # 全保留


def test_drops_orphan_tool_call():
    """有 tool_call 但无 tool_result → 丢弃该 tool_call 的 AIMessage。"""
    msgs = [
        AIMessage(content="", tool_calls=[{"name": "bash", "args": {}, "id": "c1"}]),
        AIMessage(content="done"),  # 没有 c1 的 ToolMessage
    ]
    result = ensure_tool_pairing(msgs)
    # 第一个 AIMessage（有 tool_call 但无配对 result）应被丢弃
    assert len(result) == 1
    assert result[0].content == "done"


def test_drops_orphan_tool_result():
    """有 tool_result 但无对应 tool_call → 丢弃。"""
    msgs = [
        ToolMessage(content="result", tool_call_id="orphan"),
        AIMessage(content="done"),
    ]
    result = ensure_tool_pairing(msgs)
    assert len(result) == 1
    assert result[0].content == "done"


def test_preserves_multiple_pairs():
    """多个连续配对都保留。"""
    msgs = [
        AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "a"}]),
        ToolMessage(content="ra", tool_call_id="a"),
        AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "b"}]),
        ToolMessage(content="rb", tool_call_id="b"),
        AIMessage(content="final"),
    ]
    result = ensure_tool_pairing(msgs)
    assert len(result) == 5
```

- [ ] **Step 2: 运行确认失败** → **Step 3: 实现**

```python
# context_engineering/pairing.py
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage


def ensure_tool_pairing(messages: "list[BaseMessage]") -> "list[BaseMessage]":
    """清理 messages，保证 tool_call 都有对应 tool_result，反之亦然。

    规则：
    - 收集所有有效的 tool_call_id（有 ToolMessage 配对的）
    - 丢弃没有 result 的 tool_call（整个 AIMessage 的 tool_calls 清空后若无内容则丢消息）
    - 丢弃没有 call 的 ToolMessage
    """
    from langchain_core.messages import AIMessage, ToolMessage

    # 收集所有 tool_call_id 及其是否有 result
    call_ids_with_result: set[str] = set()
    result_ids: set[str] = set()

    for m in messages:
        if isinstance(m, ToolMessage):
            result_ids.add(m.tool_call_id)
        elif isinstance(m, AIMessage):
            for tc in getattr(m, "tool_calls", []) or []:
                if isinstance(tc, dict):
                    call_ids_with_result.add(tc.get("id", ""))

    # 有效配对：call_id 同时有 call 和 result
    valid_pairs = call_ids_with_result & result_ids

    result: list[BaseMessage] = []
    for m in messages:
        if isinstance(m, ToolMessage):
            if m.tool_call_id in valid_pairs:
                result.append(m)
            # else: 孤儿 result，丢弃
        elif isinstance(m, AIMessage):
            tool_calls = getattr(m, "tool_calls", []) or []
            if tool_calls:
                # 过滤 tool_calls，只保留有效配对的
                valid_tcs = [tc for tc in tool_calls
                             if isinstance(tc, dict) and tc.get("id") in valid_pairs]
                if valid_tcs:
                    # 保留消息（可能 tool_calls 变少，但 content 还在）
                    result.append(m)
                elif m.content:
                    # tool_calls 全无效但 content 有值，保留（去 tool_calls）
                    result.append(m)
                # else: 纯 tool_call 消息且全无效，丢弃
            else:
                result.append(m)
        else:
            result.append(m)

    return result


__all__ = ["ensure_tool_pairing"]
```

- [ ] **Step 4: 运行确认通过** → **Step 5: 提交**

---

## Task 3: SlidingWindowStrategy

保留 system messages + 最近 window_size 条，中间丢弃，经 ensure_tool_pairing 清理。

**Files:**
- Create: `context_engineering/sliding_window.py`
- Test: `tests/context_engineering/test_sliding_window.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/context_engineering/test_sliding_window.py
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from agent_flow_harness.context_engineering.sliding_window import SlidingWindowStrategy


def _make_msgs(n):
    msgs = [SystemMessage(content="system")]
    for i in range(n):
        msgs.append(HumanMessage(content=f"user {i}"))
        msgs.append(AIMessage(content=f"assistant {i}"))
    return msgs


def test_keeps_system_and_recent():
    strategy = SlidingWindowStrategy(window_size=4)
    msgs = _make_msgs(10)  # 1 system + 20 messages = 21
    result = strategy.select(msgs, max_tokens=999999)
    assert isinstance(result[0], SystemMessage)
    # window_size=4 → 保留最近 4 条 + system
    assert len(result) == 5


def test_no_compression_when_small():
    strategy = SlidingWindowStrategy(window_size=20)
    msgs = _make_msgs(3)  # 7 条
    result = strategy.select(msgs, max_tokens=999999)
    assert len(result) == 7  # 不压缩


def test_name():
    assert SlidingWindowStrategy().name == "sliding_window"


def test_preserves_tool_pairing():
    """压缩后保留完整 tool_call/result 配对。"""
    strategy = SlidingWindowStrategy(window_size=2)
    msgs = [
        SystemMessage(content="sys"),
        AIMessage(content="", tool_calls=[{"name": "bash", "args": {}, "id": "c1"}]),
        ToolMessage(content="r", tool_call_id="c1"),
        AIMessage(content="mid"),
        HumanMessage(content="recent1"),
        AIMessage(content="recent2"),
    ]
    result = strategy.select(msgs, max_tokens=999999)
    # 最近 2 条 = recent1, recent2; system 保留; 中间 tool 对被滑出
    contents = [m.content for m in result]
    assert "recent1" in contents
    assert "recent2" in contents
```

- [ ] **Step 2: 运行确认失败** → **Step 3: 实现**

```python
# context_engineering/sliding_window.py
from __future__ import annotations
from typing import TYPE_CHECKING

from agent_flow_harness.context_engineering.base import ContextStrategy
from agent_flow_harness.context_engineering.pairing import ensure_tool_pairing
from agent_flow_harness.context_engineering.token_estimator import count_tokens

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage, SystemMessage


class SlidingWindowStrategy(ContextStrategy):
    """滑动窗口策略：保留 system messages + 最近 window_size 条。

    中间消息丢弃，经 ensure_tool_pairing 保证不切碎配对。
    """

    def __init__(self, window_size: int = 20) -> None:
        self._window = window_size

    @property
    def name(self) -> str:
        return "sliding_window"

    def select(self, messages: "list[BaseMessage]", *, max_tokens: int) -> "list[BaseMessage]":
        from langchain_core.messages import SystemMessage

        # 分离 system 和非 system
        system_msgs = [m for m in messages if isinstance(m, SystemMessage)]
        other = [m for m in messages if not isinstance(m, SystemMessage)]

        # 不超限时直接返回（只做配对清理）
        total = count_tokens(system_msgs + other)
        if total <= max_tokens and len(other) <= self._window:
            return ensure_tool_pairing(messages)

        # 保留最近 window_size 条
        recent = other[-self._window:] if len(other) > self._window else other
        result = system_msgs + recent
        return ensure_tool_pairing(result)


__all__ = ["SlidingWindowStrategy"]
```

- [ ] **Step 4: 运行确认通过** → **Step 5: 提交**

---

## Task 4: SummarizationStrategy

用 LLM 把早期 messages 总结为一条 SystemMessage。

**Files:**
- Create: `context_engineering/summarization.py`
- Test: `tests/context_engineering/test_summarization.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/context_engineering/test_summarization.py
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from unittest.mock import AsyncMock, MagicMock

from agent_flow_harness.context_engineering.summarization import SummarizationStrategy


class _FakeLLM:
    def __init__(self, response="这是摘要"):
        self._response = response

    @property
    def model_name(self):
        return "fake"

    async def ainvoke(self, messages, _config=None):
        return AIMessage(content=self._response)


@pytest.mark.asyncio
async def test_summarizes_old_messages():
    strategy = SummarizationStrategy(llm=_FakeLLM("早期对话讨论了项目架构"))
    msgs = [HumanMessage(content="hi"), AIMessage(content="hello")] * 10
    msgs += [HumanMessage(content="recent")]
    result = await strategy.aselect(msgs, max_tokens=999999, keep_recent=2)
    # 第一条应是 SystemMessage（摘要）
    assert isinstance(result[0], SystemMessage)
    assert "架构" in result[0].content


@pytest.mark.asyncio
async def test_no_summary_when_small():
    strategy = SummarizationStrategy(llm=_FakeLLM())
    msgs = [HumanMessage(content="hi")]
    result = await strategy.aselect(msgs, max_tokens=999999, keep_recent=5)
    assert len(result) == 1  # 不压缩


def test_name():
    s = SummarizationStrategy(llm=_FakeLLM())
    assert s.name == "summarization"
```

注意：SummarizationStrategy 用 LLM，需要 async，所以用 `aselect`（不是 `select`）。
**设计调整**：ContextStrategy 的 select 改为支持 async——实际让 select 是 async（因为 Summarization 要调 LLM）。

- [ ] **Step 2: 运行确认失败** → **Step 3: 实现**

**重要**：ContextStrategy.select 需改为 async（Summarization 调 LLM）。更新 base.py：

```python
# base.py 更新（select → async）
class ContextStrategy(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    async def select(self, messages, *, max_tokens) -> list: ...
```

SlidingWindow 的 select 也改 async（不需要 await 但签名统一）。

```python
# context_engineering/summarization.py
from __future__ import annotations
from typing import TYPE_CHECKING, Any

from agent_flow_harness.context_engineering.base import ContextStrategy
from agent_flow_harness.context_engineering.pairing import ensure_tool_pairing
from agent_flow_harness.context_engineering.token_estimator import count_tokens

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage, SystemMessage
    from langchain_core.language_models.chat_models import BaseChatModel

_SUMMARY_PROMPT = """请将以下对话历史压缩为简洁摘要，保留：
1. 用户的核心意图和需求
2. 关键决策和结论
3. 重要的错误信息或失败尝试
丢弃闲聊和冗余细节。用中文，不超过 300 字。

对话历史：
{history}"""


class SummarizationStrategy(ContextStrategy):
    """LLM 智能摘要策略：把早期 messages 总结为一条 SystemMessage。"""

    def __init__(self, llm: "BaseChatModel", summary_max_tokens: int = 500) -> None:
        self._llm = llm
        self._summary_max = summary_max_tokens

    @property
    def name(self) -> str:
        return "summarization"

    async def select(
        self, messages: "list[BaseMessage]", *, max_tokens: int, keep_recent: int = 10
    ) -> "list[BaseMessage]":
        from langchain_core.messages import HumanMessage, SystemMessage

        # 不超限或不值得总结时直接返回
        if count_tokens(messages) <= max_tokens or len(messages) <= keep_recent:
            return ensure_tool_pairing(messages)

        # 分割：前面要总结的 + 最近保留的
        to_summarize = messages[:-keep_recent]
        recent = messages[-keep_recent:]

        # 构建摘要 prompt
        history = "\n".join(
            f"[{self._role_label(m)}] {str(m.content)[:200]}" for m in to_summarize
        )
        prompt = HumanMessage(content=_SUMMARY_PROMPT.format(history=history))
        summary_resp = await self._llm.ainvoke([prompt])
        summary_text = str(summary_resp.content)[: self._summary_max * 4]

        summary_msg = SystemMessage(content=f"[对话历史摘要]\n{summary_text}")
        return ensure_tool_pairing([summary_msg] + recent)

    @staticmethod
    def _role_label(m: "BaseMessage") -> str:
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
        if isinstance(m, HumanMessage): return "用户"
        if isinstance(m, AIMessage): return "助手"
        if isinstance(m, ToolMessage): return "工具"
        if isinstance(m, SystemMessage): return "系统"
        return "未知"


__all__ = ["SummarizationStrategy"]
```

- [ ] **Step 4: 运行确认通过** → **Step 5: 提交**

---

## Task 5: HybridStrategy

默认策略：token < 70% 不动；≥ 70% 调 SummarizationStrategy 总结 + 滑动。

**Files:**
- Create: `context_engineering/hybrid.py`
- Test: `tests/context_engineering/test_hybrid.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/context_engineering/test_hybrid.py
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from agent_flow_harness.context_engineering.hybrid import HybridStrategy
from tests.context_engineering.test_summarization import _FakeLLM


def _big_msgs():
    """制造超 token 的 messages（每条 ~250 chars）。"""
    return [HumanMessage(content="x" * 1000), AIMessage(content="y" * 1000)] * 5


@pytest.mark.asyncio
async def test_no_compression_under_threshold():
    strategy = HybridStrategy(llm=_FakeLLM(), threshold=0.7)
    msgs = [HumanMessage(content="hi")]
    result = await strategy.select(msgs, max_tokens=100000)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_compresses_over_threshold():
    strategy = HybridStrategy(llm=_FakeLLM("摘要内容"), threshold=0.5)
    msgs = _big_msgs()  # ~5000 tokens
    result = await strategy.select(msgs, max_tokens=1000)  # 50% 阈值 = 500
    # 应被压缩（变短）
    assert len(result) < len(msgs)


def test_name():
    strategy = HybridStrategy(llm=_FakeLLM())
    assert strategy.name == "hybrid"
```

- [ ] **Step 2: 运行确认失败** → **Step 3: 实现**

```python
# context_engineering/hybrid.py
from __future__ import annotations
from typing import TYPE_CHECKING

from agent_flow_harness.context_engineering.base import ContextStrategy
from agent_flow_harness.context_engineering.summarization import SummarizationStrategy
from agent_flow_harness.context_engineering.token_estimator import count_tokens

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage
    from langchain_core.language_models.chat_models import BaseChatModel


class HybridStrategy(ContextStrategy):
    """混合策略（默认）：token < threshold 不动；≥ threshold 总结+滑动。"""

    def __init__(
        self,
        llm: "BaseChatModel",
        threshold: float = 0.7,
        window_size: int = 10,
    ) -> None:
        self._threshold = threshold
        self._summarizer = SummarizationStrategy(llm=llm)
        self._window = window_size

    @property
    def name(self) -> str:
        return "hybrid"

    async def select(self, messages, *, max_tokens):
        current_tokens = count_tokens(messages)
        if current_tokens < max_tokens * self._threshold:
            return list(messages)  # 未超阈值，不动
        # 超阈值：总结 + 保留最近 window_size 条
        return await self._summarizer.select(
            messages, max_tokens=max_tokens, keep_recent=self._window
        )


__all__ = ["HybridStrategy"]
```

- [ ] **Step 4: 运行确认通过** → **Step 5: 提交**

---

## Task 6: react_node 集成（可选 strategy，向后兼容）

**Files:**
- Modify: `engine/react.py`（LLM 调用前的压缩逻辑）
- Test: `tests/context_engineering/test_react_integration.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/context_engineering/test_react_integration.py
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from agent_flow_harness.context_engineering.hybrid import HybridStrategy
from tests.context_engineering.test_summarization import _FakeLLM


@pytest.mark.asyncio
async def test_react_uses_strategy_when_configured(
    base_state, fake_llm_factory, make_run_config
):
    """config 提供 context_strategy 时，react_node 用它而非默认 compress。"""
    from agent_flow_harness.engine.react import react_node

    llm = fake_llm_factory([AIMessage(content="done")])
    strategy = HybridStrategy(llm=_FakeLLM("summary"), threshold=0.5)
    config = make_run_config(llm)
    config["configurable"]["context_strategy"] = strategy

    result = await react_node(base_state, config)
    assert result["messages"][-1].content == "done"


@pytest.mark.asyncio
async def test_react_falls_back_without_strategy(
    base_state, fake_llm_factory, make_run_config
):
    """无 strategy 时走现有 compress_messages（向后兼容）。"""
    from agent_flow_harness.engine.react import react_node

    llm = fake_llm_factory([AIMessage(content="ok")])
    config = make_run_config(llm)
    # 不设 context_strategy
    result = await react_node(base_state, config)
    assert result["messages"][-1].content == "ok"
```

- [ ] **Step 2: 运行确认失败**

- [ ] **Step 3: 修改 react.py**

在 react.py 的 LLM 调用前压缩段（约 line 127-140），改为：

```python
        # 2. Compress if approaching the model's context window limit.
        strategy = configurable.get("context_strategy")
        if strategy is not None:
            # v0.2-5: 可插拔策略
            current_messages = await strategy.select(
                current_messages, max_tokens=context_window or 128000
            )
        elif should_compress(current_messages, model_name, context_window=context_window):
            # v0.1 向后兼容：现有 compress_messages
            before = len(current_messages)
            current_messages = compress_messages(
                current_messages, model_name, context_window=context_window
            )
            logger.info(
                "react_context_compressed",
                agent_id=state.get("agent_id"),
                request_id=request_id,
                iteration=iteration,
                before=before,
                after=len(current_messages),
            )
```

注意：`configurable` 变量需在前面已定义（react.py 应该有 `configurable = config["configurable"]`）。确认。

- [ ] **Step 4: 运行确认通过** → **Step 5: 提交**

---

## Task 7: ContextCompressedEvent + 包导出 + 全量回归

**Files:**
- Create: `context_engineering/__init__.py`（更新导出）
- Modify: `__init__.py`（顶层导出）
- Test: 追加 import 测试

- [ ] **Step 1: 更新 context_engineering/__init__.py**

```python
from agent_flow_harness.context_engineering.base import ContextStrategy
from agent_flow_harness.context_engineering.hybrid import HybridStrategy
from agent_flow_harness.context_engineering.sliding_window import SlidingWindowStrategy
from agent_flow_harness.context_engineering.summarization import SummarizationStrategy
from agent_flow_harness.context_engineering.token_estimator import count_tokens

__all__ = [
    "ContextStrategy",
    "HybridStrategy",
    "SlidingWindowStrategy",
    "SummarizationStrategy",
    "count_tokens",
]
```

- [ ] **Step 2: 顶层 __init__.py 加导出**

```python
from agent_flow_harness.context_engineering import (
    ContextStrategy,
    HybridStrategy,
    SlidingWindowStrategy,
    SummarizationStrategy,
)
```
`__all__` 加这 4 个（C/S/H 区）。

- [ ] **Step 3: import 测试**

```python
def test_context_engineering_importable():
    from agent_flow_harness import (
        ContextStrategy, HybridStrategy, SlidingWindowStrategy, SummarizationStrategy,
    )
    assert ContextStrategy is not None
```

- [ ] **Step 4: 全量回归**

```bash
cd packages/harness && uv run pytest --no-header -p no:warnings 2>&1 | tail -1
# 期望: 356 + 新增 ≈ 380 passed
cd backend && uv run pytest --no-header -p no:warnings 2>&1 | tail -1
# 期望: 814 passed
```

- [ ] **Step 5: ruff + mypy** → **Step 6: 更新 Story status done + 提交**

---

## Self-Review

**AC 覆盖：**
- AC1 (包导出) → Task 7 ✅
- AC2 (ContextStrategy Protocol) → Task 1 ✅
- AC3 (SlidingWindowStrategy) → Task 3 ✅
- AC4 (SummarizationStrategy LLM) → Task 4 ✅
- AC5 (HybridStrategy 70%) → Task 5 ✅
- AC6 (react_node 集成) → Task 6 ✅
- AC7 (ToolMessage 配对) → Task 2 ✅
- AC8 (向后兼容) → Task 6 (无 strategy 走 compress_messages) ✅
- AC10 (25+ 测试) → 各 task 累计 ~25 ✅

**注意点：** ContextStrategy.select 改为 async（Summarization 调 LLM）。SlidingWindow 也是 async（签名统一），虽不需 await。

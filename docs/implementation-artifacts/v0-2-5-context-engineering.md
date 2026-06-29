# Story v0.2-5: Context Engineering — 可插拔上下文压缩策略

**Epic:** v0.2 — P1 增强模块
**Status:** done (实施完成 2026-06-25，384 harness 测试 + 814 backend 测试全绿)
**Depends on:** v0.1-2 (react_node)

> ⚠️ 本 Story 已根据现状修正：v0.1 的 `engine/context.py` **已有** 压缩
> （`compress_messages` 滑动窗口 + 机械摘要 + 70% 阈值 + react.py:128 集成）。
> v0.2-5 不是从零做，而是**重构为可插拔 Strategy** + 补 LLM 智能摘要 +
> ToolMessage 配对保护 + 事件 emit。现有 compress_messages 保留为
> SlidingWindowStrategy 的基础（向后兼容）。

---

## Story

As **Agent Flow 性能工程师**,
I want **把 v0.1 硬编码的上下文压缩重构为可插拔 ContextStrategy 协议，提供 SlidingWindow/Summarization/Hybrid 三策略，并补 LLM 智能摘要 + ToolMessage 配对保护 + 压缩事件**,
So that **长会话能持续运行不超 context window，且压缩策略可按场景切换、ToolMessage 配对不被破坏、前端能感知压缩**。

---

## 背景与动机

当前 v0.1-2 的 react_node **无脑追加 messages**：

```python
current_messages.append(tool_message)  # 永远只增不减
```

长会话的痛点：

1. **token 爆炸** — messages 累积 → 超过模型 context window → API 失败
2. **成本飙升** — 每次 LLM 调用要付 N * token_price
3. **性能下降** — 长 prompt 处理慢，且 LLM 在长 prompt 中找不准重点
4. **历史失忆** — 即使压缩也不能简单丢弃，需要保留关键决策

`context_engineering` 模块目标：在 react_node 的 REACT 循环中插入**智能上下文管理**。

---

## 范围

### Must（必须做）

- `ContextStrategy` Protocol 定义（`select(messages, *, max_tokens) -> list[BaseMessage]`）
- 3 个内置策略：
  - `SlidingWindowStrategy` — 保留最近 N 条
  - `SummarizationStrategy` — 把早期 messages 总结为一条 system message
  - `HybridStrategy` — 滑动窗口 + 总结（默认）
- 接入 v0.1-2 `react_node` 内部（每次 LLM 调用前调用策略）
- 与 v0.1-4 `TokenBudgetGuard` 联动（接近上限时主动压缩）
- 保留 system message、ToolMessage 配对（不能切碎 tool_call/tool_result）

### Should（应该做）

- `VectorRetrievalStrategy`（v0.2-5 准备接口，**实际实现推 v0.3+**，因为需要向量数据库）
- 可配置 token 估算器（默认用 `tiktoken`）
- 压缩事件 emit（`ContextCompressedEvent(orig_count, new_count, strategy_name)`）

### Won't（不在本 Story 做）

- 跨 session 上下文检索（需要 v0.3+ 向量存储）
- LLM 自动决定何时压缩（避免不可预测，由 token 阈值触发）
- 上下文重要性评分（用启发式 + 简单规则，不引入 embedding）

---

## Acceptance Criteria

- **AC1:** `packages/harness/src/agent_flow_harness/context_engineering/__init__.py` 导出 `ContextStrategy` Protocol / 3 个策略类
- **AC2:** `ContextStrategy` Protocol 包含 `name: str` / `select(messages: list[BaseMessage], *, max_tokens: int) -> list[BaseMessage]`
- **AC3:** `SlidingWindowStrategy(window_size: int = 20)` 实现：保留 system + 最近 N 条
- **AC4:** `SummarizationStrategy(llm: BaseChatModel, summary_max_tokens: int = 500)` 实现：把早期 messages 用 LLM 总结为一条 HumanMessage（`[Summary of past N messages] ...`）
- **AC5:** `HybridStrategy(window_size=10, summary_threshold=0.7)` 实现：token 占用 > 70% → 总结 + 滑动
- **AC6:** `react_node` 在每次 LLM 调用前 `strategy.select(messages, max_tokens=context_window)`
- **AC7:** `react_node` 不切碎 `ToolMessage`（tool_call 必须有对应的 tool_result）
- **AC8:** 与 v0.1-4 `TokenBudgetGuard` 联动 — `total_tokens >= max_tokens * 0.7` → 主动调用 `strategy.select`
- **AC9:** `HybridStrategy` 触发压缩时 emit `ContextCompressedEvent` 走 v0.1-3 适配器
- **AC10:** 25+ 单元测试通过（5+ 边界：ToolMessage 配对 / 总结质量 / 滑动窗口 / Hybrid 联动）

---

## Tasks / Subtasks

1. **ContextStrategy Protocol**
   - `name: str` 字段
   - `select(messages, *, max_tokens) -> list[BaseMessage]` 方法
2. **token 估算器**
   - `tiktoken.encoding_for_model(model_name)` 默认
   - 失败 fallback 到 `len(text) // 4`（粗略估计）
3. **SlidingWindowStrategy**
   - 保留 system messages（`type="system"`）不动
   - 保留最近 `window_size` 条
   - 中间消息丢弃
4. **SummarizationStrategy**
   - 找到分割点（保留最近 N 条不总结）
   - 用 LLM 总结前面的 messages 为一段文本
   - 用 `HumanMessage(content="[Summary of past N messages]\n{summary}")` 替换
5. **HybridStrategy**
   - 检查 token 占用率（当前 tokens / max_tokens）
   - < 70% → 返回原 messages
   - ≥ 70% → 调 SummarizationStrategy 总结 + 滑动窗口
6. **react_node 集成**
   - 在 `await llm_with_tools.ainvoke` 前调 `strategy.select(messages, max_tokens=context_window)`
   - `context_window` 从 `LLMConfig` 读取（不同模型不同上限）
7. **ToolMessage 配对保护**
   - select 算法必须保证：被丢弃的 messages 不会让保留区出现"tool_call 没有 tool_result"
   - 用反向扫描：从尾往头保留，找到第一个 tool_result 对应的 tool_call 停止
8. **TokenBudgetGuard 联动**
   - `react_node` 检查 `state.get("total_tokens", 0) >= context_window * 0.7` → 主动压缩
   - 压缩后再调 LLM
9. **事件 emit**
   - `HybridStrategy` 触发时 `on_event(ContextCompressedEvent(orig_count, new_count, strategy_name))`
   - v0.1-3 适配器加新事件 schema
10. **测试**
    - 25+ 单元测试：3 个策略各 5 个 + 配对保护 + token 估算 + react 集成

---

## Dev Notes

### 关键设计点

1. **保守优先** — 宁可压缩不够，也不要切碎 tool_call/tool_result（会破坏 LLM 推理）
2. **总结保真度** — SummarizationStrategy 的 prompt 要明确"保留关键决策、用户意图、错误信息"
3. **与 v0.1-4 TokenBudgetGuard 协同** — Guard 阻断超限，ContextStrategy 提前避免超限
4. **可配置性** — strategy 选哪个、window 多大、阈值多少都由 `agent_doc["context_strategy"]` 配置
5. **不要异步化** — 压缩是同步操作（在 LLM 调用前），不要搞 async 复杂化

### 与 v0.1 兼容

- 不修改 v0.1-2 react_node 核心逻辑，仅在 LLM 调用前插入压缩步骤
- 不修改 v0.1-3 适配器（新增 `ContextCompressedEvent` 一种事件）
- 不修改 v0.1-4 TokenBudgetGuard（仅在 react_node 内联动）

### 策略选型决策树

```
┌──────────────────────────┐
│ react_node 即将调 LLM    │
└──────────┬───────────────┘
           │
           ▼
    ┌──────────────┐     No
    │ total_tokens │──────────────┐
    │ >= 70% ?     │              │
    └──────┬───────┘              ▼
       Yes │              ┌──────────────┐
           ▼              │ 调 LLM        │
   ┌──────────────┐       │ (正常)        │
   │ Hybrid       │       └──────────────┘
   │ Strategy     │
   │ .select()    │
   └──────┬───────┘
          │
          ▼
   ┌──────────────┐
   │ emit         │
   │ ContextComp- │
   │ ressedEvent  │
   └──────┬───────┘
          │
          ▼
   ┌──────────────┐
   │ 调 LLM       │
   │ (压缩后)     │
   └──────────────┘
```

### 策略选型 vs 场景

| 场景 | 推荐策略 | 原因 |
|---|---|---|
| 短会话（< 20 轮） | 不需要 | 还没超限 |
| 中等会话（20-100 轮） | `SlidingWindowStrategy` | 简单高效 |
| 长会话（100+ 轮） | `HybridStrategy` | 平衡保留 + 节省 |
| 客服 / 教学场景 | `SummarizationStrategy` | 保留关键对话内容 |
| 代码 Agent | `SlidingWindowStrategy` | 代码上下文重要，摘要损失信息 |

### 安全考量

- **总结不能注入** — SummarizationStrategy 的 prompt 必须固定（不能从 user input 派生），防止 prompt injection
- **tool_call 完整性** — 切碎 messages 时严格保留配对，否则 LLM 会幻觉
- **隐私保护** — 总结后的 system message 不应包含 PII（依赖 v0.1-4 ContentGuard 的 PII redact）

---

## File List

**新增文件:**
- `packages/harness/src/agent_flow_harness/context_engineering/__init__.py`
- `packages/harness/src/agent_flow_harness/context_engineering/base.py` — ContextStrategy Protocol
- `packages/harness/src/agent_flow_harness/context_engineering/token_estimator.py` — tiktoken 封装
- `packages/harness/src/agent_flow_harness/context_engineering/strategies/__init__.py`
- `packages/harness/src/agent_flow_harness/context_engineering/strategies/sliding_window.py`
- `packages/harness/src/agent_flow_harness/context_engineering/strategies/summarization.py`
- `packages/harness/src/agent_flow_harness/context_engineering/strategies/hybrid.py`
- `packages/harness/src/agent_flow_harness/context_engineering/tool_pairing.py` — ToolMessage 配对保护
- `packages/harness/tests/context_engineering/test_sliding_window.py`
- `packages/harness/tests/context_engineering/test_summarization.py`
- `packages/harness/tests/context_engineering/test_hybrid.py`
- `packages/harness/tests/context_engineering/test_tool_pairing.py`
- `packages/harness/tests/context_engineering/test_react_integration.py`

**修改文件:**
- `packages/harness/src/agent_flow_harness/engine/react.py` — 每次 LLM 调用前调 strategy.select
- `packages/harness/src/agent_flow_harness/adapters/app_event.py` — 新增 `ContextCompressedEvent`
- `packages/harness/src/agent_flow_harness/state.py` — `context_strategy: dict | None` 字段
- `packages/harness/src/agent_flow_harness/__init__.py` — 导出 context_engineering API
- `packages/harness/pyproject.toml` — 新增 `tiktoken` 依赖

---

## References

- [SPEC.md §12.5 context_engineering](../../SPEC.md) — 详细设计
- [v0.1-2 react node](v0-1-2-single-react-node-and-merge.md) — 集成点
- [v0.1-3 adapter](v0-1-3-astream-events-adapter.md) — ContextCompressedEvent 走适配器
- [v0.1-4 TokenBudgetGuard](v0-1-4-four-guards-as-nodes.md) — 70% 阈值联动
- [tiktoken](https://github.com/openai/tiktoken) — token 估算

# 上下文压缩实现审查

> 审查日期：2026-11-25
>
> 审查分支：`feature/execution-model`
>
> 审查范围：harness 压缩主流程、上下文分区、Token 估算、工具结果归档与回取、Todo 注入、Chat Checkpointer 接入。
>
> 本文是静态代码审查记录，不代表已运行测试。未在本次审查中修改运行时代码。

## 1. 总体结论

当前项目已经有一套相当完整的上下文压缩机制，尤其是：
- 按 Token 预算与工具批次边界处理单条 HumanMessage 的长程 Agent 任务；
- 保护未消费的 Tool Result；
- 压缩前检查 Tool Call / Tool Result 配对；
- 分级缩短已消费工具输出，再进行 LLM 语义摘要，最后才进入硬上限裁剪；
- 为压缩后的工具结果提供 Recall 工具；
- 使用摘要熔断器控制持续失败带来的成本。

因此不建议推翻重写。后续应以现有 `compress_node → _compress_by_turns` 流程为基础，修正上下文边界与可靠性问题。

但当前实现仍有几个与新架构决策不一致的地方，其中 Token 预算完整性、工具原文归档可靠性和“首条用户消息永久锚定”需要优先处理。

## 2. 当前实现结构

### 2.1 主流程

生产压缩入口是：

- `backend/packages/harness/src/agent_flow_harness/graph/nodes/llm_nodes.py`
- `compress_node()` 在每次 LLM 调用前执行。
- `_compress_by_turns()` 负责分级工具压缩、LLM 摘要和硬上限兜底。
- 图结构为 `compress → llm → tools → compress`。

### 2.2 压缩组件

| 文件 | 当前职责 |
|---|---|
| `context_engineering/turns.py` | 按用户轮数或工具批次切分 outer / recent |
| `context_engineering/pairing.py` | 清理不完整 Tool Call / Tool Result 配对 |
| `context_engineering/tool_output.py` | 缩短已消费 Tool Result，保护未消费结果 |
| `context_engineering/llm_summary.py` | 将较早历史渲染为结构化摘要 |
| `context_engineering/compact_circuit.py` | 摘要失败/无进展时熔断 |
| `engine/context.py` | Token 估算和模型窗口查找 |
| `app/engine/harness_integration/context.py` | 注入原文归档和图片 Recall formatter |
| `app/services/tool_output_archive_service.py` | 持久化压缩前的工具结果原文 |
| `app/engine/agent/recall_tool.py` | Agent 按 tool_call_id 回取工具结果 |

### 2.3 当前压缩顺序

1. 清理不完整工具配对，并标注中断。
2. 对较旧图片做降级。
3. Token 未达软阈值时不做常规压缩。
4. 切分 outer / recent。
5. 压缩 outer 中已消费的大工具结果。
6. 仍超阈值时压缩 recent 中已消费的大工具结果。
7. 仍超阈值时对 outer 做 LLM 摘要。
8. 接近硬上限时裁剪更早消息，并清理配对。

现有实现默认使用 70% 软阈值、90% 硬阈值；近期保护默认 5 个 HumanMessage，长任务分区使用 15% 窗口预算和至少 3 个工具批次。

## 3. 已有设计值得保留

### 3.1 长程 Agent 不只按 HumanMessage 切分

`turns.py::split_for_compression` 已处理“一个用户任务指令 + 大量工具往返”的场景。HumanMessage 数不足保护轮数时，按 Token 预算从尾部累计工具批次，并在批次边界切分。

这是必要能力，应保留。

### 3.2 未消费的工具结果受到保护

`tool_output.py::find_unconsumed_tool_call_ids` 识别尚未被后续 AIMessage 消费的工具结果；`compress_tool_outputs` 不会截断这些结果。

这能避免模型还没看到结果就先把它缩成占位符，应保留。

### 3.3 工具配对作为压缩安全约束

`ensure_tool_pairing` 在压缩前后保护 Tool Call / Tool Result 配对，避免向供应商发送结构不完整的工具轨迹。

### 3.4 摘要不取代原始事实

摘要中保留工具结果 Recall 引用；Agent 可以用 `recall_tool_result` 按需取回原始工具输出。这符合“完整历史按需回溯，而不是全部重新注入 Prompt”的方向。

### 3.5 摘要熔断器只控制成本

`compact_circuit` 的进程内状态用于避免无效摘要反复消耗成本，不承担正确性或恢复职责。这个边界是合理的。

## 4. 需要优先处理的问题

### P1 — Token 预算没有覆盖完整 Model Input

涉及：
- `context_engineering/engine/context.py::estimate_context_tokens`
- `graph/nodes/llm_nodes.py::llm_node`
- `app/engine/harness_integration/todo_middleware.py::before_llm`

当前 Token 估算主要基于 `messages`。但实际 Model Input 还包括：

1. `llm_node` 通过 `llm.bind_tools(tool_list)` 绑定的工具定义；
2. Middleware 在 `before_llm` 中临时注入的 Todo 消息；
3. 供应商协议可能附加的其他结构化输入。

其中 Todo 是在 `compress_node` 完成压缩后、真正调用模型前才加入 `call_state["messages"]` 的。因此压缩节点看到的 Token 数并不等于最终发送给模型的 Token 数。

此外，`estimate_context_tokens` 在历史被压缩改写后会切换到全量估算，但全量估算仍只遍历 messages，不包含工具定义。

**风险：** 工具较多、Schema 较大或 Todo 较长时，压缩器认为上下文低于阈值，供应商实际收到的输入却可能超窗。

**建议：**
- 把预算对象从“消息 Token 数”提升为“完整 Model Input Token 估算”。
- 至少纳入当前工具 Schema 和所有调用前 Middleware 注入内容。
- 若供应商无法精确计算工具 Schema Token，使用保守预算或预留量。
- 最终调用前保留一次预算校验；不能只在 compress_node 检查。
- Usage Metadata 可作为上次调用的校准值，但任何前缀、工具定义或动态注入变化都必须使旧基准失效。

### P1 — 工具原文归档是 fire-and-forget，压缩却立即宣称可回取

涉及：
- `app/engine/harness_integration/context.py::_schedule_archive`
- `app/engine/harness_integration/context.py::_make_tool_output_reference_formatter`
- `app/services/tool_output_archive_service.py::archive`

当前 formatter 在压缩前调用 `_schedule_archive`，后者用 `asyncio.create_task` 异步写归档；formatter 不等待归档完成，直接返回“完整原文已存档”的提示。归档服务失败时只记录日志并吞掉异常。

对 chat，部分场景可能还有产品消息 Timeline 作为回退；但 IM / workflow 等场景可能没有完整 Message 明细，归档是唯一原文来源。

**风险：** 压缩后的上下文已经只剩 Recall 标记，但归档写入尚未完成或最终失败；进程在后台任务完成前崩溃时，原文可能永久丢失。

**建议：**
- 压缩器需要知道 formatter / archive 是否成功，而不只是拿到一段提示文本。
- 归档成功前不能丢弃唯一原文副本；失败时保留原 ToolMessage 或跳过该条压缩。
- 可以异步优化非关键工作，但“原文已持久化”必须是有确认的事实。
- 归档保留期与产品历史和长程任务回溯要求对齐，不能只作为短期缓存处理。

### P1 — 第一条 HumanMessage 被永久当成 Session 级任务目标

涉及：
- `context_engineering/turns.py::split_for_compression`
- `graph/nodes/llm_nodes.py::_compress_by_turns`

当前 `split_for_compression` 会把 outer 中第一条 HumanMessage 移入 recent；硬上限裁剪时也尝试保护该消息。代码注释将其定义为“任务指令”。

这对“一条用户指令驱动的长任务”有意义，但新产品模型允许同一个 Conversation 持续讨论多个话题，且可以没有 Work / Current Objective。

**风险：**
- 普通聊天第一条用户消息会永久占用上下文预算，即使它早已无关。
- 它并不一定是当前 Work 的 Goal。
- 任务目标与 Conversation 首条消息被错误地绑定。

**建议：**
- 不要把首条 HumanMessage 作为所有 Context Session 的永久锚点。
- 普通 Conversation 只保护近期交互单元；较早内容可摘要或裁剪，原始历史由 History Recall 保留。
- 如果某个 Work 需要长期保留 Goal，应以 Work 的结构化 Goal / Work Context 为锚点，而不是复用 Session 第一条用户消息。
- 在 Work 与 Context Session 关联机制尚未完成前，不要简单删除保护逻辑；先明确 chat 与长程 Work 两种模式的锚定策略。

### P1/P2 — 硬上限兜底按单条消息裁剪，不是完整交互单元

涉及：
- `graph/nodes/llm_nodes.py::_compress_by_turns`，硬上限裁剪部分。

常规 outer / recent 切分已尽量按用户轮或工具批次边界完成；但硬上限兜底会逐条从 outer 头部移除消息，必要时再逐条移除 recent 的较早消息，最后用 `ensure_tool_pairing` 清理不完整配对。

**风险：** 硬上限路径可能把一个交互单元拆开；配对清理只能避免非法 Tool Call 结构，不能保证语义上的完整性。用户消息、Agent 回复、工具批次可能只保留一部分。

**建议：**
- 硬上限裁剪也应复用统一的 Compression Unit 边界。
- 每次丢弃一个完整 Unit，而不是任意一条 Message。
- 裁剪后验证工具配对、当前未完成调用、近期交互保护和任务状态。
- 若固定占用本身已超窗，明确失败，不要继续破坏历史结构。

## 5. 其他需要修正或明确的行为

### P2 — System Message 去重后提前返回，跳过本轮压缩

涉及：`graph/nodes/llm_nodes.py::compress_node`。

当检测到多个带 ID 的 SystemMessage 时，当前逻辑删除旧消息后立即返回替换 Patch，没有继续执行 Token 预算检查和压缩。

**风险：** 如果同一轮既发生 SystemMessage 去重又已经超过上下文预算，当前模型调用仍可能使用超预算的历史。

**建议：** 去重后继续执行同一轮压缩流程，或确保在调用 LLM 前再次运行预算校验。

### P2 — Todo 每次 LLM 调用都注入，而不是仅在用户轮 / 执行轮边界提醒

涉及：`app/engine/harness_integration/todo_middleware.py::before_llm`。

当前 Middleware 在每次模型调用前都将 Todo 临时追加到本次输入，不写入持久化 messages。这避免了历史版本堆积，但一个 REACT 循环内多次工具往返会反复支付 Todo Token。

这与本项目已确定的 Todo 定位（轻量进度提醒器，在轮次结束 / 下一轮推进时提醒当前状态）不完全一致。

**建议：**
- 保留 Todo 的独立状态事实源。
- 明确提醒频率：优先在新的用户轮或需要恢复任务位置的模型调用时注入，不要默认每个工具循环都重复注入。
- 动态 Todo 注入必须纳入完整 Model Input Token 预算。

### P2 — Token Usage 基准在 Prompt 前缀变化后可能失效

涉及：`engine/context.py::estimate_context_tokens`。

当前逻辑使用最近一条 AIMessage 的 `usage_metadata.input_tokens` 作为历史基准，再估算其后的新增消息。这个基准隐含前提是：该 AIMessage 之前的消息内容没有变化。

但新的用户请求会更新固定 ID 的 SystemMessage（当前组装 ID 为 `sys`），Prompt 可能因此变化。若复用上次 AIMessage 的 usage 基准，却没有感知 SystemMessage 内容变化，Token 估算就可能沿用旧 Prompt 的输入量。

**建议：**
- 为 usage 基准记录其对应的消息前缀摘要 / 版本，或在 System Prompt、工具定义等前缀变化时使其失效。
- 不需要建立复杂 Prompt Revision 领域对象；一个 Runtime 内部的输入指纹即可。
- 该问题与完整 Model Input 预算问题一起处理。

### P2 — Chat 的 Checkpointer Thread ID 仍直接使用产品 Session ID

涉及：
- `backend/app/engine/harness_integration/execution.py`
- `backend/app/services/agent_execution_service.py`

当前 Chat 执行将 LangGraph `thread_id` 设为 `session_id`，Recall Archive 也使用这个 thread 标识。产品消息集合与 Checkpointer 状态虽然是两套存储，但身份边界仍然是一对一绑定。

这对当前“一个 Chat Session 持续一个模型上下文”的行为足够；但未来一个 Conversation 中出现多个 Work、多个 Agent 或显式 Fork 时，产品 Conversation 与模型 Context Session 不再必然一一对应。

**建议：**
- MVP 不必立即重构所有 ID。
- 在 Runtime 中引入 Session Resolution 抽象，让调用方通过 Runtime 取得 Context Session，而不是在业务代码中直接假定 `thread_id == session_id`。
- 后续再按 Work / Agent / Fork 场景决定是否创建独立 Context Session。
- Archive / Recall 的关联键也应逐步转向 Context Session + 稳定 Tool Invocation 标识，避免依赖产品 Session ID。

### P2 — Context Epoch 与压缩来源目前没有显式记录

当前压缩结果直接写回 LangGraph State / Checkpoint；没有看到独立的 Context Epoch 或明确记录 Summary 来源消息范围的机制。

这并不意味着必须新建 Epoch 集合。MVP 可以先用轻量压缩记录：压缩序号、来源消息 ID / 范围、摘要消息 ID、压缩时间，并确保 Checkpoint 与该状态一致。

如果现有 Checkpoint 已完整保存压缩后的 messages，恢复正确性可以依赖 Checkpoint；Epoch 的首要价值是诊断、审计和理解多次压缩后的来源关系。

## 6. 与目标架构的对照

| 目标设计 | 当前实现 | 判断 |
|---|---|---|
| 历史与执行上下文独立演化 | Message 集合 + LangGraph Checkpointer；新会话不从 History 重建，Legacy Migration 是兼容路径 | 基本符合 |
| Agent 按需 Recall 历史 | 已有 `recall_tool_result`，主要覆盖压缩工具结果 | 部分符合；通用 History Recall 尚需扩展 |
| 普通 Conversation 不固定 Current Objective | 首条 HumanMessage 永久锚定 | 不符合 |
| 长程任务按完整交互 / 工具批次压缩 | 已有 Token + 批次边界切分 | 基本符合，硬上限路径需加强 |
| 未消费 Tool Result 不压缩 | 已实现 | 符合 |
| 原文可可靠回取 | 异步 best-effort Archive + 30 天 TTL | 不符合可靠性要求 |
| Todo 不进入压缩历史 | Todo 在独立 state 中，并临时注入 | 符合 |
| Todo 作为轻量提醒 | 每次 LLM 调用都注入 | 需要调整频率 |
| Token Budget 覆盖完整 Prompt | 主要估算 messages，工具定义 / Middleware 注入未完整计入 | 不符合 |
| Prompt 更新无需 Session Migration | 新请求重新装配 Agent Prompt / Tool 集合，System Message 以固定 ID 更新 | 基本符合 |
| Prompt Cache 独立于业务状态 | 未发现平台显式 Provider Cache 管理层 | 不应在 MVP 新建复杂缓存域 |
| Context Epoch / Summary 来源追踪 | 未发现显式实现 | 可用轻量记录补足 |

## 7. 推荐修正顺序

1. **先修 Token Budget 完整性**：确保最终发送给模型的输入（消息、工具定义、Middleware 动态注入）都被预算覆盖。
2. **再修原文归档可靠性**：未确认归档成功前，不允许压缩掉唯一原文。
3. **调整锚定策略**：区分普通 Conversation 与有 Work 的长程任务；不要永久锚定 Conversation 第一条消息。
4. **统一 Compression Unit**：常规切分和硬上限裁剪复用同一套交互单元边界。
5. **修复 System 去重后的提前返回**，并处理 Prompt 前缀变化导致的旧 usage 基准失效。
6. **调整 Todo 提醒频率**，并把 Todo 注入纳入 Token Budget。
7. **最后补轻量压缩来源记录**，不急于实现独立 Epoch 服务。

## 8. 本次审查不建议做的事情

- 不推翻现有 `turns.py`、`tool_output.py` 和 `llm_summary.py`。
- 不为了 Prompt Cache 引入独立的会话版本迁移系统。
- 不要求 Prompt / Tool Definition 修改触发 Session Fork 或 Migration。
- 不把产品历史重新构造成每次模型调用的完整 Prompt。
- 不把 Summary 当成事实数据库。
- 不把 Todo 变成第二套长期记忆。
- 不在没有数据规模和合规要求前设计复杂的归档冷热分层系统。


## 9. 深入设计：完整 Model Input Token Budget

本节进一步明确 P1 问题的根因和建议实现方式。核心不是简单给 messages 估算加一个工具 Token 常量，而是让压缩器和真正的 LLM 调用基于同一份 **Invocation Input**。

### 9.1 当前预算为什么不完整

当前调用链：

```text
compress_node
  └── estimate_context_tokens(state.messages)
       └── _compress_by_turns(state.messages)
            └── estimate_context_tokens(messages)
                 │
                 ▼
llm_node
  ├── llm.bind_tools(config.tools)
  ├── MiddlewareChain.before_llm
  │    └── TodoSalienceMiddleware 追加临时 HumanMessage
  └── llm.ainvoke(call_state.messages)
```

有三个输入维度没有被压缩器完整看到：

1. **Tool Definitions**：`llm_node` 把当前 tools 传给 `bind_tools`，但压缩器只估算 messages。
2. **Todo 动态注入**：`TodoSalienceMiddleware` 在 compress_node 之后追加临时消息；该消息不持久化，但会消耗真实 Input Tokens。
3. **其他未来的动态输入**：任何在压缩之后、模型调用之前改变消息或请求参数的 Middleware，都可能造成预算盲区。

此外，`estimate_context_tokens` 复用上一次 `AIMessage.usage_metadata.input_tokens` 时，默认上一次调用的固定输入仍然有效。实际上 System Prompt、Tool Definitions、Todo 内容、Model Configuration 可能已经变化。

### 9.2 目标模型：Invocation Input

建议增加一个轻量的调用输入概念（Runtime 内部对象，不是持久化领域对象）：

```text
InvocationInput
├── messages
│   ├── Persistent Execution Conversation
│   └── Ephemeral Context Messages
├── tools
│   └── Current Tool Definitions
├── model_config
└── input_fingerprint
```

其中：
- Persistent Execution Conversation 是当前 Context Session 的持久化消息。
- Ephemeral Context Messages 是本次调用临时注入的 Todo 等信息，不写入 Execution Conversation。
- Tools 是本次调用实际传给 `bind_tools` 的工具集合。
- input_fingerprint 是 Runtime 内部诊断 / Token 基准校验信息，不是 Agent Version，也不是 Session Migration 机制。

压缩器只修改 Persistent Execution Conversation；预算估算同时计算 Persistent Messages、Ephemeral Context Messages 和 Tools。

### 9.3 不要重复执行任意 before_llm Middleware

不能简单在 compress_node 里提前调用一次 `chain.run_before_llm`，再在 llm_node 调用一次。Middleware 可能有计时、Recorder 等副作用，执行两次会重复记录或产生不一致。

当前真正修改消息的只有 TodoSalienceMiddleware；UsageMiddleware 和 RecorderMiddleware 主要观察调用。因此建议把“提供模型上下文”从通用 Middleware 改写钩子中分离：

- 引入明确的 Context Provider / Context Contributor 接口，例如 `context_messages(state) -> list[BaseMessage]`。
- 该接口必须是无副作用、确定性的读取操作。
- `compress_node` 使用它计算预算。
- `llm_node` 使用同一接口构造最终模型输入。
- TodoSalienceMiddleware 改为提供临时 Todo Context Message，不再通过普通 `before_llm` 追加。
- Usage / Recorder 等观察型 Middleware 仍只在真实调用时执行一次。

这样不需要把任意 Middleware 运行两遍，也不需要把 Todo 消息写入 Checkpoint。

### 9.4 Tool Definition Token 估算

预算必须覆盖传给 `bind_tools` 的同一组工具定义，而不是另行维护一份可能漂移的工具列表。

建议抽象为 Model Adapter 的能力：

```python
estimate_input_tokens(
    messages=current_messages,
    tools=current_tools,
    model_config=current_model_config,
) -> TokenEstimate
```

估算策略按可靠性排序：

1. 如果供应商 / LangChain Model Adapter 提供包含 Tools 的精确 Token 计数能力，优先使用。
2. 否则对 Tool Schema 做规范化序列化，按 Schema 字段、描述、参数定义等进行保守估算。
3. 额外保留可配置安全余量，避免启发式低估。
4. 从真实模型响应的 `usage_metadata.input_tokens` 校准估算偏差，并记录估算值与真实值的差距。

不要假定所有 Provider 的工具 Schema Token 计算完全一致；工具定义可能以独立请求字段发送，并不一定表现为普通 Message。

### 9.5 Usage 基准必须有适用条件

上一轮 `input_tokens` 可以作为当前估算基准，但只能在其静态输入条件仍然一致时复用。

至少需要校验：
- System / Platform / Agent Instructions 内容指纹；
- 当前 Tool Definitions 指纹；
- Model / Provider Configuration 指纹；
- Ephemeral Context Messages 指纹（尤其是 Todo 内容）；
- 上次调用之后的持久化消息确实只是追加，而不是被重排、替换或压缩。

任一条件变化，旧 usage 基准失效，退回对当前完整 Invocation Input 的重新估算。

这只是一个 Runtime 内部 fingerprint，不需要创建 Prompt Revision、Tool Revision 或 Context Session Migration 领域模型。

特别注意：Prompt 或 Tool Definition 更新后，下一次新的执行请求使用最新定义；同一次运行中已装配的工具集合保持一致。Usage 基准不能跨越这类输入变化继续复用。

### 9.6 压缩算法如何使用完整预算

`_compress_by_turns` 仍然只对持久化 messages 做切分和压缩，但每个阶段都要用完整输入预算判断：

```text
estimate(
  persistent_messages_after_compaction
  + ephemeral_context_messages
  + current_tool_definitions
)
```

- Ephemeral Context Messages 和 Tool Definitions 属于本轮固定开销，不参与历史压缩。
- 当预算超阈值时，压缩器只压缩持久化 Execution Conversation。
- 若固定开销本身已过大，明确报错或要求减少工具 / 动态上下文，而不是继续删除历史。
- 最终调用前再执行一次 preflight 校验，确保 `llm_node` 实际发送的输入与压缩器预算使用同一份上下文贡献和工具集合。
- 保留回复 Token 预留；当前 `RESERVED_RESPONSE = 4000` 应统一进入 Token Budget 配置，不能散落在多个检查函数中。

### 9.7 Prompt Cache 的兼容方式

该设计不会要求平台自己管理供应商缓存：

- System Prompt 与 Tools 保持稳定时，前缀自然更容易复用。
- Todo 等动态上下文放在持久化对话之后，变化尽量只影响后缀。
- Tool Definitions 变化允许 Provider Cache 失效。
- 不为缓存命中保留过时的 Prompt 或 Tool Schema。
- `cached_input_tokens` 继续作为观测指标；不参与正确性判断。

### 9.8 建议测试矩阵

| 场景 | 预期 |
|---|---|
| 首次调用，有 System + Messages + Tools | 预算包含三者 |
| 工具 Schema 很大，Messages 很短 | 仍触发压缩或固定开销告警 |
| Todo 很长，持久化 Messages 很短 | Todo Token 被计入 |
| Todo 状态从短变长 | 旧 usage 基准失效 |
| Agent Prompt 更新 | 旧 usage 基准失效；下一次新执行使用新 Prompt |
| Tool Definition 更新 | 旧 usage 基准失效；下一次新执行使用新定义 |
| 同一次 REACT 工具循环 | Tool Set 保持本次运行装配的一致性 |
| Middleware 观察钩子 | 预算预检不重复触发 Recorder / Usage |
| Context Compression 改写历史 | 旧 usage 基准失效 |
| Ephemeral Todo 不写入 messages state | Checkpoint 不积累 Todo 快照 |
| 最终 preflight 与 compress 估算 | 对同一 Invocation Input 得到一致的输入组成 |
| Provider Usage 返回真实 Token 数 | 记录估算偏差并校准后续预算 |

### 9.9 推荐实施切片

1. 先引入 `InvocationInput` / Context Provider 的最小抽象，先迁移 Todo 注入，保证压缩和调用看到同一动态上下文。
2. 为当前工具集合增加 Schema Token 估算；先做保守估算与安全余量，不追求跨 Provider 完美精确。
3. 将 `compress_node`、`_compress_by_turns`、`_check_oversized_prompt`、`_check_oversized_tool_result` 统一改用完整 Invocation Input 预算。
4. 增加 usage fingerprint，输入固定部分变化时自动退回全量估算。
5. 在 `llm_node` 调用前增加最终 preflight，并补齐上述测试。

不建议为此引入独立 Token Budget Service，也不建议把 Provider Cache、Prompt Revision 或 Tool Revision 变成业务领域对象。

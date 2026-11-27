# Conversation Context 与上下文压缩架构

> 状态：**架构设计草案，待结合当前实现审查后定稿**
>
> 目标：明确产品级会话历史、模型执行上下文、运行时动态信息、上下文压缩与 Prompt Cache 的边界。
>
> 本文记录 agent重构项目在 2026-11-25 讨论中形成的设计决策。它定义目标架构，不代表当前代码已经全部实现。

## 1. 核心原则

1. **Conversation History 与 Execution Conversation 是两份职责不同、独立演化的数据。**
2. 模型执行会话是模型实际使用的持续上下文；后续调用直接延续它，不从完整产品历史反复重建 Prompt。
3. 产品历史保持完整、稳定，不因模型上下文压缩而被改写。
4. Agent 需要回顾过去时，通过 History Recall 按需查询原始历史；不把全部历史自动注入模型上下文。
5. 普通 Conversation 不要求始终存在一个 Current Objective。用户可以在同一会话中讨论多个话题，也可以在没有 Work 的情况下持续聊天。
6. Prompt、Tool Definition 的更新不触发 Context Session Migration；下一次模型调用使用当时最新的有效定义。
7. Context Compression 在安全的交互边界执行，不在模型 Token Stream 生成过程中修改上下文。
8. Prompt Cache 是性能优化，不是会话状态、恢复依据或正确性保证。

## 2. 核心对象与职责

### 2.1 Conversation History

产品级历史记录，面向用户展示、审计和按需回溯。

包括：
- 用户消息与 Agent 回复；
- Tool Call 与 Tool Result 的历史事实；
- 用户打断、澄清、授权等交互；
- Plan/Todo 相关的必要事件；
- Artifact、文件和其他执行产物的引用。

约束：
- 历史记录追加写入，不因 Context Compression 删除或覆盖原始事实。
- 大型内容可以外置到 Artifact / Archive，但历史记录必须保留稳定引用。
- History Recall 按需检索消息、工具调用、工具结果和产物；召回结果作为本次模型输入的补充，不替换整个 Execution Conversation。
- 历史展示格式可以是消息列表或 Timeline；底层存储不要求与模型消息格式一致。

### 2.2 Execution Conversation

模型实际使用的持续消息上下文，是模型上下文连续性的边界。

包括：
- 模型消息序列；
- Tool Call / Tool Result；
- Context Compression 产生的 Summary；
- 当前保留的近期交互内容。

约束：
- 初始内容通常由当前交互及必要上下文形成，与产品历史在起点上大致一致。
- 后续独立追加、压缩和恢复，不要求与产品历史保持逐条一致。
- 压缩只改变 Execution Conversation，不修改 Conversation History。
- Checkpoint 保存恢复所需的 Execution Conversation 状态。
- Resume 继续原上下文；Fork 才创建新的上下文分支；不因普通 Prompt 更新而 Fork 或 Migration。

### 2.3 Conversation、Work、Execution 与 Context Session

这些概念不能互相替代：

| 概念 | 职责 |
|---|---|
| Conversation | 用户长期交互与产品历史的容器 |
| Work | 可选的持续业务目标；一个 Conversation 可以包含多个 Work，也可以没有 Work |
| Execution | 一次具体运行过程，负责运行状态、工具调用和恢复 |
| Context Session | 模型上下文连续性的边界，拥有持续演化的 Execution Conversation |

重要约束：
- 普通聊天不必创建 Work，也不必构造 Current Objective。
- 只有用户提出持续目标时，Runtime 才按产品策略创建或关联 Work。
- Work Goal 是结构化任务定义；原始用户消息仍然保留在 Conversation History。
- 用户切换话题时，Runtime 不应把新话题强行归入之前的 Work。
- Runtime 负责决定 Execution 使用哪个 Context Session；Agent 不需要理解或选择内部 Session ID。

### 2.4 Plan 与 Todo

- Plan 表达较长期、可版本化的任务规划。
- Todo 是轻量的进度提醒器，提示 Agent 当前推进位置；不是第二套长期记忆，也不替代 Execution History。
- Todo 状态应独立于可压缩的 messages 保存。
- Todo 的更新不应不断向 Execution Conversation 追加历史版本；需要提醒模型时，以临时 Runtime Context 形式提供当前状态。
- Todo 是 Agent 自己维护的轻量进度提醒器，状态独立于可压缩的 messages 保存；Runtime 不解释或改写 Todo 项的语义状态。
- 新任务首次执行时，Agent 可按需要创建 Todo；不要求 Runtime 预先注入空 Todo。
- Agent 每次准备结束一次执行时，Runtime 检查当前 Todo：全部完成则正常结束；仍有未完成项则向 Agent 注入一次结束前提醒，让 Agent 决定继续执行，或向用户说明阻塞 / 无法继续的原因。
- 结束前提醒不是强制门控：Runtime 不无限阻止结束，也不因 Execution 结束而自动把 Todo 标记完成。Todo 内容与完成状态始终由 Agent 通过 `todo_write` 管理。
- 如果 Execution 未结束而需要恢复，在新一轮执行开始时读取并注入当前 Todo 一次，帮助 Agent 恢复进度；同一次 Execution 内的普通 LLM / Tool 循环不重复注入。
- Todo 提醒注入后应进入当前执行上下文，使 Agent 在本次继续执行期间持续可见；Todo 的独立状态仍不参与 Context Compression。

## 3. Model Invocation 输入结构

逻辑上，一次模型调用由以下部分组成：

```text
Model Invocation
├── Stable Instructions
│   ├── Platform Instructions
│   ├── Agent Instructions / Prompt
│   └── Tool Definitions
│
├── Execution Conversation
│   ├── Earlier Messages / Summary
│   ├── Recent Messages
│   └── Completed Tool Call / Result
│
├── Optional Runtime Context
│   ├── Relevant Work State
│   ├── Plan / Todo Reminder
│   └── Current Execution Constraints
│
└── Current User Input (when applicable)
```

这是一种逻辑结构，不强制所有供应商使用相同的 Message Role 或消息布局。Model Adapter 负责映射到具体供应商协议。

### 3.1 Stable Instructions 与动态更新

- Platform Instructions、Agent Prompt 和 Tool Definitions 在每次新的执行请求 / 测试请求装配上下文时解析当前有效版本；同一次运行中已经装配的配置保持一致，不要求热更新。
- 修改 Prompt 后，下一次新的执行 / 测试请求直接使用最新 Prompt；不需要创建新 Context Session，不需要重新构建历史，也不需要迁移。
- 修改 Tool Definition 后，下一次新的执行请求装配当前定义；同一次运行中继续使用已装配的工具集合。已经完成的旧 Tool Call / Result 是历史事实，不需要迁移或重新解释。
- 当前工具是否可用、当前操作是否授权，由 Runtime 在工具执行时检查。Prompt Cache 命中不能代替权限检查。
- 不建立一套要求用户管理的 Prompt Revision / Tool Revision / Session Migration 领域系统。
- 为调试和审计，可以在 Invocation 记录实际使用的 Prompt、Tool 与 Model 配置标识或摘要；这是诊断元数据，不是 Session 迁移条件。

### 3.2 Runtime Context

Runtime Context 是某次模型调用的辅助状态快照，不是 Conversation Message，也不是固定的 Current Objective。

- 仅在相关时注入。
- Todo 有两个明确的提醒时机：恢复未结束的 Execution 时，在新一轮执行入口注入当前 Todo 一次；Agent 每次准备结束执行时，如果仍有未完成项，再注入一次结束前提醒。
- 结束前提醒只促使 Agent 重新检查进度，不构成强制门控。Agent 可以继续执行，也可以判断无法继续并向用户说明原因；Runtime 不替 Agent 修改 Todo 状态。
- 同一次 Execution 内的普通 LLM / Tool 循环不重复注入恢复提醒；Todo 状态由 Agent 更新并独立保存，不参与消息压缩。
- 其他 Runtime Context 仍仅在相关时注入；内容发生变化时更新，不因变化而向 Execution Conversation 追加历史版本。
- 尽量放在稳定前缀之后，减少对 Prompt Prefix Cache 的影响。
- 只注入模型完成当前推理真正需要的信息。
- 权限与安全状态在执行时重新验证，不依赖模型输入中的旧快照。

## 4. Prompt Cache 设计边界

Prompt Cache 通常依赖稳定的 Prompt Prefix，但不同模型供应商的缓存粒度、TTL、最小 Token 数、缓存断点和工具定义处理方式不同。

平台遵循以下原则：

1. 稳定指令与工具定义尽可能保持稳定的内容、顺序和序列化。
2. Execution Conversation 采用追加优先的维护方式，不在每轮无故重建全部消息。
3. 动态 Runtime Context 放在稳定前缀之后，且仅在需要时更新。
4. Prompt 或 Tool Definition 更新会改变相应前缀；允许供应商缓存因此失效，不为缓存而延迟 Prompt 更新。
5. 压缩会改变上下文前缀，也允许缓存失效；不能为了命中缓存而保留已经不适合当前任务的历史。
6. Provider Cache State 由 Model Adapter 处理，不成为 Conversation、Work 或 Context Session 的业务事实。
7. 缓存未命中、缓存过期或供应商不支持缓存，都不能影响执行正确性与恢复能力。

## 5. Context Compression

### 5.1 触发与时机

- 以模型上下文 Token 预算为主要依据，预留模型输出空间。
- 达到软阈值时开始分级压缩；硬阈值用于最后防线，而不是常规压缩目标。
- 优先在一个完整交互单元结束后压缩。
- 也可以在下一次 Model Invocation 前执行受控压缩。
- 不在模型 Token Stream 生成中途修改当前上下文。
- 未完成的 Tool Call / Tool Result 批次、尚未被模型消费的最新工具结果必须受到保护。

### 5.2 压缩单元与安全边界

压缩边界不能只按 HumanMessage 划分。

需要识别：
- 用户交互轮边界；
- Agent 完整响应边界；
- 一次 Tool Call 及其全部 Tool Result；
- 并行工具调用批次及其全部结果；
- 中断、取消和恢复时的未完成调用；
- 当前模型调用正在消费的消息。

压缩必须保证：
- 不留下没有对应结果的 Tool Call；
- 不留下没有对应调用的孤儿 Tool Result；
- 不拆开同一工具批次；
- 不压缩尚未被 Agent 消费的最新 Tool Result；
- 当前交互与必要的执行约束不会被普通历史压缩误删。

### 5.3 分级压缩策略

建议按以下顺序处理：

1. **旧工具结果内容压缩**：对已被 Agent 消费的历史 Tool Result 优先缩短内容，保留 Tool Call / Result 结构和稳定回取引用。
2. **近期工具结果内容压缩**：仍只处理已被消费的结果；对模型马上要用的最新结果保持保护。
3. **历史语义摘要**：将较早的完整交互单元压缩为结构化 Summary，保留关键意图、决策、失败尝试、未完成事项和可回取引用。
4. **硬上限兜底**：只有在常规压缩仍无法满足预算时，才裁剪更早的历史内容；应优先保留近期上下文，并通过摘要或提示说明发生了历史裁剪。

Summary 是有损上下文，不是完整事实来源。需要精确事实时，Agent 必须能够通过 History Recall / Artifact Recall 取得原始记录。

### 5.4 不把首条用户消息视为所有会话的永久目标

普通 Conversation 可以持续讨论多个话题，因此不能把第一条 HumanMessage 永久定义为整个 Session 的 Current Objective。

- 没有 Work 时，不存在必须永久固定的单一目标。
- 有 Work 时，Work Goal 是该 Work 的结构化目标；是否需要在压缩后保留，由 Work 与 Runtime Context 机制负责。
- 历史消息可以进入 Summary 或从 Execution Conversation 中裁剪，但原始 Conversation History 必须可按需检索。
- 对长程任务的连续性保护不能依赖“第一条用户消息永远不删”这一条规则。

### 5.5 工具结果归档与回取

- 大型 Tool Result 被压缩前，应确保原始内容已经可靠保存，并生成稳定引用。
- 回取应以稳定的 Tool Invocation / Tool Call 标识定位，支持分页。
- 归档失败时，不能静默地把唯一原文副本删除；应保留原文、跳过该条压缩，或采用其他可靠持久化路径。
- 归档保留期应与产品历史、审计和长程任务回溯需求一致，不能只按短期缓存 TTL 决定。
- 对于本身就是 Artifact 的工具结果，优先保存 Artifact 引用，不要把大型内容长期塞在模型消息中。

## 6. Context Epoch 与 Checkpoint

Context Epoch 是 Execution Conversation 的逻辑压缩代次，不是供应商 Cache Key，也不需要成为独立的复杂领域对象。

它用于说明：
- 当前执行上下文属于哪次压缩后的版本；
- 压缩前后的消息范围或消息标识；
- 新 Summary 的来源范围；
- 当前保留的消息集合；
- 对应的 Checkpoint。

建议 MVP 以简单的递增代次或压缩记录实现，并与 Checkpoint / Execution Event 关联；不需要独立 Epoch 服务或单独集合。

示意：

```text
Context Session
  Epoch 0: M1 ... M50
       │ compaction
       ▼
  Epoch 1: Summary(M1 ... M35) + M36 ... M50
       │ compaction
       ▼
  Epoch 2: Summary(previous summary + M36 ... M45) + M46 ... M60
```

约束：
- Checkpoint 必须能恢复与其对应的 Execution Conversation。
- 压缩结果与 Checkpoint 的提交顺序必须明确，不能出现 Checkpoint 指向不存在或不完整的上下文版本。
- 恢复直接加载 Checkpoint 中的执行上下文，不从 Conversation History 重建 Prompt。
- History Recall 仍可在恢复后按需查询更早的原始事实。

## 7. 运行时与 Agent 的职责边界

### Runtime 负责

- Conversation History 与 Execution Conversation 的独立持久化；
- Context Session Resolution；
- Prompt / Tool Definition 的当前版本解析；
- Token Budget 与压缩触发；
- 安全压缩边界与工具配对保护；
- Summary、归档和 Recall 能力；
- Checkpoint 与 Context Epoch 对齐；
- Provider Cache 的适配与观测；
- 当前工具可用性和授权校验。

### Agent 负责

- 理解用户当前消息及连续对话；
- 理解当前注入的 Work / Plan / Todo（如果存在）；
- 根据需要调用 History Recall / Artifact Recall；
- 根据当前工具定义发起新的 Tool Call；
- 在上下文不足或历史信息不确定时主动回溯，而不是把 Summary 当成绝对事实。

Agent 不需要知道 Context Session ID、Checkpoint ID、Epoch 存储结构、数据库集合或供应商 Cache Key。

## 8. 关键决策汇总

| 主题 | 决策 |
|---|---|
| 历史与执行上下文 | 两份独立数据，独立演化 |
| 历史是否重建 Prompt | 否；模型直接延续 Execution Conversation |
| 历史回溯 | Agent 按需调用 History Recall |
| 普通聊天是否必须有 Work / Objective | 否 |
| Work Goal | 仅在相关 Work 存在时作为结构化目标 |
| Prompt 更新 | 下一次模型调用使用当前 Prompt，不迁移 Session |
| Tool Definition 更新 | 下一次模型调用使用当前定义，不迁移 Session |
| 历史 Tool Call / Result | 保留为历史事实，不做版本迁移 |
| 权限与可用性 | 工具执行时检查当前状态 |
| Todo | Agent 独立维护；恢复未结束 Execution 时注入一次，且每次准备结束执行时若仍有未完成项则提醒 Agent；提醒不是强制门控 |
| 压缩时机 | 完整交互边界或下一次模型调用前，不在 Token Stream 中途压缩 |
| 压缩边界 | 按交互单元、工具批次与消费状态识别，不只按 HumanMessage |
| Prompt Cache | 优化层，不是正确性或恢复依据 |
| Context Epoch | 轻量压缩代次，与 Checkpoint 关联，不建立复杂领域系统 |

## 9. 非目标与后续演进

当前设计不要求 MVP 一次性实现：
- 多供应商统一的缓存断点管理；
- 独立的 Context Epoch 服务；
- 完整的历史全文语义搜索；
- 多 Agent 之间共享模型消息列表；
- 复杂的 Session Migration / Prompt Revision 治理系统。

但架构需要保留扩展能力：更丰富的 History Recall、Artifact Recall、Provider Cache 观测、跨 Agent 的结构化 Work Context，以及更高级的压缩和恢复策略。

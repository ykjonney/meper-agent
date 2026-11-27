# GAP-02：Automation / Routine（自动化与例行任务）

> 状态：**Design Proposal（设计提案，待评审）**
>
> 日期：2026-11-26
>
> 本文将 GAP-02 从差距清单展开为可评审的产品设计。新增设计均为提案，不自动视为已批准的 MVP 需求。

## 1. 背景与目标

Personal Agent 不应只在用户主动发起对话时工作。用户应能够将重复性或事件驱动的工作交给 Agent，在约定时间或条件满足时自动启动，并持续查看每次执行的结果。

本设计引入 Routine 作为长期自动化规则，重点回答：
- Routine 与 Work、Execution、Workflow 的边界；
- 定时和事件触发如何统一表达；
- 每次触发是否产生新的 Work；
- Routine 的所有权、执行 Agent 和 Owner Conversation 如何确定；
- 重复触发、并发、失败和重试如何处理；
- 如何确保自动化不会扩大用户授权。

目标是先建立简单可靠的 Scheduled Routine 闭环，为未来 Event Trigger、Webhook 和高级 Workflow 留出扩展空间。

## 2. 核心概念与边界

### 2.1 Routine

Routine 是长期存在的自动化定义，描述：
- 何时触发（Trigger）；
- 触发后要完成什么工作（Work Definition / Instructions）；
- 由哪个 Agent 执行；
- 使用哪个 Owner Conversation；
- 如何处理并发、失败和重复触发；
- 如何通知用户。

Routine 本身不是一次执行，也不承载某次运行的 Task、进度或最终产物。

### 2.2 Work

Work 是每次触发后需要完成的具体工作，仍然包含目标、计划、Task、进度和验收。

**提案：每次 Routine 触发默认创建一个新的 Work。**

这样每次运行都有独立状态、执行轨迹、结果和 Artifact，失败也不会污染其他周期的工作。MVP 暂不引入“轻量执行但不创建 Work”的第二种执行模式。

### 2.3 Execution

Execution 是 Runtime 的运行边界。它负责执行某次 Work，并处理运行状态、恢复、重试和运行记录。

Execution 重试与 Routine 再次触发必须严格区分：
- Execution 重试：继续同一次 Work，不创建新的 Work。
- Routine 再次触发：产生下一次独立 Work。

### 2.4 Workflow

Workflow 描述如何完成工作，例如步骤编排、DAG、条件分支和并行执行。Routine 描述何时启动工作。

Routine 可以使用结构化 Workflow，也可以直接让 Agent 根据工作意图规划；Routine 不应依赖完整 DAG 才能工作。

## 3. 触发类型

### 3.1 Scheduled Trigger

按时间或周期触发，例如：
- 每天早上 9 点；
- 每周一检查项目进展；
- 每月最后一天生成报告；
- 每隔一段时间检查某项状态。

时间配置必须明确时区，不能依赖服务器所在时区。时区变更、夏令时和错过触发时间后的补偿行为需要由调度协议明确定义。

### 3.2 Event Trigger

由外部事件触发，例如：
- GitHub 收到新的 PR；
- Issue 状态发生变化；
- 收到符合条件的邮件；
- 日历事件即将开始；
- 外部系统通过 Webhook 通知。

Event Trigger 涉及 Connector 事件订阅、Webhook 验证、事件过滤、去重、重放保护和授权传播。建议作为同一 Routine 模型的扩展触发类型，但不纳入首个 MVP 闭环。

## 4. 所有权、执行 Agent 与 Conversation

### 4.1 所有权

建议 Routine 默认归属于 User，而不是执行 Agent。Routine 表达用户委托的长期自动化安排。

### 4.2 执行 Agent

Routine 可以指定执行 Agent：
- 默认使用 Primary Agent；
- 用户可以选择专业 Agent；
- Agent 可以参与和执行 Work，但不拥有 Routine；
- 更换执行 Agent 不应改变 Routine 的所有权和历史执行记录。

执行 Agent 必须具备完成工作所需的能力，但 Agent 可用能力不代表它自动获得所有资源和操作权限。

### 4.3 Owner Conversation

现有领域规则要求每个 Work 必须且只能归属一个 Owner Conversation。建议创建 Routine 时绑定当前 Conversation；该 Routine 每次触发创建的 Work 都归属同一个 Owner Conversation。

Routine 由其他 Agent 执行时，Work 归属仍不改变。

需要特别处理 Conversation 生命周期：归档或删除 Conversation 不能静默破坏仍然 Active 的 Routine。产品必须在允许归档/删除前提示用户暂停、停用或迁移 Routine，或提供明确的受保护归属机制。迁移规则需要单独评审，不应隐式改变 Work 的 Owner Conversation。

## 5. Routine 生命周期

建议状态：
- **Draft**：尚未启用，正在配置。
- **Active**：已启用，等待触发。
- **Paused**：用户主动暂停。
- **Disabled**：已停用，不再触发。
- **Error**：配置或持续执行问题需要用户处理。

Routine 状态与 Work 状态分离。单次 Work 失败不应自动将 Routine 标记为失败或停用。Runtime 可以根据连续失败策略将 Routine 转为 Error，或要求用户处理。

用户应能够创建、编辑、暂停、恢复和停用 Routine。删除策略、历史记录保留期限和恢复行为需结合数据治理设计进一步确定。

## 6. 每次触发的执行协议

建议每次有效触发执行以下流程：

1. Trigger 到达或事件被接收。
2. Runtime 验证 Routine 当前为 Active。
3. 检查触发是否已处理，执行幂等校验。
4. 检查并发策略，决定启动、排队或跳过。
5. 验证当前 Agent、Connector、资源和操作授权。
6. 创建本次独立 Work，并绑定 Owner Conversation、Routine 和触发记录。
7. 创建并启动 Execution。
8. Work 完成、等待用户输入或失败后，更新本次结果。
9. 按配置向用户通知，并保留可追溯执行记录。

Work 应能够反向引用来源 Routine 和本次触发记录；Routine 的历史视图则可以展示关联 Work。具体数据结构和事件协议留待领域设计阶段确定。

## 7. 幂等、并发与错过触发

### 7.1 幂等

同一个计划触发时间或同一个外部事件可能被重复投递。Runtime 必须保证重复投递不会创建多个 Work。

建议为每次逻辑触发生成稳定的 idempotency key，并对 Routine ID + trigger occurrence / event identity 建立唯一约束。

### 7.2 并发与重入

例如每 5 分钟触发一次，但上一次执行耗时 30 分钟。系统不能无条件启动多个重叠 Work。

MVP 建议默认采用 **Skip if running**：若该 Routine 上一次 Work 仍处于活动状态，则跳过本次触发并记录原因。

后续可扩展：
- Queue：排队等待；
- Parallel：允许并行执行；
- Replace / Cancel previous：取消或替换之前的运行（需要更严格的语义和安全评估）。

### 7.3 错过的触发时间

调度器停机、系统维护或用户设备离线时，可能错过计划触发。MVP 必须定义基本策略，建议默认不无限补跑所有错过的周期，而是根据最近一次有效触发窗口进行有限补偿，并记录被跳过的 occurrence。精确补偿窗口和可配置策略留待 Runtime 调度协议评审。

## 8. 失败与重试

- 瞬时运行错误：对同一次 Work / Execution 进行有限次数重试。
- 权限失效：暂停本次执行并通知用户，不应不断重试。
- 用户取消：停止当前 Work，不自动重启。
- 达到重试上限：将本次 Work 标记为失败，并保留错误和运行记录。
- 连续失败：可以通知用户并将 Routine 标记为 Error，具体阈值和自动停用策略需要后续确定。

重试不能创建新的周期 Work。只有新的逻辑触发才创建新的 Work。

## 9. 权限与 Action Governance

Routine 不是永久授权凭证。每次运行都必须使用当前有效的用户授权和组织策略。

启用前建议检查：
- 执行 Agent 是否可用；
- 所需 Connector 是否已连接；
- 目标资源是否已授权；
- 所需操作是否允许自动执行；
- 哪些操作仍需每次审批。

用户撤销授权或组织策略收紧后，后续执行必须立即遵守新的权限状态。Routine 获得某个 Connector 的读取权限，不代表它同时获得写入、删除、发送、合并等权限。

所有外部副作用继续遵循 GAP-03 Action Governance。用户接受一次建议或启用一个 Routine，也不能被解释为超出配置范围的无限授权。

## 10. 用户体验

### 10.1 创建

以自然语言为主，例如：

“每周五下午帮我总结本周的工作进展。”

Agent 将其转化为可检查的配置预览：
- Routine 名称和工作说明；
- 触发时间、周期和时区；
- 执行 Agent；
- Owner Conversation；
- 每次触发创建独立 Work 的说明；
- 所需数据源和授权；
- 并发与失败默认策略。

用户确认后启用。不要要求普通用户直接编写 Cron 表达式或配置 DAG。

### 10.2 管理与历史

用户应能查看：
- Routine 当前状态；
- 下一次触发时间；
- 最近一次触发时间；
- 历史触发记录；
- 每次 Work 的状态、结果和 Artifact；
- 失败原因和被跳过原因。

用户可以编辑、暂停、恢复和停用 Routine。编辑触发时间或工作说明时，应明确变更从何时生效，避免修改历史运行的定义。

### 10.3 Test Run

Test Run 有价值，但需要区分：
- 配置验证：检查时间、Agent、Connector 和权限，不执行实际工作；
- 手动运行：立即启动一次真实 Work；
- 沙盒测试：在不产生真实外部副作用的环境中验证。

MVP 可先提供配置验证和“立即运行一次”，并明确立即运行会创建真实 Work、可能产生外部副作用，仍受审批规则约束。完整沙盒测试后续实现。

## 11. MVP 建议范围

### 11.1 建议纳入

- 用户级 Routine。
- 自然语言创建和配置预览。
- Scheduled Trigger，支持基本周期和明确时区。
- 指定执行 Agent。
- 固定 Owner Conversation。
- 每次触发创建独立 Work。
- Routine 基础生命周期：Draft、Active、Paused、Disabled、Error。
- 触发幂等和默认防重入（Skip if running）。
- 同一次 Work / Execution 的有限重试。
- 历史触发记录、关联 Work 和结果查看。
- 当前权限检查与基础失败通知。
- 配置验证和手动立即运行。

### 11.2 暂缓实现

- Event Trigger 和通用 Webhook。
- Queue、Parallel 等高级并发策略。
- 复杂补跑策略和可视化调度日历。
- 完整沙盒 Test Run。
- Routine 模板、跨用户共享和市场。
- Routine 间依赖和编排。
- 高级 Workflow / DAG。
- 复杂企业自动化策略管理。

## 12. 初步领域模型建议

Routine 至少需要表达：
- identity：Routine ID；
- ownership：User scope 与 Owner User；
- definition：名称、工作意图和执行指令；
- trigger：触发类型、时间规则、时区或事件订阅定义；
- executor：执行 Agent；
- owner conversation：固定的 Owner Conversation；
- lifecycle：状态；
- execution policy：并发、重试和错过触发策略；
- authorization references：所需 Connector、资源和授权范围的引用；
- timestamps：创建、更新、启用和最近触发时间。

每次逻辑触发应有独立 Trigger Occurrence / Run Record，用于幂等、调度状态和审计。它关联本次 Work 与 Execution，但不应因此引入一个取代现有 Work 的新业务对象。具体是独立领域实体还是调度事件记录，留待 Runtime 设计确定。

## 13. 与既有领域边界的兼容性

- **User**：拥有 Routine。
- **Agent**：作为可配置执行者，不拥有 Routine 或 Work。
- **Conversation**：Routine 固定绑定 Owner Conversation，保证每次 Work 的归属稳定。
- **Work**：每次逻辑触发默认创建一个新 Work；Work 仍唯一归属 Owner Conversation。
- **Execution**：执行一次 Work；同一 Work 的重试不产生新 Work。
- **Workflow**：可选的执行编排方式，不负责触发调度。
- **Project**：Routine 可以在工作内容中访问授权 Project 资源，但本提案不将 Routine 默认归属 Project。
- **Action Governance**：每次运行都遵循当前权限和审批策略。
- **Goal**：Routine 可以帮助推进某个 Goal，但 Routine 与 Goal 是不同对象；一次 Routine 可不关联 Goal。

## 14. 待评审问题

1. Routine 是否默认 User-owned？本提案建议是。
2. Routine 创建时是否固定绑定当前 Owner Conversation？本提案建议是，以保持 Work 归属规则稳定。
3. 每次触发是否默认创建新 Work？本提案建议是。
4. MVP 是否只做 Scheduled Trigger？本提案建议是。
5. 默认并发策略是否采用 Skip if running？本提案建议是。
6. Routine 是否指定执行 Agent，默认 Primary Agent？本提案建议是。
7. Conversation 归档或删除时，如何保护关联的 Active Routine？本提案建议禁止静默破坏，要求先处理 Routine。
8. MVP 是否提供“立即运行一次”？本提案建议提供，并明确它会创建真实 Work。

## 15. 验收标准（产品层）

- 用户可以通过自然语言创建并预览一个 Scheduled Routine。
- 用户能明确看到触发时间和时区。
- Routine 可以指定执行 Agent，但所有权仍属于用户。
- 每次逻辑触发最多创建一个 Work。
- 每次周期触发创建独立 Work，且 Work 的 Owner Conversation 稳定。
- 同一 Work 的 Execution 重试不会创建额外 Work。
- 上一次 Work 未结束时，默认不会无条件并发启动新 Work。
- 用户可以暂停、恢复和停用 Routine。
- 用户可以查看历史触发、关联 Work、结果和失败原因。
- 授权撤销或策略收紧会影响后续运行。
- Routine 不会绕过 Action Governance。
- Event Trigger 和高级 Workflow 不会成为完成首个 Scheduled Routine 闭环的前置条件。

## 16. 后续依赖

- GAP-03：Action Governance，明确自动化操作的授权、审批和审计。
- GAP-04：Artifact 工作台，完善每次 Routine Work 的成果查看。
- GAP-05：Workspace / Sandbox，支持更完整的自动化执行环境。
- GAP-10：Usage / Cost / Observability，提供 Routine 的成本和运行可观测性。

---

**提案结论：** 引入 User-owned 的 Routine 作为长期自动化定义。Routine 决定何时启动什么工作；每次触发默认创建一个归属于固定 Owner Conversation 的独立 Work；Execution 负责运行和恢复；Workflow 是可选的执行编排方式。MVP 聚焦 Scheduled Routine 的可靠闭环，Event Trigger、Webhook 和高级 DAG 后续扩展。

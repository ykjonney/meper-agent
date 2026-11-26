# GAP-01：Personal Agent 主动服务与长期目标管理

> 状态：**Design Proposal（设计提案，待评审）**
>
> 日期：2026-11-26
>
> 本文将 GAP-01 从差距清单展开为可评审的产品设计。除已有明确决策外，本文中的新增设计均为提案，不自动视为已批准的 MVP 需求。

## 1. 背景与目标

当前产品已经围绕 Agent、Conversation、Work、Task、Execution 和 Project 建立了基础概念，但产品体验仍主要由用户发起请求驱动。Personal Agent 的长期价值不仅是完成单次任务，还应帮助用户持续实现重要目标：理解用户想要实现的状态，结合实际工作识别进展，在合适的时机提出有依据的建议，并在获得授权后推进工作。

本设计希望回答：

- 如何表达用户的长期目标？
- Goal 与 Work、Task 如何分工？
- Agent 如何从日常对话中识别目标？
- 如何利用真实工作结果跟踪进展？
- 主动建议、Follow-up 和后台 Monitoring 如何划分？
- 如何保证主动服务可控、可解释且不越权？

设计目标是建立轻量、可演进的 Goal 能力，而不是在 MVP 阶段建设完整的个人 OKR、项目管理或自动化平台。

## 2. 核心概念

### 2.1 Goal

Goal 表示用户希望实现的长期状态或方向，回答“希望实现什么”。

示例：
- 建立一个可持续迭代的个人 Agent 产品。
- 提升团队研发交付效率。
- 掌握某项专业技能。

Goal 具有持续性，但不要求一定有截止日期、量化指标或预先拆分的里程碑。Goal 不等同于一个大型 Work，也不应被强制转化为待办清单。

### 2.2 Work

Work 表示为了实现某个目标，或响应用户某次请求，而持续推进的一项工作，回答“正在做什么”。

- 一个 Goal 可以关联多个 Work。
- 一个 Work 可以不关联任何 Goal，例如临时请求或独立任务。
- 一个 Work 可以支持多个 Goal，但关联关系需要有明确语义，不能仅凭主题相似自动认定。
- Goal 与 Work 的关联不改变 Work 的 Owner Conversation。

Work 仍唯一归属一个 Owner Conversation；Work 不归属于执行 Agent。Agent 可以参与 Work，但不因此取得 Work 或 Goal 的所有权。

### 2.3 Task

Task 是 Work 内可执行、可跟踪和可验收的步骤，回答“下一步做什么”。

Task 不直接承担长期目标管理职责。Goal 不需要复制 Work 内的 Task。

### 2.4 关系

```text
User
 └── Goals
      ├── Goal A
      │    ├── Work 1 (Owner Conversation X)
      │    │    └── Tasks
      │    └── Work 2 (Owner Conversation Y)
      └── Goal B
           └── Work 2 (可选的多目标关联)

Agent / Execution 可以参与 Work，但不拥有 Goal 或改变 Work 归属。
```

## 3. Goal 的归属与管理

### 3.1 默认归属

MVP 建议 Goal 默认归属于 User，而不是 Primary Agent 或某个专业 Agent。

理由：
- Goal 描述的是用户希望实现的事情，不应随着 Agent 切换而改变归属。
- Primary Agent 是默认的理解、协调和管理入口，不是 Goal 的所有者。
- 专业 Agent 可以基于授权读取与其工作相关的 Goal 信息，并参与关联 Work。
- 用户未来更换 Primary Agent 时，Goal 仍然持续存在。

### 3.2 Scope 扩展

MVP 先实现 User scope。领域模型应避免将归属字段设计成只能容纳 User，以便未来支持 Project 或 Team scope；但不在本阶段引入完整的多层级 Goal 继承和共享规则。

## 4. Goal 的创建与变更

### 4.1 创建来源

MVP 建议支持两种来源：

1. **用户明确创建**：用户直接要求记录或跟踪某个长期目标。
2. **Agent 提议**：Agent 从长期对话或持续工作中识别出可能的目标，向用户说明判断依据并请求确认。

未来可考虑从文档或外部系统导入。

### 4.2 Agent 提议原则

Agent 不应把每个重要话题、单次请求或大型 Work 自动升级为 Goal。提议前应判断：
- 是否具有持续性，而非一次性请求；
- 是否表达了用户希望实现的状态或方向；
- 是否会对未来的工作建议产生实际帮助；
- 是否与已有 Goal 重复或冲突。

Agent 提议时应简要说明识别依据。用户可以接受、修改或拒绝；拒绝后不应反复以相同理由骚扰用户。

### 4.3 变更治理

Agent 可以提出 Goal 描述、状态和关联关系的调整建议。建议的处理方式应结合变更风险：
- 用户明确指令可直接执行相应变更。
- Agent 推断出的重要目标变更、完成或放弃，应请求用户确认。
- 自动生成的进展观察应保留为观察或建议，不应静默覆盖用户定义的目标。

该机制与 Project Memory 的“Agent 提议、Runtime 管理”原则相容，但 Goal 与 Memory 是不同领域对象，不应复用同一套存储语义。

## 5. Goal 生命周期与状态

MVP 建议采用少量清晰状态：

- **Active**：当前持续关注和推进。
- **Paused**：用户暂时不希望跟踪或推进。
- **Achieved**：用户确认目标已实现。
- **Abandoned**：用户确认不再追求该目标。

不建议使用“百分比完成”作为 Goal 的唯一状态表达。Goal 可以有开始时间、可选目标日期和简短描述，但不强制要求截止日期、优先级评分或量化指标。

Goal 的状态由用户意图主导。Agent 可以根据证据建议状态变更，但不能仅因关联 Work 全部完成就自动将 Goal 标记为 Achieved。

## 6. 进展跟踪与证据

### 6.1 信息来源

Goal 进展可以参考：
- 关联 Work 的状态与近期活动；
- Work 中 Task 的完成情况；
- Artifact、Evidence 和 Verification；
- 用户在 Conversation 中明确提供的新信息；
- 用户明确授权的外部数据源。

### 6.2 不以 Work 数量计算完成度

不应采用“已完成 Work 数量 / 总 Work 数量”作为 Goal 完成度。长期目标的 Work 集合会不断变化，Work 的规模和价值也不同。

MVP 建议展示：
- 当前状态；
- 最近进展摘要；
- 关联 Work 及其状态；
- 已形成的成果与证据；
- 当前阻塞或不确定事项；
- Agent 对下一步的建议。

Agent 的总结应区分事实、推断和建议，并尽可能链接到对应 Work 或 Artifact。证据不足时应明确说明未知，不得生成看似精确的进度百分比。

### 6.3 多目标关联

允许一个 Work 支持多个 Goal，但应避免无差别自动关联。MVP 可先由用户明确关联，或由 Agent 提议并由用户确认。后续再评估自动关联的置信度和治理方式。

## 7. 主动服务模型

主动服务建议拆为三个层次：

1. **发现（Discover）**：识别目标变化、工作停滞、阻塞或值得关注的信息。
2. **建议（Suggest）**：向用户说明观察依据，并提出可选的下一步。
3. **执行（Act）**：用户接受或已有明确授权后，创建/恢复 Work 或执行具体操作。

发现和建议不等于执行授权。用户接受一条建议，也不意味着 Agent 获得超出该建议范围的长期权限。

### 7.1 Follow-up

Follow-up 关注已有事项是否需要继续处理，例如：
- Work 长时间没有进展；
- Work 被阻塞或等待用户输入；
- 用户承诺稍后提供信息；
- 已有执行结果需要用户确认。

MVP 可依托现有 Work 状态、Execution 结果和会话上下文提供基础 Follow-up，不必先建设通用调度平台。

### 7.2 Proactive Suggestions

Proactive Suggestions 是 Agent 基于 Goal、Work 和已授权信息提出的建议，例如：
- 某个目标长期没有相关工作推进；
- 一个 Work 的成果揭示了新的必要步骤；
- 目标与当前计划出现冲突；
- 近期工作可能需要调整优先级。

建议应包含简明原因、相关证据和可执行的后续动作。用户可以接受、拒绝或暂时忽略。

### 7.3 Monitoring

Monitoring 指持续或周期性检查外部信息源或事件，例如 GitHub、邮件、日历或其他 Connector 数据。

这通常需要 Scheduled Routine、Event Trigger、授权管理、执行历史和失败恢复能力。它与基于已有上下文的 Goal Review 不同，建议放到 GAP-02 Automation / Routine 及相关 Connector 设计中处理。

## 8. 用户控制与安全边界

主动服务必须尊重用户控制权。设计至少预留：

- 暂停或恢复单个 Goal；
- 忽略、接受或拒绝 Agent 建议；
- 控制主动建议的类别和频率；
- 说明建议的触发原因和依据；
- 对外部数据源 Monitoring 单独授权；
- 对外部副作用操作遵守 Action Governance；
- 用户可以随时撤销已有授权。

MVP 可先提供基础控制，不必建设完整的通知偏好中心。后台监控、外部触发和主动执行不能仅凭 Goal 存在而默认启用。

## 9. MVP 建议范围

### 9.1 建议纳入

- User scope 的 Goal 创建、编辑、暂停、恢复、完成和放弃。
- 用户明确创建 Goal。
- Agent 从对话中提议 Goal，并由用户确认。
- Goal 与一个或多个 Work 建立关联。
- 查看 Goal 的关联 Work、近期进展和成果证据。
- Agent 基于已有 Work、Artifact 和 Conversation 信息生成进展总结。
- 基础 Follow-up 和有依据的 Proactive Suggestions。
- 用户可以接受、拒绝或忽略建议。

### 9.2 暂缓实现

- 复杂目标树、OKR/KPI、量化评分和自动完成度预测。
- 完整里程碑依赖图与资源规划。
- 通用 Scheduled Routine 和 Event Trigger。
- 持续外部 Monitoring 和机会检测。
- 多渠道通知编排。
- Team Goal、组织目标和跨组织目标。
- 无需用户确认的自主目标创建或目标放弃。

“暂缓实现”不代表产品永远不做；领域模型和接口应避免阻断这些后续能力。

## 10. 初步领域模型建议

建议 MVP 的 Goal 至少表达以下信息：

- identity：Goal ID；
- ownership：User scope 与 Owner User；
- content：标题、描述；
- lifecycle：状态；
- dates：创建时间、更新时间，可选目标日期；
- relationships：关联 Work；
- provenance：创建来源（用户明确创建或 Agent 提议）；
- review context：最近一次进展摘要或观察的来源引用。

不建议在 MVP 中把 Agent 的自然语言总结直接当作唯一事实状态。关联 Work、Artifact 和 Evidence 应保留可追溯引用；具体持久化结构、事件模型和索引方式留待领域模型设计阶段确定。

## 11. 与现有领域边界的兼容性

- **Agent**：Primary Agent 是默认管理入口；专业 Agent 在授权范围内参与。
- **Conversation**：Goal 不属于某个 Conversation。
- **Work**：Work 仍唯一归属 Owner Conversation。
- **Execution**：Execution 是运行边界，不因 Goal 引入新的 Work Run 概念。
- **Project**：Project 仍是跨 Conversation 的协作边界；本阶段不将 Goal 默认归属 Project。
- **Artifact / Evidence / Verification**：作为 Goal 进展判断的事实依据或引用来源，不被 Goal 替代。
- **Memory**：Goal 是明确的目标对象，不等同于从对话提炼出的记忆。

## 12. 待评审问题

以下问题需要在进入实现或正式领域模型前确认：

1. User scope 是否作为 MVP 唯一 Goal scope？
2. Agent 提议 Goal 后，是否一律要求用户确认？本提案建议是。
3. 一个 Work 关联多个 Goal 是否进入 MVP？本提案建议支持，但先采用显式关联或确认式提议。
4. Goal 的 Active / Paused / Achieved / Abandoned 状态是否足够？
5. 基础 Follow-up 是否进入 MVP，还是先只做 Goal 与 Work 关联和进展总结？
6. 用户是否需要在 MVP 中配置主动建议频率，还是先提供全局开关和单个 Goal 暂停？

## 13. 验收标准（产品层）

- 用户能通过自然语言创建一个长期 Goal。
- Agent 能在合适场景提出 Goal，但不会未经确认擅自建立推断目标。
- 用户可以查看 Goal 及其关联 Work。
- Work 的 Owner Conversation 不因关联 Goal 而改变。
- Goal 进展摘要能引用实际工作或产物，不将推断伪装成事实。
- Agent 不会仅因 Work 完成而擅自宣布 Goal 已实现。
- 用户可以暂停 Goal，并停止围绕该 Goal 的主动跟进。
- Agent 的建议与实际执行授权清晰分离。
- 外部 Monitoring 和副作用操作遵循独立授权与治理机制。

## 14. 后续依赖

- GAP-02：Automation / Routine，负责周期性与事件驱动触发。
- GAP-03：Action Governance，负责主动执行中的授权、审批和审计。
- GAP-04：Artifact 工作台，增强成果的查看、引用和持续编辑。
- GAP-07：Personal Memory，增强对用户长期背景和偏好的理解。

---

**提案结论：** 引入轻量、User-owned 的 Goal 作为长期方向对象；Work 继续作为持续推进的工作单元；Agent 通过真实工作和证据理解进展，并将主动服务拆分为发现、建议和授权后执行。MVP 聚焦 Goal 与 Work 的关联、可追溯进展和基础 Follow-up，不提前建设通用自动化与后台 Monitoring 系统。

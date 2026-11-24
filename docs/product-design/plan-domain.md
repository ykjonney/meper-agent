# Plan Domain：目标导向规划与任务管理

> 状态：**Proposed（领域设计基线，部分原则已确认）**
>
> 本文定义 Work Plan、Plan Version、Milestone、Task、Dependency、Verification 与 Agent Local Plan 的产品领域边界。
>
> 本文描述目标产品模型，不代表当前代码已经实现。与统一 Execution、Step、Checkpoint、ToolInvocation 和恢复协议的关系见 [Domain Model Overview](./domain-model.md) §5、§8 及 [Execution Model Proposal](../EXECUTION-MODEL-PROPOSAL.md)。

## 1. Purpose and Principles

Plan 是 Agent Runtime 的一等能力：它把业务目标转化为可执行、可分配、可追踪、可验证并可调整的工作方案。

Plan 不是 Todo List，也不是 Workflow/DAG 的别名：

- **Work** 定义业务目标、约束、Owner 和最终验收责任。
- **Work Run** 表示一次实际推进 Work 的业务执行周期。
- **Plan** 描述该 Work Run 当前采用的整体执行方案。
- **Task** 是 Plan 中可分配、可追踪和可验证的基本工作单元；Todo 是 Task 面向用户的清单视图。
- **Execution** 承载 Agent、Workflow 或工具相关的实际技术运行。
- **Verification** 判断 Task 或 Work 是否满足其验收条件。
- **Workflow** 表达需要确定性执行和强制 Gate 的可复用流程，不取代 Agent 的目标导向规划。

核心原则：

1. Plan 管理“准备如何实现目标”，Execution 记录“实际发生了什么”。
2. Task 不等于模型调用、Execution、Workflow Step 或 Tool Invocation；一个 Task 可以跨越多个 Execution。
3. Plan 状态、Task 状态和 Execution 状态各自有权威来源，不重复维护同一事实。
4. Agent 可以提出计划和完成声明，但不能修改用户明确的目标、约束、审批要求或验收标准。
5. 计划结构变化必须可追溯；重新规划不能抹去已发生的执行事实、完成任务和证据。
6. Skill 可以提供 Planning Guidance、Procedure 和 Verification Rules，但 Plan 的持久化、版本和状态由平台管理。
7. Todo 是交互投影，不是独立领域事实源。

## 2. Domain Relationship

```text
Work
└── Work Run
    └── Work Plan (stable identity)
        ├── Plan Version (immutable plan-structure snapshot)
        │   ├── Goal / Constraints
        │   ├── Acceptance Criteria
        │   ├── Milestones
        │   ├── Tasks
        │   └── Dependencies
        └── Active Plan Version

Task
├── Assignment / Assigned Agent
├── Execution(s)
├── Delegation(s)
├── Evidence
└── Verification(s)

Delegated Task
└── Delegation
    └── Agent Local Plan
        ├── Local Tasks
        ├── Local Executions
        └── Handoff Result / Evidence
```

### 2.1 Work Run and Plan Cardinality

**Confirmed direction：**

- 一个 Work 可以有多个 Work Run。
- 一个 Work Run 有一个稳定的 Work Plan 身份。
- 一个 Work Plan 可以有多个 Plan Version。
- 同一时刻，一个 Work Plan 只有一个 Active Plan Version。
- 新 Plan Version 替代旧版本成为 Active Version；旧版本保留为历史，不被覆盖。

这里的“一个 Plan”指同一 Work Run 的主计划身份，不限制未来引入独立子计划或其他计划类型；如需多个并行、互相独立的主计划，必须另行定义协调和验收语义。

### 2.2 Work Plan and Agent Local Plan

Work Plan 管理 Work Run 的整体目标、任务分解、优先级、依赖、责任分配和验收进度。

Agent Local Plan 是某个 Agent Worker 为完成被分配或委派的工作而制定的局部方案。它必须关联：
- 所属 Work Run；
- 对应的父 Task；
- 对应的 Delegation（若由委派产生）；
- 负责执行的 Agent / Worker Execution。

Local Task 的完成只表示局部工作完成，不自动使父 Task Completed。父 Task 仍需按自己的 Acceptance Criteria 完成验证。

**Proposed：** Work Plan 与 Agent Local Plan 复用相同的 Plan / Plan Version / Task 概念，通过 scope 和 parent-task / execution 关联表达层级，避免维护两套不兼容的计划系统。MVP 可先支持一层委派和 Local Plan。

## 3. Core Objects

### 3.1 Plan

Plan 是一个稳定的计划身份，通常由一个 Work Run 持有。

建议职责：
- 引用所属 Work Run；
- 指向当前 Active Plan Version；
- 维护计划级执行状态；
- 记录创建来源、规划者、触发原因和生命周期时间；
- 关联计划版本和重新规划历史。

Plan 不保存 Execution Lease、Tool Invocation 状态或 Sandbox 资源状态。

### 3.2 Plan Version

Plan Version 是某一时刻计划结构的不可变快照。

建议内容：
- Plan Goal：本计划要实现的目标，必须与 Work 目标一致；
- Constraints：执行约束和不可违反条件；
- Acceptance Criteria：计划层面的验收标准；
- Milestones、Tasks 和 Dependencies；
- 任务分配和计划策略的版本化引用；
- Planner / Agent / Skill Guidance 的来源引用；
- Replan Reason：本版本产生的原因及触发证据。

计划结构变化时创建新版本。Task 的运行进度、Execution 事件和工具调用结果不是 Plan Version 内容，不应因进度变化而不断生成新版本。

### 3.3 Milestone

Milestone 表示一个可识别的阶段性目标，用于组织和呈现一组 Task，并定义阶段完成条件。

**Proposed：** Milestone 在领域语义上独立，但 MVP 可以采用 Plan Version 内的轻量实体或 Task Group 实现，不要求独立服务或独立集合。Milestone 完成必须基于其必要 Task 和阶段验收条件，而不是简单统计 Todo 勾选数。

### 3.4 Task

Task 是 Plan 中最小的业务工作单元。它表达需要完成的工作，而不是执行它的进程或一次模型调用。

建议字段/关系：
- stable task identity；
- title、description、purpose；
- acceptance criteria；
- dependency references；
- milestone reference（可选）；
- assignee / assigned Agent（可选）；
- priority、required / optional 标记（如适用）；
- status；
- Execution / Delegation references；
- Evidence 和 Verification references；
- result summary；
- created / updated timestamps。

Task 应具有稳定身份，以便跨 Plan Version 追踪。新版本可以保留、调整、拆分、替换或取消未完成 Task；拆分和替换必须保留来源关系，例如 `derived_from`、`supersedes`，不能把旧 Task 的执行历史直接挪给新 Task。

**Open：** Task 是否允许多个并行 Assignee、任务锁定和显式协作者，需结合 Assignment Domain 进一步确定。MVP 建议一个主要负责 Agent / User，可有多个 Execution 参与。

### 3.5 Dependency

Dependency 表达 Task 之间的先后或条件关系。

MVP 建议先支持基础的 finish-to-start 依赖：前置 Task 达到指定可接受状态后，后置 Task 才可进入 Ready。依赖必须防止环路，并能解释阻塞原因。

复杂依赖类型、动态 DAG 调度、跨 Work / 跨 Work Run 依赖暂缓；底层关系不应限制未来扩展。

### 3.6 Acceptance Criteria

Acceptance Criteria 描述可判断的完成条件，可分别作用于 Work、Plan、Milestone 和 Task。

规则：
- Work 的目标、用户明确约束和最终验收标准是上层权威要求。
- Agent 可以细化或补充 Task 级验收条件，但不能削弱或改写上层要求。
- 验收条件应尽量可观察、可测试，并能关联验证方式。
- 如果 Agent 发现要求冲突或不可实现，应创建 Interaction / 请求澄清，而不是自行更改要求。

### 3.7 Evidence and Verification

Evidence 是支持执行结果或完成结论的可追溯材料，例如 Artifact Version、测试报告、工具调用结果、日志、数据来源、外部资源引用或人工确认记录。

Verification 是针对 Acceptance Criteria 执行的检查，并记录：
- 验证对象（Task / Milestone / Plan / Work）；
- 适用的 Acceptance Criteria；
- Verification Policy / Method；
- 验证者（系统验证器、Agent、User 或授权主体）；
- 输入 Evidence；
- 结果、时间和失败原因。

Evidence 可以引用 Artifact、Execution Event 或 ToolInvocation 结果；不应把大文件或执行日志复制进 Plan 文档。

## 4. Task Lifecycle

以下状态机为 **Proposed**，需要与现有 Task / Execution 状态和 UI 投影进一步对齐。

| Status | Meaning |
|---|---|
| Draft | 已创建，尚未满足进入执行队列的条件 |
| Ready | 依赖和前置条件满足，可以执行 |
| In Progress | 正在推进，可能关联一个或多个 Execution |
| Blocked | 因外部条件、Interaction 或依赖问题无法继续 |
| Verifying | Agent 已提交结果，正在执行验收 |
| Completed | 按适用 Verification Policy 验收通过 |
| Failed | 按当前策略无法继续，需重试、重新规划或人工处理 |
| Cancelled | 经授权取消 |
| Skipped | 计划调整后确认不再需要执行 |

状态规则：
- Task 创建后可为 Draft；被纳入 Active Plan 且前置条件满足时成为 Ready。
- Ready 被选中执行后进入 In Progress。
- 依赖、权限、资源或用户输入问题可使 Task 进入 Blocked。
- Agent 的“已完成”是 completion claim，不是 Completed 状态；提交结果和证据后进入 Verifying。
- Verification 通过后才能进入 Completed。
- Verification 未通过时可回到 In Progress / Ready、进入 Blocked，或按策略进入 Failed。
- Cancelled / Skipped 必须记录原因和操作者；已完成任务不能因重新规划被静默改为 Skipped。
- 允许的状态转换由平台领域规则校验，不由模型任意写入。

## 5. Risk-based Verification Policy

**Confirmed direction：** 采用风险分级验证，而不是所有任务一律人工验收，也不是所有任务都由 Agent 自我声明完成。

每个 Task 可关联 Verification Policy，至少表达：
- 风险级别或风险标签；
- 必需验证方式；
- 需要的 Evidence 类型；
- 是否允许 Agent 自检；
- 是否要求独立验证器；
- 是否需要人工审批 / 确认；
- 失败后的处理策略。

示例：

| Task type | Baseline verification |
|---|---|
| 普通信息收集 | 检查结果结构和来源证据；低风险场景可由 Agent 自检 |
| 代码修改 | 测试、Lint、静态检查或 Review 证据，按任务风险组合 |
| 数据分析 | 检查数据来源、计算过程、关键结果和可复现性 |
| 生产环境操作 | 执行权限与 Policy 检查；按风险强制审批和操作后验证 |
| 企业关键决策 | 授权主体确认；Agent 总结不能代替正式决策 |

强制规则：
1. Agent 可以提交 completion claim、result 和 Evidence，但不能绕过 Policy。
2. Verification Policy 指定的 Gate 必须由平台、验证器或授权人工主体执行。
3. Verification 结果必须可追溯到具体 Evidence 和 Acceptance Criteria。
4. Verification 通过不代表 Work 自动完成；Work 还必须满足自身最终 Acceptance Criteria。
5. 权限、审批和安全 Policy 优先于 Skill 建议或 Planner 决策。

## 6. Replanning and Versioning

Replanning 是 Agent Runtime 的正常能力，不是直接编辑 Todo 列表。

触发原因可以包括：
- 新证据改变原有判断；
- 某项任务不可行或依赖不可获得；
- Verification 失败；
- 用户修改目标或约束；
- 资源、权限或预算条件变化；
- 子 Agent 返回结果要求调整后续工作。

Replanning 流程：
1. 记录触发原因和相关 Evidence / Event。
2. 读取当前 Active Plan Version、Task 状态、Execution / Delegation 状态、Interaction 和已有结果。
3. 生成新的 Plan Version，并说明变化。
4. 校验新计划没有削弱 Work 的目标、约束和 Acceptance Criteria。
5. 建立新旧 Task 的保留、拆分、替代、取消关系。
6. 原子地将新版本设为 Active Version。
7. 将新版本中的 Ready Task 交给 Runtime 继续推进。

历史规则：
- 已完成 Task、Execution、Delegation、ToolInvocation 和 Evidence 是历史事实，不能被新版本覆盖。
- 运行中的 Task 不得在没有协调策略的情况下被新版本静默删除；需要先等待、取消、暂停或显式迁移。
- 旧 Plan Version 保留，标记为 Superseded / Historical；Plan 的执行状态与 Version 的采用状态分开管理。
- Plan Version 变更不代表创建新的 Work Run；只有新的业务执行周期才创建新的 Work Run。

**Confirmed（PD-022）：** Task 采用 Task Identity、Task Revision、Task Runtime State 三层分离。Identity 在版本间保持稳定；Revision 不可变；Runtime State 单独维护当前状态和活动 Attempt 指针。Plan Version 通过显式 PlanVersionTask 关系引用 Task Revision。结构性变化通过新 Revision 或新 Task + lineage relation 表达。

### 6.1 Task Attempt and Revision Binding

**Confirmed（PD-031）：** 一个 Task 默认最多允许一个活动业务 Attempt。一个 Attempt 可以关联多个 Execution / Delegation，以支持同一业务尝试中的多 Agent 协作。Attempt 不等于 Execution；Worker 崩溃恢复同一 Execution 不创建新 Attempt。Attempt 的状态机、Coordinator、数据库约束和 Recovery 协议见 [Plan Runtime Integration & Recovery Protocol](./plan-runtime-integration.md)。

## 7. Runtime, Execution and Recovery Integration

Plan Domain 与 Execution Domain 协作，不取代 Execution Domain。

| Plan concept | Runtime / Execution relationship |
|---|---|
| Plan / Plan Version | 定义当前目标导向执行方案；版本固定并可追溯 |
| Task | 可关联多个 Execution / Delegation；不是 Execution 的别名 |
| Task status | 业务工作进度；不取代 Execution status |
| Dependency | 决定 Task 是否 Ready；不直接承担资源调度 |
| Evidence | 引用 Execution、ToolInvocation、Artifact 等事实 |
| Verification | 消费 Evidence，产生可追溯的验收结论 |
| Checkpoint | 保存恢复所需的运行进度，不复制 Plan 作为唯一状态源 |

恢复时，Runtime 至少需要重建：
- Work Run 与 Active Plan Version；
- Task 状态、依赖和 Assignment；
- 未完成 Task 对应的 Execution / Delegation；
- 当前 Interaction、等待原因和审批状态；
- Evidence 与 Verification 记录；
- ToolInvocation 的已提交、失败或 UNKNOWN 副作用状态。

Checkpoint 负责记录一致性恢复位置；Plan / Task 持久化记录业务计划与进度；Execution / ToolInvocation 记录运行事实和外部副作用。三者通过稳定 ID 和事件关联，不互相复制成多个权威状态源。

Task 重试与 Worker 恢复也必须区分：
- Worker 崩溃、Lease 接管或消息重投递：恢复同一 Execution，不自动重置 Task。
- 同一 Task 的局部 Step / Tool 重试：遵循 Execution 的幂等和副作用裁决协议。
- 业务策略决定重新执行整个 Task：创建新的 Execution / Attempt 关联，保留之前结果和失败证据。
- ToolInvocation 结果 UNKNOWN 时不得盲目重试；先查询外部状态、使用幂等键或进入人工裁决。

## 8. Skill, Workflow and Delegation Integration

### 8.1 Skill

Skill 可提供：
- Planning Guidance：建议如何拆分目标、排序和选择策略；
- Procedure：Task 内部的专业执行步骤；
- Completion Rules：专业完成条件；
- Verification Rules：需要哪些证据和检查。

Skill 不负责成为平台 Plan 状态的唯一存储，也不应自行覆盖 Work 的用户验收要求。Skill 的 Required / Recommended / Conditional 指引与平台强制 Policy Gate 必须区分。

### 8.2 Workflow

Workflow Definition 是可复用的确定性流程；Plan 是 Agent 为达成目标动态生成和调整的方案。

Task 可以由 Agent 执行，也可以绑定或触发 Workflow Execution。Workflow 的强制 Gate 必须由 Workflow Engine / Runtime 执行，不能仅依赖模型遵守 Skill 文本。

### 8.3 Delegation

父 Agent 的 Work Plan 维护整体 Task；委派时将一个 Task 或其明确子范围交给目标 Agent。

子 Agent 可以生成 Agent Local Plan，并在其范围内拆分 Local Tasks。父 Task 通过 Delegation Handoff 接收：
- 结构化结果；
- 完成声明；
- Evidence；
- Local Verification 结果；
- 未完成事项和阻塞原因。

父 Task 是否 Completed 仍由父级 Acceptance Criteria 和 Verification Policy 决定。MVP 先支持有限层级和显式绑定的委派，不实现无限嵌套或动态 Agent Discovery。

## 9. MVP and Deferred Scope

### MVP

- Work Run 关联稳定 Work Plan；
- Plan Version 与单一 Active Version；
- Plan Goal、Constraints 和 Acceptance Criteria；
- Task 基础生命周期与持久化；
- 基础 Milestone / Task Group；
- 基础 Task Dependencies（无环、优先 finish-to-start）；
- Task Assignment；
- Completion Claim、Evidence 和 Verification；
- 风险分级 Verification Policy 的基础规则；
- Replanning、Task lineage 和历史版本；
- Work Plan 与 Agent Local Plan 的父子关联；
- 与 Execution、Delegation、Checkpoint、Recovery 的稳定关联；
- Todo List 作为 Task 的 UI 投影。

### Deferred

- 复杂 DAG 可视化与动态并行调度；
- 跨 Work / 跨 Work Run 依赖；
- 多层嵌套 Agent Local Plan 的复杂聚合；
- 自动计划优化、成本/时间最优调度；
- 高级验证器市场和复杂验证工作流；
- 跨多个 Work 的 Portfolio Planning。

Deferred 表示暂缓实现，不代表产品不做。MVP 不需要复杂 DAG UI，但底层 Dependency 和 Plan Version 设计不得阻断未来扩展。

## 10. Open Questions

2. Milestone 在 MVP 中采用嵌入式结构还是独立持久化对象？
3. Task 是否允许多个并行 Assignee，以及如何表达共同负责、协作和审阅？
4. Task 状态在 Plan Version 变化时如何投影，尤其是运行中 Task 的暂停、迁移和取消策略？
5. Verification Policy 的风险等级、默认策略和组织可配置边界如何定义？
6. Verification 由 Agent 自检、独立 Agent、确定性验证器或人工执行时，如何定义独立性和防止自我验收？
7. Work 最终验收与 Work Run 完成之间的状态转换和重开规则是什么？
8. Agent Local Plan 是否复用同一 Plan 持久化模型，以及 Local Task 如何映射父 Task 的验收范围？
8. 现有执行架构 Task 与产品 Plan Task 的数据模型、API 和迁移边界是什么？

在这些问题明确前，除已确认的原则外，本文中的实体拆分和状态细节均为 Proposed，不应直接视为实现约束。

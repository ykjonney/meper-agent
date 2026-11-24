# Domain Model Overview

> 状态：**Proposed（跨领域关系基线，待评审）**
>
> 本文把产品战略与 Agent Domain 放到同一张业务对象关系图中，明确 Organization、Project、Collaboration Space、Work、Agent、Execution 和 Artifact 的职责边界。
>
> 本文是目标产品领域模型，不是当前代码实现说明。与既有执行架构提案的关系见 §8。

## 1. Modeling Principles

### 1.1 Business Objects and Runtime Objects Are Different

产品领域对象表达企业要做什么、谁参与、如何协作、产生什么成果；执行领域对象表达平台如何可靠地运行、观察和恢复一次执行。

不能用一个 Task / Execution 对象同时承担业务目标、协作关系、执行状态、资源租约和恢复检查点。

### 1.2 Association Is Not Ownership or Authorization

对象之间的关联、可见性、所有权和访问授权必须分开：

- 关联表示业务上下文关系。
- Owner 表示归属和管理责任。
- Membership 表示参与某个协作范围。
- Access Grant / Policy 表示实际可执行的访问权限。
- Mention、Assignment 或 Artifact Link 都不自动授予资源访问权限。

### 1.3 Avoid Rigid Parent-Child Trees

Project、Space、Work 和 Artifact 不是严格树形层级。一个 Project 可以关联多个 Space 和 Work；一个 Work 可以在多个 Space 中被讨论；一个 Artifact 可以同时成为 Work 交付物和 Project 参考资料。

用显式关联表达关系，不通过移动对象或改变父级来隐式改变归属和权限。

### 1.4 Keep the MVP Small Without Closing the Model

MVP 只实现核心闭环需要的关系和状态。高级协作、动态 DAG、多 Agent 编排、Marketplace 和更多 Sandbox Provider 暂缓，不代表产品不做。不要为了未来可能性提前引入没有明确语义的通用对象。

## 2. Core Domain Map

### 2.1 Conceptual Relationship Diagram

~~~mermaid
flowchart TB
  Org[Organization]
  User[User / Principal]
  Team[Team]
  Project[Project]
  Space[Collaboration Space]
  Agent[Agent Definition + Version]
  Participation[Agent Participation]
  Work[Work]
  Assignment[Assignment]
  Run[Work Run]
  Execution[Execution]
  Delegation[Delegation]
  Interaction[Interaction]
  Message[Message / Thread]
  Proposal[Proposal]
  Decision[Decision]
  Artifact[Artifact + Version]
  Link[Artifact Link]
  Memory[Scoped Memory / Context]

  Org --> Team
  Org --> Project
  Org --> Space
  Org --> Agent
  User --> Project
  User --> Space
  User --> Work
  Project --- Space
  Project --- Work
  Space --- Work
  Space --> Message
  Space --> Proposal
  Proposal --> Decision
  Space --> Participation
  Agent --> Participation
  Work --> Assignment
  Agent --> Assignment
  User --> Assignment
  Work --> Run
  Run --> Execution
  Execution --> Delegation
  Delegation --> Execution
  Run --> Interaction
  Work --> Link
  Run --> Link
  Project --> Link
  Space --> Link
  Link --> Artifact
  Agent --> Memory
  Project --> Memory
  Space --> Memory
  Work --> Memory
~~~

图中的箭头表示概念关系，不代表所有关系都是数据库外键或严格的级联生命周期。

### 2.2 Domain Areas

| Domain | Core Objects | Responsibility |
|---|---|---|
| Organization & Identity | Organization, User, Team, Membership, Principal | 租户、主体、成员和组织结构 |
| Project | Project, Project Membership, Project Context | 长期目标、项目背景和项目级协作组织 |
| Collaboration | Space, Message, Thread, Proposal, Decision, Activity | 讨论、提及、协调、提案与决策 |
| Work Management | Work, Assignment, Work Run, Interaction | 工作目标、责任分配、业务执行周期和人工交互 |
| Planning | Work Plan, Plan Version, Milestone, Task, Dependency, Acceptance Criteria, Verification, Evidence | 目标导向计划、任务推进、重新规划和完成验证 |
| Agent | Agent Definition, Version, Access, Participation, Binding | Agent 身份、配置、版本、参与和可委派关系 |
| Execution | Execution, Step, Lease, Checkpoint, Event, ToolInvocation, ResourceBinding | 技术执行、调度、恢复、副作用和资源关联 |
| Artifact | Artifact, Artifact Version, Artifact Link, Artifact Access | 产物归档、版本、关联、共享和交付 |
| Context & Memory | Memory Namespace, Memory Item, Context Snapshot, Memory Policy | 分层上下文、记忆和可追溯检索 |

Identity & Access Control、Policy、Audit、Observability、Quota 是横向能力，不应被某一个业务领域私有化。

## 3. Organization, Project and Collaboration

### 3.1 Organization

Organization 是企业租户和治理边界，负责：

- 组织成员与身份关联。
- Team、Project、Space 等组织级对象的管理范围。
- 组织级 Policy、配额、安全和审计边界。
- Organization-owned Agent 和 Artifact 的归属范围。

Organization 是租户边界，不是所有业务对象都必须有的直接父对象。个人 Work、Personal Agent 和 Personal Artifact 可以先存在于个人空间，之后再显式关联或分享给组织范围。

### 3.2 Team

Team 表达企业中相对稳定的组织结构或协作团队。

Team 不是临时讨论群，也不是 Project 或 Space 的别名。MVP 可以只提供基础 Team / Membership 能力；复杂矩阵组织、跨组织团队和继承式权限后续演进。

### 3.3 Project

Project 是围绕长期目标组织工作和共同上下文的容器，负责：

- 项目目标、背景、范围和约束。
- Project Membership。
- 关联的 Collaboration Spaces。
- 关联的 Works。
- 项目级 Decisions、Artifacts 和 Context。

Project 与 Work、Space 是显式关联，不要求 Work 或 Space 必须归属于一个 Project。

### 3.4 Collaboration Space

Space 是人和 Agent 围绕主题交流、分享、协调和决策的场所。它可以是 Temporary 或 Persistent，并可以独立于 Project 存在。

Space 负责讨论上下文，不负责成为 Work 的父对象，也不自动拥有 Space 中所有 Work 或 Artifact 的所有权。

Space 的主要对象：

- Message：一条不可混淆为业务决策的消息。
- Thread：围绕一条消息展开的回复上下文。
- Proposal：等待讨论或确认的建议。
- Decision：由有权主体确认的正式决策。
- Membership / Agent Participation：当前空间中的参与关系。
- Activity：可查询的协作活动投影。

一个 Work 可以被多个 Space 讨论；一个 Space 可以讨论多个 Work。Work 与 Space 的关联应可增加或解除，而不移动 Work 的 Owner 或自动改变其访问权限。

### 3.5 Membership and Participation

Membership 表达人或主体是否属于 Organization、Team、Project 或 Space，以及对应成员角色。

Agent Participation 是 Agent 在 Project / Space 等上下文中的局部参与配置，例如 Role、Responsibilities、Subscriptions 和 Participation Policy。

Membership / Participation 不替代授权系统：

- 是成员不代表能访问所有关联资源。
- Agent 被 @Mention 不代表获得访问权限。
- Agent 加入 Space 不意味着其个人 Memory 自动共享给 Space。
- Participation 不创建新的 Agent Definition。

## 4. Work Management

### 4.1 Work

Work 是一个有明确目标、负责人、执行过程和交付标准的业务工作对象。

Work 负责：

- 用户表达的工作目标和业务描述。
- Owner、创建主体和业务访问边界。
- 优先级、截止时间和业务状态。
- 关联 Project、Space、Assignment 和 Artifact。
- 验收标准、业务结果与工作历史。

Work 可以由以下入口创建：

- Personal Workspace 中的自然语言委托。
- Collaboration Space 中明确提出的工作请求。
- Project 中直接创建。
- Agent 提议并经授权创建。
- 定时或外部事件触发。

Work 不等于 Message、Workflow Definition 或 Execution。Work 可以没有 Project、Space 或 Agent；也可以经历多次 Work Run。

### 4.2 Assignment

Assignment 表达某个 Work 的责任分配，参与者可以是 User、Agent 或 Team（若后续需要）。

Assignment 主要回答：

- 谁负责？
- 谁执行？
- 谁协作或审阅？
- 责任范围和预期交付是什么？

Assignment 不等于一次执行。一个 Agent 可以先被分配 Work，稍后才启动执行；同一个 Assignment 也可能在多个 Work Run 中被执行。

**Proposed：** 将 Assignment 作为独立的一等对象，避免把 assignee_id 直接固化为 Work 的单一字段。MVP 可以先限制为简单负责人 + 协作者，不必实现复杂责任矩阵。

### 4.3 Work Run

Work Run 表示某个 Work 的一次业务执行周期。

建议语义：

- 一个 Work 可以有多个 Work Run。
- 每个 Work Run 记录本轮执行目标、启动原因、执行配置引用、业务级状态和结果摘要。
- 一个 Work Run 可以包含多个 Execution，例如主 Agent 执行、并行 Research Agent 执行和 Review Agent 执行。
- 同一 Work Run 中的子 Agent 委派仍属于本轮 Work Run。
- Work Run 完成后，Work 可被验收、继续修改或启动新的 Work Run。

Work Run 的业务状态与 Execution 的技术状态不同。Work Run 可以是 in_progress、blocked、completed 等业务状态；Execution 则有自己的调度和执行状态。单个 Worker Execution 失败不必然意味着整个 Work Run 失败，平台可根据 Work Run 的完成条件决定是否重试、重新规划或请求人工介入。

**Confirmed direction：** Work Run 具有一个稳定的 Work Plan 身份；该 Plan 可产生多个 Plan Version，同一时刻只有一个 Active Plan Version。Plan 管理本轮整体执行方案，Task 管理可分配、可追踪和可验证的工作项。详细模型见 [Plan Domain](./plan-domain.md)。

### 4.4 Interaction

Interaction 表示执行或协作过程中，需要用户或其他有权限主体响应的事项，例如：

- 补充信息 / Clarification。
- Tool 或资源授权。
- 审批。
- 关键决策确认。
- 验收或交付确认。

Interaction 不是另一套任务系统，也不等于普通 Message。它具有请求者、响应对象、所需权限、状态、截止时间和响应记录。

MVP 可以提供统一的 Inbox 投影聚合不同来源的 Interaction，但 Interaction 本身仍由产生它的领域负责生命周期和授权语义。

## 5. Agent and Execution

### 5.1 Agent Definition and Version

Agent Definition 是可复用的身份与配置定义；Agent Version 是不可变的已发布配置版本。

Agent Definition 不等于执行进程、Session、Work 或 Worker。一个 Agent Definition 可以被多个 Work 和多个 Work Run 使用，每次执行都具有隔离的运行上下文。

Agent 的 Owner、Visibility、Access、Publisher 和 Executor 是不同概念。Platform、Personal 和 Organization Agent 使用同一领域模型。

### 5.2 Execution

Execution 是平台统一的技术执行对象，表示一次逻辑执行，适用于 Agent、Workflow、Chat 和 Subagent 等执行场景。

Execution 负责：

- 稳定的执行身份与状态。
- 当前 Worker Lease 和 fencing token。
- Step / Attempt。
- Checkpoint Manifest。
- Execution Event。
- ToolInvocation 副作用账本。
- ResourceBinding。
- 配置快照引用和恢复协议。

Execution 是执行事实的权威来源；不能把租约、恢复点和外部副作用状态塞回 Work 或 Work Run。

### 5.3 Worker Execution

Worker Execution 不是与 Execution 平行的第二种持久化执行对象。

它表示“某个 Agent Definition / Version 在一个 Execution 中承担 Worker 职责”的语义视图。建议通过 Execution 的 executor_kind=agent、agent_definition_id、agent_version_id 等字段表达，而不是另建一套执行状态、Lease 和 Checkpoint。

因此：

- 一个 Work Run 可以有多个 Worker Executions。
- 每个 Worker Execution 有独立的 Session / Context / Execution State。
- Agent Definition 可以被多个 Work Run 并发使用。
- Agent 的局部计划属于对应 Worker Execution，不是 Agent Definition 的全局状态。
- Worker Execution 的恢复、取消和资源控制遵循统一 Execution 协议。

### 5.4 Work Run, Execution and Delegation

这是跨领域最重要的关系：

~~~text
Work
 ├── Assignment(s)
 └── Work Run R1
      ├── Execution E1 (primary Agent Worker)
      │    ├── Step(s)
      │    └── Delegation D1
      │          └── Execution E2 (Review Agent Worker)
      ├── Execution E3 (Research Agent Worker)
      ├── Interaction(s)
      └── Artifact Link(s)
~~~

建议约束：

1. 一个 Work 可以有多个 Work Run；一个 Work Run 只属于一个 Work。
2. 一个 Work Run 可以关联多个 Execution。
3. 每个 Execution 最多归属于一个 Work Run；纯 Chat / Session Execution 可以没有 Work Run。
4. 一个 Execution 可以通过 Delegation 关联 Child Execution；父子 Execution 在 MVP 中属于同一个 Work Run。
5. Delegation 记录来源 Binding、目标 Agent Version、委派输入、权限评估和结果交接。
6. Delegation 不自动创建新 Work；只有需要独立业务生命周期、负责人或验收标准时才创建独立 Work。
7. Work Run 的业务状态由 Work Run 规则管理；Execution 状态由 Execution Domain 管理，避免双重事实源。

**Proposed：** Work Run 是业务执行聚合边界，Execution 是技术执行边界。一个 Work Run 可以包含多个并行或串行 Execution，但不把 Work Run 本身当作 Worker Lease 的持有者。

### 5.5 Planning and Workflow

Planning、Workflow 和 Execution 是不同概念：

- Work Plan：Work Run 层面的整体执行方案，拥有稳定身份和版本化计划结构。
- Plan Version：某一时刻的计划结构快照；计划调整产生新版本，历史版本保留。
- Task：Plan 中的业务工作项；Todo 是 Task 的用户界面视图，不是独立领域事实源。
- Agent Local Plan：某个 Worker Execution 针对被分配或委派 Task 制定的局部计划，必须关联父 Task / Delegation。
- Workflow Definition：可复用的确定性流程定义及版本。
- Workflow Run / Workflow Execution：在 Work Run 中实际运行某个 Workflow 的 Execution。
- Step：Execution 内可观测、可恢复的执行单元。

Planner 是平台能力；Agent 可以依据专业偏好决定是否规划、拆分或委派。Workflow/DAG 负责确定性流程控制，不等于 Planner，也不应成为所有 Work 的强制表达形式。Task 不等于 Execution：一个 Task 可以跨多个模型调用、Execution 或 Delegation。Agent 的完成声明必须遵循 Task 的 Verification Policy，不能直接绕过验收进入 Completed。详细实体、生命周期、重新规划和恢复集成见 [Plan Domain](./plan-domain.md)。

### 5.6 Session and Conversation Context

Session / Conversation 保存交互历史与对话连续性；Execution 保存一次逻辑执行的状态。

一次用户请求不必然创建 Work。Chat Execution 可以独立存在；当用户明确委托一个有目标和交付要求的工作时，平台可以创建 Work 并启动 Work Run。

Agent Memory 与 Conversation History 不等价。Personal、Project、Space、Work 和 Run State 的 Scope 必须隔离；Context Snapshot 记录一次执行实际读取的上下文来源、版本和授权依据。

## 6. Artifact and Decision

### 6.1 Artifact

Artifact 是有独立身份、归属、版本和访问策略的工作成果，例如文档、代码变更、报告、数据文件、图表或其他交付物。

Artifact 不只是消息附件或 Sandbox 路径。它需要具备：

- Artifact Identity / Owner。
- Artifact Type / Metadata。
- Artifact Version（版本内容不可被历史覆盖）。
- Storage Reference。
- Access / Sharing Policy。
- Lifecycle（Draft、Published、Archived 等按产品需要定义）。

### 6.2 Artifact Link

Artifact 与 Work、Work Run、Project、Space、Message 或 Decision 的关系通过 Artifact Link 表达。

Link 表示“此对象引用或使用了这个 Artifact”，不改变 Artifact Owner，也不自动授予访问权限。Artifact 的分享和访问授权必须显式处理。

**Proposed：** 一个 Artifact 可以被多个业务对象引用；一个 Work Run 可以产出多个 Artifact。Artifact 的版本历史归 Artifact Domain 管理，Work Run 只记录本轮使用或产出的具体 Artifact Version 引用。

### 6.3 Proposal and Decision

Proposal 是一个待讨论、修改或确认的建议；Decision 是经授权主体明确确认的正式决策。

AI Summary、Agent 回复和 Proposal 不自动成为 Decision。Decision 应记录：

- 决策内容和状态。
- 决策主体与授权依据。
- 确认时间。
- 相关 Proposal、Message、Work、Project 和 Artifact 引用。
- 如有需要，替代或撤销的历史决策。

Decision 可以影响 Project / Work 的后续执行，但不等同于 Work 状态变更。

## 7. Cross-cutting Rules

### 7.1 Authorization

授权不是对象关系图中的隐式边。执行资源访问时必须结合：

- Initiating Principal。
- Agent Identity / Executor。
- Owner 与 Membership。
- Work / Project / Space 的访问策略。
- Organization Policy。
- Tool / Resource Capability。
- 当前 Delegation 的权限上限。

关联 Work、被 @Mention、被 Assignment 或拥有 Delegation Binding，都不能单独作为访问敏感资源的充分条件。

### 7.2 Events and Activities

至少区分三类事件语义：

- **Collaboration Events**：Message、Thread、Membership、Proposal、Decision 等协作事实。
- **Work Domain Events**：Work、Assignment、Work Run、Interaction 的业务生命周期事实。
- **Execution Events**：Execution、Step、Lease、Checkpoint、ToolInvocation 和 Resource 的运行事实。

Activity 可以作为跨领域时间线/通知投影，但不能取代上述领域的事实源。Audit Event 还应保持独立的访问控制和保留策略。

### 7.3 Deletion and Lifecycle

跨领域关系默认不意味着级联删除。归档、撤销关联、撤销授权和删除数据是不同操作。

执行记录、审计事实和已交付 Artifact 的保留应受组织策略和合规要求约束。删除 Agent Definition 不应破坏历史 Execution 对具体 Agent Version 的引用；删除或禁用 Binding 也不应抹去已发生 Delegation 的历史。

## 8. Relationship to Existing Execution Architecture

仓库已有的 [Execution Model Proposal](../EXECUTION-MODEL-PROPOSAL.md) 定义 Execution、Step、Checkpoint Manifest、Execution Event、ToolInvocation、ResourceBinding、Lease 和恢复协议；[Execution Architecture](../EXECUTION-ARCHITECTURE.md) 定义这些对象在当前代码库中的模块落位。

本文不替代这些技术文档，而是补充产品领域对象与执行对象的映射：

| Product Domain | Execution Domain | Relationship |
|---|---|---|
| Work | — | 业务目标，不是执行记录 |
| Work Run | One-to-many Execution; one Work Plan identity | 一次业务执行周期聚合多个技术执行，并有一个版本化主计划 |
| Assignment | — | 责任分配，不等于执行 |
| Work Plan / Plan Version / Task | — | 业务计划与工作项；不替代 Execution / Step |
| Agent Local Plan | Worker Execution / Delegation references | 子 Agent 局部计划映射到父 Task 和委派事实 |
| Verification / Evidence | Execution Event, ToolInvocation, Artifact references | 验收结论消费可追溯执行证据 |
| Agent Definition / Version | Execution configuration snapshot | 执行引用固定 Agent Version |
| Worker Execution | Execution with Agent executor | 语义角色，不是独立重复的执行状态机 |
| Delegation Binding | — | Agent Domain 的长期配置 |
| Delegation | Parent / Child Execution relation + handoff metadata | 运行时委派事实；需要显式业务记录 |
| Interaction | Execution may wait; Work Run may be blocked | 交互请求与执行等待状态分离 |
| Artifact / Artifact Version | Artifact references in Step result / output | 产物事实由 Artifact Domain 管理 |
| Collaboration Activity | Execution Event is not a substitute | 跨领域 Activity 为投影 |

**重要兼容说明：** 现有技术提案中的 Task 是当前执行架构演进中的业务任务对象，不能未经迁移设计就直接等同于新产品战略中的 Work。当前代码中的 Task、Session、Workflow Task 和新产品 Work 的映射需要单独制定迁移方案，本文不宣称这些概念已经在代码中统一。

### 8.1 Existing Multi-Agent Collaboration Design

现有 [Multi-Agent Collaboration](../multi-agent-collaboration.md) 文档讨论 delegate、dispatch、pipeline、loop、parallel、judge 和 supervisor 等协作范式。它提供执行模式和实现演进参考，但不定义产品级 Agent 类型，也不改变本文的 Work / Work Run / Execution 分层。

未来应将这些范式作为 Work Run 的执行编排策略，而不是创建五种固定 Agent 类型。MVP 以显式 Delegation Binding 和有限委派为主；高级模式按路线图演进。

## 9. MVP and Deferred Scope

### MVP Domain Baseline

- Organization、基础 User / Membership。
- 基础 Project 和 Collaboration Space。
- Message、Thread、@Mention、Proposal、Decision 的基础模型。
- Work、Assignment、Work Run 的核心业务边界。
- Work Run 关联 Work Plan；Plan Version、Task、基础依赖和验收验证能力。
- Agent Definition、Version、Access、Participation 和显式 Delegation Binding。
- Execution 与 Work Run 的关联；复用统一 Execution 恢复协议。
- Artifact、Artifact Version、Artifact Link 和基础访问授权。
- Interaction 与基础 Inbox 聚合。
- Scoped Memory / Context 的基础隔离。

### Deferred

- 复杂 Team 组织结构和继承式组织权限。
- 跨 Project / 跨 Work Run 的长期 Supervisor 协调。
- 高级 DAG、动态 Planner 和复杂多 Agent Debate / Judge。
- Agent 间 P2P 消息总线和无限自主协商网络。
- Artifact 实时协作编辑、高级审阅和知识图谱。
- 多租户公共 Marketplace 与完整 Capability 生态。

Deferred 是暂缓实现，不是产品不做。领域模型应允许演进，但 MVP 不提前实现复杂机制。

## 10. Open Questions

1. Work 的 Owner 与 Creator 是否必须分离，以及 Personal Work 关联 Project 后的默认授权策略。
2. Assignment 在 MVP 中是否需要独立实体，还是先采用 Work 上的简单负责人字段并预留迁移。
3. Work Run 的业务状态机、重新规划、重试和验收条件。
4. 一个 Work Run 是否允许多个并行的顶层 Agent Execution，以及取消/部分成功的聚合规则。
5. Work Run 与 Session / Conversation 的关联 cardinality 和消息上下文选择规则。
6. Interaction 的创建者、响应主体、超时和撤销语义。
7. Artifact Owner、Artifact Access、Artifact Link 与组织/个人分享之间的授权模型。
8. Decision 的确认权限、撤销、替代和对 Work 的影响机制。
9. Personal / Project / Space / Work Memory Namespace 的 ACL 继承、保留和删除策略。
10. 现有 Task、Workflow Run、Session 与新 Work / Work Run 的数据迁移及 API 兼容策略。
11. Activity 投影、Collaboration Event、Work Domain Event 和 Audit Event 的统一查询与保留策略。
12. Plan Domain 中 Task 稳定身份、跨版本结构变更和运行中 Task 迁移的具体持久化语义（见 [Plan Domain Open Questions](./plan-domain.md#10-open-questions)）。

在这些问题明确前，本文中的 Proposed 关系可作为讨论基线，不应直接转成不可变的实现约束。

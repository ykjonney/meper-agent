# Project Architecture & Implementation Roadmap

> 状态：**Architecture Consolidation Draft（全局收口草案，待逐项评审）**
>
> 适用分支：`feature/execution-model`
>
> 本文是项目级导航与实施路线图，不取代各领域详细设计，也不表示本文列出的目标能力已经实现。文中严格区分已确认决策、推荐方案、待决问题、暂缓实现和当前代码现状。

## 1. 本文目的与使用方式

当前仓库已经积累了产品战略、Agent Domain、Plan Domain、Execution Domain、Context Compression 和 Multi-Agent 等多份设计文档，但这些文档分属不同层次，状态也不一致。若直接进入大规模代码改造，容易出现三类问题：

1. 把某份 Proposed 方案误当成已经确认的全局约束；
2. 把当前代码中的旧 Task / Session / Workflow 概念直接映射到新的 Work / Work Run / Context Session；
3. 在实现某个局部能力时，提前引入高级机制，或者反过来把 MVP 暂缓误解为产品不做。

本文负责：
- 给出统一的产品与技术架构地图；
- 汇总目前已经明确的产品决策；
- 标出仍需评审的关键架构问题；
- 区分当前实现、目标设计和迁移工作；
- 给出分阶段实施顺序及每阶段的退出条件；
- 维护高级能力的演进方向，避免 MVP 设计封死未来。

本文不是新的领域模型规范。发生冲突时，先回到对应领域文档和决策记录评审，再更新本文。

## 2. 产品目标与核心闭环

### 2.1 产品定位

**Enterprise Intelligent Work Coordination Platform（企业智能工作协调平台）**。

平台让企业员工、AI Agent 与企业业务能力共同参与工作，完成沟通、协调、决策、执行与交付。

核心闭环：

`Discussion → AI Understanding → Work Planning → Collaborative Execution → Deliverables & Decisions`

用户主要通过 Agent 发起和推进工作；Collaboration 提供人和 Agent 的共同工作环境；Artifact 承载可管理、可共享和可交付的结果。**Work 是 Agent、Collaboration 和 Artifact 之间的业务枢纽。**

### 2.2 核心产品原则

1. 人和 Agent 都是工作参与者，但 Agent 的身份不等于它拥有资源权限。
2. Message、Work、Plan Task、Execution、Artifact、Proposal 和 Decision 是不同对象，不以聊天消息或单一 Task 表达所有事实。
3. Agent 负责目标理解与规划；Workflow/DAG 负责确定性、可复用、可验证的流程控制，两者采用 Hybrid 模式。
4. 执行事实、业务状态和授权状态必须有明确权威来源。
5. 执行需要持久化、可观测、可审计、可暂停和可恢复。
6. MVP 聚焦核心闭环，但保留高级能力的合理扩展点；暂缓实现不等于产品不做。

详细依据：[产品战略基线](./product-design/product-strategy.md)。

## 3. 统一领域与运行时地图

### 3.1 领域分层

| 层次 | 核心对象 | 主要职责 | 权威边界 |
|---|---|---|---|
| Organization & Identity | Organization、User、Team、Membership、Principal | 租户、身份、组织成员与治理边界 | 身份和组织归属 |
| Project & Collaboration | Project、Space、Conversation、Message、Thread、Proposal、Decision、Activity | 讨论、上下文、协作、提案和决策 | 协作事实 |
| Work Management | Work、Assignment、Work Run、Interaction | 业务目标、责任分配、一次业务推进周期和人工交互 | Work 目标与业务生命周期 |
| Planning | Work Plan、Plan Version、Milestone、Plan Task、Task Revision、Task Attempt、Verification、Evidence | 将目标拆解为可分配、可追踪、可验证的工作 | 计划结构与 Task 业务状态 |
| Agent | Agent Definition、Agent Version、Access、Participation、Delegation Binding | Agent 身份、所有权、配置、能力、记忆和委派配置 | Agent 配置与访问关系 |
| Execution | Execution、Step、Lease、Checkpoint Manifest、Execution Event、ToolInvocation、ResourceBinding | 技术执行、调度、恢复、副作用与资源生命周期 | 技术执行事实 |
| Context & Memory | Context Session、Execution Conversation、History Session、Memory Namespace、Context Snapshot | 模型上下文连续性、历史回溯和记忆隔离 | 历史事实与模型上下文分别管理 |
| Artifact | Artifact、Artifact Version、Artifact Link、Artifact Access | 产物归档、版本、关联、共享和交付 | 产物及访问事实 |
| Governance | Policy、Grant、Audit、Quota、Security | 有效权限、审计、安全与企业治理 | 授权和治理事实 |

这张表是目标领域地图，不代表所有对象都需要在 MVP 中独立建表或独立服务。

### 3.2 核心对象关系

```text
Organization / User
       │
       ├── Project ───────────────┐
       │      │                   │
       │      └── Collaboration Space
       │                 │
       │             Conversation / Message
       │                 │
       └── Work ◄────────┘  (显式关联，不是父子包含)
              │
              └── Work Run
                    │
                    ├── Work Plan
                    │     └── Plan Version
                    │           └── Plan Task / Revision
                    │                 └── Task Attempt
                    │
                    ├── Agent Assignment / Delegation
                    │
                    └── Execution(s)
                          ├── Step
                          ├── Checkpoint Manifest
                          ├── Execution Event
                          ├── ToolInvocation
                          └── ResourceBinding

Work / Work Run / Project / Space
       └── Artifact Links ──> Artifact / Artifact Version
```

关键关系约束：
- Project、Space、Work、Artifact 采用显式关联，不强制单根树形层级。
- 一个 Work 可以在没有 Project 或 Space 的情况下开始。
- 一个 Work Run 可以包含多个技术 Execution；一个 Task Attempt 也可以关联多个 Execution / Delegation。
- Plan Task 是业务工作单元，不等于 Execution、Workflow Step、模型调用或 Tool Invocation。
- Agent Definition 可复用；一次执行使用明确的 Agent 配置和授权上下文。
- 多 Agent 默认通过 Work、Plan、Decision、Artifact 等结构化信息协作，不默认共享完整模型消息列表。

详细依据：[领域模型总览](./product-design/domain-model.md)、[Agent Domain](./product-design/agent-domain.md)、[Plan Domain](./product-design/plan-domain.md)。

## 4. 已确认决策

以下决策来自产品决策记录和本项目讨论，作为后续设计基线。若详细文档尚未同步，应补充到对应文档和 Decision Log。

### 4.1 产品与 Agent

| 主题 | 已确认决策 |
|---|---|
| 核心客户 | Enterprise |
| 主要入口 | Agent |
| DAG 定位 | Hybrid：Agent 目标导向规划 + Workflow/DAG 确定性执行 |
| 核心体验 | Agent、Collaboration、Artifact；Work 是连接枢纽 |
| MVP 原则 | 聚焦核心闭环，同时预留长期扩展点 |
| Agent 所有权 | Shared 使用模型，支持 Personal 与 Organization Owner |
| Agent 与 Work | Agent Definition 可复用，实际执行 Work-scoped |
| Agent 创建入口 | Studio 与自然语言会话 both |
| Agent Version | Manual Upgrade |
| Space 创建 Agent 默认 Owner | Personal |
| Agent Memory | Scoped |
| Agent Identity | Hybrid：Agent 独立身份，同时明确本次执行代表的授权主体 |
| 委派发现 | 显式配置 Delegation Binding，不要求 Agent 动态发现子 Agent |
| 委派权限 | 每次实际委派执行重新评估权限 |

### 4.2 Conversation、Work 与执行上下文

| 主题 | 已确认决策 |
|---|---|
| Conversation 与 Work | 一个 Conversation 可以有多个 Work，也可以只有普通聊天 |
| 普通聊天 | 不要求创建 Work、Objective 或 Plan |
| 用户打断 | 用户可以直接打断当前执行并输入新消息；不引入复杂消息分类体系 |
| 暂停提醒 | 必要时由 Runtime 给出简单暂停/状态提醒，Agent 根据上下文理解用户意图 |
| History 与 Execution Context | 两份独立数据，开始时内容可相近，之后独立演化 |
| History 用途 | 展示完整产品历史，并在需要时按需 Recall |
| Execution Context 用途 | 作为模型实际连续使用、压缩和恢复的上下文 |
| History 注入 | 不把完整 History 每轮重建成 Prompt |
| Work Goal | 仅在相关 Work 存在时提供结构化目标，不制造全局 Current Objective |
| Prompt / Tool 更新 | 新执行请求使用当前有效配置；不为 Prompt 或 Tool 修改设计 Session Migration |
| 工具权限 | 在具体工具/危险操作执行时检查权限；不依赖 Prompt 自我约束 |

### 4.3 Plan、Todo 与 Context Compression

| 主题 | 已确认决策 |
|---|---|
| Plan | 长期业务任务规划与状态管理能力，不等于 Todo |
| Todo | Agent 自己维护的轻量执行提醒清单，不是第二套长期记忆 |
| Todo 状态 | 由 Agent 通过 Todo 工具维护，Runtime 不替 Agent 判断业务完成或自动改状态 |
| Todo 结束前提醒 | 每次 Execution 准备正常结束时检查；仍有未完成项则提醒 Agent 一次 |
| Todo 提醒语义 | 提醒不是强制门控；Agent 可以继续，也可以说明阻塞后结束 |
| Todo 恢复 | 未结束 Execution 在后续执行中恢复时，入口读取当前 Todo 并提醒一次 |
| Todo 压缩 | Todo 状态独立保存，不参与 Context Compression |
| 压缩边界 | 保护完整交互单元、工具批次和未消费工具结果 |
| Provider Prompt Cache | 性能/成本优化，不是正确性或恢复依据 |
| Context Epoch | 先用轻量压缩代次和来源记录，不建设复杂独立服务 |

Plan/Todo 的领域边界见 [Plan Domain](./product-design/plan-domain.md) 与 [Context Compression Implementation Review](./CONTEXT-COMPRESSION-IMPLEMENTATION-REVIEW.md)。

## 5. 设计状态与待决问题

### 5.1 状态约定

- **Confirmed**：用户已明确确认的产品决策。
- **Proposed**：当前推荐设计，仍需评审；不能直接当成不可变实现约束。
- **Open**：尚未决策，必须在实现依赖它之前解决。
- **Deferred**：明确暂缓到后续阶段，不代表产品不做。
- **Out of Scope**：明确不属于产品目标。

### 5.2 关键设计状态

| 领域 | 当前状态 | 下一步 |
|---|---|---|
| 产品战略 | Baseline；核心方向已确认 | 后续仅按产品反馈调整 |
| Agent Domain | Design Baseline；主要决策已确认，治理细节仍有 Open | 评审权限矩阵、撤销和版本依赖 |
| 跨领域 Domain Model | Proposed | 评审 Work / Work Run / Conversation / Space 关系 |
| Execution Model | 修订草案；代码已有较多基础设施 | 完成协议评审、对照代码和生产一致性验证 |
| Execution Architecture | 有具体实施架构与 E0–E9 顺序 | 按阶段实施并完成集成验证 |
| Plan Domain | Proposed；部分核心原则已确认 | 继续确认 Work Run、Task、Verification 细节 |
| Plan Runtime Integration | Proposed；若干决策已确认 | 先冻结集成契约，再建设 Coordinator |
| Plan Persistence | Proposed | 评审事务边界、索引与恢复协议 |
| Conversation / Work / Context Session Resolution | 讨论已形成方向，但完整规则尚未定稿 | 单独形成正式设计，尤其是多 Work、多 Agent 和 Fork |
| Context Compression | 有专项设计和实现审查 | 按优先级修正 Token Budget、归档可靠性等问题 |
| Todo | 提醒规则已确认，当前实现仍需调整 | 最小改造结束前提醒与恢复入口 |
| Multi-Agent | 有缺失分析与模式设计 | 定义 MVP 委派范围和结构化协作上下文 |
| Skill / Capability | 有既有 Skill、Tool、MCP 与 Sandbox 实现 | 形成统一能力装配、授权和执行边界设计 |
| Collaboration / Artifact / Interaction | 领域方向已有概念，详细模型未完成 | 补充 MVP 交互和数据契约 |
| Product UX / Workbench | 仅有部分历史设计和讨论 | 形成当前目标产品的端到端体验规格 |

### 5.3 必须继续解决的架构问题

**A. Conversation、Work 与 Context Session**
1. Conversation、History Session、Execution Conversation、Context Session 的正式实体关系和标识边界。
2. 同一 Conversation 中多个 Work 如何选择、复用或 Fork Context Session。
3. 同一 Work 下多个 Agent 的 Context Session 如何隔离；多个 Execution 如何安全串行复用。
4. Resume、Fork、Reset 的精确定义及其 Checkpoint / History 关系。
5. 普通聊天与 Work 执行之间如何自然切换，而不引入强制 Objective 或复杂消息分类。

**B. Work 与 Plan**
1. Work Owner、Creator、Assignment 的 MVP 最小模型。
2. Work Run 状态机、重试、重新规划、完成验收和多个顶层 Execution 的聚合规则。
3. Task 多 Assignee、并行执行、运行中 Replanning 的迁移语义。
4. Verification 风险等级和独立验证要求。

**C. Agent、Skill 与权限**
1. Agent Access、Organization Policy、Work Policy 与 Delegation Binding Constraints 的有效权限合并规则。
2. Skill / Tool / MCP / Sandbox 如何形成统一可装配能力，而不把“配置可用”误认为“执行已授权”。
3. Skill、Tool 定义变化时，新执行如何使用当前配置；同一次运行如何保持配置一致。
4. Agent Version、Skill 依赖和平台能力升级之间的兼容边界。

**D. Collaboration 与 Artifact**
1. Proposal 转 Decision 的授权与审计流程。
2. Interaction 的创建、响应、超时、撤销和执行等待关系。
3. Artifact Owner、分享、访问撤销、版本可见性和跨 Space / Project 引用。
4. Activity、Domain Event、Execution Event 与 Audit Event 的边界。

以上问题不能因为总文档存在就视为已经解决。详细问题列表继续维护在 [Decision Log](./product-design/decision-log.md) 与各领域文档的 Open Questions。

## 6. 目标运行时架构

### 6.1 分层职责

```text
Product / API Layer
  Conversation, Work, Space, Project, Agent, Artifact APIs
                 │
                 ▼
Application Services
  Work coordination / Assignment / Interaction / Authorization
                 │
                 ▼
Domain Coordinators
  Plan Coordinator       Agent & Delegation Resolver
  Context Session Resolver   Artifact / Collaboration services
                 │
                 ▼
Execution Runtime
  Execution Repository / Lease / Fencing / Events
  Checkpoint Manifest / Tool Ledger / Resource Manager
  Dispatcher / Recovery Supervisor
                 │
                 ▼
Execution Adapters
  Agent Harness / Workflow Runtime / Subagent Runtime
                 │
                 ▼
Providers
  LLM / Tools / MCP / Skills / Sandbox / External Systems
```

这是逻辑职责图，不要求每层成为独立微服务。MVP 优先保持模块化单体和清晰接口，只有在负载、团队边界或独立部署需求明确后再拆服务。

### 6.2 关键权威边界

| 事实 | 权威来源 | 不应由谁替代 |
|---|---|---|
| 用户可见完整消息历史 | History / Conversation Store | Execution Checkpoint |
| 模型当前连续上下文 | Context Session / Execution Checkpoint | 产品 History |
| Work 目标与业务状态 | Work Domain | Chat Message / Execution 状态 |
| Plan / Task 结构和业务状态 | Plan Domain / Task State Coordinator | Todo / Execution Step |
| Agent 配置与版本 | Agent Domain | 某次 Execution 的临时 Prompt |
| 技术执行状态与恢复位置 | Execution Domain | Plan Task 或 Celery 状态 |
| 外部工具副作用意图与结果 | ToolInvocation Ledger + 外部系统核对 | 普通 ToolMessage |
| 产物与版本 | Artifact Domain | 聊天文本或临时 Sandbox 文件 |
| 有效权限 | Identity / Access / Policy Runtime | Prompt、Skill 描述或 Agent 自述 |

### 6.3 Invocation Input 与上下文装配

每次模型调用的实际输入需要作为一个整体预算，而不只估算持久化 messages：

```text
InvocationInput
├── Persistent Execution Messages
├── Ephemeral Context Messages (e.g. Todo / Work Context)
├── Resolved Tool Definitions
├── Model Configuration
└── Input Fingerprint (internal diagnostic / budget baseline)
```

- 压缩器只修改持久化 Execution Messages。
- 动态上下文以无副作用 Context Contributor 方式提供，压缩预算与真实调用复用同一份输入。
- 工具定义、动态消息和协议开销纳入 Token Budget。
- Prompt / Tool 更新不触发 Session Migration；新执行请求装配当前有效配置，同一次运行使用一致配置。
- InvocationInput 是调用期对象，不作为长期业务实体或 Checkpoint 内容。

详细方案见 [Context Compression Implementation Review](./CONTEXT-COMPRESSION-IMPLEMENTATION-REVIEW.md)。

## 7. 当前实现基线与迁移原则

### 7.1 当前已有的技术底座

根据当前分支的设计文档和此前静态代码审查，Execution Domain 已具备或正在落地以下基础设施：

- Execution 身份、状态和 Repository；
- LeaseManager、CAS、fencing 与 takeover；
- CheckpointCoordinator / Manifest；
- Execution Event 持久化与序号；
- ToolInvocation Ledger 的幂等和 UNKNOWN 语义；
- Dispatcher、RecoverySupervisor；
- ResourceBinding / ResourceManager；
- Harness 中的 Agent、Tool、Middleware、Context Compression、Todo 和 Plan Approval 基础能力。

具体代码完成度、测试覆盖和生产验证必须以代码审查及测试结果为准；设计文档存在不等于所有功能已正确上线。

### 7.2 主要缺口

1. 旧 Workflow Task 仍承担部分生产执行入口和业务状态权威；Plan Domain 尚未正式接管。
2. 新产品 Work / Work Run 与旧 Task、Workflow Run、Session 的迁移映射尚未完成。
3. Plan Task、Task Revision、Task Attempt、Coordinator、Verification 和 Plan Outbox/Inbox 尚需建设。
4. 产品级 Conversation / Context Session Resolution 尚未定稿。
5. 通用 History Recall、Artifact Recall 和多 Work 上下文选择仍需补齐。
6. Skill / Capability 的统一治理和执行授权模型尚未收口。
7. Collaboration、Interaction、Artifact 的完整产品闭环仍需补足。

### 7.3 迁移原则

- 不做一次性推翻重写；优先复用 Execution 技术底座。
- 业务状态与技术执行状态分开，禁止新旧 Task 双重权威。
- 先冻结新旧对象映射和读写边界，再迁移生产入口。
- 每阶段保留可观测、可对账和可回滚路径。
- 不因 Prompt 或 Tool 定义变化迁移历史 Session。
- 不把完整 History 重建成每次模型调用的 Prompt。
- 不把 Todo 合并进 Plan Runtime，也不把当前 Markdown Plan Approval 误认为完整 Plan Runtime。

详细依据：[Execution Model Proposal](../EXECUTION-MODEL-PROPOSAL.md)、[Execution Architecture](../EXECUTION-ARCHITECTURE.md)、[Execution ↔ Plan Gap Analysis](./execution-plan-gap-analysis.md)。

## 8. MVP 实施路线图

路线图按依赖关系排序。阶段可以拆成多个 PR；未满足退出条件，不进入依赖该阶段的生产切换。

### Phase 0 — 设计契约冻结与基线测试

目标：先统一术语、权威来源、接口边界和测试基线。

工作：
- 评审本总文档中的领域关系和待决问题。
- 冻结 Execution 与 Plan 的集成契约、事件契约和状态权威矩阵。
- 完成 Work / Work Run / Conversation / Context Session 的最小关系决策。
- 盘点旧 Task、Workflow Run、Session 的实际读写入口。
- 为当前 Execution、Checkpoint、Tool Ledger、Recovery 和 Context Compression 建立回归测试基线。

退出条件：
- 不再存在同一业务状态由旧 Task 与新 Plan 双重写入的模糊路径。
- Execution / Plan / Conversation / Context Session 的 ID 与关联规则有明确文档。
- 核心恢复和副作用测试有可重复结果。

### Phase 1 — Execution Runtime 可靠性收口

目标：让技术执行事实、恢复和副作用处理可信，作为上层 Plan Runtime 的稳定底座。

工作：
- 按 Execution Architecture 的 E0–E9 顺序完成部署前提、事务、fencing、事件、Checkpoint、Tool Ledger、Dispatcher 和 Recovery。
- 明确 MongoDB Replica Set / 事务部署要求，并通过真实 Replica Set 集成测试验证。
- 验证 Zombie Worker、重复派发、Lease takeover、Checkpoint Manifest 和 UNKNOWN ToolInvocation。
- 补齐资源侧 fencing 的能力声明；不把数据库 fencing 夸大为真实 Sandbox 已被隔离。
- 处理 Chat / Workflow / Subagent Runtime Adapter 的统一执行边界。

退出条件：
- Worker 崩溃和重复投递不会无条件重复已提交副作用。
- 过期 Worker 无法继续写入执行事实。
- Checkpoint、事件和状态水位一致。
- 关键恢复场景有集成测试和可操作的排障信息。

### Phase 2 — Plan Persistence 与 Task State Coordinator

目标：建设业务任务管理层，不重建 Durable Execution。

工作：
- 建设 Work Run、Work Plan、Plan Version、Plan Task、Task Revision、Task Runtime State、Task Attempt 的持久化模型。
- 建设 Task State Coordinator，统一 Task / Attempt 状态写入口。
- 落地命令幂等、CAS、活动 Attempt 唯一约束。
- 建设 Plan Outbox / Inbox，与 Execution Event 保持不同聚合边界。
- 实现 Plan Version 构建、Prepare、激活和恢复协议。
- MVP 先限制一个 Task 最多一个活动 Attempt；一个 Attempt 可以关联多个 Execution / Delegation。

退出条件：
- Plan 状态不会被 Execution 状态或旧 TaskService 直接覆盖。
- 并发 Start / Complete / Replan 有确定性结果。
- Outbox / Inbox 可在重复投递下幂等处理。
- Plan Version 激活和部分 Task 协调可恢复。

### Phase 3 — Agent Runtime 与 Plan / Execution 集成

目标：Agent 能围绕持久化 Plan 执行工作，并可靠地报告进度。

工作：
- Work Run 启动时解析 Agent、配置、授权和执行上下文。
- Plan Task Attempt 创建和 Execution 启动之间建立明确事务/事件协议。
- Agent 通过受控接口读取任务、更新进展、提交完成声明和证据。
- Execution 完成事件由 Plan Coordinator 幂等消费。
- Completion Claim 与 Verification 分离；高风险任务按策略要求验证。
- 保留现有 Plan Approval Workflow，但明确它只是计划审批交互，不等于完整 Plan Runtime。
- Todo 保持 Agent 侧轻量提醒；按已确认规则实现结束前提醒和恢复入口提醒。

退出条件：
- Task Attempt 可以跨多个 Execution / Delegation 延续。
- 技术 Execution 结束不自动等于业务 Task 完成。
- 完成声明、验证结果和最终 Task 状态可追溯。
- Todo 不与 Plan Task 双重维护同一业务状态。

### Phase 4 — Conversation / Context Session Resolution

目标：支持一个 Conversation 多话题、多 Work 的连续交互，同时保证模型上下文不混乱。

工作：
- 明确 History Session 与 Context Session 的身份、生命周期和关联关系。
- 普通聊天不强制创建 Work。
- 定义 Work 从普通聊天产生时如何继承或 Fork 当前执行上下文。
- 定义同一 Work、同一 Agent 跨 Execution 的 Context Session 复用规则。
- 定义不同 Work、不同 Agent 的默认隔离规则。
- 定义 Resume / Fork / Reset，以及并发写入控制。
- 通过 Runtime Resolver 选择 Context Session；不让 Agent 自行管理底层 Session ID。
- 完成按需 History Recall，必要时能从原始历史恢复被压缩掉的上下文。

退出条件：
- History 与 Execution Context 独立演化，互不覆盖。
- 多 Work 切换不会把不相关上下文混入当前模型输入。
- Resume / Fork / Reset 的行为可测试、可审计。
- Checkpoint、Archive / Recall 使用稳定的 Context Session 标识，而不是隐含依赖产品 Session ID。

### Phase 5 — Skill / Tool / Sandbox Capability Boundary

目标：让 Skill 能可靠复用平台能力，而不是依赖 Prompt 描述能力。

工作：
- 定义 Skill、Tool、MCP、Knowledge、Model 和 Sandbox 的装配关系。
- 区分能力声明、配置绑定、运行时可用性与执行授权。
- 统一执行前权限检查、危险操作授权和审计。
- 明确一次 Execution 的配置快照边界；配置更新在下一次执行生效。
- 建立 Sandbox Provider 接口和资源回收协议，MVP 先使用当前 Docker Sandbox。
- 为未来公共能力市场、组织能力市场和更多 Provider 预留接口，不提前实现完整 Marketplace。

退出条件：
- Agent 只能调用本次执行已装配且已授权的能力。
- 配置变化不会在同一次运行中造成工具定义漂移。
- Skill 不需要绕过 Runtime 直接访问未授权资源。
- Sandbox 资源创建、使用、回收和审计可追踪。

### Phase 6 — Collaboration / Artifact MVP 闭环

目标：让 Agent 执行的工作能进入团队协作并形成正式交付。

工作：
- 建设基础 Organization / Project / Space Membership。
- 支持 Message、Thread、@Agent 和 Work 关联。
- 建设基础 Proposal / Decision 流程，区分 AI 建议和正式决策。
- 建设 Work / Assignment / Interaction 的基础产品流程。
- 建设 Artifact、Artifact Version、Artifact Link 和基础访问控制。
- 将执行产物、验证证据和协作决策关联起来。
- 建设基础 Activity / Inbox 投影，不把 Execution Event 直接当成所有产品活动。

退出条件：
- 用户可以从 Agent 或 Space 发起 Work。
- 人与 Agent 可以围绕 Work 讨论、分配和处理必要交互。
- Work 结果可以形成 Artifact 并按权限共享。
- Proposal、Decision、Artifact 和执行证据之间可追溯。

### Phase 7 — MVP 集成验证与旧路径切换

目标：在端到端工作闭环通过验证后，逐步切换旧系统入口。

工作：
- 建立端到端场景测试：普通聊天、多 Work 会话、长程任务、人工等待、工具副作用、恢复、多人协作和产物交付。
- 对旧 Task / Workflow / Session 进行数据映射、双读对账和必要的兼容适配。
- 按领域逐步切换读写权威，避免长时间双写。
- 通过 Feature Flag / 分批流量控制切换风险。
- 明确回滚时的权威数据和补偿步骤。

退出条件：
- 核心产品闭环通过端到端测试。
- 新旧数据对账达到预定标准。
- 回滚不需要猜测哪套状态才是事实。
- 旧 Task 不再承担新 Plan Runtime 的业务状态权威。

## 9. 长期演进路线

以下能力属于产品长期规划，不纳入当前 MVP 的交付门槛，但应通过清晰接口和领域边界保留扩展空间。

| 能力 | 演进方向 | 当前原则 |
|---|---|---|
| Agent Collaboration | 更丰富的 Agent 角色、协作对话、交叉验证、Judge / Supervisor | 先显式委派和结构化共享，不做无限自主群聊 |
| Advanced Workflow / DAG | 动态 DAG、循环、复杂 Join、可视化编排和 Human Gate | Agent 规划与确定性 Workflow 协同 |
| Public / Organization Capability Marketplace | Skill、Tool、Agent、Workflow 的发布、发现、版本和治理 | 当前先统一能力契约与授权边界 |
| Workbench & Multimodal Agent | 丰富工作台、多模态输入输出、交互式 Artifact | 先保证基础 Conversation、Work 和 Artifact 关系 |
| Sandbox Providers | Docker 之外的容器集群、K8s、VM 等 Provider | Resource / Provider 抽象预留，MVP 不做多 Provider |
| Enterprise Governance | 更细粒度 Policy、成本配额、审计、合规、数据边界 | MVP 先做好主体、资源、权限和审计基础 |
| Artifact Collaboration | 实时协作编辑、高级审阅、版本比较和知识关联 | 先完成 Artifact 归档、版本和访问控制 |
| Memory & Context | 更丰富的跨 Work Recall、Scoped Memory、上下文策略 | 访问控制先于检索，History 与模型上下文分离 |

## 10. 不建议在 MVP 提前建设的复杂度

- 不建设通用的、无限层级的 Work / Plan / DAG 元模型。
- 不把 Todo 扩展为第二套任务管理系统或事件子系统。
- 不建设复杂 Prompt Revision / Tool Revision / Session Migration 体系。
- 不为 Provider Prompt Cache 建立业务正确性依赖。
- 不默认共享不同 Agent 的完整模型消息历史。
- 不要求每个 Conversation 都有 Work 或固定 Current Objective。
- 不把 Agent 的工具调用权限交给 Prompt 或 Skill 自我声明。
- 不重建已有 Execution Durable Runtime。
- 不在缺乏明确需求前拆成大量微服务。
- 不把 Deferred 功能解释为 Out of Scope。

## 11. 文档索引与维护责任

### 11.1 核心设计文档

| 文档 | 负责内容 | 当前定位 |
|---|---|---|
| [Product Strategy](./product-design/product-strategy.md) | 产品定位、核心体验、MVP 边界 | 战略基线 |
| [Decision Log](./product-design/decision-log.md) | 已确认决策和 Open Questions | 决策事实源 |
| [Domain Model](./product-design/domain-model.md) | 跨领域对象关系 | Proposed 总览 |
| [Agent Domain](./product-design/agent-domain.md) | Agent 身份、所有权、能力、记忆、参与和委派 | Design Baseline |
| [Execution Model Proposal](../EXECUTION-MODEL-PROPOSAL.md) | Execution 对象模型和恢复协议 | 修订草案 |
| [Execution Architecture](../EXECUTION-ARCHITECTURE.md) | Execution 技术模块落位与实施顺序 | 实施架构 |
| [Plan Domain](./product-design/plan-domain.md) | Work Plan、Task、Verification | Proposed |
| [Plan Runtime Integration](./product-design/plan-runtime-integration.md) | Task Attempt、Coordinator、Recovery | Proposed |
| [Plan Persistence](./product-design/plan-persistence-transaction-design.md) | Collection、事务、Outbox / Inbox | Proposed |
| [Execution / Plan Gap Analysis](./product-design/execution-plan-gap-analysis.md) | 现有代码复用、迁移风险和顺序 | Review |
| [Conversation Context Compression](./CONVERSATION-CONTEXT-COMPRESSION.md) | History / Execution Context、压缩和 Session 原则 | 设计基线 |
| [Compression Implementation Review](./CONTEXT-COMPRESSION-IMPLEMENTATION-REVIEW.md) | 当前压缩实现问题与修正顺序 | 实现审查 |
| [Multi-Agent Collaboration](../multi-agent-collaboration.md) | 多 Agent 协作范式和缺失分析 | 评审稿 |

### 11.2 后续应补充的正式文档

1. Conversation / Context Session Resolution：实体关系、Resolver、Resume / Fork / Reset、并发规则。
2. Work & Work Run Domain：Owner、Assignment、生命周期、Interaction 和完成验收。
3. Capability / Skill Runtime：能力装配、版本一致性、授权、执行和审计。
4. Collaboration / Artifact MVP Spec：用户流程、数据契约、访问控制和验收标准。
5. MVP End-to-End Specification：端到端场景、验收矩阵、迁移和回滚策略。

### 11.3 更新规则

- 领域决策在对应 Decision Log 中记录；本文只做汇总和导航。
- 新的 Proposed 设计不得直接覆盖 Confirmed 决策。
- 状态变化时同步更新本文与对应详细文档。
- 实现完成必须附代码、测试和迁移证据；不能因文档写有目标能力就标记为 Implemented。
- 每个实施阶段结束后更新路线图的实际状态、遗留风险和下一阶段入口。

---

## 12. 当前结论

项目已有足够多的局部设计，下一步不应继续无边界地增加概念，也不应立即全面改写代码。

建议按本文路线推进：

1. 先评审并冻结关键契约，尤其是 Conversation / Work / Context Session 和 Plan / Execution 边界；
2. 收口 Execution Runtime 的可靠性；
3. 建设 Plan Domain 与 Agent Runtime 集成；
4. 再补齐 Context Session Resolver、Capability Boundary 和产品协作交付闭环；
5. 最后通过端到端验证逐步切换旧路径。

**当前状态：全局架构已形成可评审的收口草案，但尚未达到“所有设计完成、可以无条件开始全面实现”的状态。**

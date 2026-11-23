# 产品战略基线

> 状态：**Baseline（持续细化）**
>
> 日期：2026-11-23
>
> 本文记录当前产品讨论中已经形成的战略基线。它是后续领域设计的约束来源；尚未确认的细节不应被当作既定事实。

## 1. 产品定位

**Enterprise Intelligent Work Coordination Platform（企业智能工作协调平台）**

平台让企业员工、AI Agent 与企业业务能力共同参与工作，完成沟通、协作、决策、执行与交付。

产品不是单纯的 Agent Platform，也不是 Slack、Jira、Agent Builder 与 Workflow Engine 的功能拼装。核心价值是打通完整工作链路：

`Discussion → AI Understanding → Work Planning → Collaborative Execution → Deliverables & Decisions`

讨论是工作协调的入口和上下文，不是产品的最终目的。Agent 不只是后台执行引擎，而是可以被使用、被分配工作、参与协作并受企业治理的工作参与者。

## 2. 核心客户与产品入口

- **核心客户：Enterprise。**
- **主要入口：Agent。** 用户可以通过 Agent 发起工作、委托任务、获得分析与协调支持；Agent 也可以进入团队协作场景。
- **DAG 定位：Hybrid。** 平台同时支持 Agent 面向目标进行规划，也支持确定性 Workflow/DAG 承担可复用、可验证的流程控制。Agent 负责目标导向的理解与规划，Workflow 负责明确的流程执行；两者协作而不是互相取代。

## 3. 用户可感知的三项核心能力

### 3.1 Agent 能力

用户能够创建、配置、管理、组合和使用 Agent。Agent 能理解目标、规划工作、调用被授权的能力、执行 Work，并在需要时向人请求澄清、授权或审批。

Agent 可以承担 Assistant、Analyst、Coordinator、Executor、Specialist 等参与职责。这些是 Agent 在具体工作上下文中的角色或参与模式，不是必须固化为平台级类型枚举的五种 Agent 类别。

### 3.2 协作能力

员工与 Agent 围绕共同目标和上下文进行讨论、协调、分工、提案和决策。Agent 可以被提及、被分配工作，也可以在明确订阅和治理规则下主动提供进展或发现问题。

协作能力不以复制完整企业即时通讯产品为目标。MVP 不建设完整的视频会议、语音和实时通讯套件。

### 3.3 产物管理能力

工作结果需要成为可组织、可共享、可审阅、可迭代和可交付的 Artifact，而不是散落在聊天记录或执行日志中。Artifact 应有明确归属、访问权限和生命周期；版本、审阅、协作编辑等能力按路线图逐步演进。

### 3.4 三者的闭环关系

- Agent：承担工作、规划与执行。
- Collaboration：推动工作沟通、协调、分工和决策。
- Artifact：承载工作成果、共享与交付。

**Work 是连接三者的枢纽：Agent 执行 Work；协作推动 Work；Work 产生 Artifact。**

## 4. 核心产品原则

1. **人和 Agent 都是工作参与者。** Agent 具有独立身份；具体执行时还必须明确其代表自身、用户还是组织，以及对应授权。
2. **Work 不等于 Message。** 消息可以触发 Work 创建，但 Message、Proposal、Decision、Work 和 Assignment 是不同业务对象。
3. **AI 输出不自动成为团队事实。** AI Summary 是总结，Proposal 是建议，Decision 是经授权成员确认的决策。
4. **执行与授权分离。** Agent 引用了某项 Skill 或 Tool，不代表它天然拥有执行该能力的权限；权限应在运行时按主体、资源和策略检查。
5. **上下文与记忆按作用域隔离。** 不同用户、Project、Space、Work 的上下文不能无条件混合；检索前必须执行访问控制。
6. **可靠执行是平台基础能力。** Work 执行需要可观测、可审计、可暂停、可恢复，而不是依赖一个长期存活的 Agent 进程。
7. **MVP 聚焦闭环，但不封死演进。** 暂不实现不等于产品不做；MVP 应为高级能力预留合理扩展点，避免提前建设复杂抽象。

## 5. 核心业务对象概览

以下是当前领域模型的概念边界，具体属性、状态机和关系将在领域文档中进一步定义。

| 对象 | 主要职责 |
|---|---|
| Organization | 企业租户、安全与治理边界 |
| Team | 企业中相对稳定的组织或团队结构 |
| Project | 围绕长期目标组织上下文、成员、Work 与成果 |
| Collaboration Space | 人与 Agent 围绕主题讨论、协调和决策的场所 |
| Work | 有目标、负责人、执行过程和交付标准的工作对象 |
| Work Run | Work 的一次实际执行记录 |
| Interaction | 执行过程中需要人补充信息、授权、审批或确认的交互 |
| Agent | 具有稳定身份、所有权、版本和能力配置的工作参与者 |
| Artifact | 可管理、共享、审阅和交付的工作成果 |
| Message / Thread | 协作讨论记录 |
| Proposal | 成员或 Agent 提出的建议 |
| Decision | 经授权人员确认的团队决策 |
| Assignment | Work 的负责人、执行者和参与者分配 |
| Activity | 协作与工作过程中的活动事件 |

对象之间不是严格的单根树形层级。例如，一个 Project 可以关联多个 Space 和 Work；一个 Work 也可能在多个 Space 中被讨论或由多个团队参与。应通过显式关系表达关联，而不是强行规定唯一父子容器。

## 6. Workspace 概念方向

当前区分三种工作环境：

- **Personal Workspace**：个人委托、管理个人 Work、处理待响应 Interaction、管理个人可访问的 Agent 和 Artifact；无需先创建 Project 或 Space 就能开始一项工作。
- **Collaboration Space**：围绕某个主题进行讨论、协调、分工和决策；可为临时或持久场所。
- **Project Workspace**：围绕长期目标组织项目背景、成员、Agent、多个 Space、Work、决策和成果。

三者不是互斥的产品孤岛，也不应被设计成僵硬的树形父子关系。Work、Artifact、Membership 和访问控制关系负责连接这些工作环境。

## 7. MVP 目标与边界

### 7.1 MVP 要验证的核心闭环

一个团队围绕明确目标协作，Agent 理解上下文并协助协调工作；人和 Agent 共同执行，最终形成可交付成果。

### 7.2 MVP 必须覆盖的能力

- Organization 与基础成员/权限边界。
- 基础 Project 和 Collaboration Space。
- 讨论基础：Message、Thread、文件或 Artifact 引用。
- Agent Participation、@Agent 和受控的主动总结。
- AI Coordination：总结、行动项提取、Proposal 生成。
- Decision 确认与记录。
- Work 创建、关联、分配与执行。
- Artifact 共享、基础版本与预览。
- 执行持久化、恢复、审计与基础可观测性。
- Agent Runtime、Skill/Tool/Knowledge 基础能力。
- 基础 Workflow Runtime 与 Docker Sandbox。

### 7.3 MVP 暂缓，不等于产品不做

- 组织内部 Capability Marketplace：后续 P1。
- 公共插件/能力市场与生态：后续 P2。
- 高级 DAG、复杂 Workflow 编排：逐步演进。
- 完整 Multi-Agent 协作与群体讨论：后续阶段。
- 更多 Sandbox Provider（K8s、VM、物理机等）：后续阶段。
- 丰富 Agent Studio、多模态交互：后续阶段。
- Artifact 实时协作编辑与高级审阅：后续阶段。
- 企业级高级治理、策略与成本管理：按企业需求演进。

### 7.4 明确不作为产品目标的方向

- 复制完整 Slack/钉钉级即时通讯产品，包括完整视频会议、语音和实时通讯能力。
- 把所有业务对象都做成聊天消息或把所有工作都限制在会话中。
- 让 Agent 绕过组织权限，依靠 Prompt 自我约束访问数据。
- 以无限制自主多 Agent 群聊作为核心产品体验。

## 8. 支撑领域与横向能力

核心产品能力由以下领域支撑：

- **Collaboration Infrastructure**：Conversation、Event、Membership、Context。
- **Agent & Capability Infrastructure**：Agent Runtime、Skills、Tools、Models、Knowledge。
- **Work & Workflow Infrastructure**：Work、Assignment、Workflow、DAG。
- **Execution & Resource Infrastructure**：Sandbox、Scheduler、Persistence、Recovery。

横向企业能力包括 Identity & Access Control、Security、Audit、Observability、Governance、Billing & Quota。

## 9. 设计约束与待细化事项

后续领域设计必须进一步回答：

1. Personal Work 如何转入 Project 或升级为团队协作工作？
2. Personal Artifact 如何分享给 Space、Project 或其他成员，分享后权限如何变化？
3. Personal Agent 如何加入 Organization 或 Space，个人所有权与组织使用权如何并存？
4. Agent 独立身份与代表用户/组织执行时，如何计算有效权限并防止 confused deputy？
5. Agent Memory Namespace、Context Snapshot 和执行主体之间如何建立可审计的访问边界？
6. Work、Work Run、Assignment、Interaction 的状态和生命周期如何定义？
7. Decision 如何与 Proposal、Message、Work 和 Artifact 建立可追溯关系？

这些问题将在相应领域文档中逐项解决，不在本战略基线中提前臆造答案。

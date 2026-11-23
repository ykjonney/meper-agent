# Product Design Decision Log

> 状态：持续维护。
>
> 本文只记录已经明确确认或当前推荐的决策。尚未拍板的内容放在 Open Questions 中，不得误读为既定约束。

## Decision records

### PD-001：核心客户定位为 Enterprise

- **状态：Confirmed**
- **决策：** 产品核心客户定位为企业客户。
- **影响：** Organization、权限、安全、审计、治理和多成员协作是产品设计的一等约束，而不是后期附加功能。

### PD-002：主要产品入口为 Agent

- **状态：Confirmed**
- **决策：** Agent 是用户发起和推进工作的主要入口。
- **影响：** Agent 必须能连接协作上下文、Work 和 Artifact；产品不能退化为仅供开发者配置 Agent 的控制台。

### PD-003：DAG 采用 Hybrid 定位

- **状态：Confirmed**
- **决策：** Agent 负责目标导向理解与规划；Workflow/DAG 负责确定性、可复用、可验证的流程控制。两者协同。
- **影响：** 不能把所有任务都强制转成 DAG，也不能让 Agent 取代需要确定性保证的流程。

### PD-004：产品核心体验由 Agent、Collaboration、Artifact 三项能力组成

- **状态：Confirmed**
- **决策：** 用户可感知的核心能力是 Agent 能力、协作能力和产物管理能力；Work 是三者之间的枢纽。
- **影响：** 导航、领域拆分和 MVP 都应围绕完整工作闭环，而不是围绕底层技术组件组织。

### PD-005：MVP 聚焦核心闭环，但保留长期演进空间

- **状态：Confirmed**
- **决策：** MVP 必须足够聚焦，但不能通过错误的领域边界或不可扩展设计封死高级能力。
- **影响：** 文档必须区分 MVP、Deferred 和 Out of Scope；架构为 Marketplace、高级 DAG、多 Agent、多种 Sandbox、丰富 Agent Studio 与企业治理预留合理扩展点。

### PD-006：Agent 支持 Shared 使用模型

- **状态：Confirmed**
- **决策：** 同时支持 Personal Agent 和 Organization Agent；Agent 可被分享或授权给其他成员使用。
- **影响：** Agent Owner、Visibility、Access、Publisher 和 Executor 必须区分。

### PD-007：Agent Definition 与 Work 执行关系为 Work-scoped

- **状态：Confirmed**
- **决策：** 同一 Agent Definition 可以承担多个 Work；每个 Work 有独立执行状态、上下文和恢复信息。
- **影响：** Agent 定义、Assignment、Work Run 和 Runtime Instance 不应混为一个对象。

### PD-008：Agent 创建入口同时支持 Studio 与自然语言会话

- **状态：Confirmed**
- **决策：** Agent 可通过 Agent Studio 创建，也可在自然语言交互中创建。
- **影响：** 两种入口应复用同一 Agent Domain 模型和生命周期。

### PD-009：Agent Version 使用 Manual Upgrade

- **状态：Confirmed**
- **决策：** 已发布版本不可变；新 Work 默认使用最新 Published Version；已启动 Work 默认固定启动时版本，升级由用户显式发起。
- **影响：** 版本升级必须可审计，并记录升级前后版本与配置差异。

### PD-010：Space 创建 Agent 的默认 Owner 为 Personal

- **状态：Confirmed**
- **决策：** 用户在 Space 中创建 Agent 时，默认 Owner 为当前用户；创建时应明确展示所有权。
- **影响：** 在 Space 中创建或使用 Agent，不自动意味着 Agent 归 Organization 所有。

### PD-011：Agent Memory 采用 Scoped 模型

- **状态：Confirmed**
- **决策：** Agent Memory 按作用域隔离，而不是为一个 Agent 建立跨用户、跨项目的无差别共享记忆。
- **影响：** Personal、Project、Space、Work 等 Scope 的读写策略必须明确；私人记忆不能因共享 Agent 而泄漏给其他用户。

### PD-012：Agent Identity 采用 Hybrid 模型

- **状态：Confirmed**
- **决策：** Agent 拥有独立身份；具体操作可代表用户或组织执行，执行时必须明确操作主体和授权上下文。
- **影响：** 后续必须定义有效权限计算、委托链、审计主体和防止 confused deputy 的机制。

### PD-013：Personal Workspace 是独立工作环境

- **状态：Proposed**
- **决策：** Personal Workspace 不等于个人聊天窗口，也不等于 Collaboration Space；它承载个人 Work、Interaction、Artifact、Agent 和会话入口。
- **影响：** 个人可不创建 Project/Space 就发起 Work；与团队协作的连接通过显式关联和授权完成。

## Open Questions

以下问题尚未拍板，后续应在对应领域设计中决策：

1. Personal Work 转入 Project 的具体操作语义：迁移、关联、复制还是创建协作 Work。
2. Personal Artifact 分享后的归属、访问控制继承、撤销与版本可见性。
3. Personal Agent 加入 Space 时，Participation、Agent Access 与委托执行权限的组合规则。
4. Memory Namespace 的唯一键、ACL 继承、保留和删除策略。
5. Context Builder 在 Agent Identity、Delegating Principal、Organization Policy 与资源 ACL 之间的有效权限计算。
6. Proposal 转 Decision 的授权、确认和审计流程。
7. Work 与 Space/Project 的多对多关联、状态投影和归档策略。

## Change policy

- 新决策使用递增编号，不复用已撤销编号。
- 决策变化时保留原记录，更新状态为 Superseded 或 Rejected，并链接替代决策。
- 重要决策必须记录背景、备选方案、理由、影响范围和迁移要求。
- 实现阶段发现领域冲突时，先回到决策记录修订，再修改实现；不要只在代码中形成隐式产品规则。

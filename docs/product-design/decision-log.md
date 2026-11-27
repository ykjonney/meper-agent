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

### PD-014：Agent 委派采用显式绑定，不要求动态发现

- **状态：Confirmed**
- **决策：** Agent 的委派目标来自显式 Delegation Binding。平台提供通用 Agent，用户可以手动绑定其他 Agent；运行时 Agent 在已绑定且当前获准的目标范围内自主决定是否委派及选择目标，不要求运行时发现未知 Agent。
- **背景与理由：** MVP 优先保证委派关系可理解、可配置和可治理，避免提前引入动态发现、候选检索与路由系统。
- **影响：** Delegation Binding 是配置期关系；Agent Pool 实体、动态 Agent Discovery 和智能路由暂缓，不代表未来不做。

### PD-015：Delegation Binding 与 Delegation 是不同对象

- **状态：Confirmed**
- **决策：** Delegation Binding 表示长期配置的可委派关系；Delegation 表示某次实际发生的委派执行。Binding 不构成永久父子关系，也不改变 Agent Ownership。
- **影响：** 同一目标 Agent 可以被多个 Source Agent 绑定；运行时 Delegation 必须关联来源 Binding，并记录实际目标版本。

### PD-016：Delegation Binding 支持基础用途与版本配置

- **状态：Confirmed**
- **决策：** Binding 至少支持 Purpose、Enabled 和 Version Policy；MVP 的版本策略支持 Latest Published 与 Pinned Version。复杂条件路由、评分和优先级暂缓。
- **影响：** Agent Studio 可以显式管理委派目标及用途；实际 Delegation 创建时必须解析并固定具体 Agent Version。

### PD-017：Platform、Personal 与 Organization Agent 复用同一领域模型

- **状态：Confirmed**
- **决策：** Platform Agent、Personal Agent 和 Organization Agent 使用同一套 Agent Domain 模型，通过 Owner、Publisher 等属性区分。
- **影响：** 平台通用 Agent 是可复用的 Agent Definition / Template，不是特殊 Agent 类型；Clone 后的自定义 Agent 是独立定义。

### PD-018：委派执行必须重新进行权限评估

- **状态：Confirmed**
- **决策：** Delegation Binding 不等于充分授权。每次委派仍需根据父执行主体、Work、目标 Agent、组织策略和本次委派请求计算有效权限；Agent 引用或绑定 Capability 不自动获得其执行权限。
- **影响：** 子 Agent 不得因自身权限较宽而突破父执行、Work 或组织策略的限制；Delegation Context 传递不等于权限传递。

### PD-019：组织治理与个人 Agent 配置权分离

- **状态：Proposed**
- **决策：** Agent Owner / Manager 管理自身 Agent 的委派绑定；Organization Admin 通过组织级 Policy 约束组织内委派行为，但不因管理员身份自动取得个人 Agent Definition 的修改权。
- **影响：** Agent Configuration、Agent Access 和 Organization Governance 必须分离。组织策略对执行的限制仍可覆盖个人配置允许的范围。


### PD-020：Plan 是 Agent Runtime 的一等能力，Todo 是 Task 的视图

- **状态：Confirmed**
- **决策：** 平台将 Plan 作为 Agent Runtime 的一等能力；Plan 描述为实现 Work Run 目标而制定的执行方案，Task 是其中可分配、可追踪和可验证的工作项，Todo 是 Task 面向用户的清单视图，不建立独立 Todo 领域。
- **影响：** Plan 必须支持持久化、版本化、重新规划，并与 Execution、Delegation、Checkpoint 和 Recovery 集成。一个 Task 不等同于一次模型调用或 Execution。

### PD-021：Task 完成采用风险分级验证

- **状态：Confirmed**
- **决策：** Task 完成不能仅依赖 Agent 自我声明；Agent 提交 completion claim 和 Evidence 后，按风险分级 Verification Policy 验收。低风险任务可采用轻量自动检查，高风险操作或关键决策可要求确定性验证器或授权人工确认。
- **影响：** Task 需要可追溯的 Acceptance Criteria、Evidence 和 Verification Result。Work 最终完成还必须满足 Work 自身的 Acceptance Criteria，不能仅以 Todo 全部勾选作为依据。


### PD-022：Task Identity、Revision 与 Runtime State 三层分离

- **状态：Confirmed**
- **决策：** Task 采用稳定身份（Identity）、不可变定义版本（Revision）和可变运行状态（Runtime State）三层模型。
- **影响：** Plan Version 显式引用 Task Revision；运行进度不写入不可变 Revision；结构变化保留 lineage 和历史依据。

### PD-031：一个 Task 默认最多允许一个活动 Attempt

- **状态：Confirmed**
- **决策：** MVP 默认一个 Task 同时最多只有一个活动业务 Attempt。多 Agent 协作通过同一 Attempt 下的多个 Execution / Delegation 实现，不通过并行顶层 Attempt 实现。
- **影响：** Attempt 必须与 Execution 分离；单活动约束由 Coordinator 事务与数据库唯一约束共同保证。未来可通过 AttemptGroup 扩展竞争式并行尝试，不在 MVP 实现。

### PD-032：Task Attempt 状态机与活动状态集合

- **状态：Proposed**
- **建议：** 活动状态为 Created、Running、Blocked、Awaiting Verification；终态为 Succeeded、Failed、Cancelled、Superseded。
- **影响：** Blocked、暂停和 Awaiting Verification 仍占用活动 Attempt 名额，直到 Attempt 进入终态。

### PD-033：一个 Attempt 可关联多个 Execution 与 Delegation

- **状态：Proposed**
- **建议：** Attempt 是业务尝试边界，可包含多个并行或串行 Execution / Delegation；通过显式关联记录角色和是否为完成所必需。
- **影响：** 多 Agent 协作不意味着共享可写 Sandbox；父 Task 仍按自身验收标准验证。

### PD-034：技术重试与业务重试分离

- **状态：Proposed**
- **建议：** Tool Retry、Execution Retry 和 Worker Recovery 不自动创建新 Task Attempt；业务级 Task Retry 创建新 Attempt，并保留旧尝试证据。
- **影响：** 避免 Worker 崩溃、消息重投递或单工具失败导致业务尝试身份被错误重置。

### PD-035：活动 Attempt 固定绑定启动时 Task Revision

- **状态：Proposed**
- **建议：** Attempt 创建时固定 `taskRevisionId`；Plan Version 激活不自动改变运行中 Attempt 的执行语义。Revision 迁移必须先安全停止旧执行并裁决外部副作用。
- **影响：** Replanning 不会静默改变正在执行的任务定义；Acceptance Criteria 实质变化后需要重新验证。

## Open Questions
1. Personal Work 转入 Project 的具体操作语义：迁移、关联、复制还是创建协作 Work。
2. Personal Artifact 分享后的归属、访问控制继承、撤销与版本可见性。
3. Personal Agent 加入 Space 时，Participation、Agent Access 与委托执行权限的组合规则。
4. Memory Namespace 的唯一键、ACL 继承、保留和删除策略。
5. Context Builder 在 Agent Identity、Delegating Principal、Organization Policy 与资源 ACL 之间的有效权限计算。
6. Proposal 转 Decision 的授权、确认和审计流程。
7. Work 与 Space/Project 的多对多关联、状态投影和归档策略。
8. Agent Access 的具体权限矩阵及 Manager 可管理范围。
9. Organization Policy、Work Policy 与 Binding Constraints 的策略合并和解释机制。
10. Binding 被撤销、目标 Agent 被禁用或 Version 被 Deprecated 时，对运行中 Delegation 的精确影响。
11. Clone 后的能力依赖、Skill / Tool 版本锁定及平台升级迁移机制。
12. Delegation Policy 的默认配额、审批条件和企业管理员配置体验。
13. Milestone 在 MVP 中采用嵌入式结构还是独立持久化对象。
14. Task 多 Assignee、并行 Execution 和运行中 Task 的 Replanning 迁移策略。
15. Verification Policy 的风险等级、默认策略、独立验证要求及组织可配置边界。
16. Agent Local Plan 的持久化模型、层级深度和父 Task 验收映射。

## Change policy

- 新决策使用递增编号，不复用已撤销编号。
- 决策变化时保留原记录，更新状态为 Superseded 或 Rejected，并链接替代决策。
- 重要决策必须记录背景、备选方案、理由、影响范围和迁移要求。
- 实现阶段发现领域冲突时，先回到决策记录修订，再修改实现；不要只在代码中形成隐式产品规则。

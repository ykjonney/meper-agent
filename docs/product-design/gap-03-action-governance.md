# GAP-03：Action Governance（操作授权、审批与审计）

> 状态：**Design Proposal（设计提案，待评审）**
>
> 日期：2026-11-26
>
> 本文将 GAP-03 从差距清单展开为可评审的产品设计。新增设计均为提案，不自动视为已批准的产品或 MVP 决策。

## 1. 背景与目标

Personal Agent 会使用 Tools、Connectors、Workspace 和外部系统执行真实操作；Routine 会在用户不在线时启动工作；专业 Agent 之间也会发生委派。系统必须明确谁在代表谁执行、允许访问哪些资源、哪些操作需要人工确认，以及实际发生了什么。

本设计将 Action Governance 定义为贯穿 Agent Runtime 的统一治理能力，而不是单纯的危险 Tool 弹窗。

核心目标：
- 在每次操作前计算有效权限；
- 由平台和组织策略限制用户授权范围；
- 对需要确认的操作执行可靠审批；
- 使长程 Work 和无人值守 Routine 能正确等待审批并恢复；
- 记录可追溯、不可由 Agent 擅自篡改的操作与治理事件；
- 防止 Agent 委派、Routine 或 Connector 绕过权限边界。

## 2. 四个核心概念

### 2.1 Permission（权限）

Permission 表示某个主体是否具备某种能力，例如读取仓库、写入文件、发送邮件。它回答：“这个主体有没有能力做这类事？”

### 2.2 Policy（策略）

Policy 是 Runtime 在当前上下文下执行的规则，决定某个操作是否允许、是否需要审批、是否需要附加约束。Policy 可以基于主体、资源、操作、风险、Work / Routine 上下文和组织要求进行判断。

### 2.3 Approval（审批）

Approval 是针对某个具体操作请求的人工确认，回答：“这一次具体操作是否得到有权人员同意？”

审批不是权限本身。审批通过不能突破 Permission 或 Policy 的禁止规则。

### 2.4 Audit（审计）

Audit 记录操作请求、权限判断、审批、实际执行和结果，回答：“系统实际发生了什么？”

Conversation 中 Agent 的自然语言陈述不能替代 Audit；Agent 说操作成功，不代表外部系统真的执行成功。

## 3. 现有权限体系与 Agent Action Governance 的关系

当前产品已有用户、角色、权限键和 API 访问控制。该体系主要保护平台 UI 和 API，例如用户是否可以访问管理页面或调用某个管理端点。

Agent Action Governance 面向运行时的具体动作，例如：
- 某个 Agent 能否读取指定仓库；
- 当前 Work 是否允许修改文件；
- Routine 是否允许自动发送邮件；
- 某次 PR 合并是否必须经过审批。

两者应协同，但不能混为一谈：
- 平台 API RBAC 保护用户对平台功能和资源的访问；
- Agent Action Governance 控制 Agent 代表用户或组织执行外部动作；
- 外部 Connector 的凭证和服务端 ACL 仍然是独立的安全边界。

不能因为用户拥有平台某个页面的 write 权限，就推导 Agent 自动获得对应外部资源的写权限。

## 4. 统一操作模型

Runtime 应将 Tool / Connector 调用归一化为可评估的 Action Request。至少包含：

- Acting Principal：实际发起操作的 Agent / Execution；
- Delegating Principal：委派链上的调用主体；
- User / Organization Context：代表哪个用户、属于哪个组织；
- Work / Routine / Conversation：操作发生的业务上下文；
- Capability / Action：具体能力和动作；
- Resource：目标资源及其归属；
- Parameters：实际操作参数或安全摘要；
- Risk Context：操作影响、可逆性和数据敏感性；
- Correlation：关联 Execution、Delegation 和追踪 ID。

Agent 可以提出操作请求，但不能自行决定最终权限结果，也不能通过修改请求元数据来降低风险等级。

## 5. 有效权限计算

### 5.1 多层约束

建议有效权限不得超过所有适用授权边界的交集：

    P_effective =
      P_user_authorization
      ∩ P_agent_capability
      ∩ P_work_or_routine
      ∩ P_delegation_chain
      ∩ P_organization_policy
      ∩ P_platform_baseline

其中：
- User Authorization：用户对 Agent、Connector 和资源的授权；
- Agent Capability：Agent 被配置和允许使用的能力；
- Work / Routine：当前工作或自动化定义授予的操作范围；
- Delegation Chain：委派链上各主体的权限约束；
- Organization Policy：组织策略；
- Platform Baseline：平台不可被下级覆盖的安全基线。

显式拒绝优先于允许。任何一层禁止都不能被其他层的 Allow 覆盖。

### 5.2 委派权限

每次 Delegation 都必须重新计算有效权限。子 Agent 不得因自身配置权限较宽而突破父执行主体、当前 Work、用户授权或组织策略的限制。

Delegation Context Package 传递上下文不等于传递权限。父 Agent 可以提供完成任务所需的信息和资源引用，但 Runtime 必须验证子 Agent 对这些资源的访问权限。

这与既有 Agent Domain 的 Delegation Governance 设计一致，本提案不另造一套冲突的委派权限模型。

### 5.3 动态重新验证

权限不是创建 Work 或 Routine 时一次性冻结的永久凭证。每次实际操作前都要基于当前有效权限和策略重新判断。

用户撤销 Connector 授权、管理员收紧组织策略或 Agent 被停用后，后续操作必须立即受影响。运行中的操作是否需要中断，应依据撤销类型和操作风险处理；不能仅凭创建时的权限快照继续执行高风险动作。

## 6. 风险分类与审批策略

不建议只按 Tool 名称区分安全与危险。相同 Tool 可能执行不同影响的动作。例如 GitHub Tool 的读取 Issue、创建 Issue、合并 PR 和删除仓库，风险显著不同。

风险评估应至少考虑：
- 操作类型；
- 目标资源及其重要性；
- 是否产生外部副作用；
- 是否可逆及恢复成本；
- 数据敏感性；
- 影响范围；
- 是否涉及资金、对外沟通、生产环境或权限变更；
- 当前是否为无人值守 Routine。

建议的初始风险档位：

| 风险 | 示例 | 默认策略建议 |
|---|---|---|
| Low | 读取、搜索、查询 | 权限通过后直接执行 |
| Medium | 创建评论、修改普通文件、发送普通通知 | 按授权规则执行；无明确授权时请求确认 |
| High | 合并 PR、删除数据、对外发送重要信息、生产变更 | 默认每次审批 |
| Prohibited | 违反平台安全基线或组织硬性禁止项 | 直接拒绝，不允许审批覆盖 |

风险分类应由 Runtime 根据规范化 Action Request 和受信任的规则计算，不能只依赖 Agent 自报风险等级。实际阈值和具体动作映射需在实施阶段形成可维护的分类表。

## 7. 用户授权模式

建议提供四种基础授权选择：

### 7.1 Allow Once

仅允许当前具体 Action Request。授权必须绑定操作主体、资源、动作和关键参数；不能扩展为同类操作的永久许可。

### 7.2 Always Allow

建立一条范围明确的授权规则，使未来符合规则的操作可以免于逐次询问。

Always Allow 必须限定：
- 主体或 Agent 范围；
- 资源范围；
- 动作范围；
- 必要的参数约束；
- 生效时间和可选到期时间；
- 是否允许委派执行；
- 适用的 Work / Routine 范围（如有）。

不能将“允许这个 Agent 使用 GitHub”解释为允许它对所有仓库执行所有写操作。用户应能查看和撤销长期授权。组织策略和平台基线始终可以收紧或拒绝该授权。

### 7.3 Ask First

符合规则的操作每次执行前都请求用户确认。建议作为需要人工确认的操作的默认模式。

### 7.4 Deny

拒绝当前操作。用户可以选择仅拒绝本次请求，或建立限定范围的拒绝规则。拒绝规则不能覆盖平台和组织的硬性策略，只能进一步限制用户自己的授权范围。

## 8. 审批执行协议

### 8.1 统一门控

建议所有产生外部副作用或需要特殊授权的操作经过同一 Runtime 门控：

1. Agent 提交 Action Request。
2. Runtime 规范化主体、资源、动作和参数。
3. Runtime 计算当前有效权限。
4. Policy Engine 评估允许、拒绝或需要审批。
5. 若拒绝，返回结构化拒绝原因并记录事件。
6. 若需要审批，创建 Approval Request 并暂停当前操作。
7. 用户或有权审批人作出决定。
8. 执行前重新验证权限、策略、审批有效期和操作快照。
9. 通过后才调用外部 Tool / Connector。
10. 记录实际执行结果和关联 Audit Event。

**不得先执行外部副作用，再补审批记录。**

### 8.2 Approval Request

审批请求至少需要记录：
- Approval ID；
- 对应 Action Request 的不可变快照或摘要；
- 请求主体和委派链；
- 目标资源与操作影响；
- 请求原因和相关 Evidence；
- 审批人及其审批权限；
- 状态、创建时间和过期时间；
- 决策及决策时间；
- 执行前重新验证结果。

### 8.3 审批与操作绑定

审批必须绑定具体操作，而不是仅绑定 Tool 名称或宽泛意图。

例如批准合并仓库中的 PR #128，不代表批准未来合并所有 PR。

如果目标资源、关键参数、提交内容或影响范围发生实质变化，旧审批必须失效或重新评估。不能把对旧操作的批准复用于新操作。

### 8.4 审批人权限

只有对目标资源和该风险级别具备审批权限的用户才能批准。发起操作的 Agent 不能批准自己的请求。企业策略可以要求特定角色或双人审批；MVP 先支持当前用户或明确授权的审批人，复杂审批链后续扩展。

### 8.5 等待与恢复

审批等待应是长程 Work 的正常状态：
- Work / Execution 进入 Awaiting Approval 或相应阻塞状态；
- 当前 Tool 调用不应一直占用运行线程；
- 审批通过后恢复执行；
- 审批拒绝后由 Agent 根据 Work 计划决定停止、调整或继续其他允许的步骤；
- 审批超时或请求过期时不得自动视为批准。

Routine 在无人值守运行时遇到审批要求，应暂停相关操作并通知用户，不能绕过审批，也不应把整个 Routine 的读取授权解释为写入授权。

## 9. 审批用户体验

审批卡片不应只显示 Tool 名称或“Agent 请求权限”。至少应展示：
- 谁发起操作、是否由其他 Agent 委派；
- 代表哪个用户或组织执行；
- 操作目标和具体资源；
- 实际操作及关键参数；
- 影响范围和风险说明；
- Agent 请求原因；
- 相关 Work、Artifact 或 Evidence；
- 本次授权的范围；
- 请求有效期和可用决策。

对高风险操作，应允许查看完整操作详情和关键参数，不能只展示 Agent 自己生成的一句理由。

## 10. Audit 与 Activity Log

### 10.1 与 Conversation 的区别

Conversation 保存用户与 Agent 的交互；Audit 保存系统实际发生的治理与操作事实。Agent 的自然语言陈述不能证明外部操作成功。

### 10.2 事件类别

建议至少记录三类事件：

- **Action Event**：Action Request、权限判断、Tool / Connector 实际调用和执行结果。
- **Approval Event**：审批请求创建、批准、拒绝、过期和撤销。
- **Policy Event**：权限或策略变更、授权撤销及其对运行的影响。

### 10.3 审计字段

关键事件应能关联：
- Actor / Acting Principal；
- User / Organization；
- Delegation Chain；
- Work / Routine / Conversation；
- Execution；
- Action / Resource；
- Policy Decision；
- Approval；
- Result / Error；
- Timestamp；
- Correlation ID。

### 10.4 完整性与数据最小化

Audit 应采用追加式记录。普通 Agent 不应具有修改或删除审计记录的能力。更正应通过新的补充事件表达。

审计记录需要保留足以追溯的操作摘要和资源引用，但不应无差别保存密码、访问令牌、密钥或不必要的敏感数据。敏感参数应脱敏、摘要化或通过受控引用访问。

### 10.5 MVP 可见性

MVP 建议提供：
- 用户可查看与自己相关的操作历史；
- 审批历史与实际执行结果关联；
- 能区分成功、失败、拒绝、等待审批和跳过；
- 具备基本时间、Agent、Work 和操作类型筛选。

完整企业审计导出、SIEM 集成和异常检测后续实现。

## 11. Routine 与无人值守执行

Routine 的启用不等于对所有未来操作的无限授权。

例如用户授权每周读取 GitHub Issue，不代表 Routine 可以自动合并 PR。

Routine Work 遇到需要审批的操作时：
1. 创建本次 Work；
2. Agent 提交具体 Action Request；
3. Runtime 执行权限和审批判断；
4. 需要审批时，Work 进入等待状态；
5. 通知用户或有权审批人；
6. 审批通过后重新验证并恢复；
7. 拒绝或过期则记录结果，Agent 按 Work 计划处理后续步骤。

Routine 的授权范围必须在每次实际操作时重新评估，不能依赖启用时的旧权限快照。

## 12. MVP 建议范围

### 12.1 建议纳入

- 统一 Action Request 规范化和 Runtime 操作门控。
- Permission、Policy、Approval、Audit 的职责分离。
- 基础风险分类和默认审批规则。
- 用户、Agent、Work、Routine、Delegation 和 Organization 的授权边界。
- 有效权限交集计算，明确拒绝优先。
- Allow Once、Always Allow（范围限定）、Ask First、Deny 的基础语义。
- 需要审批的操作进入可恢复等待状态。
- Approval Request 绑定具体操作快照。
- 执行前重新验证权限、策略和审批有效性。
- 基础 Approval History。
- 基础 Activity Log / Audit Event。
- 委派执行重新计算有效权限。
- Routine 遇到审批时暂停并通知，不绕过审批。

### 12.2 暂缓实现

- 通用可编程 Policy DSL 和复杂策略引擎。
- 多级审批、审批委托和 SLA。
- 复杂授权规则管理中心。
- 完整审计搜索、导出和分析平台。
- 自动异常行为检测。
- 企业 SIEM / SOAR 集成。
- 高风险操作双人审批的通用编排。
- 自动回滚和跨系统补偿事务。

## 13. 初步领域模型建议

建议区分以下概念，不必在 MVP 一次性实现所有独立服务：

- **Action Request**：规范化的一次操作请求及其不可变关键参数快照。
- **Authorization Grant**：用户或管理员授予的有范围限制的授权规则。
- **Policy Decision**：Runtime 对当前操作的允许、拒绝或需审批判断及其依据。
- **Approval Request**：针对具体 Action Request 的人工确认流程。
- **Audit Event**：追加式治理与操作事实记录。

Policy Definition 可由平台、组织和用户不同层级提供；Policy Decision 是一次运行时评估结果。Authorization Grant 不能代替 Policy，也不能代替 Approval。

具体持久化结构、版本策略、缓存和撤销传播机制留待领域与 Runtime 设计阶段确定。

## 14. 与既有领域边界的兼容性

- **User / Organization**：提供授权主体与治理范围。
- **Agent**：是可执行主体，但不能自行扩大权限。
- **Conversation**：提供交互上下文，不是权限真源。
- **Work**：可以进一步限制当前工作的操作范围；审批等待与 Work 生命周期衔接。
- **Execution**：执行前必须通过 Runtime 门控；等待审批后可恢复。
- **Delegation**：每次委派重新计算权限，Context 不等于权限传递。
- **Routine**：长期触发定义不是永久授权凭证；每次执行重新评估。
- **Connector**：凭证与外部系统 ACL 仍是独立安全边界。
- **Project / Workspace**：资源访问必须检查资源 ACL 和当前授权。
- **Artifact / Evidence**：可作为审批依据与审计引用，不替代授权记录。

## 15. 待评审问题

1. MVP 风险等级是否采用 Low / Medium / High / Prohibited 四档？本提案建议是。
2. Always Allow 是否必须限制 Agent、资源、动作和有效期？本提案建议是。
3. Allow Once 是否绑定完整关键参数快照？本提案建议是。
4. 用户是否可以设置长期 Deny 规则？本提案建议支持限定范围的拒绝规则。
5. Routine 遇到审批时是否将 Work 置于 Awaiting Approval 并等待恢复？本提案建议是。
6. MVP 是否只支持单人审批，复杂多级审批后续实现？本提案建议是。
7. 审计是否在 MVP 提供用户可见的基础 Activity Log？本提案建议是。
8. 用户授权、Organization Policy 和 Platform Policy 的最终优先级与撤销传播协议，是否在领域设计阶段单独形成 ADR？本提案建议是。

## 16. 验收标准（产品层）

- Agent 的每个受治理操作都经过 Runtime 统一权限判断。
- 平台 API RBAC 不会被误当作 Agent 对外部资源的授权。
- 用户授权不能突破组织或平台禁止策略。
- Work 限制和委派链限制会收紧有效权限。
- Agent 不能通过自报风险等级绕过 Runtime 风险评估。
- 需要审批的操作在外部副作用发生前等待确认。
- 审批绑定具体操作，关键参数变化后不能复用旧审批。
- 审批通过后执行前重新验证权限和策略。
- Routine 不会因为无人值守而跳过审批。
- 用户撤销授权或组织策略收紧会影响后续操作。
- 用户可以查看审批结果和实际操作记录。
- Audit 能区分 Agent 请求、Runtime 决策、审批和外部执行结果。
- Agent 无法篡改或删除其操作审计记录。

## 17. 后续依赖

- GAP-02：Automation / Routine，衔接无人值守执行与审批等待。
- GAP-04：Artifact 工作台，提供审批依据和操作产物的查看入口。
- GAP-05：Workspace / Sandbox，定义文件、终端和浏览器操作的资源权限。
- GAP-08：多模态与跨设备交互，承载移动端审批和通知。
- GAP-10：Usage / Cost / Observability，扩展运行监控和审计分析。

---

**提案结论：** 建立统一 Action Governance：Runtime 将每次 Tool / Connector 调用规范化为 Action Request，基于用户授权、Agent 能力、Work / Routine 范围、委派链、组织策略和平台基线计算有效权限；需要人工确认时创建绑定具体操作的 Approval Request；实际请求、决策、审批和执行结果写入追加式 Audit。MVP 聚焦可靠的操作前门控、范围受限授权、可恢复审批和基础审计，不提前建设复杂企业策略引擎。

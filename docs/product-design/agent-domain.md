# Agent Domain

> 状态：**Design Baseline（持续细化）**
>
> 本文定义 Agent 的身份、所有权、版本、能力、记忆、参与和委派领域边界。它描述目标领域模型，不代表所有能力已经在当前代码中实现。
>
> 状态标记：**Confirmed** 为已明确确认的产品决策；**Proposed** 为当前推荐设计；**Open** 为仍需评审的问题；**Deferred** 为明确暂缓而非产品不做。

## 1. Domain Purpose

Agent Domain 管理可被创建、配置、发布、授权、使用和委派的 Agent Definition。它定义 Agent 是谁、由谁拥有、具备什么能力、如何被使用，以及允许建立哪些委派关系。

Agent Domain 不负责承载某次实际执行。一次 Work 中的执行状态、上下文、检查点和恢复信息属于 Execution Domain；委派的运行时关系也属于 Execution Domain。

核心边界：

- **Agent Definition** 是可复用的配置与身份定义。
- **Agent Version** 是不可变的已发布配置版本。
- **Agent Access** 表达主体对 Agent 的访问权限。
- **Delegation Binding** 表达一个 Agent 被配置为可委派给哪些目标 Agent。
- **Delegation** 表达一次实际发生的委派，属于运行时执行记录。
- **Worker Execution** 表达某个 Agent 在一次 Work Run 中的实际执行。

## 2. Agent Identity, Ownership and Access

### 2.1 Agent Identity

**Confirmed：** Agent 具有独立身份；具体操作可以代表 Agent 自身、用户或组织执行，但每次执行必须明确操作主体和授权上下文。

Agent Identity 不等于用户身份，也不意味着 Agent 自身拥有对所有资源的权限。平台必须能够追踪：

- Agent Identity：哪个 Agent 发起了操作。
- Initiating Principal：哪个用户或系统主体发起了工作。
- Delegating Principal：谁将任务委派给当前 Agent。
- Execution Authority：本次执行实际使用的授权主体与权限范围。

具体授权计算由 Identity & Access Control / Governance 能力负责，不由 Prompt 自我约束。

### 2.2 Ownership

**Confirmed：** Agent 支持 Personal Owner 和 Organization Owner。每个 Agent Definition 具有明确 Owner。

Owner 类型：

- **User Owner**：个人拥有的 Agent。
- **Organization Owner**：组织拥有的 Agent。

Agent 在 Space 中创建时，默认 Owner 为当前用户；在 Space 中创建、使用或参与，不自动改变 Agent 所有权。

### 2.3 Ownership, Visibility, Access and Publisher

以下概念必须分开：

| 概念 | 语义 |
|---|---|
| Owner | 对 Agent Definition 负有所有权和最终管理责任的主体 |
| Visibility | 哪些主体能够发现或查看 Agent |
| Access | 哪些主体能够使用或管理 Agent，以及对应权限 |
| Publisher | 发布或分发 Agent 的主体 |
| Executor | 某次执行中实际运行 Agent 的主体/运行时身份 |

分享 Agent 不改变 Owner。可见不代表可使用；可使用不代表拥有配置管理权；Agent 引用了某项 Capability 也不代表执行时自动获得该能力的授权。

### 2.4 Agent Access

**Proposed：** MVP 的 Agent 管理访问级别采用 Owner、Manager、User 三类：

- Owner：管理 Agent 定义、版本发布和访问授权。
- Manager：在 Owner 授权范围内管理 Agent 配置。
- User：按授权使用 Agent，不默认修改其定义。

具体操作仍需结合组织策略和资源权限检查。此处的 Agent Access 不替代 Tool / Resource Authorization。

## 3. Agent Definition and Version

### 3.1 Agent Definition

Agent Definition 描述一个可复用 Agent 的稳定身份和配置，建议包含：

- Identity：名称、描述、头像及身份信息。
- Purpose：职责、目标和适用场景。
- Instructions：行为指令与约束。
- Model Strategy：模型选择与模型配置策略。
- Planning Preferences：专业规划偏好，不是必填的独立 Planner 插件。
- Capabilities：引用的 Skills、Tools、Knowledge 和可调用 Workflow。
- Memory Policy：允许使用的 Memory Scope 与读写策略。
- Runtime Policy：运行时资源和环境偏好。
- Interaction Policy：澄清、通知、审批和用户交互策略。
- Delegation Configuration：允许委派的目标 Agent 及相关配置。
- Governance References：适用的治理策略引用。

上述字段是领域配置维度，不意味着 MVP 必须一次性开放全部配置 UI。

### 3.2 Version Lifecycle

**Confirmed：** Agent Version 采用 Manual Upgrade：

- Draft 可编辑。
- Published Version 不可变。
- 修改已发布 Agent 时创建新的 Draft Version。
- 新 Work 默认使用创建时可解析到的最新 Published Version。
- 已启动 Work 默认固定启动时选定的 Agent Version。
- 对运行中的 Work 升级 Agent Version 必须显式发起，并记录升级前后版本与配置变化。

建议生命周期：

`Draft → Published → Deprecated → Archived`

**Proposed：** 每次 Delegation 在创建时解析并固定目标 Agent 的具体 Published Version ID。即使 Binding 使用 Latest Published 策略，历史 Delegation 也必须记录最终解析出的版本，不能在执行中自动漂移。

## 4. Agent Capabilities

Agent 的专业能力由可组合的 Capability 构成：

| Capability | 职责 |
|---|---|
| Skill | 专业方法、规范、知识和操作指南 |
| Tool | 可执行的外部或内部操作 |
| Knowledge | Agent 可检索或读取的知识资料 |
| Workflow | 确定性、可复用的流程定义 |
| Model | 提供推理与生成能力的模型及配置 |

Agent 引用 Capability 不等于获得执行权限。Tool Gateway / Policy Evaluation 必须在运行时针对主体、资源、Work 和操作进行授权检查。

Agent 类型不应在底层固化为固定枚举。Research、Coding、Review、Testing 等首先是具体 Agent Definition、模板或职责描述，而不是平台强制的 Agent 类型系统。

## 5. Agent Memory and Context

**Confirmed：** Agent Memory 采用 Scoped 模型。共享 Agent Definition 不意味着共享所有使用者的私人记忆。

建议的作用域：

| Scope | 内容示例 |
|---|---|
| Personal Memory | 某用户与 Agent 的偏好和授权信息 |
| Project Memory | 项目目标、背景、约束和确认决策 |
| Space Context | 团队讨论脉络、议题和协作状态 |
| Work Memory | Work 计划、进度、中间发现和待办 |
| Run State | 执行检查点、临时状态和恢复信息 |

Run State 属于 Execution State，不应与长期 Memory 混为一谈。Conversation 保存交互历史；Context Snapshot 记录一次执行实际使用的上下文来源、版本和授权依据。

检索必须先执行访问控制，不能先检索所有内容再依赖 Prompt 过滤。Memory Promotion 到更广作用域需要明确授权或治理流程。

## 6. Agent Participation

Agent 可以作为参与者加入 Collaboration Space、Project 等协作上下文。

Agent Participation 是局部参与配置，不创建新的 Agent Definition，也不等于权限授予。Participation 可以表达：

- Role：在当前上下文中的参与角色。
- Responsibilities：局部职责。
- Subscriptions：关注的主题或事件。
- Participation Policy：主动发言、总结和通知的行为约束。

同一个 Agent 可以在多个 Space 以不同 Participation 参与，也可以不加入任何 Space 而直接承担 Work。

## 7. Delegation Configuration

### 7.1 Product Decision

**Confirmed：** Agent 可以委派给其他 Agent，但 MVP 不要求 Agent 在运行时动态发现未知 Agent。

委派目标来自显式配置的 Delegation Binding：

1. Platform 提供可复用的通用 Agent。
2. 用户可以为自己的 Agent 手动绑定其他有权使用的 Agent。
3. 运行时 Agent 可以在已绑定且当前获准的目标范围内自主判断是否委派、选择谁以及如何拆分任务。
4. 未绑定的 Agent 不会因为组织中存在或可见而自动成为可委派目标。

核心原则：**自主决定如何委派，不等于自主发现委派对象。**

### 7.2 Platform Provided Agents

**Confirmed：** 平台可以提供 Research、Coding、Review、Testing、Data Analyst、Writing 等通用 Agent。

这些是平台发布的 Agent Definition / Template，不是特殊 Agent 类型。平台 Agent 可以被用户或组织选择绑定使用。

用户不能直接修改平台原始定义。**Proposed：** 用户可 Clone 平台 Agent，形成独立的 Personal Agent 或 Organization Agent Definition，再自行修改。Clone 后不持续继承原始 Agent 的动态配置；平台更新通过显式升级或迁移处理。

### 7.3 Delegation Binding

**Confirmed：** Delegation Binding 是长期配置关系，表示 Source Agent 被允许将任务委派给 Target Agent；它不是永久父子关系，也不代表目标 Agent 的所有权从属于 Source Agent。

同一个 Target Agent 可以被多个 Source Agent 绑定。

建议字段：

| 字段 | 语义 |
|---|---|
| Binding ID | 稳定的绑定标识 |
| Source Agent Definition ID | 发起委派的 Agent |
| Target Agent Definition ID | 目标 Agent |
| Source | Platform Default / Organization Configured / User Configured |
| Purpose | 为什么绑定该目标、适合承担什么任务 |
| Enabled | 是否启用该绑定 |
| Version Policy | Latest Published 或 Pinned Version |
| Constraints | 该绑定上的额外委派限制 |
| Created / Updated By | 配置变更审计主体 |

MVP 配置面优先支持 Purpose、Enabled 和 Version Policy。复杂条件路由、自动评分和优先级系统暂缓。

Binding 是必要条件，但不是充分授权：实际委派仍需通过 Agent Access、Work Policy、Organization Policy 和执行准入检查。

### 7.4 Version Policy

MVP 建议支持：

- **Latest Published**：每次新 Delegation 创建时解析当时最新的 Published Version。
- **Pinned Version**：始终使用指定的 Agent Version。

无论采用哪种策略，Delegation 创建后必须记录实际解析出的 Agent Version ID 和必要配置快照。

## 8. Delegation Execution Boundary

Delegation Binding 与 Delegation 必须是两个独立对象：

- Binding：配置期关系，说明可以委派给谁。
- Delegation：运行期关系，说明某次委派实际发生了什么。

建议的运行时关系：

```
Work
 └── Work Run
      ├── Worker Execution: Coding Agent
      │     ├── Local Plan
      │     └── Delegation
      │           └── Worker Execution: Review Agent
      └── Worker Execution: Research Agent
```

对象职责：

- Work：用户级工作目标。
- Work Run：一次 Work 执行过程。
- Worker Execution：一个 Agent 在该 Work Run 中的一次实际执行。
- Delegation：父 Worker Execution 到子 Worker Execution 的一次委派关系。
- Local Plan：某个 Worker Execution 自己的专业执行计划。

一个 Delegation 默认不创建新的 Work。只有当委派任务需要独立业务生命周期、单独负责人、独立交付或跨团队追踪时，才考虑创建独立子 Work。

### 8.1 Delegation Context Package

子 Agent 不应自动继承父 Agent 的完整对话历史、Memory 或全部权限。父 Agent 应提供最小必要的结构化上下文：

- Objective / Task Instructions
- Input Artifacts
- Constraints
- Acceptance Criteria
- Relevant Context References
- Requested Capabilities

平台必须验证这些上下文引用是否可访问，并在子执行中重新计算权限。上下文传递不是权限传递。

## 9. Delegation Governance

### 9.1 Governance Boundary

**Proposed：** 委派治理由多个层次共同约束：

- Agent Owner / Manager 管理 Agent 自身的 Delegation Binding。
- Work Policy 限制当前 Work 中的委派行为。
- Organization Policy 规定组织级允许范围、禁止项和执行约束。
- 平台在每次 Delegation 创建及敏感操作时进行授权与策略评估。

Organization Admin 可以通过 Organization Policy 限制组织内的委派行为，但不因组织管理员身份自动获得个人 Agent Definition 的修改权。

### 9.2 Effective Permission

**Proposed：** 子 Agent 的有效权限不得超过所有相关授权边界的交集：

[
P_{effective} =
P_{parent}
cap P_{work}
cap P_{delegatee}
cap P_{organization}
cap P_{delegation}
]

其中：

- (P_{parent})：父执行主体可委派的权限。
- (P_{work})：当前 Work 授予的权限。
- (P_{delegatee})：目标 Agent 可使用的权限。
- (P_{organization})：组织策略允许的权限。
- (P_{delegation})：本次委派请求明确授予的权限范围。

显式拒绝优先于允许。Agent 自身拥有某项 Tool 权限，不代表在某次只读委派中可以使用该权限。

### 9.3 Policy Dimensions

**Proposed：** Delegation Policy 至少需要覆盖：

- Allowed Agent Scope / Target Bindings
- Delegation Depth
- Maximum Concurrent Workers
- Delegation Count / Execution Budget
- Capability Boundary
- Cycle Detection
- Approval Requirements
- Cancellation / Revocation Behavior

MVP 先实现有限层级、并发与预算约束、能力边界和基础循环检测；复杂审批工作流与动态策略规则引擎后续演进。

### 9.4 Revocation and In-flight Execution

**Open：** Binding 被禁用或删除后，尚未启动的 Delegation 应被阻止，这是当前推荐方向。

正在执行的 Delegation 是否继续，需要区分普通 Binding 变更与权限/Policy 撤销。普通配置变更不应默认造成历史执行关系丢失；安全策略撤销则可能要求暂停或终止运行中的执行。具体中断语义、宽限期和恢复规则仍需单独评审。

Delegation 应保存创建时的 Binding Reference、目标 Agent Version、授权评估结果和 Policy Snapshot，以支持审计和复现。快照用于追溯，不可替代敏感操作时的实时授权检查。

## 10. Platform, Personal and Organization Agents

**Confirmed：** Platform Agent、Personal Agent 和 Organization Agent 使用同一套 Agent Domain 模型，通过 Owner 和 Publisher 等属性区分，不建设三套不同的 Agent 实现。

| Agent Origin / Ownership | Owner | 管理边界 |
|---|---|---|
| Platform Agent | Platform Publisher | 平台维护原始定义和发布版本 |
| Personal Agent | User | Owner 按授权管理个人定义 |
| Organization Agent | Organization | 组织按组织治理规则管理定义 |

**Proposed：**

- 用户可以直接绑定并使用 Platform Agent，但不能修改其原始定义。
- 用户 Clone Platform Agent 后得到独立的 Personal Agent。
- 组织可以基于 Platform Agent Clone / Customize 出 Organization Agent，作为企业标准 Agent。
- 平台升级原始 Agent 不自动覆盖已 Clone 的 Agent。
- Agent Owner、Publisher、Visibility、Access 和 Executor 必须保持语义独立。

## 11. MVP Scope and Evolution

### MVP

- Personal / Organization Agent 的统一 Definition 模型。
- Agent Owner、基础 Access 和手动 Version Upgrade。
- Platform 提供一组通用 Agent。
- Agent Studio 支持显式 Delegation Binding。
- Binding 支持 Purpose、Enabled、Latest Published / Pinned Version。
- Agent 在已绑定目标中自主选择是否委派。
- Delegation 创建独立 Worker Execution，具备独立 Session、状态和恢复信息。
- 结构化 Context Package、权限重新计算、版本固定和审计。
- 有限委派层级、基础并发/预算约束和循环检测。

### Deferred

- 运行时动态 Agent Discovery 与 Agent Pool 实体。
- 自动语义匹配、智能路由和候选评分。
- 复杂委派条件、优先级与自动路由规则。
- 多层自主 Agent 网络、复杂 Debate / Judge 和高级 Multi-Agent 协商。
- 完整企业审批工作流与动态策略引擎。
- 公共 Agent Marketplace 与发布生态。

Deferred 表示暂不实现，不代表产品不做。领域模型应保留后续能力扩展空间，但 MVP 不应提前引入无实际需求的复杂抽象。

## 12. Open Questions

1. Agent Access 的具体权限矩阵及 Manager 可管理范围。
2. Organization Policy、Work Policy 与 Binding Constraints 的策略合并和解释机制。
3. Binding 被撤销、目标 Agent 被禁用或 Version 被 Deprecated 时，对运行中 Delegation 的精确影响。
4. Clone 后的能力依赖、Skill / Tool 版本锁定及平台升级迁移机制。
5. Delegation Policy 的默认配额、审批条件和企业管理员配置体验。
6. Delegation Context Package 的引用授权、数据最小化和敏感信息处理规则。

这些问题在评审确认前不得当作实现约束。

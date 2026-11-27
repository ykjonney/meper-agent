# 产品竞品差距与待决议题清单

> 状态：**Discussion Backlog（待逐项讨论，不代表已确认产品范围）**
>
> 日期：2026-11-26
>
> 本文记录当前围绕 Grok Bot、Muse、WorkBuddy 的竞品对照分析，以及我们现有产品设计中暴露出的潜在功能缺口。本文的目的首先是保存问题和讨论入口，而不是直接确定全部功能都要实现。
>
> **重要约束**
> - “竞品有”不等于“我们必须做”；每项能力都要回到产品定位、目标用户和核心体验判断。
> - 本文中的 MVP / P1 / 长期建议只是初步建议，尚未经过用户逐项确认。
> - “未设计”表示当前产品设计讨论中尚未形成明确方案，不代表当前代码中一定不存在该能力。
> - 后续逐项讨论时，需要决定：纳入产品、暂缓、合并到已有概念、明确不做，或需要进一步调研。

## 1. 当前产品定位背景

当前讨论方向是：**以 Personal Agent 体验为核心，同时具备企业环境所需的协作、权限、安全和治理能力。**

已确认的 Agent 组织方式：
- 每个用户有一个默认 Primary / Personal Agent。
- 用户可以拥有多个专业 Agent。
- 专业 Agent 有独立身份、Conversation 和 Memory。
- 用户可以直接使用专业 Agent，也可以由 Primary Agent 调用。
- Agent 间调用默认需要授权。
- Work 唯一归属 Owner Conversation，不因执行 Agent 改变归属。
- Agent 所有权、可用范围和调用授权需要分开表达。

本清单应与上述方向及后续正式产品战略保持一致。现有产品战略文档仍包含较早的“企业智能工作协调平台”定位，后续需要在产品战略重新确认后统一修订，不能把旧文档中的表述自动视为最新决策。

## 2. 竞品观察摘要

### Grok Bot
重点观察方向：
- 持久化、可配置的专业 Bot。
- Bot 的身份、记忆、工具和运行环境。
- Bot 间委派与协作。
- Skill 的创建、复用和沉淀。
- Routine / 定时及事件触发自动化。
- 持久化云端电脑、运行历史和操作审计。
- Bot 模板、复制和团队共享。

### Muse
重点观察方向：
- 以个人 Agent 为中心的长期助手体验。
- 理解用户和长期目标。
- 持续跟踪目标、主动建议和后台执行。
- 连接个人应用和外部服务。
- 在真实操作前进行授权或审批。
- 用户可以检查、介入和控制 Agent 的行动。

### WorkBuddy
重点观察方向：
- 自然语言驱动的工作执行和成果交付。
- 本地文件与云端执行环境。
- 专业 Agent、专家模板和 Skills。
- MCP / Connector 等能力扩展。
- 多 Agent 协作。
- 项目空间、文件浏览和团队复用。
- 定时任务、模型与执行配置、任务结果管理。

以上为产品层面的观察摘要。竞品具体能力、可用范围和版本差异，在正式对外引用或制定功能优先级前应再次核验官方资料。

## 3. 潜在功能差距清单

### GAP-01：Personal Agent 主动服务与 Goal Tracking

**当前设计情况：** 部分设计 / 尚未形成完整产品方案。

潜在能力：
- Goal：记录用户希望长期实现的目标。
- Goal Tracking：跟踪目标进展及相关 Work。
- Proactive Suggestions：根据目标、上下文和变化主动提出建议。
- Follow-up：发现工作停滞、遗漏或待响应事项时提醒。
- Monitoring：持续关注用户授权的信息源和事件。
- Opportunity Detection：发现值得用户关注的新信息或机会。

待解决问题：
- Goal 与 Work、Task 的边界是什么？
- Goal 是否需要成为独立领域对象，还是先作为轻量用户目标记录？
- Agent 主动建议的触发条件、频率和打扰控制如何设计？
- 主动发现与后台监控的权限和成本如何约束？

初步建议：将 Goal 纳入产品概念讨论；MVP 可以从用户显式定义目标、关联 Work、基础进度跟踪开始。主动发现和复杂监控可分阶段演进。

### GAP-02：Automation / Routine

**当前设计情况：** 尚未形成完整产品概念与生命周期设计。

潜在能力：
- Scheduled Routine：按时间或周期触发。
- Event Trigger：由邮件、GitHub、Slack 等授权事件触发。
- Webhook Trigger：由外部系统触发。
- Recurring Work：周期性创建或推进 Work。
- Automation History：查看每次触发和执行结果。
- Pause / Resume：暂停和恢复自动化。
- Test Run：启用前测试。
- Failure Handling：失败通知、重试、恢复和人工介入。

待解决问题：
- Routine 与 Work、Execution、Workflow 的边界是什么？
- Routine 每次触发是否创建 Work，还是也支持轻量直接执行？
- 触发器、执行定义和执行历史如何分离？
- 自动化如何继承 Agent、用户和组织权限？
- 如何防止重复触发、并发重入和无限重试？

初步建议：把 Automation 作为明确产品能力讨论；先确定 Scheduled Routine，再讨论事件驱动自动化。

### GAP-03：Action Governance（操作授权、审批与审计）

**当前设计情况：** 已讨论危险操作授权，但缺少完整统一的产品模型。

潜在能力：
- 操作前预览与影响说明。
- Allow Once：仅允许本次操作。
- Always Allow：在明确范围内保存授权规则。
- Ask First：每次执行前请求确认。
- Deny：拒绝操作。
- Approval History：审批记录。
- Activity Log：Agent 实际执行行为的可追溯记录。
- Policy：组织策略可以限制个人授权范围。
- 失败、撤销和补偿操作的记录。

待解决问题：
- 权限、审批、策略和审计分别属于什么层次？
- 哪些操作需要审批，如何定义风险等级？
- 用户授权能否被组织策略覆盖或收紧？
- 委派 Agent 如何继承调用者权限，如何防止 confused deputy？
- 用户如何查看、撤销和修改长期授权？

初步建议：基础权限检查、关键操作审批和操作记录应进入核心设计；复杂策略管理按阶段演进。

### GAP-04：Artifact 工作台与成果生命周期

**当前设计情况：** 已有 Artifact、Evidence、Verification 概念，但用户可见的管理体验不完整。

潜在能力：
- 集中查看 Agent 生成的文件和成果。
- 按 Conversation、Work、Project、Agent 组织。
- 文档、代码、图片、表格等预览。
- 版本历史与差异。
- 基于已有 Artifact 继续编辑。
- 下载、导出、分享。
- 与 Evidence、Verification 和 Work 交付标准关联。
- 跨 Conversation / Project 引用并执行权限检查。

待解决问题：
- Artifact 的统一入口和导航方式是什么？
- Artifact 的归属、共享和版本策略如何设计？
- Agent 如何找到并继续编辑已有成果？
- Artifact、Evidence、Knowledge 的边界是什么？

初步建议：MVP 至少需要成果列表、基本预览、归属与权限、可引用和可继续编辑的能力；高级协作编辑后续考虑。

### GAP-05：持久化 Workspace 与 Computer Use

**当前设计情况：** 已讨论 Sandbox，但 Workspace 的用户概念和生命周期尚未明确。

需要区分：
- **Workspace**：用户和 Agent 可以持续访问、检查和接管的工作环境。
- **Sandbox**：为某次或某类执行提供隔离和资源约束的运行环境。

潜在能力：
- 文件系统、浏览器、终端和项目文件。
- Local Workspace 与 Cloud Workspace。
- 跨 Execution 保留必要工作状态。
- 用户查看和接管 Agent 当前工作。
- Workspace 与 Project、Agent、Work 的关联。
- 资源生命周期、清理、快照和恢复。

待解决问题：
- Workspace 是否属于用户、Agent、Project 或 Work？
- 多个 Agent 是否可以共享同一个 Workspace？如何隔离？
- Workspace 与 Sandbox 的生命周期如何解耦？
- MVP 先做云端、Local，还是仅保留统一抽象？
- 用户接管执行环境需要哪些安全边界？

初步建议：先定义 Workspace 与 Sandbox 的概念边界和资源生命周期，不预设 MVP 必须实现完整云端电脑。

### GAP-06：Skill 生命周期、学习与复用

**当前设计情况：** Skill 作为 Agent 能力扩展方式已讨论，但生命周期设计不完整。

潜在能力：
- 从成功 Work 中提炼 Skill 草案。
- 用户通过实际操作演示工作流程。
- Skill 测试、版本、发布和回滚。
- 多 Agent 复用 Skill。
- Personal、Project、Team 等范围的共享。
- Skill 模板和市场。
- Skill 的来源、权限、依赖和安全审查。

待解决问题：
- Skill 是指令、流程、工具组合，还是可执行能力包？
- Skill 与 Workflow、Routine、Tool 的边界是什么？
- Agent 自动提炼 Skill 后如何验证和发布？
- Skill 共享时如何处理依赖和权限？

初步建议：先明确 Skill 的定义和生命周期；从任务提炼 Skill、Skill 市场等高级能力后续演进。

### GAP-07：Personal Memory 的用户控制与跨 Agent 共享

**当前设计情况：** Project Memory 已有较明确设计；Personal Memory 的产品体验与跨 Agent 共享规则仍需补充。

潜在能力：
- 用户查看 Agent 记住的信息。
- 更正、失效或删除记忆。
- 查看记忆来源和证据。
- 识别过期、冲突或低置信度记忆。
- 用户授权的共享信息可被多个 Agent 使用。
- 从其他 AI 产品导入记忆。
- 记忆访问范围和访问记录可检查。

待解决问题：
- Personal Memory 与各 Agent 独立 Memory 如何共存？
- 哪些用户事实可跨 Agent 共享？
- 用户如何控制共享范围？
- Memory 的来源、证据、版本和失效流程如何设计？
- 导入的记忆如何验证、去重和处理冲突？

初步建议：先明确用户共享记忆与 Agent 独立记忆的边界，以及用户可见、可纠正的管理体验；Memory Import 后续评估。

### GAP-08：多模态与跨设备交互

**当前设计情况：** 有多模态输入和输出的方向，但整体交互产品设计不完整。

潜在能力：
- 桌面端与移动端体验。
- 语音输入和语音交互。
- 图片、文件和多模态输入。
- 多模态 Artifact 输出。
- 后台任务通知与交互式审批。
- 通过外部消息渠道访问 Agent。

待解决问题：
- 哪些交互方式是核心体验，哪些只是渠道扩展？
- Conversation、Work 和 Approval 如何跨设备连续？
- 语音和外部渠道如何继承身份、权限和上下文？
- MVP 是否需要移动端或语音？

初步建议：先保证文件、图片等核心多模态输入输出；语音、外部消息渠道和丰富移动端体验分阶段规划。

### GAP-09：Agent 管理体验

**当前设计情况：** Agent Identity、Version、Ownership、Sharing 和创建机制已有设计方向，但日常管理体验不完整。

潜在能力：
- Agent 分组、收藏和固定。
- 按用途或 Project 组织 Agent。
- 隐藏、归档和复制 Agent。
- 从模板导入 Agent。
- 查看 Agent 当前工作、最近活动和失败记录。
- 管理 Agent 的 Routine 和授权。
- Agent 版本比较、回滚和停用。

待解决问题：
- Agent 数量增长后如何组织和发现？
- Primary Agent 与专业 Agent 的切换、调用和管理入口如何呈现？
- Agent 的直接 Conversation 与被委派工作如何区分？
- Agent 归档或删除如何保留历史引用？

初步建议：先提供基础列表、搜索、默认 Agent 选择、编辑、复制、归档和活动查看；市场能力后续考虑。

### GAP-10：Usage、Cost 与运行可观测性

**当前设计情况：** 已关注 Token Usage 和 Runtime 可观测性，但用户侧成本透明度尚未形成产品设计。

潜在能力：
- 按 Agent、Work、Routine 统计消耗。
- 模型调用、Token、工具调用次数。
- 执行时长、失败率和重试情况。
- 后台自动化成本。
- 用户额度、预算和使用提醒。
- 企业配额与成本归属。

待解决问题：
- 用户应该看到哪些成本信息？
- 如何归因多 Agent 协作中的成本？
- 如何设置个人预算和组织配额？
- 成本超限时如何暂停、降级或请求授权？

初步建议：底层 Usage 计量应可靠；用户侧可视化和复杂成本治理分阶段实现。

## 4. 初步优先级建议（未确认）

以下仅作为讨论起点，不构成已批准的 MVP 范围。

### 核心体验候选
- Primary Agent 与专业 Agent。
- 自然语言创建、配置和使用 Agent。
- Conversation 与 Work 连续性。
- 基础 Goal 与 Work 关联。
- Personal Memory、Project Memory。
- Skills、Tools、Connectors。
- Artifact 基础管理。
- 基础 Workspace / Sandbox。
- 关键操作审批与操作记录。
- 长程执行、恢复和进度跟踪。

### 后续优先候选
- Scheduled Routine。
- Event Trigger / Webhook。
- Goal Tracking 与主动提醒。
- Skill 从 Work 中沉淀。
- Memory Import 和更完善的用户管理。
- Artifact 版本和更完整工作台。
- 多 Agent 并行协作。
- Usage / Cost 用户可视化。

### 长期能力候选
- Skill Marketplace、Agent Marketplace。
- Agent 自主创建和组合专业 Agent。
- 高级 Multi-Agent DAG。
- 高级事件驱动自动化。
- 多种 Local / Cloud / Remote Workspace 与 Sandbox Provider。
- 企业级高级治理、策略和成本管理。

## 5. 逐项解决的工作方式

本清单采用逐项决策，不一次性接受全部建议。每个 GAP 需要形成以下结论：

1. 产品问题与用户价值：解决谁的什么问题？
2. 产品行为：用户如何发现、配置、使用和控制该能力？
3. 核心概念：是否需要新领域对象，还是复用已有概念？
4. MVP 边界：最小可验证闭环是什么？
5. 后续演进：哪些能力明确 Deferred？
6. 架构影响：需要新增或调整哪些领域、Runtime 和权限机制？
7. 验收标准：如何判断设计和实现真正完成？

逐项决策状态：
- GAP-01：待讨论
- GAP-02：待讨论
- GAP-03：待讨论
- GAP-04：待讨论
- GAP-05：待讨论
- GAP-06：待讨论
- GAP-07：待讨论
- GAP-08：待讨论
- GAP-09：待讨论
- GAP-10：待讨论

建议按 GAP-01 至 GAP-10 的顺序讨论，但可以根据依赖关系调整。每项确认后再更新产品战略和对应领域文档。

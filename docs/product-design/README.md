# Product Design

> 本目录记录 Agent Flow 下一阶段的产品战略、领域模型与产品架构设计。
>
> 当前状态：**设计进行中**。本文档集描述目标产品方向，不代表所有能力已经在当前代码中实现。

## 文档导航

| 文档 | 内容 | 状态 |
|---|---|---|
| [产品战略基线](./product-strategy.md) | 产品定位、核心用户价值、产品边界、核心闭环、MVP 与演进原则 | Baseline |
| [架构决策记录](./decision-log.md) | 已确认的产品与领域设计决策、理由和待决问题 | Living document |
| [领域模型总览](./domain-model.md) | Organization、Project、Space、Work、Work Run、Agent、Execution、Artifact 等跨领域关系 | Design baseline |
| [Agent Domain](./agent-domain.md) | Agent 身份、所有权、版本、能力、记忆、参与、委派绑定与治理 | Design baseline |
| [Plan Domain](./plan-domain.md) | Work Plan、Plan Version、Milestone、Task、Verification、Replanning 与 Agent Local Plan | Proposed |
| [Plan Runtime Integration](./plan-runtime-integration.md) | Task Revision、Task Attempt、Coordinator、Execution 集成、事件一致性与 Recovery 协议 | Proposed |
| Collaboration Domain | Space、Conversation、Message、Proposal、Decision、Membership | Planned |
| Work & Workflow Domain | Work、Assignment、Work Run、Interaction、Workflow/DAG | Planned |
| Artifact Domain | 产物、版本、共享、审阅与生命周期 | Planned |
| Workspace & Context | Personal Workspace、Project Workspace、Context Builder、Memory Scope | Planned |
| MVP 规格 | 用户流程、功能范围、验收标准与实施切分 | Planned |

## 设计状态约定

- **Confirmed**：已由产品决策明确确认。
- **Proposed**：当前推荐方案，仍需进一步评审。
- **Open**：尚未决策，不能作为实现约束。
- **Deferred**：明确暂缓到后续阶段，不代表产品不做。
- **Out of Scope**：明确不属于产品目标。

## 设计与实现的关系

1. 本目录描述目标产品和目标领域模型；现有代码与历史文档描述当前实现或此前阶段的设计。
2. 目标设计与现有实现不一致时，必须明确记录迁移关系，不得把目标设计误写成现状。
3. 领域模型优先表达稳定业务概念；技术实现细节放入对应架构文档。
4. 每批设计完成后更新本文档导航和决策记录，并以独立、可审查的提交进入约定开发分支。
5. 任何重要决策变更都应更新原决策状态和理由，不通过悄悄覆盖旧结论来改变设计。

## 推荐阅读顺序

1. [产品战略基线](./product-strategy.md)
2. [架构决策记录](./decision-log.md)
3. [Agent Domain](./agent-domain.md)
4. [领域模型总览](./domain-model.md)
5. [Plan Domain](./plan-domain.md)
6. [Plan Runtime Integration & Recovery Protocol](./plan-runtime-integration.md)
7. 各领域详细设计
8. MVP 规格与实施路线图

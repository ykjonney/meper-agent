# Plan Domain Persistence & Transaction Design

> 状态：**Proposed**
>
> 适用分支：`feature/execution-model`
>
> 本文定义 Plan Domain 在 MongoDB 上的持久化模型、事务边界、Plan Version 激活协议、命令幂等、Outbox / Inbox 和并发控制。
>
> 本文是目标设计，不代表下述 Collection 或领域服务已在代码中实现。相关基线：
> - [Plan Domain](./plan-domain.md)
> - [Plan Runtime Integration & Recovery Protocol](./plan-runtime-integration.md)
> - [Execution Domain ↔ Plan Runtime Gap Analysis](./execution-plan-gap-analysis.md)

## 1. Design Goals

1. Plan Domain 具有独立于旧 Workflow Task 和 Execution Domain 的持久化边界。
2. Task Identity、Task Revision、Task Runtime State、Task Attempt 分层存储和管理。
3. 所有跨文档业务状态转换具有明确事务边界和幂等协议。
4. Plan Version 是不可变完整快照，激活时不需要在一个事务中批量改写全部 Task。
5. Execution Event、Verification Event、Interaction Event 可以至少一次投递，并由 Plan Inbox 幂等应用。
6. 并发创建 Attempt、完成 Attempt、Replanning 和恢复不会互相覆盖。
7. 支持 MongoDB Replica Set / Sharded Cluster 的事务部署要求；不把 FakeDB 或单文档原子性当成跨文档事务证明。

## 2. Core Design Decisions (Proposed)

| ID | Design | Status |
|---|---|---|
| PPD-001 | Plan Domain 使用独立 Collections，不复用旧 `tasks` 集合 | Proposed |
| PPD-002 | 一个 Work Run 的 Active Plan Version 由 WorkPlan 单文档指针决定 | Proposed |
| PPD-003 | Plan Version 先完整构建并 Prepare，再通过单事务切换 Active Pointer | Proposed |
| PPD-004 | Plan Version 激活不批量更新所有 Task Runtime State；Task 按 Activation Item 异步协调 | Proposed |
| PPD-005 | Task Attempt 的唯一活动约束使用显式 `active: true` partial unique index | Proposed |
| PPD-006 | Plan Command Receipt、领域状态、Outbox 在同一事务提交 | Proposed |
| PPD-007 | Inbox 去重记录与对应领域状态变更在同一事务提交 | Proposed |
| PPD-008 | Outbox 至少一次投递；消费者必须幂等，不承诺跨系统 exactly-once | Proposed |
| PPD-009 | MVP 不增加 Work Run Lease；使用聚合 CAS、唯一索引和短事务协调 | Proposed |
| PPD-010 | MongoDB 多文档事务是生产一致性要求，必须用 Replica Set 集成测试验证 | Proposed |

以上均为建议，不自动成为 Confirmed 产品决策。

## 3. Collection Design

### 3.1 Collection Overview

| Collection | Aggregate / purpose | Mutability |
|---|---|---|
| `work_runs` | Work Run 身份、生命周期、版本指针 | Mutable |
| `work_plans` | Work Plan 身份、Active Plan Version 指针、CAS version | Mutable |
| `plan_versions` | 不可变 Plan Version 元数据和完整性 Manifest | Draft → Prepared → Active → Superseded |
| `plan_version_tasks` | Plan Version 中的 Task + Revision 快照关系 | Immutable after Prepared |
| `plan_version_changes` | 新旧 Plan Version 的 Task 差异快照 | Immutable after Prepared |
| `tasks` | 新 Plan Task Identity | Mostly immutable |
| `task_revisions` | 不可变 Task Revision | Immutable |
| `task_runtime_states` | Task 当前业务状态、活动 Attempt 指针、应用进度 | Mutable with CAS |
| `task_attempts` | 业务执行尝试 | State transitions only |
| `task_attempt_executions` | Attempt 与 Execution 关联 | Append / controlled update |
| `task_attempt_delegations` | Attempt 与 Delegation 关联 | Append / controlled update |
| `plan_activations` | 一次 Plan Version 激活的协调进度 | Mutable with CAS |
| `plan_activation_tasks` | 激活中每个 Task 的应用/迁移状态 | Mutable with CAS |
| `plan_command_receipts` | 命令幂等和原始响应 | Immutable |
| `plan_outbox` | Plan Domain committed events | Append-only + delivery metadata |
| `plan_inbox` | 外部事件消费去重和处理结果 | Immutable receipt |
| `completion_claims` | Agent/Worker 提交的完成声明 | Immutable |
| `verification_records` | Plan 对 Verification Domain 结果的引用/投影 | Append / immutable result |
| `interaction_links` | Interaction 与 Task / Attempt 的关联 | Append / controlled update |

**Collection 命名说明：** 新 Plan Task 的 `tasks` 与旧 Workflow Task 不能共用同一个 Collection。为避免命名冲突，实际实现建议使用显式前缀，例如 `plan_tasks`、`plan_task_revisions`、`plan_task_runtime_states`。本文以下用领域名表达逻辑集合；实现必须采用不会与现有 `tasks` 集合冲突的物理名称。

### 3.2 WorkRun and WorkPlan

```typescript
interface WorkRunDocument {
  _id: string;
  workId: string;
  status: "created" | "active" | "blocked" | "completed" | "failed" | "cancelled";
  createdAt: Date;
  startedAt?: Date;
  finishedAt?: Date;
  version: number;
}

interface WorkPlanDocument {
  _id: string;
  workRunId: string;
  activePlanVersionId: string | null;
  activationId: string | null;
  version: number;
  updatedAt: Date;
}
```

WorkRun 表达一次业务运行周期；WorkPlan 是该 Run 的计划身份。不要把 WorkRun 的所有计划和 Task 状态塞进一个超大文档。

### 3.3 PlanVersion

```typescript
interface PlanVersionDocument {
  _id: string;
  workPlanId: string;
  versionNumber: number;
  status: "draft" | "prepared" | "active" | "superseded" | "abandoned";
  basedOnPlanVersionId?: string;
  taskCount: number;
  changeCount: number;
  manifestHash: string;
  createdAt: Date;
  createdBy: string;
  preparedAt?: Date;
  activatedAt?: Date;
  version: number;
}
```

Prepared 之后：
- PlanVersion 的任务清单、变更清单和 Manifest 不可修改；
- 新增或修改任务必须创建新的 Plan Version；
- `manifestHash` 对规范化后的 Task Membership + Revision + Dependency + Milestone 关系计算；
- 激活前必须验证 count、hash、引用完整性和依赖合法性。

Plan Version 的 status 可作为生命周期投影，但 **WorkPlan.activePlanVersionId 才是当前生效版本的唯一权威指针**。状态字段不能与该指针出现两个互相竞争的权威源。

### 3.4 PlanVersionTask and PlanVersionChange

```typescript
interface PlanVersionTaskDocument {
  _id: string;
  planVersionId: string;
  taskId: string;
  taskRevisionId: string;
  milestoneId?: string;
  position: number;
  dependencyTaskIds: string[];
}

interface PlanVersionChangeDocument {
  _id: string;
  planVersionId: string;
  taskId: string;
  action: "add" | "retain" | "revise" | "remove";
  previousRevisionId?: string;
  targetRevisionId?: string;
  migrationPolicy: "none" | "safe_switch" | "requires_stop" | "cancel_or_skip";
}
```

PlanVersionTask 是完整计划快照中的成员关系。PlanVersionChange 是相对前一版本计算出的不可变差异，供激活协调使用。

依赖关系必须在 Prepare 阶段验证：
- 依赖 Task 必须在同一 Plan Version 中，或被明确标记为外部已满足依赖；
- 不允许形成不被支持的循环；
- 不能只验证 UI 展示顺序；
- 依赖边应有独立稳定语义，不要只用 position 表达执行依赖。

### 3.5 Plan Task and Revision

```typescript
interface PlanTaskDocument {
  _id: string;
  workRunId: string;
  createdAt: Date;
  createdBy: string;
  derivedFromTaskId?: string;
  supersedesTaskId?: string;
}

interface PlanTaskRevisionDocument {
  _id: string;
  taskId: string;
  revisionNumber: number;
  title: string;
  description: string;
  acceptanceCriteria: AcceptanceCriterion[];
  dependencies: TaskDependency[];
  requiredCapabilities: CapabilityRequirement[];
  verificationPolicyRef?: string;
  planningConstraints: string[];
  createdAt: Date;
  createdBy: string;
  changeReason: string;
}
```

Revision 不可变。Revision 的业务内容不得原地更新；修正拼写或验收条件也应形成新 Revision，并记录变更原因。

### 3.6 TaskRuntimeState

```typescript
interface PlanTaskRuntimeStateDocument {
  _id: string; // taskId
  workRunId: string;
  status: TaskStatus;
  activeRevisionId: string;
  activeAttemptId: string | null;
  appliedPlanVersionId: string | null;
  activationStatus: "applied" | "pending" | "blocked" | "requires_migration";
  blockers: Blocker[];
  lastEventSequence: number;
  version: number;
  updatedAt: Date;
}
```

字段语义：
- `activeRevisionId` 是 Task Runtime 当前接受的业务定义版本，不会因 Active Plan Version 指针变化而自动覆盖。
- `appliedPlanVersionId` 表示该 Task Runtime 已完成协调的计划版本。
- `activationStatus` 表示该 Task 是否已应用当前 Active Plan Version 对它的变更。
- 若 Plan Version 已激活但该 Task 尚未完成协调，则 `activationStatus != applied`，此时不允许创建新的 Attempt。
- 运行中 Attempt 继续绑定自己的 `taskRevisionId`；不能因为 TaskRuntimeState.activeRevisionId 或 Plan Version 指针改变而改写 Attempt。

这样可以明确区分“全局计划已激活”和“单个 Task 已完成迁移”，避免在 Task Runtime State 中伪装成所有任务同时更新成功。

### 3.7 TaskAttempt

```typescript
interface PlanTaskAttemptDocument {
  _id: string;
  taskId: string;
  taskRevisionId: string;
  attemptNumber: number;
  status: AttemptStatus;
  active: boolean;
  assignedAgentId?: string;
  createdAt: Date;
  startedAt?: Date;
  finishedAt?: Date;
  resultRef?: string;
  failureReason?: string;
  version: number;
}
```

`active` 是为唯一索引服务的持久化约束字段，必须与状态转换在同一事务维护：
- Created / Running / Blocked / AwaitingVerification → `active: true`
- Succeeded / Failed / Cancelled / Superseded → `active: false`

应用代码不得独立修改 active 字段。状态与 active 不一致属于数据完整性故障，必须告警并由 Coordinator 修复。

## 4. Indexes and Uniqueness

以下为逻辑索引建议，真实索引需按 MongoDB 版本和查询模式验证。

```javascript
// 一个 Work Run 只有一个 WorkPlan
db.work_plans.createIndex({ work_run_id: 1 }, { unique: true });

// 同一个 WorkPlan 的版本号唯一
db.plan_versions.createIndex(
  { work_plan_id: 1, version_number: 1 },
  { unique: true }
);

// 一个 Plan Version 中每个 Task 只有一个成员记录
db.plan_version_tasks.createIndex(
  { plan_version_id: 1, task_id: 1 },
  { unique: true }
);

// 一个 Task 的 Revision 编号唯一
db.plan_task_revisions.createIndex(
  { task_id: 1, revision_number: 1 },
  { unique: true }
);

// 一个 Task 一个 Runtime State
db.plan_task_runtime_states.createIndex(
  { _id: 1 },
  { unique: true }
);

// 一个 Task 最多一个活动 Attempt
db.plan_task_attempts.createIndex(
  { task_id: 1 },
  {
    unique: true,
    partialFilterExpression: { active: true }
  }
);

// Attempt 关联不能重复
db.task_attempt_executions.createIndex(
  { attempt_id: 1, execution_id: 1 },
  { unique: true }
);
db.task_attempt_delegations.createIndex(
  { attempt_id: 1, delegation_id: 1 },
  { unique: true }
);

// 每个 Command 只处理一次
db.plan_command_receipts.createIndex(
  { tenant_id: 1, command_id: 1 },
  { unique: true }
);

// 一个 Consumer 对同一个 Event 只应用一次
db.plan_inbox.createIndex(
  { consumer_name: 1, event_id: 1 },
  { unique: true }
);

// Outbox 事件 ID 全局唯一
db.plan_outbox.createIndex({ event_id: 1 }, { unique: true });
```

Additional query indexes：
- `plan_version_tasks(plan_version_id, position)`
- `plan_version_changes(plan_version_id, task_id)`
- `plan_task_runtime_states(work_run_id, status)`
- `plan_task_attempts(task_id, created_at)`
- `plan_activation_tasks(activation_id, status, task_id)`
- `plan_outbox(status, next_attempt_at, created_at)`
- `plan_inbox(consumer_name, processed_at)`

不要给每个状态查询都建立索引。上线前用真实查询计划和数据规模验证索引成本。

## 5. Transaction Model

### 5.1 Transaction Requirements

所有需要跨多个 Collection 保持原子性的 Plan Domain 命令，必须运行在 MongoDB transaction 中。生产部署必须使用支持多文档事务的 Replica Set 或 Sharded Cluster，并正确配置 read concern / write concern。

事务回调必须：
- 只包含数据库读写和可重试的纯逻辑；
- 不调用 LLM、Tool Provider、消息 Broker 或外部 HTTP；
- 不在事务内启动 Celery Job；
- 不依赖事务回调只执行一次（MongoDB Driver 可能重试事务回调）；
- 使用稳定 commandId / eventId，避免回调重试生成不同业务身份。

事务外副作用一律由 Outbox Dispatcher 或明确的 Saga / Interaction 流程触发。

### 5.2 Command Transaction Boundary

通用命令处理流程：

1. 验证身份、授权和 Policy（外部检查结果必须有版本或决策引用）。
2. 计算 canonical request hash。
3. 开启事务。
4. 查找 `plan_command_receipts(tenant_id, command_id)`。
5. 若已有相同 request hash，返回原结果；若 hash 不同，返回 Idempotency Conflict。
6. 读取聚合当前状态并检查 expectedVersion。
7. 执行领域状态转换与不变量校验。
8. 更新聚合文档 / Attempt / 关联记录。
9. 分配 aggregate sequence 并插入 Outbox event。
10. 插入 Command Receipt（保存结果引用、事件 ID 和响应摘要）。
11. 提交事务。
12. 事务提交后由 Outbox Dispatcher 异步投递。

Command Receipt 示例：

```typescript
interface PlanCommandReceipt {
  tenantId: string;
  commandId: string;
  commandType: string;
  requestHash: string;
  aggregateType: string;
  aggregateId: string;
  result: {
    status: "accepted" | "rejected";
    resultRef?: string;
    eventIds: string[];
    responseCode: string;
  };
  createdAt: Date;
}
```

需要区分：
- 业务拒绝（例如依赖未满足）可以保存确定的拒绝结果，避免同一命令重复产生不同结果；
- CAS 冲突属于并发竞争，调用方重新读取后应以新的 commandId 发起新的业务意图，或由服务端在明确语义下重试；
- 同一 commandId + 不同 requestHash 必须拒绝。

### 5.3 StartTaskAttempt Transaction

**这是必须保证单活动 Attempt 的关键事务。**

事务内：
1. 检查 Command Receipt。
2. 读取 TaskRuntimeState，校验 expected version。
3. 校验 Task 为 Ready，且 `activationStatus == applied`。
4. 校验依赖、权限、Capability 和 Policy。
5. 校验 `activeAttemptId == null`。
6. 计算下一个 attemptNumber（在 Task 状态版本保护下）。
7. 插入 Attempt，`status=created`、`active=true`。
8. 更新 TaskRuntimeState.activeAttemptId、version。
9. 插入 TaskAttemptCreated Outbox Event。
10. 插入 Command Receipt。
11. 提交。

若并发请求同时通过应用层检查，唯一索引只允许一个活动 Attempt 插入成功；失败事务整体回滚。调用方收到冲突后重新加载状态，不应自动创建另一个 Attempt。

### 5.4 Attempt State Transition Transaction

Attempt 的状态、active 字段、Task Runtime State 和 Outbox 必须在同一个事务中更新。

例如 Verification Passed：
1. Inbox 去重并锁定 / CAS Task Runtime State；
2. 确认 activeAttemptId 指向回调中的 Attempt；
3. 确认 Attempt 绑定的 Revision 与 Verification 的 Task / Revision / Attempt 一致；
4. 将 Attempt 更新为 Succeeded、active=false；
5. 将 Task Runtime State 更新为 Completed、activeAttemptId=null；
6. 写入 TaskAttemptSucceeded 和 TaskCompleted Outbox；
7. 插入 Inbox Receipt；
8. 提交。

Verification Failed 且允许重试时，Attempt 变为 Failed、active=false，Task 回到 Ready 并清空 activeAttemptId；不在同一个 Attempt 内复活执行。

### 5.5 Do Not Use One Giant Transaction for Plan Activation

Plan Version 可能包含数百或数千个 Task。不得在一个事务中：
- 插入所有 Task Revision；
- 插入全部 PlanVersionTask；
- 更新所有 Task Runtime State；
- 迁移所有活动 Attempt；
- 写入所有事件。

这种事务容易触及事务时长、写冲突、锁竞争、WiredTiger cache、事务大小和运维超时等限制。

改为 Prepare + Atomic Pointer Switch + Per-Task Reconciliation。

## 6. Plan Version Build and Activation Protocol

### 6.1 Phase A — Build Draft

Planning Service 创建 Draft Plan Version。
- 版本号由 WorkPlan 的 CAS / 事务分配，不能用客户端时间戳。
- Task Revision 先创建为独立不可变记录。
- PlanVersionTask / PlanVersionChange 分批写入。
- Draft 不影响当前 Active Plan Version。
- 同一 Draft 的并发修改需要版本 CAS，或只允许一个明确的 Draft Editor Session。

### 6.2 Phase B — Prepare

Prepare 不是激活。它把 Draft 冻结成完整、可校验的快照。

Prepare 流程：
1. 关闭 Draft 写入口并递增 Draft version。
2. 读取 PlanVersionTask / Change 全量清单。
3. 校验每个 Task / Revision 引用存在且归属正确。
4. 校验 Dependency、Milestone、Capability Requirement 和约束。
5. 校验无非法循环和重复成员。
6. 规范化排序并计算 manifestHash。
7. 核对实际记录数与声明 taskCount / changeCount。
8. 记录 Prepared 状态、hash 和 preparedAt。
9. 之后拒绝修改该版本的成员和变更记录。

若 Prepare 过程中发现数据不完整，保持 Draft 或标记 Abandoned；不得激活部分快照。

### 6.3 Phase C — Atomic Activation

激活事务只处理有限文档：
1. 检查 Command Receipt。
2. 读取 WorkPlan，校验 expected version 和 expectedActivePlanVersionId。
3. 校验目标 PlanVersion.status == Prepared。
4. 校验 PlanVersion.basedOnPlanVersionId 与当前 Active Plan Version 匹配；若不匹配，要求重新 Rebase / Replan。
5. 更新 WorkPlan.activePlanVersionId = target。
6. 更新 WorkPlan.activationId = newActivationId，递增 version。
7. 更新目标 PlanVersion 状态为 Active；旧版本变为 Superseded（若同一事务更新旧/新两条版本文档）。
8. 创建 PlanActivation 元数据。
9. 写入 PlanVersionActivated Outbox Event。
10. 写入 Command Receipt。
11. 提交。

**该事务提交时刻是 Plan Version 激活的线性化点。** 所有后续查询应以 WorkPlan.activePlanVersionId 为准，不得依赖客户端缓存或 PlanVersion.status 单独判断当前版本。

### 6.4 Phase D — Per-Task Reconciliation

激活事务不批量修改 Task Runtime State。激活前已准备好的 `plan_activation_tasks` 记录作为工作清单，激活后由 Coordinator 分批处理：

```typescript
interface PlanActivationDocument {
  _id: string;
  workPlanId: string;
  fromPlanVersionId: string | null;
  toPlanVersionId: string;
  status: "pending" | "running" | "completed" | "blocked" | "failed";
  totalItems: number;
  appliedItems: number;
  blockedItems: number;
  version: number;
  createdAt: Date;
  finishedAt?: Date;
}

interface PlanActivationTaskDocument {
  _id: string;
  activationId: string;
  taskId: string;
  action: "add" | "retain" | "revise" | "remove";
  targetRevisionId?: string;
  status: "pending" | "applied" | "blocked" | "requires_migration" | "skipped";
  reason?: string;
  version: number;
}
```

每个 Activation Task Item 独立短事务：
- Add：创建 Runtime State，设置目标 Revision 和初始状态。
- Retain：确认原 Revision 与目标 Revision 相同，更新 appliedPlanVersionId。
- Revise 且无活动 Attempt：应用新 Revision，重算 Ready / Blocked 等可执行状态。
- Revise 且有活动 Attempt：保留 Attempt 绑定的旧 Revision；标记 requires_migration 或按批准策略等待当前 Attempt 完成。不得热切换。
- Remove：如果没有活动 Attempt，按策略标记 Skipped / 不再纳入当前计划；如果有活动 Attempt，进入安全停止 / 迁移流程，不得直接删除 Task 或 Attempt。

执行门禁：
- `activationStatus != applied` 的 Task 不允许启动新 Attempt。
- 正在执行的 Attempt 可以继续，除非其 Activation Item 明确要求安全停止。
- Plan UI 应展示“Plan Version 已激活，部分 Task 正在协调 / 等待迁移”，不能伪装所有 Task 已同步完成。
- Activation 完成条件是所有 Item 达到 applied / blocked / requires_migration / skipped 等明确终态；Blocked 或 requires_migration 不等于整个 Plan Version 激活失败。

这是一种**整体计划指针原子切换 + Task 级最终一致性**模型。它不声称所有 Task 的运行状态在同一个瞬间改变。

### 6.5 Activation Recovery

Coordinator 崩溃后：
- 读取 WorkPlan.activePlanVersionId 和 PlanActivation。
- 若指针尚未切换，目标版本仍是 Prepared，不应开始应用 Task Item。
- 若指针已切换，继续处理 pending Item。
- 每个 Item 通过自己的 CAS 和幂等 Command Receipt 防止重复应用。
- PlanActivation 的计数是可重建投影；权威事实是每个 Activation Task Item 的状态。
- 若发现 WorkPlan.activationId 与 Activation 目标版本不匹配，停止自动推进并进入对账，不猜测恢复目标。

## 7. Outbox / Inbox Design

### 7.1 Outbox Schema

```typescript
interface PlanOutboxDocument {
  _id: string;
  eventId: string;
  eventType: string;
  schemaVersion: number;
  aggregateType: "work_plan" | "task" | "task_attempt" | "work_run";
  aggregateId: string;
  sequence: number;
  payload: Record<string, unknown>;
  occurredAt: Date;
  recordedAt: Date;
  correlationId: string;
  causationId?: string;
  status: "pending" | "publishing" | "published" | "dead_letter";
  attemptCount: number;
  nextAttemptAt: Date;
  publishedAt?: Date;
  lastError?: string;
}
```

Outbox Event payload 应包含必要业务事实和稳定引用；不复制整个 Task、Artifact 或 Execution 快照。

### 7.2 Aggregate Sequence

- 每个 Plan 聚合有自己的 sequence。
- sequence 分配与聚合状态更新在同一事务中完成。
- WorkPlan、Task、TaskAttempt 可以是不同 aggregate。
- 不要求全局事件总序；跨聚合因果关系使用 correlationId / causationId。
- 消费者不得假设不同 aggregate 的事件存在全局顺序。
- 同一 aggregate 的事件若有 sequence gap，应延迟应用并从 Outbox / event history 补读，不能跳过缺口推进状态。

### 7.3 Outbox Dispatcher

Dispatcher：
1. 使用 `findOneAndUpdate` 原子 claim pending / expired publishing 事件；
2. 设置短期 claim owner、claim expiry 和 attemptCount；
3. 在事务外发布到 Broker / 内部事件总线；
4. 发布成功后标记 published；
5. 失败时指数退避并更新 nextAttemptAt；
6. 超过重试上限进入 dead_letter，提供人工重放工具。

崩溃窗口：
- Broker 接收成功、Outbox 尚未标记 published：事件会重复投递；
- 因此消费者必须 Inbox 去重。
- 不得先标记 published 再发布，否则崩溃会永久丢事件。

MVP 可先使用 Mongo Outbox + 内部 Poller；不要求引入新的 Broker。现有 Redis Pub/Sub 可作为低延迟通知，但不是可靠事实来源。

### 7.4 Inbox Schema and Consumer Transaction

```typescript
interface PlanInboxDocument {
  _id: string;
  consumerName: string;
  eventId: string;
  producer: string;
  aggregateType: string;
  aggregateId: string;
  sequence?: number;
  receivedAt: Date;
  processedAt: Date;
  result: "applied" | "ignored" | "rejected";
  resultRef?: string;
}
```

消费 Execution / Verification / Interaction Event：
1. 开启 Plan Domain 事务。
2. 插入 Inbox 唯一键 `(consumerName, eventId)`。
3. 若唯一键冲突，读取原 Receipt 并返回已处理结果。
4. 校验事件 schema、producer、aggregate identity 和因果关系。
5. 执行 Coordinator 命令或状态协调。
6. 更新 Plan Task / Attempt 状态并写 Plan Outbox。
7. 写 Inbox Receipt。
8. 提交。
9. 事务外执行后续 Outbox 发布。

**Inbox Receipt 与业务状态变更必须同事务。** 若先写 Inbox 后更新状态，进程崩溃会导致事件被误判为已消费；若先更新状态后写 Inbox，重复事件可能重复产生业务效果。

### 7.5 Event Contract Versioning

- 每个 Event 必须包含 schemaVersion。
- 新字段应向后兼容；语义变更需要新版本。
- Consumer 对未知必需字段 / 不支持版本应隔离，不可静默丢弃。
- 保留原始外部事件引用或必要审计内容，避免消费失败后无法重放。
- Event payload 不应包含 Secret、凭据或无必要的个人敏感信息。

## 8. Command Idempotency and Concurrency

### 8.1 Command Identity

每个业务命令带：
- tenantId
- commandId
- commandType
- actor / principal
- aggregateRef
- expectedVersion
- requestHash
- correlationId
- causationId
- occurredAt

commandId 表示一次业务意图。网络重试必须沿用同一 commandId；用户明确发起新的操作才生成新 commandId。

### 8.2 CAS Rules

| Operation | CAS aggregate | Additional invariant |
|---|---|---|
| Create Task Attempt | TaskRuntimeState.version | activeAttemptId == null + unique active index |
| Start Attempt | Attempt.version + TaskRuntimeState.version | Attempt is current active Attempt |
| Block / Resume Attempt | Attempt.version + TaskRuntimeState.version | legal state transition |
| Complete Attempt | Attempt.version + TaskRuntimeState.version | matching Verification + active pointer |
| Activate Plan Version | WorkPlan.version | expected previous Active Plan Version |
| Apply Activation Item | ActivationTask.version + TaskRuntimeState.version | WorkPlan pointer still targets activation |
| Create Revision | Task revision counter / Task version | unique (taskId, revisionNumber) |
| Apply Replanning | WorkPlan.version | target Prepared and based on expected active version |

### 8.3 Cross-Aggregate Commands

不要尝试让一个命令跨越多个长期业务流程并保持一个巨型事务。

例如 Plan Version Activation：
- WorkPlan Pointer Switch 是短事务；
- 每个 Task 的 Revision Migration 是独立短事务；
- Execution 停止、UNKNOWN Tool Invocation 裁决、人工 Interaction 是事务外异步流程；
- 所有步骤通过 Activation ID、Task ID、Attempt ID 和 Outbox Event 关联。

这是 Saga / durable process 的边界，不是一个 MongoDB transaction。

### 8.4 Concurrent Completion and Replanning

若 Verification Passed 与 Plan Version Activation 同时发生：
- Verification Consumer 必须 CAS TaskRuntimeState 和 Attempt。
- Activation Item 也必须 CAS 同一个 TaskRuntimeState。
- 谁先提交，另一个必须重读当前状态并重新评估。
- 如果 Completion 先提交，Activation 看到 Completed Task，应保留历史完成结果并按业务规则决定是否需要新 Task。
- 如果 Activation 先将 Task 标记 requires_migration，Verification 仍需检查其 Attempt Revision 和验收标准是否仍适用；不能因新 Plan Version 激活而直接拒绝一个本来有效的旧 Revision 验证。
- 具体是否接受旧 Revision 的完成结果，必须由 PlanVersionChange.migrationPolicy 和 Verification Policy 明确，不由事件到达顺序猜测。

## 9. MongoDB Transaction and Deployment Requirements

### 9.1 Production Topology

跨 Collection 的事务要求 MongoDB Replica Set 或 Sharded Cluster。生产部署必须：
- 使用支持事务的 MongoDB 部署形态；
- 设定合适的 `readConcern: snapshot`、`writeConcern: majority` 和事务超时；
- 事务中所有操作使用同一 session；
- 避免长时间事务和外部网络调用；
- 对 transient transaction error 和 unknown commit result 实现官方推荐的重试处理；
- 对 DuplicateKey / CAS conflict 做业务层分类，不盲目无限重试。

具体 concern、超时、连接池和重试配置需要在真实部署拓扑压测后确认，本文不预设固定数值。

### 9.2 Test Environment

必须使用真实 MongoDB Replica Set 集成测试验证：
- 多文档事务提交和回滚；
- 唯一索引并发竞争；
- 两个 Coordinator Worker 的 CAS 冲突；
- Outbox / Inbox 原子性；
- 事务提交结果未知时的重试；
- Plan Activation 中途崩溃恢复；
- 大型 Plan Version Prepare 的分批写入与 hash 校验。

Mock / FakeDB 只用于领域单元测试，不可作为事务隔离、唯一索引和故障恢复正确性的证据。

## 10. Observability and Repair

关键指标：
- plan_command_conflict_total
- plan_command_idempotent_replay_total
- plan_attempt_active_index_conflict_total
- plan_outbox_pending_count / oldest_age
- plan_outbox_dead_letter_total
- plan_inbox_duplicate_total
- plan_activation_pending_items / blocked_items / duration
- plan_task_activation_lag
- plan_task_runtime_invariant_violation_total
- plan_attempt_revision_mismatch_total
- plan_recovery_reconciliation_total

Repair 操作必须：
- 由 Coordinator / 专用 Repair Service 执行；
- 有 dry-run 和审计记录；
- 不直接修改不可变 Revision、PlanVersion Snapshot 或历史事件；
- 对无法唯一推导的冲突进入人工裁决；
- 每次修复使用独立 commandId 并产生 Repair Event。

## 11. MVP Implementation Order

1. **Persistence contracts**：Collection、文档 schema、索引、ID 规范。
2. **PlanRepository / UnitOfWork**：Mongo session、CAS、事务重试、Command Receipt。
3. **Task / Revision / Runtime State**：独立持久化和不可变约束。
4. **TaskAttempt**：active 字段、唯一索引、单活动 Attempt 状态机。
5. **Outbox / Inbox**：同事务写入、至少一次投递、幂等消费。
6. **Plan Version Prepare / Activate**：Manifest、Atomic Pointer Switch、Activation Task Items。
7. **Execution Adapter**：Attempt-Execution 关联和 Execution Event Inbox。
8. **Verification / Interaction**：事件集成。
9. **Recovery / Repair**：激活恢复、Attempt 对账、事件补读。
10. **Legacy cutover**：单独迁移旧 Workflow Task；不与新 Plan Domain 首次上线绑定。

## 12. Acceptance Criteria

- [ ] 新 Plan Task 使用独立 Collection，不与旧 Workflow Task 混用。
- [ ] Task Identity / Revision / Runtime State / Attempt 职责分离。
- [ ] Revision 和 Prepared Plan Version Snapshot 不可变。
- [ ] Plan Version 的 Active Pointer 是唯一权威生效指针。
- [ ] Plan Version 激活采用 Prepare + Atomic Pointer Switch + Per-Task Reconciliation。
- [ ] 激活中尚未应用的 Task 不允许启动新 Attempt。
- [ ] 活动 Attempt 继续固定绑定其 Task Revision。
- [ ] 一个 Task 最多一个 active Attempt，由 MongoDB 唯一索引和 Coordinator 事务共同保证。
- [ ] Command Receipt、领域状态、Outbox 在同一事务。
- [ ] Inbox Receipt 与消费效果在同一事务。
- [ ] Outbox 支持重复投递，消费者支持幂等。
- [ ] 事件 sequence 只保证 aggregate 内顺序，不假设全局顺序。
- [ ] MongoDB Replica Set 集成测试覆盖事务、并发和崩溃窗口。
- [ ] MVP 不引入 Work Run Lease。
- [ ] 外部调用、LLM、Broker Publish 不在 MongoDB transaction 内执行。

## 13. Open Questions

1. Milestone 是否作为 PlanVersion 内嵌数组，还是独立 Collection？若需要独立协作、权限和大规模增量更新，才应升级为独立聚合。
2. PlanVersionTask 的 Dependency 是嵌入 Task Membership 还是独立边集合？MVP 可采用单任务依赖数组，但需定义规模上限和索引需求。
3. PlanActivation 的 blocked / requires_migration 是否需要用户可见的审批 Interaction，以及由谁批准迁移。
4. WorkRun 与 WorkPlan 是否严格一对一；若未来同一 Work Run 支持多个候选 Plan 或实验性 Plan，需要调整模型。
5. 是否需要保留所有 Command Receipt 永久记录，还是按审计策略归档并保留幂等窗口；涉及重放时必须保证不会因过早删除 Receipt 而重复产生效果。

## Appendix A. Transaction Boundaries at a Glance

| Use case | Atomic transaction contents | Outside transaction |
|---|---|---|
| Start Attempt | Receipt + Task Runtime State + Attempt + Outbox | Dispatch Execution |
| Attach Execution | Attempt relation + Receipt + Outbox | Execution creation / resource provisioning, coordinated by durable adapter flow |
| Complete Attempt | Inbox + Attempt + Task Runtime State + Outbox | Verification execution happens before callback |
| Prepare Plan Version | Freeze Draft metadata + manifest record | Batch snapshot validation / hash computation |
| Activate Plan Version | WorkPlan pointer + PlanVersion lifecycle + Activation metadata + Receipt + Outbox | Per-Task reconciliation |
| Apply Activation Item | Inbox/Command Receipt + Task Runtime State + Activation Item + Outbox | Stop Execution / resolve side effects / human approval |
| Publish Outbox | Claim metadata only | Broker publish |
| Consume External Event | Inbox + Plan state + Plan Outbox | Follow-up Outbox publication |

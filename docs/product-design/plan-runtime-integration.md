# Plan Runtime Integration & Recovery Protocol v1

> 状态：**Proposed（技术设计基线，已确认决策除外）**
>
> 适用分支：`feature/execution-model`
>
> 本文把 [Plan Domain](./plan-domain.md) 的业务计划模型与现有 Execution Domain 连接起来，定义 Task Revision、Task Attempt、Task State Coordinator、事件一致性、Replanning 和 Recovery 协议。
>
> 本文描述目标架构，不表示所有 Plan Domain 对象已经在当前代码中实现。现有 Execution 能力与迁移边界见第 12 节。

## 1. Goals and Non-goals

### 1.1 Goals

1. 为 Work Run 提供持久化、可版本化、可重新规划的 Work Plan。
2. 明确 Task 业务进度与 Execution 技术运行状态的权威边界。
3. 让一次 Task 业务尝试可以跨多个 Execution、Delegation 和 Agent 协作。
4. 通过 Coordinator、CAS、唯一约束和幂等事件处理，避免并发执行、恢复和 Replanning 相互覆盖。
5. 复用现有 Execution Lease、Fencing、Checkpoint Manifest、Execution Event、Tool Invocation Ledger 和 RecoverySupervisor。
6. 在 Worker 崩溃、重复投递、未知外部副作用和人工等待后，恢复同一业务尝试，而不是错误地创建新 Attempt 或重复执行副作用。

### 1.2 Non-goals

MVP 不实现：
- 同一 Task 的多个并行顶层 Attempt / AttemptGroup；
- 跨 Work Run 的计划依赖和 Portfolio Planning；
- 多层任意嵌套 Plan 的复杂聚合；
- 任意动态 DAG 调度、自动成本最优调度；
- 完整 Event Sourcing；
- 第二套通用 Durable Execution Engine；
- 对不支持幂等或状态查询的外部 Provider 承诺 exactly-once。

Deferred 表示暂缓实现，不代表产品不做。

## 2. Confirmed Decisions and Design Status

### 2.1 Confirmed

- Plan 是 Agent Runtime 的一等能力，不是 Todo UI 或 Execution State 的附属 JSON。
- Work 定义业务目标和最终验收责任；Work Run 是一次业务执行周期；Plan 管理该周期采用的执行方案。
- Task 是可分配、可追踪、可验证的业务工作单元，不等于模型调用、Execution、Workflow Step 或 Tool Invocation。
- Plan Version 是不可变计划结构快照；一个 Work Run 的 Work Plan 同时只有一个 Active Plan Version。
- Task 采用三层分离：Task Identity、Task Revision、Task Runtime State。
- Task Revision 不可原地修改；结构性变化通过新 Revision 或新 Task + lineage 表达。
- 一个 Task 默认最多只有一个活动 Attempt；多 Agent 协作通过同一 Attempt 下多个 Execution / Delegation 实现。
- Worker 崩溃接管恢复同一个 Execution；业务级重新尝试才创建新的业务 Attempt，并按执行策略创建新的 Execution。
- Agent 只能提交完成声明和 Evidence；Task 是否完成由平台验证与状态协调规则决定。
- 用户明确的目标、约束、审批要求和验收标准不能被 Agent 自行削弱或修改。

### 2.2 Proposed in this document

- Task Attempt 的完整状态机、活动状态集合和持久化字段。
- Task State Coordinator 的职责、命令接口和唯一写入权。
- Task Attempt 与 Execution / Delegation 的显式关联表。
- Task Runtime State 与活动 Attempt 的数据库一致性约束。
- Domain Event Outbox / Inbox、Command Receipt 和 CAS 的落地协议。
- Replanning 与活动 Attempt 的迁移规则。
- Work Run Recovery Coordinator 与 Execution RecoverySupervisor 的职责边界。

### 2.3 Deferred

- AttemptGroup、多 Attempt 竞争评估和 Winner Selection。
- 跨 Work Run 的计划协调。
- 复杂的自动 Revision Compatibility 推断。
- 第三方 Planner 插件化和高级动态并行调度。

## 3. Domain Model and Ownership

### 3.1 Relationship

```text
Work
└── WorkRun
    └── WorkPlan (stable identity)
        ├── PlanVersion V1 (immutable)
        │   └── PlanVersionTask -> Task + TaskRevision
        ├── PlanVersion V2 (immutable)
        │   └── PlanVersionTask -> Task + TaskRevision
        └── active_plan_version_id

Task (stable business identity)
├── TaskRevision R1 (immutable definition)
├── TaskRevision R2 (immutable definition)
├── TaskRuntimeState (mutable current state)
└── TaskAttempt (one active at most)
    ├── TaskAttemptExecution -> Execution(s)
    ├── TaskAttemptDelegation -> Delegation(s)
    ├── Evidence references
    └── Verification references
```

### 3.2 Authority Matrix

| Object | Authoritative owner | Responsibility |
|---|---|---|
| Work / Work Run | Work Domain | Business goal, lifecycle and acceptance responsibility |
| Work Plan / Plan Version | Plan Domain | Current adopted plan and immutable plan snapshots |
| Task Identity / Revision | Plan Domain | Stable business identity and immutable task definition |
| Task Runtime State | Plan Domain Coordinator | Current business progress and active Attempt pointer |
| Task Attempt | Plan Domain Coordinator | One business execution attempt and its lifecycle |
| Execution / Step / Lease | Execution Domain | Technical execution and worker ownership |
| Checkpoint Manifest | Execution Runtime | Recoverable technical boundary |
| Tool Invocation | Tool Gateway / Execution Domain | External side-effect state and idempotency |
| Delegation | Agent Orchestration Domain | Runtime agent handoff facts |
| Evidence | Artifact / Execution / domain source | Traceable supporting material |
| Verification | Verification Domain | Acceptance evaluation and result |
| Domain Outbox | Domain Event Infrastructure | Reliable publication of committed business facts |

关键原则：

> Plan 管理业务执行进度；Execution 管理技术运行状态；Checkpoint 管理技术恢复位置；Event Log 记录已经发生的事实。它们通过稳定 ID 关联，不互相复制成对方的权威状态源。

Execution 的 succeeded 不等于 Task Completed；Checkpoint committed 不等于业务 Task 完成；Agent 的 completion claim 也不等于 Verification Passed。

## 4. Core Data Model

以下为逻辑模型，字段类型可按现有 MongoDB / Pydantic 规范落地。字段不是当前代码现状。

### 4.1 Task Identity

```typescript
interface TaskIdentity {
  id: string;
  workRunId: string;
  createdAt: string;
  createdBy: string;
  derivedFromTaskId?: string;
  supersedesTaskId?: string;
}
```

Task Identity 表达“这项业务工作是什么”。它跨 Plan Version 保持稳定，不承载可变描述和运行状态。

### 4.2 Task Revision

```typescript
interface TaskRevision {
  id: string;
  taskId: string;
  revisionNumber: number;
  title: string;
  description: string;
  acceptanceCriteria: AcceptanceCriterion[];
  dependencies: TaskDependency[];
  requiredCapabilities: CapabilityRequirement[];
  verificationPolicyRef?: string;
  planningConstraints: string[];
  createdAt: string;
  createdBy: string;
  changeReason: string;
}
```

Revision 创建后不可变。计划版本通过 `PlanVersionTask` 引用确切 Revision：

```typescript
interface PlanVersionTask {
  planVersionId: string;
  taskId: string;
  taskRevisionId: string;
  milestoneId?: string;
  position: number;
}
```

同一 Task Revision 可以被后续 Plan Version 复用。Plan Version 是结构快照，不应因 Task 进度变化而不断生成新版本。

### 4.3 Task Runtime State

```typescript
interface TaskRuntimeState {
  taskId: string;
  status: TaskStatus;
  activeRevisionId: string;
  activeAttemptId: string | null;
  progress?: number;
  blockers: Blocker[];
  lastEventSequence: number;
  version: number;
  updatedAt: string;
}
```

- `activeRevisionId`：当前 Plan 采用的 Task Revision。
- `activeAttemptId`：当前唯一活动 Attempt；无活动 Attempt 时为 null。
- `version`：CAS 版本，用于协调并发命令。
- `lastEventSequence`：Task 聚合内已应用事件水位；不取代 Execution Event 序号。

### 4.4 Task Attempt

```typescript
interface TaskAttempt {
  id: string;
  taskId: string;
  taskRevisionId: string;
  attemptNumber: number;
  status: AttemptStatus;
  assignedAgentId?: string;
  startedAt?: string;
  finishedAt?: string;
  resultRef?: string;
  failureReason?: string;
  createdAt: string;
  createdBy: string;
}
```

Attempt 固定绑定启动时的 `taskRevisionId`。后续 Plan Version 切换不会悄悄改变该 Attempt 的执行语义。

Attempt 是业务尝试，不是 Execution 的别名：
- 一个 Attempt 可以包含多个 Execution。
- 一个 Attempt 可以包含多个 Delegation。
- 一个 Execution 崩溃恢复不创建新 Attempt。
- Tool / Step / Execution 技术重试通常不创建新 Attempt。
- 业务策略决定重新完成整个 Task 时才创建新 Attempt。

### 4.5 Explicit Relations

建议使用独立关联集合，而不是仅在 Attempt 中维护 ID 数组：

```typescript
interface TaskAttemptExecution {
  attemptId: string;
  executionId: string;
  role: string;
  requiredForCompletion: boolean;
  attachedAt: string;
}

interface TaskAttemptDelegation {
  attemptId: string;
  delegationId: string;
  role: string;
  requiredForCompletion: boolean;
  attachedAt: string;
}
```

这允许同一 Attempt 下存在 Parent Agent、Coding Agent、Testing Agent、Review Agent 等多个执行单元，同时保留每个执行单元独立的 Execution 状态和权限边界。

## 5. State Machines and Invariants

### 5.1 Task State

建议状态：

| Status | Meaning |
|---|---|
| Draft | 已创建，尚未进入可执行计划 |
| Ready | 已纳入 Active Plan，依赖与前置条件满足 |
| In Progress | 当前 Attempt 正在推进 |
| Blocked | 当前工作因外部条件、权限、资源或 Interaction 阻塞 |
| Verifying | 已提交 Completion Claim，正在验收 |
| Completed | 满足适用 Verification Policy |
| Failed | 当前策略下不再继续，需人工处理或新业务决策 |
| Cancelled | 经授权取消 |
| Skipped | 计划调整后确认不再需要执行 |

### 5.2 Attempt State

建议状态：

| Status | Active? | Meaning |
|---|---:|---|
| Created | Yes | 已创建并占用活动名额，尚未开始实际执行 |
| Running | Yes | 正在执行 |
| Blocked | Yes | 等待外部条件、权限或 Interaction |
| Awaiting Verification | Yes | 执行结果已提交，正在验收 |
| Succeeded | No | 验收通过 |
| Failed | No | 本次业务尝试失败 |
| Cancelled | No | 本次尝试被取消 |
| Superseded | No | 因任务定义变化不再作为当前执行依据，历史保留 |

活动状态集合：

`Created | Running | Blocked | AwaitingVerification`

终态集合：

`Succeeded | Failed | Cancelled | Superseded`

暂停不自动释放活动名额。Blocked 和 Awaiting Verification 仍占用活动名额，直到 Attempt 进入终态。

### 5.3 State Transition Matrix

| Trigger | Attempt transition | Task transition |
|---|---|---|
| Create Attempt | — → Created | Ready → Ready |
| First Execution starts | Created → Running | Ready → In Progress |
| External wait / Interaction | Running → Blocked | In Progress → Blocked |
| Resume | Blocked → Running | Blocked → In Progress |
| Submit Completion Claim | Running → Awaiting Verification | In Progress → Verifying |
| Verification Passed | Awaiting Verification → Succeeded | Verifying → Completed |
| Verification Failed, retry allowed | Awaiting Verification → Failed | Verifying → Ready |
| Verification Failed, no retry | Awaiting Verification → Failed | Verifying → Failed |
| Attempt cancelled, Task continues | Created/Running/Blocked → Cancelled | In Progress/Blocked → Ready |
| Whole Task cancelled | Active → Cancelled | Any non-terminal → Cancelled |
| Revision migration | Active → Superseded (after safe stop) | Current state recalculated by Coordinator |

Create Attempt 时 Task 保持 Ready，但 `activeAttemptId` 已设置并占用唯一活动名额；只有第一个关联 Execution 真正开始后，Task 才进入 In Progress。这样避免“Attempt 已创建但还未运行”时把 Task 错误显示为执行中。

Task Completed 必须同时满足：
1. 当前 Attempt 是该 Task 的活动 Attempt；
2. Completion Claim 绑定当前 Attempt 和实际使用的 Task Revision；
3. 必需 Execution / Delegation 已达到可接受终态；
4. 必需 Evidence 已持久化；
5. Verification Domain 对该 Revision 的 Acceptance Criteria 返回 Passed；
6. Coordinator 成功提交 Attempt Succeeded、Task Completed 和对应领域事件。

### 5.4 Database Invariants

MVP 必须由数据库约束与事务共同保证单活动 Attempt，而不只依赖应用层检查。

建议 MongoDB partial unique index：

```javascript
db.task_attempts.createIndex(
  { task_id: 1 },
  {
    unique: true,
    partialFilterExpression: {
      status: {
        $in: ["created", "running", "blocked", "awaiting_verification"]
      }
    }
  }
)
```

同时维护以下不变量：
- 一个 Task 最多一个活动 Attempt。
- `activeAttemptId` 指向同一 Task 的活动 Attempt；无活动 Attempt 时必须为 null。
- 活动 Attempt 的 `taskRevisionId` 必须是已存在的不可变 Revision。
- 一个 Attempt 只能归属一个 Task。
- Attempt 的业务终态只能由 Coordinator 提交。
- Task Runtime State 的更新必须使用 version CAS。
- Attempt 创建 / 终结、活动指针更新、Task 状态变更和 Outbox 事件必须在同一事务中提交。

实现时应验证 MongoDB 对数组值的 partialFilterExpression 与当前部署版本的兼容性；若不支持所需表达式，应改用显式 `active: true` 字段和 partial unique index，并在同一事务内维护，不得退化为仅应用层约束。

## 6. Task State Coordinator

### 6.1 Responsibility

Task State Coordinator 是 Plan Domain 内部唯一的 Task Runtime State 与 Attempt 生命周期协调者。

它负责：
- 校验 Task 状态转换；
- 创建、启动、阻塞、恢复、终结 Attempt；
- 维护 `activeAttemptId`；
- 接收 Execution / Delegation / Verification 的事实和结论；
- 聚合必需 Execution / Delegation 结果；
- 管理 Completion Claim；
- 协调 Verification；
- 应用 Replanning / Revision Migration；
- 以幂等方式修复可推导的状态不一致；
- 在同一事务中写入状态与 Outbox 事件。

它不负责：
- 生成 Plan（Planning Service）；
- 执行 Agent / Workflow / Tool（Execution Runtime）；
- 管理 Execution Lease / Checkpoint（Execution Domain）；
- 直接执行 Verification（Verification Domain）；
- 决定外部副作用是否发生（Tool Invocation Ledger / Provider 查询）。

### 6.2 Runtime Placement

MVP 可以与 Execution Runtime 部署在同一应用进程，但必须保持独立的领域接口、Repository 和持久化边界。后续可以独立部署，不改变领域契约。

### 6.3 Command API

建议命令：

| Command | Purpose |
|---|---|
| CreateTask | 创建 Task Identity / 初始 Revision / Runtime State |
| CreateTaskRevision | 创建不可变 Revision |
| AssignTask | 更新负责人或分配关系 |
| MakeTaskReady | 校验依赖和前置条件后设为 Ready |
| StartTaskAttempt | 创建 Attempt 并占用活动名额 |
| ReportExecutionStarted | 首个 Execution 开始后推进 Attempt / Task |
| AttachExecution | 将 Execution 关联到 Attempt |
| AttachDelegation | 将 Delegation 关联到 Attempt |
| ReportExecutionResult | 接收 Execution 终态事实 |
| ReportDelegationResult | 接收 Delegation 结果事实 |
| BlockTaskAttempt | 因外部条件阻塞当前 Attempt |
| ResumeTaskAttempt | 条件满足后恢复当前 Attempt |
| SubmitCompletionClaim | 提交结果与 Evidence 引用 |
| ApplyVerificationResult | 消费 Verification 结论 |
| CancelTaskAttempt | 取消一次尝试 |
| CancelTask | 取消整个业务 Task |
| ApplyPlanVersion | 原子应用 Plan Version 的 Task Revision 集合 |
| MigrateTaskRevision | 在安全停止旧 Attempt 后切换 Revision |

每个 Command 应带 `commandId`、`actor`、`correlationId`、预期聚合版本或等价条件。重复命令返回原 Command Receipt，不重复产生副作用。

### 6.4 Application Service Decomposition

逻辑职责可拆分为：
- TaskCommandHandler
- TaskAttemptCoordinator
- TaskCompletionCoordinator
- TaskReplanningCoordinator

MVP 不要求拆成多个微服务；可由一个 Coordinator Facade 组合这些内部服务。

## 7. Events and Transaction Boundaries

### 7.1 Plan Domain Events

建议事件：
- TaskCreated
- TaskRevisionCreated
- TaskAssigned
- TaskReady
- TaskAttemptCreated
- TaskAttemptStarted
- TaskAttemptBlocked
- TaskAttemptResumed
- TaskExecutionAttached
- TaskDelegationAttached
- TaskCompletionClaimed
- TaskVerificationStarted
- TaskVerificationPassed
- TaskVerificationFailed
- TaskAttemptSucceeded
- TaskAttemptFailed
- TaskAttemptCancelled
- TaskAttemptSuperseded
- TaskCompleted
- TaskBlocked
- TaskCancelled
- TaskSkipped
- TaskRevisionMigrated
- PlanVersionActivated

事件至少包含：
`eventId`、`eventType`、`schemaVersion`、`aggregateType`、`aggregateId`、`sequence`、`occurredAt`、`recordedAt`、`actor`、`correlationId`、`causationId` 和必要 payload。

### 7.2 Transactional Outbox / Inbox

Plan Domain 状态和对应领域事件在同一 MongoDB 事务中写入 Outbox。发布器异步投递，消费者通过 Inbox / Processed Message Receipt 去重。

建议边界：
- Task Runtime State + Attempt + 关联记录 + Command Receipt + Outbox：同一事务。
- Verification 自己的结果与其事件：由 Verification Domain 自己的事务管理。
- Coordinator 消费 Verification Passed/Failed：Inbox 去重后，在 Plan Domain 事务内更新 Attempt / Task 并写 Plan Domain Outbox。
- Execution Event 继续由 Execution Domain 通过 ExecutionRepository 写入，不复制到 Plan Outbox。
- Execution Event 消费者通过 Inbox 幂等地通知 Coordinator；不能把 Redis Pub/Sub 当作可靠事件源。

当前 Execution Event 是按 Execution 聚合的技术事件流，不应被强行复用为 Plan Domain Event Store。MVP 不做完整 Event Sourcing。

### 7.3 Concurrency and CAS

- Task Runtime State 的每次写入带 `version = expectedVersion` 条件并递增 version。
- 创建 Attempt 时，在事务内校验 `activeAttemptId == null`、Task 状态允许执行、依赖满足，然后插入 Attempt 并设置活动指针。
- 唯一索引是第二道防线，防止并发请求绕过应用层检查。
- 终结 Attempt 时，在同一事务内验证当前活动指针仍指向该 Attempt，更新 Attempt 终态、清空活动指针、更新 Task 状态并写 Outbox。
- Replanning、Recovery、Verification 回调之间通过 CAS + 幂等 Command Receipt 串行化；冲突方重新加载事实后重新判断，不得覆盖。

## 8. Execution, Delegation and Verification Integration

### 8.1 Execution

Execution Domain 保持现有技术职责。Plan Domain 通过显式关系关联 Execution：

```text
TaskAttempt
  ├── Execution E1 (parent agent)
  ├── Execution E2 (coding worker)
  ├── Execution E3 (testing worker)
  └── Execution E4 (review worker)
```

- Execution 创建时记录 Task / Attempt 的关联元数据或通过关联表绑定。
- Execution Lease、Fencing Token、Step、Checkpoint Manifest、Execution Event 均由 Execution Domain 管理。
- Execution succeeded / failed 通过可靠事件通知 Coordinator。
- 一个 Attempt 可在一个 Execution 完成后启动另一个 Execution；也可并行执行多个 Execution。
- 并行 Execution 不代表共享可写 Sandbox；资源隔离与共享策略由 Resource / Sandbox Domain 控制。

### 8.2 Delegation

Delegation 是 Agent Orchestration 的运行时事实。父 Agent 委派的目标必须来自允许的 Delegation Binding，并在每次委派时重新执行权限和 Policy 检查。

- Attempt 可关联多个 Delegation。
- Delegation 的 Child Execution 独立拥有技术执行状态。
- 子 Agent Local Plan 的局部完成不自动完成父 Task。
- Coordinator 等待所有 `requiredForCompletion` 的 Execution / Delegation 达到可接受结果，再允许提交 Completion Claim。
- 不是所有子 Agent 都必须成功：是否必需由 Attempt 关联关系和 Verification Policy 决定，不能硬编码为“所有子 Execution 全成功”。

### 8.3 Completion Claim and Verification

Completion Claim 必须绑定：
- `taskId`
- `attemptId`
- `taskRevisionId`
- 结果摘要 / Artifact 引用
- Evidence 引用
- submitter / actor
- correlation metadata

Verification 绑定 Task、Revision、Attempt、Policy Version 和 Evidence。Verification Passed 与 TaskCompleted 是不同事实：
1. Verification Domain 产生 Passed 结论；
2. Coordinator 校验结论仍适用于当前活动 Attempt / Revision；
3. Coordinator 终结 Attempt 并将 Task 设为 Completed。

若 Verification 回调重复到达，Inbox 去重；若它属于已经 superseded / cancelled 的 Attempt，不得完成当前 Task，只记录历史结论或冲突事件。

## 9. Replanning and Revision Migration

### 9.1 Plan Version Activation

Replanning 生成新 Plan Version，不直接改写旧版本。激活流程：
1. 读取 Active Plan Version 和 Task Runtime State。
2. 创建不可变的新 Plan Version 和 PlanVersionTask 引用。
3. 对每个 Task 判断保留、Revision 更新、新建、取消或跳过。
4. 检查运行中 Attempt 是否仍兼容。
5. 通过 Coordinator 应用任务 Revision 与状态变更。
6. 原子切换 Active Plan Version。
7. 发布 PlanVersionActivated 及相关 Task 事件。

新版本不自动覆盖 Task Runtime State；Task 的业务进度与计划结构采用状态分离。

### 9.2 Replanning Rules by Task State

| Task State | Default rule |
|---|---|
| Draft | 可直接调整定义或从新版本移除 |
| Ready, no active Attempt | 可切换到新 Revision |
| Ready, Attempt Created | 先取消或 Supersede 尚未开始的 Attempt，再切换 |
| In Progress | 保留 Attempt 绑定的旧 Revision；默认不热切换 |
| Blocked | 保留阻塞事实，重新评估是否继续旧 Revision 或安全迁移 |
| Verifying | 保留现有 Verification；若 Acceptance Criteria 已改变，则旧结论不能自动适用 |
| Completed | 保留历史结果；不得被普通 Replanning 重开 |
| Failed / Cancelled / Skipped | 保留历史状态；是否重新纳入计划必须显式创建新的业务路径 |

### 9.3 Safe Revision Migration

当运行中的 Task 必须变更 Revision：
1. Coordinator 发起 Pause / Cancel 请求，Execution Runtime 停止推进相关 Execution。
2. 对每个 Execution 执行恢复协议的副作用裁决；UNKNOWN Tool Invocation 不得忽略。
3. 等待或核对关联 Delegation / Execution 的安全停止状态。
4. 记录旧 Attempt 的实际结果；按语义终结为 Failed、Cancelled 或 Superseded。
5. 清空旧活动 Attempt 指针。
6. 创建新 Task Revision（或必要时新 Task 并记录 lineage）。
7. 后续由新 Attempt 按新 Revision 执行。

MVP 不做复杂自动兼容性推断。Acceptance Criteria 实质变化时，必须重新验证；不能将旧 Verification 直接迁移为新 Revision 的通过结论。

## 10. Recovery Protocol

### 10.1 Two Recovery Levels

**Work Run / Task business coordination recovery** 与 **Execution technical recovery** 是两层：

- Work Run Recovery Coordinator：恢复 Active Plan Version、Task Runtime State、Attempt、Delegation 和 Interaction 的业务协调视图。
- Execution RecoverySupervisor：恢复某个 Execution 的 Lease、Step、Checkpoint Manifest、Tool Invocation 和资源绑定。

二者不互相取代。恢复 Work Run 时不应直接重跑所有 Task；恢复 Execution 时也不应擅自改变 Task 业务状态。

### 10.2 Recovery Sequence

1. **Acquire Work Run Coordination Ownership**：如存在多个 Coordinator Worker，使用 Work Run 级 Lease + Fencing Token 或等效 CAS 协调所有权。该 Lease 与 Execution Lease 不同；前者协调业务 Run，后者保护单个 Execution 的技术写入。MVP 若采用单协调进程，也必须保留可安全扩展的 CAS 写入边界。
2. **Load Durable Business State**：加载 Work Run、Active Plan Version、Task、Task Revision、Task Runtime State、活动 Attempt、Delegation、Interaction、Verification 和 Evidence 引用。
3. **Reconcile Attempt Relations**：校验 `activeAttemptId`、Attempt 状态、Attempt Revision、关联 Execution / Delegation 的一致性。
4. **Reconcile Technical Executions**：读取 Execution Domain 状态；调用其恢复服务处理 queued、running lease expired、waiting_input 等状态，不直接写 Execution 状态。
5. **Resolve Side Effects**：Tool Invocation 为 succeeded 时复用已持久化结果；failed 按策略处理；prepared 且确认未发出时可执行；in_progress / unknown 必须查询 Provider、沿用原幂等键或进入人工裁决。
6. **Restore Context**：从结构化业务事实重建目标、Acceptance Criteria、Active Plan Version、Task Revision、当前 Attempt、决策、阻塞、Interaction、Evidence、工具结果和 Delegation Handoff。模型生成的 Summary 只能作为辅助。
7. **Resume or Replan**：恢复现有活动 Attempt；条件未满足则保持 Blocked；需要改变目标或 Revision 时执行 Replanning / Migration；不得因为 Worker 重启直接创建新 Attempt。
8. **Repair Projections**：对可由权威事实确定的活动指针或投影差异执行幂等修复；无法确定的冲突进入人工处理并保留审计记录。

### 10.3 Reconciliation Rules

| Durable facts | Action |
|---|---|
| Attempt Running + Execution recoverable | 恢复同一 Execution、同一 Attempt |
| Attempt Blocked + Interaction unresolved | 保持 Blocked，不重复执行 |
| Execution terminal, Attempt not aggregated | 消费/补偿处理 Execution 事实，推进 Coordinator |
| Tool Invocation UNKNOWN | 先做副作用裁决，不盲目重试 |
| Attempt terminal, active pointer still set | Coordinator 幂等清理指针并记录修复事件 |
| Active pointer references missing Attempt | 不猜测创建新 Attempt；隔离并人工核查 |
| Multiple active Attempts found | 违反唯一约束，停止自动推进并进入数据修复 |
| Attempt Revision differs from Task active Revision | 按 Revision Migration 规则判断，不静默改写 Attempt Revision |
| Verification callback belongs to old Attempt | 记录历史结果，不得完成当前 Task |

### 10.4 Checkpoint and Context

Checkpoint 是 Execution Runtime 的恢复边界，不是 Plan / Task 的唯一持久化存储。恢复依据来自各领域权威对象和增量事件。

结构化 Context Reconstruction 至少恢复：
- Work Run 目标与用户约束；
- Active Plan Version 与 Task Revision；
- Task 状态、依赖、Assignment、Attempt；
- 关键决策、变更原因与 Replanning 历史；
- Blocker、Interaction、审批和超时状态；
- Execution / Delegation 关系与结果；
- Tool Invocation 意图、状态和结果引用；
- Artifact / Evidence / Verification；
- Skill 的领域进度与版本引用。

### 10.5 Unknown Side Effects

UNKNOWN 表示平台无法确定外部副作用是否已发生，不等于 Failed，也不等于可以安全重试。

处理顺序：
1. 查询 Provider 的 operation status；
2. 若 Provider 支持幂等，使用原 Idempotency Key 查询或重放；
3. 若可确认未发生，允许按原调用意图执行；
4. 若可确认已发生，持久化结果并继续；
5. 无法确认时暂停相关 Attempt 或进入人工裁决。

平台不承诺对不支持幂等键和状态查询的 Provider 实现 exactly-once。

## 11. Failure and Concurrency Test Matrix

MVP 必须覆盖以下故障和并发测试：

| Scenario | Expected result |
|---|---|
| 两个请求同时 StartTaskAttempt | 仅一个成功；另一个得到冲突或幂等原结果 |
| Attempt 插入后事务失败 | Attempt、活动指针、Task State、Outbox 全部回滚 |
| Attempt 终结后 Worker 崩溃 | 恢复时不重复终结、不重复创建 Attempt |
| Worker A lease 过期，Worker B takeover | A 的 Execution 事实写入被 Fencing 拒绝；业务 Attempt 保持同一身份 |
| Execution succeeded 事件重复投递 | Coordinator 幂等消费，不重复改变 Task |
| Verification Passed 重复回调 | 只终结一次 |
| Verification 回调晚于 Revision Migration | 旧 Revision 结果不能完成新 Revision |
| Replanning 与 Completion 同时发生 | CAS 决定唯一顺序；输家重新读取并按事实裁决 |
| Task Attempt 取消时存在 UNKNOWN Tool Invocation | 不释放活动名额直到副作用风险被裁决或显式隔离 |
| Task Runtime State 与 Attempt 不一致 | Coordinator 按权威事实幂等修复或隔离，不猜测 |
| 多 Agent 子 Execution 部分失败 | 根据 requiredForCompletion 与 Verification Policy 判断，不默认全有或全无 |
| Outbox 消息重复 / Inbox 消费者重启 | 事件可重投递且业务效果只应用一次 |
| Redis 通知丢失 | 通过 Execution Event 游标补齐，不丢失执行事实 |
| Work Run Coordinator Worker 崩溃 | 新 Coordinator 恢复同一 Work Run 和活动 Attempt |

## 12. Mapping to Current Repository

以下为对 `feature/execution-model` 当前 HEAD 的代码阅读结果，不代表测试已在本轮重新运行。

### 12.1 Existing Execution Domain

当前分支已存在以下模块：

| Current implementation | Existing responsibility | Plan Runtime integration |
|---|---|---|
| `app/engine/execution/models.py` | Execution、Step、CheckpointManifest、ExecutionEvent、ToolInvocation 等模型 | 继续作为技术执行事实模型；不把 Plan Task / TaskAttempt 塞入 Execution |
| `ExecutionRepository` | 事务写入、执行事实写入 fencing、事件同事务提交 | 保持为 Execution Domain 唯一事实写入入口 |
| `LeaseManager` | Execution Lease、Fencing Token、接管 | 只保护单个 Execution，不替代 Work Run Coordinator Ownership |
| `CheckpointCoordinator` | Manifest 两阶段提交与 checkpoint event | 继续管理技术恢复边界 |
| `RecoverySupervisor` | 待派发、过期 Lease 接管、waiting_input 恢复扫描 | 继续负责 Execution 技术恢复 |
| `MongoToolLedger` | Tool Invocation 幂等账本与 UNKNOWN 处理 | 继续作为外部副作用裁决依据；需确认所有生产写路径均已 fenced |
| `Dispatcher` / `CeleryDispatcher` | 可靠重投递抽象与 Celery 投递 | 保持技术调度职责 |
| `WorkflowRuntimeAdapter` | 把 Workflow 运行接入 Execution 生命周期 | 作为 Plan Task → Attempt → Execution 的适配入口，需逐步移除对旧 Task 状态的权威依赖 |

### 12.2 Legacy Task Model and Migration Boundary

当前 `app/models/task.py` 的 Task 是既有 Workflow / Agent 运行实例，包含：
- workflow_id / agent_id、input / output、variables；
- 旧 TaskStatus（pending / running / waiting_human / completed / failed / cancelled）；
- timeline、旧 Checkpoint、token budget、Celery 任务信息等。

当前 `WorkflowRuntimeAdapter` 仍通过旧 Task 状态映射 Execution 终态；`CheckpointCoordinator` 注释明确处于 E4 影子双写期，旧 `Task.checkpoint` 仍是权威恢复源；`TaskRecoveryService` 仍处理旧 Task 的 waiting_human 与孤儿 running 任务。

因此：
1. 不能直接把当前 `app.models.task.Task` 改名或重解释为产品级 Plan Task。
2. 不能在 Plan Coordinator 中继续把旧 Task.status 当作新 Task Runtime State 的权威状态。
3. 应先建立显式映射 / Adapter：Legacy Workflow Task ↔ Execution；未来 Plan Task Attempt ↔ one-or-more Execution。
4. 影子双写切换必须有数据对账、读路径切换、回滚和观测指标；不能同时允许两套服务自由写同一状态。
5. 旧 Task 的 Workflow 输入输出、变量池和历史 API 可在迁移期保留为执行适配数据，不必强行迁入 Plan Task Revision。

### 12.3 Gaps to Implement

- Plan Domain 的 Task Identity / Task Revision / Task Runtime State 持久化模型。
- TaskAttempt 模型、状态机、唯一活动约束和显式 Execution / Delegation 关联。
- Task State Coordinator 命令处理、CAS、Command Receipt。
- Plan Domain Event Outbox / Inbox 与幂等消费者。
- Completion Claim 与 Verification Domain 集成。
- Plan Version 激活与 Revision Migration 协议。
- Work Run 级恢复协调及其与 Execution RecoverySupervisor 的集成。
- 旧 Task / Workflow 执行路径的分阶段迁移和对账工具。

## 13. MVP Implementation Sequence

建议按以下顺序实现，避免一开始同时改动所有运行路径：

1. **P0 — Freeze contracts**：确认 Task / Attempt 状态机、字段、唯一约束、Command / Event 契约。
2. **P1 — Plan persistence**：建立 Task Identity / Revision / Runtime State、Plan Version 引用和 Repository。
3. **P2 — Attempt + Coordinator**：实现单活动 Attempt、CAS、唯一索引、Command Receipt、状态转换测试。
4. **P3 — Execution integration**：建立 Attempt-Execution 关联；Execution Event 幂等消费；保留现有 Execution Lease / Recovery。
5. **P4 — Completion & Verification**：Completion Claim、Evidence 引用、Verification 回调及 Task 完成协调。
6. **P5 — Replanning & migration**：Plan Version 激活、Revision Migration、运行中 Attempt 安全停止。
7. **P6 — Work Run recovery**：结构化 Context Reconstruction、跨领域对账、故障注入与恢复演练。
8. **P7 — Legacy cutover**：明确旧 Task 状态权威迁移、读写路径切换和回滚窗口。

每阶段独立测试、独立验收；不要先建设一套新的 Workflow Runner 或替换现有 Execution Runtime。

## 14. Acceptance Criteria

- [ ] Task Identity、Task Revision、Task Runtime State 三层职责和存储边界明确。
- [ ] Plan Version 通过显式关系引用 Task Revision。
- [ ] 一个 Task 同时最多一个活动 Attempt，数据库唯一约束和 Coordinator 事务共同保证。
- [ ] Attempt 可关联多个 Execution / Delegation；Attempt 与 Execution 状态机互不替代。
- [ ] Tool Retry / Execution Recovery 不自动创建新业务 Attempt。
- [ ] Completion Claim、Evidence、Verification 与 TaskCompleted 有明确绑定和顺序。
- [ ] Replanning 不覆盖历史计划、Task Revision、Attempt、Execution 或 Evidence。
- [ ] 运行中 Attempt 默认固定执行 Revision；迁移必须先安全停止并裁决副作用。
- [ ] Execution Recovery 复用现有 Lease / Fencing / Manifest / Tool Ledger，不建立第二套技术恢复系统。
- [ ] Plan Domain 状态与事件通过 Outbox / Inbox 幂等协调。
- [ ] Recovery 不会因 Worker 重启直接创建新 Attempt。
- [ ] 旧 Task / 新 Plan Task 的迁移边界、双写权威源、对账和回滚策略有测试。
- [ ] 故障注入矩阵的关键场景均有自动化测试。

---

## Appendix A. Design Guardrails

1. **Never conflate business retry and worker recovery.** Worker recovery resumes the same Execution and Attempt; business retry creates a new Attempt.
2. **Never infer Task completion from Execution completion.** Verification is a separate business decision.
3. **Never mutate an immutable revision.** Create a new Revision and preserve lineage.
4. **Never blindly retry UNKNOWN side effects.** Resolve external state first.
5. **Never let Planner or Agent write Task Runtime State directly.** They issue commands; Coordinator applies transitions.
6. **Never treat Redis notifications as durable facts.** Read committed events by cursor.
7. **Never treat one active Attempt as one active Execution.** Multi-Agent parallelism remains possible inside the Attempt.

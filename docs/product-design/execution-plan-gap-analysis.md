# Execution Domain ↔ Plan Runtime Gap Analysis

> 状态：**Review / Proposed**
>
> 审查基线：`feature/execution-model` @ `132a3df4e97e7505b3379fc95ea7a4a0032e25ce`
>
> 审查方式：远端源码静态审查与现有测试文件检查；本轮未在本地运行测试，也未验证真实 MongoDB Replica Set。
>
> 关联设计：[Plan Domain](./plan-domain.md)、[Plan Runtime Integration & Recovery Protocol](./plan-runtime-integration.md)、[Execution Architecture](../../EXECUTION-ARCHITECTURE.md)、[Execution Model Proposal](../../EXECUTION-MODEL-PROPOSAL.md)。

## 1. Executive Summary

**结论：复用现有 Execution 技术底座，在其上新增 Plan Domain 的业务协调层；不要重建 Durable Execution，也不要把旧 TaskService 改造成新 Plan Coordinator。**

当前 Execution Domain 已经提供了相当多可复用能力：

- Execution 身份、技术状态和 Worker Lease；
- ExecutionRepository 的事务级 fencing；
- LeaseManager 的 CAS、单调 fencing token 和 takeover；
- CheckpointCoordinator 的 Manifest 两阶段提交；
- ExecutionEvent 的持久化序号、事务内追加和游标读取；
- MongoToolLedger 的调用意图、幂等键和 UNKNOWN 状态；
- Dispatcher / RecoverySupervisor 的派发、退避、接管和重派；
- ResourceBinding 的资源关联模型。

但当前分支尚未实现产品级 Plan Runtime：后端代码树中未发现 WorkRun、PlanVersion、TaskRevision、TaskAttempt、TaskStateCoordinator、Verification 或 Plan Domain Outbox/Inbox 的正式领域模块。

当前最大的集成风险不是 Execution 能力不足，而是**旧 Workflow Task 仍是生产执行入口和业务状态权威源，Execution 目前有一部分仍处于影子双写阶段**。新 Plan Runtime 不能在这个状态下直接接管同一批旧 Task 的运行状态。

## 2. Reuse / Adapt / Build Matrix

| Area | Current implementation | Decision | Reason |
|---|---|---|---|
| Execution identity / lifecycle | `engine/execution/models.py` | Reuse | 技术执行身份与状态已经独立建模 |
| Execution transaction / fencing | `ExecutionRepository` | Reuse for Execution only | 事务内 touch + token 校验是成熟的执行写入边界 |
| Execution Lease | `LeaseManager` | Reuse | 继续保护单个 Execution 的 Worker 所有权 |
| Checkpoint Manifest | `CheckpointCoordinator` | Reuse for technical recovery | 不复制 LangGraph State，精确引用 checkpoint |
| Execution Event | `ExecutionEvent` / `read_events` | Reuse for execution facts | 仅作为 Execution 聚合事件流，不扩展成 Plan Event Store |
| Tool Invocation Ledger | `MongoToolLedger` | Reuse with boundary hardening | 保留原始意图、幂等键、UNKNOWN；确保 durable 路径始终带有效 identity |
| Dispatcher / RecoverySupervisor | `dispatcher.py` / `recovery.py` | Reuse | 负责技术派发、Execution takeover 和重派 |
| ResourceBinding | `ResourceManager` | Reuse | 资源生命周期独立于 Plan Task |
| Legacy Workflow Task | `models/task.py` + `TaskService` | Adapt then retire as execution authority | 仍承载旧 Workflow 运行状态、变量和 checkpoint |
| Plan Task / Revision / Attempt | Not present | Build | 属于新的业务领域模型 |
| Task State Coordinator | Not present | Build | 负责 Plan Task / Attempt 状态唯一写入 |
| Plan Event Outbox / Inbox | Not present | Build | Plan 领域事务与 Execution 事件流是不同聚合边界 |
| Verification integration | Not present as a Plan domain | Build / integrate later | Execution 成功不能直接成为 Task 完成结论 |
| Work Run Recovery Coordinator | Not present | Build as orchestration service | 组合各领域事实，不替代 Execution RecoverySupervisor |

## 3. Critical Findings

### F-01 — Legacy Workflow Task 仍是执行与恢复权威源

**Severity: P0 — 必须先解决迁移边界**

证据：
- `app/engine/execution/workflow_adapter.py` 的 `run_workflow_execution` 通过 `TaskService.get_task(task_id)` 读取旧 Task 状态，并调用 `WorkflowEngine().run_and_persist(task_id)` 执行。
- Adapter 将旧 Task 的 `completed / failed / cancelled / waiting_human` 映射为 Execution 终态或 waiting_input。
- `app/engine/execution/checkpoint.py` 明确说明 E4 影子双写阶段旧 `Task.checkpoint` 仍是权威恢复源，Manifest 只是影子。
- `app/services/task_recovery.py` 仍会把超时的旧 `running` Task 标记为 failed；旧 `waiting_human` 也由旧服务和定时任务恢复。
- `app/engine/execution/reconcile.py` 当前对账的方向仍是旧 Task.checkpoint 对比 Execution Manifest。

影响：
- 旧 Task 的状态转换与 Execution 的状态转换并非同一个原子事务。
- 若 Plan Coordinator 与旧 TaskService 同时写同一业务状态，CAS 只能保护各自的局部版本，不能保证两个状态机之间的一致性。
- 若旧 orphan recovery 把 Task 标记为 failed，而 Execution RecoverySupervisor 接管同一 Execution，可能产生业务状态和技术执行状态互相矛盾。
- 影子 Manifest 不能被当作 Plan Runtime 已经具备的权威恢复点。

建议：
1. MVP Plan Runtime 使用全新的 Plan Task / TaskAttempt 集合，不复用旧 `tasks` 集合中的 Workflow Runtime Task 身份。
2. 旧 Workflow 路径继续由旧 TaskService 管理，直到专门的迁移阶段。
3. 建立显式 LegacyWorkflowTaskAdapter：只负责把旧 Task 请求映射为 Execution 技术执行；不要让它写 Plan Task 状态。
4. 对同一旧 Task，迁移期间必须明确唯一权威状态源；不能同时让旧 RecoveryService 和新 Coordinator 对同一个状态拥有写权限。
5. 在 E6/E7 等旧路径切换前，继续把旧 Task Recovery 视为旧系统的一部分；不要由新 Work Run Recovery 重复接管。

### F-02 — Execution.task_id 不能直接复用为新 Plan Task ID

**Severity: P0 — 数据关联契约必须先确定**

证据：
- `Execution.task_id` 当前用于关联旧 `app.models.task.Task`。
- Workflow Adapter、CheckpointCoordinator、RecoverySupervisor 和 reconcile 都通过该字段回查旧 `tasks` 集合。
- Execution 还存在 `attempt_no` 和 `retry_of_execution_id`，但它们描述 Execution 技术模型中的重试/尝试元数据，不是产品级 TaskAttempt。

建议：
- 保留现有 `task_id` 的旧语义，不在迁移期悄悄改变其含义。
- 新 Plan Execution 增加显式业务关联字段，例如：
  - `work_run_id`
  - `plan_task_id`
  - `task_attempt_id`
  - `task_revision_id`
- 如果未来统一引用格式，使用带类型的 `business_owner_ref` / `business_context_ref`，而不是让一个无类型 `task_id` 同时指向两个不同集合。
- 创建 Execution 时固定关联 Attempt 与 Revision；恢复时不允许重新推断或覆盖。

### F-03 — ExecutionRepository 不能直接充当 Task State Coordinator Repository

**Severity: P1 — 领域写入边界**

证据：
- `ExecutionRepository.transaction(execution_id, expected_token)` 要求一个有效 Execution Lease Token。
- 每个事务首先在 Execution 主记录上做带 token 和 Lease expiry 条件的写入，再允许追加 Step、Manifest、Tool Invocation 和 Execution Event。
- 这是正确的 Execution fencing 设计，但 Plan Task Runtime State 不属于某个 Worker Lease。

影响：
- Plan Coordinator 的命令可能由 API、恢复 Worker、Verification Consumer 或用户操作触发；这些调用不一定拥有某个 Execution Lease。
- 若强行复用 ExecutionRepository，会把“谁有权改变业务任务状态”错误地等同于“谁持有执行 Worker Lease”。

建议：
- 新增 PlanRepository / PlanUnitOfWork，负责 Plan Domain 自己的事务、CAS、唯一约束、Command Receipt 和 Outbox。
- PlanRepository 不要求 Execution Lease Token；其写入权通过命令授权、聚合 version CAS 和事务约束控制。
- ExecutionRepository 继续是 Execution 技术事实写入的唯一受控通道。
- 两个 Repository 可以共享 Mongo Client / Transaction Helper，但不要共享同一个状态所有权协议。

### F-04 — 现有 ExecutionEvent 不是 Plan Domain Outbox

**Severity: P1 — 事件一致性**

证据：
- ExecutionEvent 以 `execution_id + seq` 为聚合边界，序号在 Execution 主记录中分配。
- Execution Event 写入依赖 ExecutionRepository 的有效 fencing transaction。
- Redis 通知是提交后的 best-effort 提示，消费端从 Mongo 游标补齐。
- 当前没有 Plan Task / Attempt 聚合事件的独立 Outbox / Inbox 模块。

建议：
- Plan Domain 自己维护 Task / Attempt 聚合事件和 Outbox。
- Task 状态、Attempt 状态、关联关系、Command Receipt 和 Outbox 在同一 Plan Domain Mongo 事务内提交。
- 消费 Execution Event 时，以 `execution_id + seq` 或稳定 `event_id` 作为 Inbox 去重依据。
- 不要把 TaskCompleted 写成 ExecutionEvent，也不要让 Plan Event 依赖某个 Worker Lease 才能提交。
- Redis 仍然只做通知，不承担 Plan Event 的事实存储。

### F-05 — Checkpoint 已有基础设施，但尚未完成权威切换

**Severity: P1 — Recovery 迁移前置条件**

证据：
- `CheckpointCoordinator.commit_boundary` 已实现 Graph Checkpoint 先落库、再提交 Manifest + Execution Event 的协议。
- `shadow_commit_workflow_boundary` 明确是 best-effort 影子写入。
- `ensure_workflow_execution` 为旧 Workflow Task 建立 shadow Execution，并使用长期 `workflow-shadow` Lease。
- `reconcile.py` 对比旧 Task.checkpoint 与 Manifest，不能证明新 Manifest 已成为唯一权威恢复源。

建议：
- 新 Plan Task 的恢复事实从一开始就由 Plan Domain 对象 + Execution Domain Manifest / Event 共同提供，不要复用旧 Task.checkpoint。
- 旧 Workflow 的 Manifest 权威切换继续按原 Execution 迁移阶段单独完成。
- 新 Work Run Recovery 只协调业务状态与技术执行状态，不直接读写 LangGraph checkpoint 内容。
- 影子 Lease 仅属于旧双写迁移机制，不应成为新 Plan Execution 的默认 Lease 策略。

### F-06 — Tool Ledger 有正确核心语义，但仍保留 token-less legacy 写路径

**Severity: P1 — Durable 路径必须收口**

证据：
- `MongoToolLedger` 已保存原始 request intent、request digest、idempotency key，并通过 PREPARED → IN_PROGRESS → 终态 / UNKNOWN 的状态流防止普通重放。
- 当 ExecutionIdentity 携带 fencing token 时，prepare / claim / mark 走 ExecutionRepository fenced transaction。
- 没有 token 时仍直接写 Mongo；模块注释将其描述为 E5 legacy / shadow 路径。
- Workflow Adapter 在实际执行期间绑定 ExecutionIdentity。

建议：
- 对新 Plan Execution，Tool Ledger 必须要求有效 ExecutionIdentity 和 fencing token；缺失时 fail closed。
- 旧非 durable / legacy 入口可以在迁移期保留，但应显式标记为兼容路径，不能让新 Plan Execution 静默走 token-less 分支。
- Ledger 的 UNKNOWN 仍由副作用裁决协议处理，不能因 Task Attempt 失败就直接重放。

### F-07 — 人工输入恢复仍绑定旧 Task.variables

**Severity: P1 — Interaction Domain 集成**

证据：
- Workflow Adapter 的 input intent / committed marker 记录在 Execution 文档中，但补偿时会把 variable patch 写回旧 `tasks.variables`。
- `TaskService.update_variables` 使用旧 Task.version CAS，并同步更新旧 checkpoint.variable_snapshot。
- `TaskService.resume_task_execution` 会在 Execution Dispatcher 与旧 Celery 入口之间分流。

建议：
- 新 Plan Runtime 的用户输入、审批和授权请求应绑定 Interaction ID、Task Attempt ID、Task Revision ID 和主体。
- Interaction Response 作为独立业务事实持久化；由 Coordinator 消费结果并恢复 Attempt。
- 不要把新 Plan 的输入状态写入旧 Workflow Task.variables。
- 旧 Human Node 恢复流程继续由 LegacyWorkflowTaskAdapter 管理，直到旧路径迁移完成。

## 4. Important Design Corrections

### 4.1 MVP 不新增 Work Run Lease

**建议：Deferred / 不作为 MVP 前置机制。**

现有 Execution Lease 是每个 Execution 的 Worker 所有权。Plan Domain 的并发写入可先由：
- Task Runtime State 的 version CAS；
- 单活动 Attempt 的数据库唯一约束；
- Plan Version Active Pointer 的 CAS；
- MongoDB 多文档事务；
- Outbox / Inbox 幂等消费；

共同保证。

Work Run 级 Lease 会增加第二类 Lease 的续约、接管、fencing、超时、恢复和运维语义。MVP 的 Plan Coordinator 不是一个必须长期独占 Work Run 的执行 Worker；它可以由多个短事务命令和幂等事件消费者推进。

只有未来出现确实需要 Work Run 级单一串行协调的场景（例如长时间运行的全局计划迁移、跨 Task 原子调度决策），再评估引入协调 Lease。不能为了和 Execution Lease 形式统一而提前引入。

### 4.2 不把一个 Attempt 限制为一个 Execution

一个 TaskAttempt 是业务尝试边界，可以关联多个串行或并行 Execution / Delegation。Execution 的 `retry_of_execution_id` 只表达技术执行重试关系；是否仍属于同一个业务 Attempt，由 `TaskAttemptExecution` 关联记录决定。

### 4.3 Attempt 唯一约束建议使用显式 active 字段

MongoDB partial index 对表达式的支持取决于部署版本。为减少对复杂状态表达式的依赖，建议 Attempt 文档显式维护 `active: true|false`，建立：

```javascript
db.task_attempts.createIndex(
  { task_id: 1 },
  {
    unique: true,
    partialFilterExpression: { active: true }
  }
)
```

Attempt 状态、active 标记、TaskRuntimeState.activeAttemptId 必须在同一事务内维护。启动、终结和恢复都经过 Coordinator。部署版本与索引能力应在实现前通过真实 MongoDB 集成测试确认。

## 5. Recommended Target Architecture

```text
                Planning Service
                       |
                 Plan Commands
                       v
              Task State Coordinator
                       |
               PlanRepository / UoW
          (CAS + transaction + Outbox)
                       |
        +--------------+----------------+
        |              |                |
    Task / Revision  Attempt       Plan Version
        |              |
        |       Attempt-Execution /
        |       Attempt-Delegation
        |              |
        +--------------+----------------+
                       |
                Execution Adapter
                       |
              ExecutionRepository
                       |
       +---------------+----------------+
       |               |                |
   LeaseManager  CheckpointCoordinator  ToolLedger
       |               |                |
       +---------------+----------------+
                       |
              Dispatcher / RecoverySupervisor

      Execution Events ----> Plan Inbox ----> Coordinator
      Verification Events -> Plan Inbox ----> Coordinator
      Interaction Events --> Plan Inbox ----> Coordinator
```

职责边界：
- Planning Service 生成和修改 Plan，不直接写 Task Runtime State。
- Task State Coordinator 维护 Task / Attempt 的业务状态。
- Execution Adapter 创建技术 Execution 并维护 Attempt 关联。
- Execution Domain 管理 Worker、Lease、Step、Checkpoint、Tool Invocation 和技术事件。
- Verification Domain 负责验收结论。
- Work Run Recovery 组合上述权威事实，不重新实现 Execution Recovery。

## 6. Recommended Implementation Sequence

### Phase 0 — Freeze integration contracts

1. 固定 Execution 新旧业务关联字段语义。
2. 固定 Plan Command / Event / Attempt 状态机。
3. 明确旧 Workflow Task 和新 Plan Task 是不同身份、不同集合。
4. 明确哪些旧入口仍由 LegacyWorkflowTaskAdapter 管理。

### Phase 1 — Plan persistence and Coordinator

1. Task Identity / Revision / Runtime State。
2. Plan Version / PlanVersionTask。
3. TaskAttempt + active 唯一约束。
4. PlanRepository、CAS、Command Receipt、Outbox。
5. 真实 MongoDB Replica Set 集成测试。

### Phase 2 — Execution Adapter

1. 新增 PlanExecutionAdapter，不修改旧 WorkflowRuntimeAdapter 的 Task 语义。
2. 创建 Execution 时写入 WorkRun / PlanTask / Attempt / Revision 关联。
3. 建立 TaskAttemptExecution 关联。
4. 消费 ExecutionEvent 并幂等推进 Coordinator。
5. 验证 Worker Recovery 不创建新 TaskAttempt。

### Phase 3 — Completion and Interaction

1. Completion Claim 与 Evidence。
2. Verification Request / Result。
3. Interaction Request / Response。
4. 结果事件经 Inbox 回到 Coordinator。
5. 处理旧 Attempt 回调、重复回调和 Revision 不匹配。

### Phase 4 — Replanning and Work Run Recovery

1. Plan Version 原子激活。
2. Task Revision Migration。
3. 活动 Attempt 安全停止与副作用裁决。
4. Work Run 结构化恢复与对账。
5. 故障注入与恢复演练。

### Phase 5 — Legacy cutover

1. 先选定一种旧 Workflow 执行场景做切换。
2. 双写期间只允许一个权威写入源。
3. 进行状态对账、事件对账和恢复演练。
4. 切换读路径与写路径。
5. 观测稳定后再移除旧 Task.checkpoint / orphan recovery 依赖。

## 7. Required Tests Before Production

| Test group | Required cases |
|---|---|
| Plan Coordinator CAS | 两个 StartAttempt 并发、两个终结命令并发、Replan 与 Completion 竞争 |
| Active Attempt invariant | 同一 Task 并发创建 Attempt；唯一索引拒绝第二个活动 Attempt |
| Transaction atomicity | Attempt、Runtime State、关联表、Command Receipt、Outbox 全部提交或全部回滚 |
| Execution binding | Execution 只能关联存在且 Revision 固定的 Attempt |
| Execution event consumption | 重复、乱序、延迟、缺口补读；Inbox 幂等 |
| Recovery | Execution takeover 后恢复原 Attempt，不创建新 Attempt |
| Side effects | PREPARED、IN_PROGRESS、UNKNOWN、SUCCEEDED 的重启裁决 |
| Verification | 旧 Attempt 的迟到 Passed 不得完成当前 Task |
| Interaction | 重复响应、超时、撤权、响应与取消竞争 |
| Legacy isolation | 旧 TaskRecovery 不得修改新 Plan Task；新 Coordinator 不得写旧 Task 状态 |
| Mongo transactions | 使用真实 Replica Set；FakeDB 只能作为单元测试，不作为事务并发正确性证据 |

## 8. Review Verdict

### Reuse directly
- ExecutionRepository 的事务级 fencing；
- LeaseManager；
- CheckpointCoordinator 的技术 Manifest 协议；
- ExecutionEvent / 游标读取 / Redis best-effort 通知；
- MongoToolLedger 的幂等和 UNKNOWN 语义；
- Dispatcher / RecoverySupervisor；
- ResourceBinding。

### Build new
- WorkRun / PlanVersion / Plan Task Identity / Revision / Runtime State；
- TaskAttempt；
- Task State Coordinator；
- PlanRepository / Outbox / Inbox / Command Receipt；
- Attempt-Execution / Attempt-Delegation 关联；
- Completion Claim / Verification / Interaction 集成；
- Work Run 级结构化恢复协调。

### Must not do
- 不把旧 `app.models.task.Task` 直接改名为 Plan Task；
- 不把旧 `TaskService` 直接扩展成 Task State Coordinator；
- 不把 ExecutionEvent 当成 Plan Domain Event Store；
- 不把 Execution Lease 当成 Task / Work Run 业务锁；
- 不在 Plan Runtime 中继续以旧 `Task.checkpoint` / `Task.status` 为权威事实；
- 不在新 Plan Execution 中允许 token-less Tool Ledger 写路径。

**最终建议：先实现 Plan Domain 的独立持久化与 Coordinator，再通过 PlanExecutionAdapter 连接现有 Execution。旧 Workflow 迁移应作为单独 cutover 项目，不与 Plan MVP 的首次落地绑成一次大规模重构。**

# Architecture Proposal：统一执行对象模型与恢复协议（Issue #64）

> 状态：**修订草案，待评审**
>
> 目标分支：`dev`
>
> 关联 Issues：[#64](https://github.com/ykjonney/meper-agent/issues/64)、[#65](https://github.com/ykjonney/meper-agent/issues/65)、[#66、#67、#68、#70、#71、#72](https://github.com/ykjonney/meper-agent/issues)
>
> 本文定义 Agent、Workflow、Chat 和 Subagent 共用的执行对象模型、状态归属、恢复协议及其与调度、事件、工具副作用、资源生命周期的边界。本文是架构约束，不是要求一次性实现所有组件。

---

## 0. 结论先行（TL;DR）

本提案确定以下架构决策：

1. **Task 与 Execution 分离。** Task 保留为用户可见的业务任务；Execution 表示一次逻辑执行。执行进度、恢复点、事件和资源关联不再由 Task 承载。
2. **区分 Execution、Execution Attempt 和 Worker Lease。** Worker 崩溃后由新 Worker 接管同一个 Execution，不因此创建新的业务 Attempt；业务级整体重试才创建新的 Execution。
3. **引入统一执行对象。** 核心对象为 Execution、Step、Checkpoint Manifest、Execution Event、ToolInvocation、ResourceBinding；Lease 是 Execution 的所有权记录。配置快照通过 `config_snapshot_ref` 关联。
4. **Execution Lease 与 fencing token 统一保护执行写入。** token 归属 Execution，不归属 Task。所有可能改变执行事实的写入都必须校验当前 token。
5. **恢复以 Execution 为协调边界，以 Step/Checkpoint 为精确恢复位置。** “Execution 边界恢复”不意味着从头重跑整个 Execution；已提交 Step 和副作用不得被无条件重复执行。
6. **ToolInvocation 账本显式处理 UNKNOWN。** 本地记录为进行中，不代表外部副作用没有发生。结果不确定时必须核对外部状态、使用稳定幂等键，或进入人工/风险处理，禁止默认盲目重试。
7. **统一 Checkpoint 是恢复 Manifest，不复制 LangGraph State。** 它精确引用 LangGraph checkpoint，并记录 Step 状态水位、配置引用和恢复所需的其他边界信息。
8. **Execution Event 是可靠事件事实源。** 状态变更与事件在同一 MongoDB 事务中提交；Redis Pub/Sub 只做实时通知，不能成为事实源。
9. **ResourceBinding 与资源本身的生命周期分离。** 数据库 Lease 过期不等于旧 Worker 已失去对真实 Sandbox/Browser 的控制能力；Provider 必须逐步支持资源侧 fencing 或撤销。
10. **当前阶段保留 Celery + MongoDB + LangGraph。** Celery 是执行工作投递机制，不是执行状态事实源；通过 Dispatcher 接口保留未来替换调度后端的空间。

核心原则：

- Execution 是逻辑执行的事实源，不是 Worker 运行记录。
- Lease 是执行所有权，不是业务状态。
- Checkpoint 是恢复协调 Manifest，不是第二份运行状态副本。
- ToolInvocation 是外部副作用的事实账本，不能用普通 Step 状态代替。
- ResourceBinding 表达资源关联，不代表资源天然具备 fencing 能力。

---

## 1. 目标与非目标

### 1.1 目标

- 为 workflow、chat、subagent 提供一致的执行身份、状态归属和恢复语义。
- 明确 Task、Execution、Step、Checkpoint、Event、ToolInvocation、Resource 的职责边界。
- 使 Worker 崩溃、Celery 重投递、跨 Worker 接管时能够安全恢复。
- 建立副作用账本，避免恢复时无条件重复执行外部工具。
- 建立统一事件协议，支持 UI Timeline、审计查询、断线重放和后续投影。
- 建立显式资源绑定与租约，避免通过路径或容器命名约定推断资源归属。
- 为 #65/#66/#67/#68/#71 提供共同的实现边界，避免各 Issue 各自发明状态、事件和恢复协议。

### 1.2 非目标

- 不改变用户可见 API 的语义；invoke、stream、workflow run 的外部契约保持兼容。
- 当前阶段不替换 Celery、LangGraph、MongoDB。
- 不在本文中实现 Docker Socket 隔离或 Sandbox Controller（#63）。
- 不在本文中完成 Docker 安全 Profile（#69）。
- 不在本文中完成配置快照的完整存储与治理（#70），但本文定义恢复时必须遵守的配置引用语义。
- 不在本文中实现完整 Agent Team、异步 Subagent 协作（#72）。
- 不承诺任意外部工具都能实现 exactly-once。系统提供账本、幂等键和不确定性裁决协议，但外部副作用的最终语义取决于工具提供方能力。

---

## 2. 现状与问题

以下是本提案所针对的既有架构问题；实现时应以目标分支最新代码复核具体路径和行为，不能将本节视为永久不变的代码事实清单。

| 领域 | 现状问题 | 架构影响 |
|---|---|---|
| Task | Task 同时承载业务状态、timeline、checkpoint、variables 和版本控制 | 业务生命周期与执行生命周期耦合 |
| Workflow | WorkflowEngine 管理内存执行态，并将部分进度写入 Task.checkpoint | 恢复协议依赖 Task 可空字段和隐式约定 |
| LangGraph | Chat 与 Workflow 使用不同 thread_id 约定 | Thread 身份、归属和生命周期缺少统一登记 |
| Chat | Agent 执行可能由 FastAPI 进程内后台任务承载 | 进程退出会丢失运行中的执行任务 |
| Subagent | 子 Agent 同步委派，缺少独立持久化执行身份 | 无法独立查询、恢复和取消 |
| Event / Log | 执行事件与聚合日志、Timeline 的职责交叠 | 无统一可靠事件流和重放协议 |
| Scheduling | 任务抢占、重投递和状态重读缺少统一 Lease/Fencing 协议 | 旧 Worker 可能在接管后迟到写入 |
| Tool | 缺少通用副作用账本 | 工具调用结果不确定时无法安全裁决 |
| Resource | Workspace 路径、容器命名和删除钩子隐含表达资源归属 | 难以可靠续租、接管和回收 |

核心问题不是单纯缺少状态存储，而是**状态的归属、权威来源和跨组件协议没有统一**。系统必须能够回答：

- 这次逻辑执行是谁？
- 当前哪个 Worker 有权推进它？
- 执行到哪个一致性边界？
- 哪些 Step 已经提交？
- 哪些外部副作用已确认，哪些结果不确定？
- 恢复时应该重新挂接还是重建哪些资源？
- 旧 Worker 的迟到写入和资源操作如何被阻止？

---

## 3. 核心对象模型

### 3.1 实体关系

```text
Task (用户可见业务任务)
  └── Execution (一次逻辑执行，稳定 execution_id)
        ├── ExecutionAttempt (业务级整体尝试/重试记录)
        ├── Lease (Worker 所有权，含 fencing_token)
        ├── Step (可观测、可恢复的执行单元)
        │     └── ToolInvocation (外部工具副作用账本)
        ├── CheckpointManifest (跨引擎恢复协调记录)
        ├── ExecutionEvent (append-only 执行事件)
        ├── ResourceBinding (Execution 与资源的关联)
        └── ConfigSnapshotRef (配置版本/快照引用)

Session
  └── Execution (通常每轮用户请求一个 Execution)

Resource
  └── ResourceBinding (一个资源可按策略被多个 Execution 关联)
```

### 3.2 Task

Task 保留为用户可见的业务对象，负责：

- 用户请求、业务目标和展示信息。
- 用户可见的业务状态与权限边界。
- 与 Session、租户、用户的业务关联。
- 业务级并发配额或 Admission Control 的归属（如适用）。

Task 不再作为执行进度的权威存储位置：

- 不再权威保存 Workflow checkpoint。
- 不再权威保存 Step 完成集合。
- 不再权威保存执行事件明细。
- 不再承担 Worker Lease/fencing token。
- Task.version 仍可用于 Task 业务字段的乐观并发控制，但不承担执行所有权语义。

迁移期可保留旧字段用于兼容和对账，最终删除时必须经过读写路径切换与数据迁移。

### 3.3 Execution

Execution 表示一次**逻辑执行**，具有稳定的 `execution_id`。它是 Chat、Workflow、Agent 和 Subagent 共用的执行生命周期边界。

建议字段：

```json
{
  "_id": "execution-id",
  "task_id": "task-id",
  "session_id": "session-id",
  "trigger": "chat",
  "parent_execution_id": null,
  "retry_of_execution_id": null,
  "status": "running",
  "status_version": 7,
  "lease": {
    "owner": "worker-b",
    "lease_id": "lease-id",
    "fencing_token": 12,
    "heartbeat_at": "timestamp",
    "expires_at": "timestamp"
  },
  "graph_threads": [
    {
      "thread_id": "execution-id:chat",
      "namespace": "",
      "purpose": "chat-main"
    }
  ],
  "config_snapshot_ref": "config-snapshot-id",
  "created_at": "timestamp",
  "started_at": "timestamp",
  "completed_at": null
}
```

约束：

- `execution_id` 在该逻辑执行的恢复过程中保持不变。
- Worker 崩溃、Lease 过期、Celery 重投递和跨 Worker 接管，不创建新的 Execution。
- 业务层决定整体重新执行时，创建新的 Execution，通过 `retry_of_execution_id` 关联旧 Execution。
- `parent_execution_id` 表达 Subagent/子执行委派关系。
- LangGraph thread 必须登记到 Execution，不能只依赖散落在调用点的字符串约定。
- Execution 的配置引用在创建时固定；恢复时禁止静默加载最新配置。

### 3.4 ExecutionAttempt 与 Step Attempt

必须区分业务级整体重试与局部执行重试：

- **Execution**：一次逻辑执行。
- **ExecutionAttempt**：该逻辑执行的一次业务级整体尝试。若采用“每次整体重试创建新 Execution”的策略，则 ExecutionAttempt 可先作为 Execution 元数据或关联记录，不强制单独建集合。
- **Step Attempt**：同一 Execution 内某个 Step 的局部重试次数/尝试记录。
- **Worker Lease**：当前 Worker 对 Execution 的临时执行权代次。

Worker 接管不增加业务 Attempt。Step 重试不应默认重建整个 Execution。

### 3.5 Lease 与 Fencing Token

Lease 归属 Execution，不归属 Task。

建议字段：

```json
{
  "owner": "worker-b",
  "lease_id": "lease-002",
  "fencing_token": 12,
  "heartbeat_at": "timestamp",
  "expires_at": "timestamp"
}
```

接管必须通过原子 CAS 完成。示意：

```text
条件：
  execution_id = E1
  lease.fencing_token = 11
  lease.expires_at <= now

更新：
  lease.owner = worker-b
  lease.lease_id = lease-002
  lease.fencing_token = 12
  lease.heartbeat_at = now
  lease.expires_at = now + lease_duration
```

所有会改变执行事实的写入必须携带当前 token 并校验：

- Execution 状态迁移。
- Step 创建、状态更新和完成提交。
- Checkpoint Manifest 提交。
- ToolInvocation 状态更新。
- Execution Event 追加。
- ResourceBinding 的租约和状态更新。

实现可采用统一的受控 Repository/Service 写入接口，避免业务代码绕过 token 校验直接写集合。

需要区分：

- **Execution Lease**：防止同一个 Execution 被多个 Worker 同时推进。
- **Task/Tenant Admission Control**：限制业务并发配额。

二者不是同一机制。Task.version 仍可用于业务数据并发控制。

> 重要限制：MongoDB 中的 fencing 校验只能保护经过该校验的数据库写入。它本身不能阻止旧 Worker 继续操作 Docker 容器、浏览器或外部服务。资源侧 fencing/凭证撤销由 Resource Provider/Controller 能力提供，见 §7。

### 3.6 Step

Step 是可观测、可恢复的执行单元，例如：

- Workflow Node。
- Agent Turn。
- 需要独立跟踪的其他执行阶段。

Step 不应把所有层级都压成无层级的平面列表。建议字段：

```json
{
  "_id": "step-id",
  "execution_id": "execution-id",
  "parent_step_id": null,
  "step_seq": 3,
  "kind": "agent_turn",
  "status": "running",
  "attempt": 1,
  "idempotency_key": "execution-id:step-id",
  "started_at": "timestamp",
  "completed_at": null
}
```

约束：

- `parent_step_id` 表达嵌套执行关系。
- `step_seq` 用于稳定标识/排序，不代表并行执行之间存在串行依赖。
- Step 状态是 Step 进度的权威来源。
- Step Attempt 用于表达局部重试；不得通过无条件重置已完成 Step 来掩盖重试。
- ToolInvocation 作为 Step 内部的副作用账本，不与 Step 状态重复维护同一事实。

建议状态域：

```text
pending -> ready -> running -> succeeded
                           -> failed
                           -> waiting
                           -> cancelled
```

失败后是否重试由 Retry Policy 和 Attempt 记录决定。并行 Step 可以同时处于 running。

### 3.7 Checkpoint Manifest

统一 Checkpoint 定义为**跨执行引擎的恢复 Manifest**，不是 LangGraph State 的复制品，也不是 Step 状态的第二份权威副本。

建议字段：

```json
{
  "_id": "checkpoint-id",
  "execution_id": "execution-id",
  "checkpoint_seq": 8,
  "step_id": "step-id",
  "step_state_watermark": 158,
  "graph_thread_id": "execution-id:chat",
  "graph_checkpoint_ns": "",
  "graph_checkpoint_id": "langgraph-checkpoint-id",
  "fencing_token": 12,
  "config_snapshot_ref": "config-snapshot-id",
  "created_at": "timestamp"
}
```

语义：

- `checkpoint_seq` 在同一 Execution 内单调递增。
- `graph_checkpoint_id` 精确定位 LangGraph checkpoint；仅记录 thread_id 不足以精确恢复。
- `graph_checkpoint_ns` 与 thread_id 一起确定 LangGraph checkpoint 命名空间。
- Step 状态由 Step 记录作为事实源；Manifest 通过一致性水位或状态快照引用定义恢复边界。
- 如果使用 `step_state_watermark`，必须保证相关 Step 状态提交遵守可比较的提交序号规则；否则应使用明确的 Step 状态快照引用，不能假设并行写入自然形成全局水位。
- Manifest 必须关联当时的 fencing token 和配置快照引用。
- 恢复时只允许使用已成功提交且引用可验证的 Manifest。

#### LangGraph Checkpoint 与 Manifest 的提交顺序

采用引用关系，不复制 LangGraph 内部状态。提交顺序：

1. LangGraph Checkpointer 持久化 Graph Checkpoint。
2. 验证该 checkpoint 可读取，并取得精确 checkpoint identity。
3. 在统一事务中提交 Checkpoint Manifest 及相关 Step 状态边界/事件。
4. 只有 Manifest 提交成功后，该恢复点才成为统一协议认可的恢复点。

故障语义：

- Graph Checkpoint 成功、Manifest 失败：允许产生未引用的孤儿 Graph Checkpoint；它不是权威恢复点，可由清理任务回收。
- Manifest 不得先于 Graph Checkpoint 成功提交，否则会出现引用不存在状态的不可恢复窗口。
- Step 完成状态与 Manifest 必须指向同一个一致性边界，禁止出现 Step 已标记 succeeded，但恢复 Manifest 仍指向执行该 Step 之前的 Graph 状态。

### 3.8 ToolInvocation

ToolInvocation 是外部副作用的账本。建议字段：

```json
{
  "_id": "tool-invocation-id",
  "execution_id": "execution-id",
  "step_id": "step-id",
  "tool_call_id": "provider-tool-call-id",
  "tool_name": "tool-name",
  "tool_version": "tool-version",
  "idempotency_key": "execution-id:step-id:tool-call-id",
  "request_digest": "sha256:...",
  "status": "unknown",
  "external_reference": null,
  "result_ref": null,
  "retry_count": 1,
  "started_at": "timestamp",
  "completed_at": null
}
```

建议状态：

```text
prepared -> in_progress -> succeeded
                         -> failed
                         -> unknown
                         -> compensation_pending -> compensated
```

关键语义：

- `prepared`：调用意图已持久化。
- `in_progress`：外部调用已开始或正在进行。
- `succeeded`：外部成功已确认，且结果/结果引用已持久化，可安全回放。
- `failed`：已确认调用失败，且确认没有产生目标副作用。
- `unknown`：无法确认外部副作用是否发生。
- `compensation_pending/compensated`：需要补偿或补偿已完成。

恢复裁决：

1. 已确认 succeeded：校验 tool_call_id、request_digest 和工具版本后回放原结果，不重执行。
2. prepared 且能证明外部调用尚未发出：可按原幂等键执行。
3. in_progress/unknown：优先查询外部系统状态；若工具支持外部幂等键，则使用同一 key 重试/查询。
4. 可补偿操作：补偿动作本身也必须有账本、幂等键和重试语义。
5. 无法查询且无幂等保证：进入人工处理或显式配置的风险策略，不得默认重执行。

**本系统不承诺对任意外部工具提供 exactly-once。** 对不具备幂等、查询或补偿能力的工具，必须明确暴露不确定性。

幂等键必须在同一逻辑调用的恢复过程中保持稳定；不能在重试时重新生成。工具适配器必须声明其幂等能力、幂等键作用范围、有效期和重复请求行为，不能仅凭静态布尔配置推断外部系统具备幂等保证。

LLM 结果回放必须匹配原始 tool_call_id、参数摘要和工具版本，不能把旧调用结果注入新的不同调用。

### 3.9 Execution Event

新增 `execution_events`，作为执行过程的 append-only 事实事件流。

建议字段：

```json
{
  "_id": "event-id",
  "execution_id": "execution-id",
  "seq": 18,
  "event_key": "step:step-id:completed",
  "type": "step.completed",
  "schema_version": 1,
  "producer": "workflow-runtime",
  "correlation_id": "request-id",
  "causation_id": "causing-event-id",
  "occurred_at": "timestamp",
  "recorded_at": "timestamp",
  "payload": {}
}
```

要求：

- 同一 Execution 内 `seq` 原子分配、单调递增。
- `UNIQUE(execution_id, seq)`。
- 对可重试写入提供稳定 event_key 或等效去重机制。
- 状态变更与对应 Event 在同一 MongoDB 事务中提交。
- Event 消费者支持游标重放；Redis Pub/Sub 丢失消息不能导致事实丢失。
- Event schema 必须版本化。
- 业务发生时间与持久化记录时间分开记录。
- Event payload 不应无差别复制敏感凭证、完整 Prompt 或大型工具输出；大型内容使用 Artifact/结果引用。

事件域建议分层：

- `execution_events`：执行、Step、调度、工具调用和资源生命周期事件。
- 业务审计/权限审计可以共享事件基础设施和字段约定，但保留独立语义域、访问控制和保留策略；不能因为“统一事件协议”就混成无边界的单一数据集合。

现有 `Task.timeline` 和 `execution_logs.events` 逐步迁为 Event 投影/兼容视图。聚合耗时、Token、成本等统计可以保留在 Execution Log/Projection 中，不应作为恢复事实源。

TTL、冷热分层和归档策略必须在定义审计/合规保留期限后确定。不能通过 TTL 删除仍需支持恢复、审计或事件重放的事实事件。

### 3.10 Resource 与 ResourceBinding

资源本身和 Execution 对资源的使用关系必须分开建模。

- Resource：Sandbox、Workspace、Browser 等资源本身及其 Provider 生命周期。
- ResourceBinding：Execution 与资源的关联。
- Resource Lease：对资源的临时使用权或独占权。

建议 ResourceBinding 字段：

```json
{
  "_id": "binding-id",
  "execution_id": "execution-id",
  "resource_type": "sandbox",
  "resource_id": "sandbox-id",
  "provider": "docker",
  "provider_resource_id": "container-id",
  "lease_id": "resource-lease-id",
  "fencing_token": 12,
  "lifecycle_state": "attached",
  "recovery_policy": "reattach_or_recreate",
  "lease_expires_at": "timestamp"
}
```

资源类型的差异：

| 资源 | 生命周期特点 | 恢复策略 |
|---|---|---|
| Sandbox | 临时执行环境 | 根据 Provider 能力重新挂接或重建 |
| Workspace | 持久化文件空间 | 通常跨 Worker/Execution 存在，使用权可租约化 |
| Browser | 有状态会话 | Cookie、认证、页面状态需要单独定义持久化/重建策略 |

数据库 Lease 过期不代表旧 Worker 已失去真实资源控制权。Provider/Controller 必须逐步支持：

- 撤销旧 Worker 的资源访问凭证；
- 通过受控代理执行资源操作；
- 校验资源 generation/fencing token；
- 必要时终止旧执行进程或隔离旧容器。

#68 定义资源模型与回收协议；#63/#69 负责 Controller、隔离与 Provider 安全能力。接口必须预留资源侧 fencing，不得把数据库 CAS 误当成完整资源隔离。

Workspace 不应被强制套用与 Sandbox 相同的短租约。资源持久生命周期与 Execution 临时使用权必须分离。

---

## 4. 状态机与生命周期

### 4.1 Execution 状态机

建议业务状态：

```text
created -> queued -> running -> succeeded
                    |   |----> failed
                    |   |----> cancelled
                    |   |----> timed_out
                    |   |----> waiting_input
                    |   |----> expired
                    |
                    +-------> recovering -> running
```

说明：

- Worker Lease 状态与 Execution 业务状态是两个状态机。
- Worker 崩溃或 Lease 过期不自动意味着 Execution failed。
- 接管期间可记录 recovering 状态或通过 Lease/Event 推导；具体持久化方式由实现决定。
- waiting_input 用于审批、Human Input 或显式外部等待。
- 终态 Execution 不允许被普通 Worker 继续推进；如需业务重试，创建新的 Execution 并关联旧 Execution。

### 4.2 Lease 状态机

```text
unowned -> owned -> renewed
             |
             +----> expired -> takeover (new fencing_token)
             |
             +----> released
```

Lease 的获得、续约和接管必须原子化。所有接管必须提升 fencing token。token 不得回退或复用。

### 4.3 Step 状态机

Step 状态与 Execution 状态分离。Execution 进入 recovering 时，不应批量重置 Step。恢复逻辑依据最新有效 Manifest、Step 事实记录和 ToolInvocation 账本裁决后续动作。

---

## 5. 统一恢复协议

恢复以 Execution 为协调边界，但恢复位置由 Checkpoint Manifest、Step 和 ToolInvocation 共同确定。它不是从 Execution 的第一个 Step 重新执行。

### 5.1 恢复流程

```text
1. 发现
   - Worker 心跳超时、Celery 重投递或调度扫描发现 Execution 可接管。

2. 接管
   - 原子 CAS 获取 Execution Lease。
   - fencing_token 单调递增。
   - 接管失败的 Worker 不得继续推进。

3. 定位恢复 Manifest
   - 选择该 Execution 最新的、已成功提交且引用可验证的 Manifest。
   - 校验配置快照引用和 Graph Checkpoint identity。

4. 重建执行视图
   - 查询 Manifest 对应边界的 Step 状态。
   - 查询该边界前后的 ToolInvocation 账本。
   - 查询 ResourceBinding 与 Provider 状态。

5. 副作用裁决
   - succeeded：回放持久化结果。
   - 已确认未发出：可执行。
   - unknown/in_progress：查询外部状态或使用原幂等键；无法安全裁决则人工/风险处理。

6. 资源恢复
   - 对资源续租、重新挂接或重建。
   - Provider 必须确保旧持有者不能继续控制资源；不具备 fencing 能力时按安全策略隔离/终止旧资源。

7. 续跑
   - 使用登记的 thread_id、namespace 和 checkpoint_id 恢复 LangGraph。
   - 从未完成的 Step 或 Step Attempt 继续。
   - 所有写入携带当前 fencing_token。

8. 完成
   - 在事务中提交最终状态与事件。
   - 释放/转移 Lease，并按资源策略释放或保留绑定。
```

### 5.2 Zombie Worker

场景：

```text
Worker A 持有 token=11
Worker B 接管，获得 token=12
Worker A 恢复运行并尝试写入
        |
        v
服务端校验 token=11 已过期
        |
        +--> 拒绝执行事实写入
        +--> 返回明确的 LeaseLost/Fenced 错误
        +--> Worker A 停止当前执行并退出
        +--> 由可信服务端记录拒绝/诊断事件
```

旧 Worker 不得使用旧 token 为自己追加普通执行 Event。拒绝事件应由持有当前有效权限的服务端或独立诊断通道记录。

现有孤儿任务扫描逻辑应逐步迁移到 Execution Lease 扫描。迁移期保留旧扫描与对账，不能提前删除仍承担兼容职责的逻辑。

### 5.3 取消与超时

- 取消是业务请求，必须持久化并发出事件。
- Worker 收到取消后应停止推进 Step，并执行资源清理策略。
- Worker 不在线时，调度器/Controller 应负责最终取消和资源回收。
- 超时应明确是单 Step 超时、Execution 总时限还是资源租约超时，不能共用一个含糊的 timeout 字段。
- 对不可中断的外部工具调用，取消不代表外部副作用已撤销；仍需通过 ToolInvocation 裁决。

---

## 6. MongoDB 一致性、事务和索引约束

### 6.1 部署前提

生产环境 MongoDB 必须运行在支持多文档事务的 Replica Set 或 Sharded Cluster 部署形态。普通 standalone MongoDB 不满足多文档事务前提。

需要原子一致的状态变更、事件追加和账本写入必须通过统一事务边界完成。所有参与集合必须使用同一事务 session。

### 6.2 事务边界

典型事务包括：

- Execution 状态迁移 + 对应 Execution Event。
- Step 状态提交 + 对应 Execution Event。
- ToolInvocation 状态提交 + 对应 Execution Event。
- Checkpoint Manifest 提交 + 对应 Step 边界元数据/Event。
- ResourceBinding 状态变更 + 对应 Event。

LangGraph Checkpointer 的 Graph Checkpoint 写入与 Manifest 不一定能处于同一事务，因此按 §3.7 的先 Graph Checkpoint、后 Manifest 顺序提交，并允许产生可清理的孤儿 Graph Checkpoint。

事务提交结果不确定时，调用方必须通过稳定的业务键/事件键查询最终结果，不能简单重复追加。

### 6.3 事件序号与幂等写入

- `seq` 必须由原子操作分配，不允许“读取 max(seq)+1 后插入”的非原子实现。
- 建立 `UNIQUE(execution_id, seq)`。
- 对可重试事件写入建立稳定 `event_key` 去重约束。
- 事务重试必须复用相同业务操作标识。
- Event 消费者采用至少一次投递时，消费者必须具备幂等处理能力。

### 6.4 建议索引

具体索引应根据实际查询模式和数据量压测后确定，初始建议：

| 集合 | 索引 |
|---|---|
| executions | `(task_id, created_at)` |
| executions | `(status, lease.expires_at)` |
| executions | `(parent_execution_id, created_at)` |
| steps | `(execution_id, step_seq)` |
| steps | `(execution_id, status)` |
| checkpoints | `UNIQUE(execution_id, checkpoint_seq)` |
| execution_events | `UNIQUE(execution_id, seq)` |
| execution_events | `UNIQUE(execution_id, event_key)`（event_key 非空时） |
| tool_invocations | `UNIQUE(execution_id, idempotency_key)` |
| tool_invocations | `(execution_id, status)` |
| resource_bindings | `(execution_id, lifecycle_state)` |
| resource_bindings | `(resource_type, resource_id, lease_expires_at)` |

不要仅凭上述建议直接创建所有索引；需核实 MongoDB 对稀疏/部分唯一索引的具体需求，并验证现有数据无冲突。

---

## 7. 与关联 Issue 的实现边界

| Issue | 本提案划定的边界 |
|---|---|
| #64 | 本文：对象模型、状态归属、恢复 Manifest、跨组件恢复协议 |
| #65 | Execution Lease、Heartbeat、Fencing CAS、调度接管；不建立独立调度框架 |
| #66 | Chat 执行纳入 Execution 生命周期；SSE 订阅事件，不由 FastAPI 进程拥有执行生命周期 |
| #67 | Event 事实源、事务写入、Outbox/投递和游标重放；Redis 只做通知 |
| #68 | Resource、ResourceBinding、资源 Lease 与过期回收协议 |
| #69 | Docker/Sandbox 安全 Profile、隔离和资源侧安全能力 |
| #70 | 配置快照的完整内容、存储、版本治理；#64 规定恢复必须固定配置引用 |
| #71 | ToolInvocation 账本、稳定幂等键、UNKNOWN 裁决、补偿记录 |
| #72 | Child Execution、parent_execution_id、独立状态和恢复；异步 Agent Team 协作后续演进 |
| #63 | Sandbox Controller、Docker Socket 隔离与资源控制面 |

### 7.1 Dispatcher 抽象

当前阶段继续使用 Celery，但 Execution Orchestrator 不应直接把 Celery Task ID 当作执行身份或事实源。

建议依赖：

```text
Execution Orchestrator
        |
        v
Execution Dispatcher Interface
        |
        +---- Celery Dispatcher (current)
        |
        +---- Future Durable Backend (optional)
```

Celery 负责投递执行工作；Execution、Lease、Step、Checkpoint 和 Event 由统一模型持久化。调度投递应具备可重试和去重能力，不能依赖“数据库写成功后紧接着发 Celery 消息”这一非原子序列。

### 7.2 Chat 与 Session

建议采用“每轮用户请求一个 Execution”：

```text
Session
  ├── conversation history / memory
  ├── Execution E1 (turn 1)
  ├── Execution E2 (turn 2)
  └── Execution E3 (turn 3)
```

Session 负责对话上下文，Execution 负责单轮运行状态。LangGraph thread 归 Execution，不再直接以 session_id 作为唯一 thread 身份。

必须定义同一 Session 的并发策略：例如 Session 级 turn sequence 或串行化提交，避免两轮并发执行基于相同旧上下文并产生顺序不确定的消息历史。

### 7.3 不引入 Temporal 等 Durable Runtime

当前阶段不引入 Temporal 等新 Durable Runtime 框架。理由是应先建立统一执行模型和副作用协议，避免同时维护多套权威状态。

但该决策不是永久禁止替换底层调度/执行后端。通过 Dispatcher 接口隔离 Celery，未来可根据恢复复杂度、调度规模、可观测性和运维成本重新评估。

---

## 8. 分阶段实施路线

### P1：模型与持久化地基

范围：

- 定义 Execution、Lease、Step、Checkpoint Manifest、Event、ToolInvocation、ResourceBinding 的 Schema。
- 定义状态机、唯一索引、事务边界和迁移规则。
- 建立统一 Execution Service/Repository 写入入口。
- 实现 Execution Lease/Fencing CAS 原语。
- Workflow 侧可先做受控双写，但必须指定唯一权威写入入口。

验收：

- 新旧状态对账脚本可识别差异。
- 不存在两个有效 Lease。
- 旧 token 无法写入所有执行事实集合。
- 同一业务操作重试不会重复创建 Step/Event/ToolInvocation。
- 生产 MongoDB 部署满足事务前提。
- 明确双写冲突裁决和回滚方案。

**双写约束：** 双写不是两个模型都可以被不同代码路径自由修改。迁移期由单一服务负责写入；必须明确哪个模型是权威源、如何对账、何时切换读路径、如何回滚。禁止旧写路径覆盖新模型已经确认的状态。

### P2：事件协议收敛

范围：

- Execution Event 原子序号、去重和事务提交。
- Task Timeline 与 execution_logs.events 迁移为事件投影/兼容视图。
- Redis Pub/Sub 降级为通知通道。
- 增加 Event Cursor 重放能力。
- 定义 Event schema 版本和保留/归档策略。

验收：

- 状态更新与 Event 原子提交。
- 重复提交不产生重复事件。
- Redis 消息丢失后可从 Cursor 补齐。
- Timeline 投影可重建。
- 审计事件与执行事件的权限、保留策略清晰。

### P3：恢复协议切换

范围：

- Workflow 从 Checkpoint Manifest/Step 事实源恢复。
- Chat 纳入 Execution，SSE 仅订阅 Execution Event。
- LangGraph thread/checkpoint identity 显式登记。
- ToolInvocation 接入工具执行链。
- 建立恢复裁决与故障注入测试。

验收：

- Worker A 崩溃后 Worker B 可接管同一 Execution。
- A 的迟到写入全部被 fencing 拒绝。
- 已确认成功的工具调用恢复时回放结果，不重复执行。
- UNKNOWN 调用进入外部核对/幂等重试/人工处理路径。
- LangGraph Checkpoint 与 Manifest 不一致时不会恢复到不存在的状态。
- 配置更新后旧 Execution 恢复仍使用固定配置引用。
- Chat 进程重启后 Execution 可查询、可恢复。

### P4：资源与 Subagent

范围：

- Resource 与 ResourceBinding 建模。
- Lease 过期扫描、续约、重挂接、重建和孤儿资源回收。
- Provider 逐步接入资源侧 fencing/撤销能力。
- Subagent 升级为 Child Execution。

验收：

- 资源归属不依赖路径或容器命名推断。
- 旧 Worker 不能在接管后继续控制受保护资源；不支持 fencing 的 Provider 必须执行隔离/终止策略。
- Workspace 与 Sandbox 生命周期可独立管理。
- Parent Execution 能识别 Child Execution 的状态并按策略取消/等待/恢复。

每个阶段都应有可回滚的数据迁移和兼容窗口；“可停在任意阶段”必须以权威数据源、读写路径和回滚步骤明确为前提，不能仅靠保留旧字段保证。

---

## 9. 故障注入与端到端验收矩阵

| 故障点 | 预期结果 |
|---|---|
| Execution 创建后、Celery 投递前崩溃 | Outbox/调度扫描能够重新投递，不丢任务 |
| Worker 领取后、Step 启动前崩溃 | 新 Worker 能接管同一 Execution |
| Step 执行中崩溃 | 从最后有效 Manifest 恢复 |
| 外部工具成功、本地结果保存前崩溃 | ToolInvocation 进入 UNKNOWN 或等价可判定状态，不盲目重复副作用 |
| Graph Checkpoint 成功、Manifest 失败 | 不使用未提交 Manifest；孤儿 Graph Checkpoint 可清理 |
| Manifest 成功后 Worker 崩溃 | 新 Worker 精确恢复对应 Graph Checkpoint |
| Worker A 失去 Lease 后迟到写入 | 所有旧 token 执行事实写入被拒绝 |
| Redis Pub/Sub 消息丢失 | Event Cursor 可补齐 |
| Resource Lease 过期 | 旧 Worker 不能继续控制受保护资源；否则隔离/终止资源 |
| 配置在执行中更新 | 旧 Execution 恢复仍使用原配置快照/不可变版本 |
| 同一 Session 两轮并发 | 按明确的 turn ordering 策略提交，不发生上下文乱序 |

---

## 10. 开放问题与后续决策

以下问题不阻塞核心模型，但需要在各 Issue 的实现设计中给出明确答案：

1. **Step 水位实现：** 采用单调提交序号、Step 状态快照还是二者结合，需要基于并行 Workflow 的查询与恢复成本选择。
2. **Event 保留策略：** 根据审计要求、恢复窗口和成本确定冷热分层；不能先加 TTL 再补保留语义。
3. **资源侧 fencing：** 不同 Provider 的撤销能力不同，需要声明能力矩阵和不支持时的安全降级策略。
4. **Session 并发：** 同一 Session 的 turn 是否串行执行，以及并发请求的上下文提交规则。
5. **ExecutionAttempt 物理建模：** 初期可作为 Execution 元数据/关联记录；当需要独立审计、调度或统计时再拆集合，但概念必须保持区分。

---

## 11. 决策摘要

| 决策 | 结论 |
|---|---|
| Task 与 Execution 是否分离 | 是 |
| Worker 接管是否创建新 Execution | 否 |
| 业务整体重试是否创建新 Execution | 是 |
| Fencing Token 归属 | Execution Lease |
| Fencing 是否覆盖执行事实写入 | 是 |
| Checkpoint 是否复制 LangGraph State | 否，使用恢复 Manifest 引用 |
| ToolInvocation 是否需要 UNKNOWN | 是 |
| 是否承诺任意工具 exactly-once | 否 |
| Event 是否为执行事实源 | 是 |
| Redis Pub/Sub 是否为事实源 | 否 |
| ResourceBinding 是否等同资源生命周期 | 否 |
| 当前是否引入 Temporal | 否，保留 Dispatcher 抽象 |
| Chat Execution 与 Session 的关系 | 每轮请求一个 Execution |

## 12. 验收标准（Issue #64）

- [ ] Execution、Step、Checkpoint Manifest、Execution Event、ToolInvocation、ResourceBinding 有唯一的存储与归属定义。
- [ ] Task 不再作为执行进度、Lease 和恢复状态的权威存储位置。
- [ ] Execution、业务级重试和 Worker Lease 三种概念明确区分。
- [ ] Fencing Token 归属 Execution，所有执行事实写入均校验当前 token。
- [ ] 一次崩溃恢复的全链路（接管 → 定位 Manifest → 副作用裁决 → 资源恢复 → 续跑）有端到端测试。
- [ ] Worker A 崩溃后 Worker B 能以更高 token 接管同一 Execution，A 的迟到写入被拒绝。
- [ ] ToolInvocation 能区分已确认成功、已确认失败和结果不确定；不确定调用不会被默认盲目重执行。
- [ ] LangGraph Checkpoint 与统一 Manifest 的提交顺序和一致性边界有测试。
- [ ] Event 支持原子序号、幂等追加、事务提交和 Cursor 重放。
- [ ] Resource Lease 过期后的旧持有者隔离策略明确。
- [ ] #65/#66/#67/#68/#71 的实现 PR 能引用本文对应章节作为边界依据。

---

**评审建议：** 本文作为 #64 的统一架构基线。完成对象模型、Fencing、ToolInvocation UNKNOWN、Checkpoint Manifest 一致性和 MongoDB 事务约束的评审后，再启动 #65/#67/#71 的核心实现；各 Issue 不应自行改变本文定义的执行身份、状态归属和恢复语义。

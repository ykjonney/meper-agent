# 执行域架构设计（Implementation Architecture）

> 依据：`docs/EXECUTION-MODEL-PROPOSAL.md`（#64 修订草案）。
> 本文将提案的对象模型与协议**落位到本代码库**：模块划分、代码落位、组件交互、现有接缝改造点、PR 切分。
> 提案是"什么与为什么"，本文是"在哪里与怎么做"。冲突时以提案为准。

---

## 1. 总体架构

```text
┌─ API 层 (app/api/v1) ─────────── 不感知执行域内部，只调 ExecutionService ─┐
│                                                                          │
│  app/services/                       app/engine/                          │
│  ┌──────────────────────┐           ┌───────────────────────────────┐    │
│  │ ExecutionService     │──────────>│ WorkflowRuntimeAdapter         │    │
│  │ (编排入口/查询投影)    │           │  (改造 engine.py+node_executor)│    │
│  │ TaskService(瘦身)     │           │ ChatRuntimeAdapter             │    │
│  └──────┬───────────────┘           │  (改造 agent_execution_service) │    │
│         │                           │ SubagentAdapter(harness 侧)    │    │
│         v                           └───────────┬───────────────────┘    │
│  app/engine/execution/  ◄── 全部执行事实写入的唯一通道                      │
│  ┌─────────────────────────────────────────────────────────────────┐     │
│  │ ExecutionRepository   ← 所有写入携带 fencing_token 过滤            │     │
│  │ LeaseManager          ← CAS 接管 / 心跳 / 释放                     │     │
│  │ EventWriter           ← 事务内原子 seq 分配 + append + 投影通知      │     │
│  │ CheckpointCoordinator ← LangGraph先落库→验证→Manifest 事务提交      │     │
│  │ ToolLedger(Mongo实现)  ← 注入 harness 的 SideEffectLedger 协议      │     │
│  │ ResourceManager       ← ResourceBinding 租约/回收                  │     │
│  │ RecoverySupervisor    ← 过期 Lease 扫描 + 重投递（并入 workers）    │     │
│  └─────────────────────────────────────────────────────────────────┘     │
│         │                                  │                              │
│         v                                  v                              │
│  Dispatcher 接口 ──> CeleryDispatcher      harness (包内协议,不 import app) │
└──────────────────────────────────────────────────────────────────────────┘
```

三条铁律（对应提案 §3.5/§3.9/§0）：

1. **执行事实写入只经 `ExecutionRepository`**——它是唯一带 fencing token 过滤的写入通道，业务代码直接 `update_many` 执行集合视为违规（lint/review 检查项）。
2. **状态变更 + 事件同事务**——EventWriter 的 `emit` 不单独存在，只作为 Repository 事务的组成部分。
3. **harness 不感知 Mongo**——SideEffectLedger / CheckpointManifest 以协议（Protocol）形式定义在 harness，Mongo 实现由 app 侧注入，维持"harness 可独立发布、不 import app.*"的既有边界。

---

## 2. 代码落位

### 2.1 新增：`backend/app/engine/execution/`（执行域核心包）

```text
app/engine/execution/
├── __init__.py          # 对外只暴露 ExecutionService 级入口
├── models.py            # Execution/Step/CheckpointManifest/ExecutionEvent/
│                        # ToolInvocation/ResourceBinding 的 pydantic 模型
│                        # （提案 §3 的 JSON Schema 直译，含状态机枚举）
├── collections.py       # 集合名常量 + ensure_indexes()（提案 §6.4 索引）
├── repository.py        # ExecutionRepository：唯一受控写入通道
├── lease.py             # LeaseManager：acquire/renew/takeover/release（CAS）
├── events.py            # EventWriter：seq 原子分配 + 事务追加 + 通知钩子
├── checkpoint.py        # CheckpointCoordinator：两阶段提交协议封装
├── recovery.py          # RecoverySupervisor：扫描 + 接管 + 恢复流程编排
├── dispatcher.py        # Dispatcher Protocol + CeleryDispatcher 实现
└── resource.py          # ResourceManager：binding 登记 / 租约 / 回收策略
```

依赖方向：`repository.py` 是最底层（只依赖 motor + models）；`lease/events/checkpoint` 组合 repository 提供原语；`recovery` 是最高层编排。**不新增独立 service 层 duplication**——`app/services/execution_service.py` 只做 API 编排（鉴权、查询投影、触发），执行事实操作全部下沉到本包。

### 2.2 harness 侧新增（协议，无实现）

```text
packages/harness/src/agent_flow_harness/
├── ledger.py            # SideEffectLedger Protocol：
│                        #   prepare(invocation) / mark(invocation_id, status, result_ref)
│                        #   lookup(idempotency_key) -> Invocation | None
├── execution_context.py # ExecutionIdentity（execution_id/step_id/token）contextvar，
│                        #   与现有 sandbox workspace contextvar 同模式
└── (改造) tools/…       # 工具执行链在调用外部副作用前后走 ledger 钩子
```

app 侧 `ToolLedger`（engine/execution 内）实现该 Protocol 并在 harness_integration 装配时注入——与现有 `configure_checkpointer` 单例注入同模式（`app/core/` 增 `execution_runtime.py` 装配点，lifespan 与 `worker_process_init` 各自初始化，兼顾 #62 的 fail-closed 要求：**生产模式装配失败即拒绝启动**）。

### 2.3 现有代码改造点（接缝清单）

| 现有位置 | 改造 | 阶段 |
|---|---|---|
| `app/models/task.py` | `Checkpoint`/`timeline`/`variables` 标记 deprecated（保留读兼容），`version` 语义收窄为业务字段乐观锁 | P1 |
| `app/engine/workflow/engine.py` | `_save_*_checkpoint` 系列改走 `CheckpointCoordinator`（P1 双写：旧 Task.checkpoint 照旧 + 新 Manifest）；`run_and_persist` 恢复入口改读 Manifest（P3 切换） | P1→P3 |
| `app/engine/workflow/node_executor.py:794` | thread_id 生成从 `{task_id}_{node_id}` 改为经 `ExecutionIdentity` 登记（`graph_threads` 显式记录），恢复仍走 `Command(resume)`（机制不变，身份来源变） | P3 |
| `app/services/agent_execution_service.py` | `invoke/stream/resume` 每轮创建 Execution（trigger=chat）；`asyncio.create_task` 保留为**本进程 Worker**（也持 Lease、也写事实——FastAPI 进程即一个 worker，崩溃后由 RecoverySupervisor 重投递到 Celery 接管，实现 #66 的"进程重启可恢复"）；SSE 改为订阅 ExecutionEvent 游标 | P3 |
| `app/services/session_service.py:242` | chat thread_id 从 `session_id` 改为 Execution 登记的 thread；删会话清理逻辑改为按 Execution 查 thread | P3 |
| `harness subagents/delegate.py` | 委派时创建 Child Execution（parent_execution_id），先仍同步执行但状态可查询；异步化留给 #72 | P4 |
| `app/workers/tasks/running_task_scan.py` | 孤儿 RUNNING 扫描迁移为 **Lease 过期扫描**（RecoverySupervisor 的 beat 任务），旧扫描保留对账一个阶段后删除 | P3 |
| `app/workers/tasks/maintenance.py` | `cleanup_orphan_sandboxes`/闲置容器回收改按 ResourceBinding.lease_expires_at 扫描；workspace 路径约定保留（Resource 本身），**归属判断**改读 binding | P4 |
| `app/workers/tasks/checkpoint_prune.py` | 保留（作用于 LangGraph 集合），新增 Manifest 的对应保留策略（同口径：每 Execution 保最新 N + 终态保留期） | P3 |
| `app/workers/celery_app.py` | beat 增 `execution_lease_scan`（30s，对齐现 human_timeout 节奏）；`acks_late`/`visibility_timeout` 语义不变——重投递由 fencing 兜底而非删除 | P1 |

---

## 3. 组件设计

### 3.1 ExecutionRepository —— fencing 的执行面

所有写方法签名统一为 `(execution_id, expected_token, ...)`，Mongo 更新条件恒含：

```python
{"_id": execution_id, "lease.fencing_token": expected_token}
```

匹配失败 → 抛 `LeaseLostError`（提案 §5.2：调用方必须停止推进并退出，由服务端记录 fenced 诊断事件——诊断事件由 Repository 自身在无 token 校验的独立通道写入 `execution_events`，producer 标 `system`）。

事务封装：`async with repo.transaction(execution_id, token) as tx`——session 内可组合「状态迁移 + Step 提交 + Event 追加」任意成组操作，对应提案 §6.2 的事务边界清单。**Mongo 事务前提（Replica Set）进入部署检查**，standalone 环境启动时打 WARN 并标记 execution 域 degraded（联动 #62 的健康暴露，`/health` 增 execution 域字段）。

### 3.2 LeaseManager

```python
acquire(execution_id, owner)      # created/queued → running 时首次获取
heartbeat(execution_id, token)    # 续约；失败即 LeaseLost
takeover(execution_id)            # CAS：expires_at <= now 时以 token+1 抢占
release(execution_id, token)      # 正常完成释放
```

租约时长取 `max(celery visibility_timeout 的 1/4, 任务最小心跳间隔×3)` 初始为 **45min/5min 心跳**（现 visibility_timeout=3h，重投递窗口内新 Worker 不得接管，故 lease 必须 > visibility_timeout？——**修正：lease_duration = 4h > 3h 重投递窗口**，确保 Celery 自身重投递先于 Lease 过期发生，接管者只会是 RecoverySupervisor 或重投递任务本身，避免与 Celery 机制竞争。此参数是本设计的关键调参点，评审重点）。

### 3.3 EventWriter —— seq 分配与通知

seq 分配不采用"max+1"（提案 §6.3 禁止），采用 **execution 文档内嵌计数器原子自增**：

```python
# 同一事务内：
inc = await execs.find_one_and_update(
    {"_id": eid}, {"$inc": {"event_seq_counter": 1}}, session=session)
await events.insert_one({... "seq": inc["event_seq_counter"], ...}, session=session)
```

`UNIQUE(execution_id, seq)` 兜底并发缺陷；可重试写入带稳定 `event_key`（稀疏唯一索引）。事务提交后经注入的 `Notifier` 协议发 Redis Pub/Sub（**仅通知，丢弃无损**）；SSE/游标消费一律读 `execution_events`（`find({execution_id, seq: {$gt: cursor}}).sort(seq)`）。

投影迁移（P2）：`Task.timeline` 改为 events 的物化投影——`timeline_projector` 订阅通知批量刷新；`execution_logs` 保留聚合职责（耗时/token），`events` 内嵌明细停写、改读 events。

### 3.4 CheckpointCoordinator —— 两阶段提交

严格实现提案 §3.7 顺序：

```python
async def commit(execution_id, token, step_boundary, thread_id, ns):
    cp_id = await langgraph_aseave(...)            # ① Graph Checkpoint 落库
    verify = await langgraph_aget_tuple(...)        # ② 读回验证取得精确 identity
    if verify is None: raise CheckpointVerifyError  #    不产 Manifest（允许孤儿）
    async with repo.transaction(...) as tx:         # ③ Manifest+Step 边界+Event 同事务
        ...
```

现有 `engine.py` 的四处 checkpoint 写点（progress/cancel/pause-resume/complete-clear）全部收敛到本方法；「完成时清 checkpoint 防误 resume」（engine.py:414）语义变为「终态 Manifest + Execution 终态同事务」，不再依赖字段删除作为信号。

### 3.5 ToolLedger —— harness 协议 + Mongo 实现

工具执行链织入点选 **harness 的工具分发层**（不是每个工具内部）：

```python
# ledger.py (harness)
class SideEffectLedger(Protocol):
    async def prepare(self, inv: ToolInvocationDraft) -> ToolInvocation: ...
    async def mark(self, invocation_id: str, status: LedgerStatus,
                   *, result_ref: str | None, error: str | None) -> None: ...
    async def lookup(self, idempotency_key: str) -> ToolInvocation | None: ...
```

执行协议：分发前 `prepare`（status=prepared）→ 发起外部调用前 `mark(in_progress)` → 终态 succeeded/failed/unknown。**崩溃窗口即账本状态**：恢复时 `lookup(idempotency_key)` 命中 succeeded → 直接回放 `result_ref`；命中 prepared → 按原 key 执行；命中 in_progress/unknown → 走裁决（查询外部/幂等键/人工），由工具元数据声明能力（现有 `tools` 模型的能力声明字段扩展：`idempotency_capability: none|key|queryable|compensable`），无能力且不可查询 → 执行挂 waiting_input 转人工，**绝不默认重执行**（提案 §3.8）。

回放校验：`tool_call_id + request_digest + tool_version` 三匹配才注入，不匹配视为新调用。

### 3.6 RecoverySupervisor

beat 任务（30s）：`find({status: running/queued, lease.expires_at < now})` → 逐个 `takeover` → 经 Dispatcher 重投递。接管成功本身是一个 Event（`execution.takeover`），供诊断与 UI。与 Celery `acks_late` 重投递的关系：两者都可能到达，靠 acquire/takeover CAS 互斥，输家收 `LeaseLostError` 退出——**不删除现有 zombie guard（engine.py:360 重读 status），它降级为防御性断言**。

### 3.7 Dispatcher

```python
class Dispatcher(Protocol):
    async def dispatch(self, execution_id: str) -> None: ...   # 幂等
```

Celery 实现包装 `run_workflow_task` 语义；投递丢失由 RecoverySupervisor 扫描兜底（覆盖提案 §9 第一行故障矩阵）。**不引入 outbox 集合**——"创建 Execution（事务）+ dispatch（可能失败）"的非原子缺口由扫描兜底闭合，等价 outbox 语义而不新增存储（评审点：若后续要求投递延迟更严格，再引入 dispatch_outbox，接口已预留）。

---

## 4. 关键时序

**Chat 单轮（P3 后）**

```text
POST /agents/{id}/stream
  → ExecutionService: 创建 Execution(trigger=chat, thread 登记进 graph_threads)
  → 本进程 Worker 角色: LeaseManager.acquire → 跑 harness 图
      (工具调用经 ToolLedger; CheckpointCoordinator 周期提交)
  → SSE: 订阅 execution_events 游标推流
  [进程崩溃]
  → RecoverySupervisor: lease 过期 → takeover(token+1) → dispatch
  → Celery Worker: 定位 Manifest → 副作用裁决 → Command(resume) 续跑
  → SSE 重连从游标续读（断线重放天然支持）
```

**Workflow 恢复**：同上，只是 Step 集合 = 未完成 nodes，恢复点 = 最新 Manifest + Step 状态（替代现 `resume_from_checkpoint` 的数据来源，控制流逻辑本身改动很小）。

---

## 5. PR 切分（映射提案 P1–P4）

| PR | 内容 | 依赖 |
|---|---|---|
| E1 | models+collections+repository+lease（含索引、LeaseLostError、health 字段） | #62 |
| E2 | EventWriter + Notifier + 事件读取游标 API | E1 |
| E3 | CheckpointCoordinator + workflow 双写（旧路径仍权威）+ 对账脚本 | E2 |
| E4 | Dispatcher + RecoverySupervisor + beat（接管/重投递/ fenced 诊断） | E1 |
| E5 | timeline/events 投影迁移（P2，删 execution_logs.events 写路径） | E2,E3 |
| E6 | workflow 恢复切读 Manifest（P3 前半，删 Task.checkpoint 读路径） | E3,E4 |
| E7 | harness ledger 协议 + ToolLedger 接入工具链（#71 核心） | E1 |
| E8 | chat 纳入 Execution + SSE 游标（#66 核心） | E2,E4,E6 |
| E9 | ResourceManager + maintenance 迁移（#68） | E1 |
| E10 | Subagent Child Execution（#72 一期） | E6,E8 |

E1–E4 纯叠加无行为变化；E5 起每个 PR 带回滚开关（config 读路径选择）与数据迁移脚本。

---

## 6. 与提案开放问题（§10）的落地回答

1. **Step 水位**：采用「Step 状态快照引用」——Manifest 内嵌 `committed_step_ids` 列表（非序号水位），避免并行提交下水位不可比问题；Step 集合仍是事实源，Manifest 快照仅为恢复定位用。
2. **Event 保留**：`execution_events` 与 `execution_logs` 同 TTL（365d）起步，恢复窗口只依赖 Manifest/账本（永久保留至 Execution 终态+N 天），事件 TTL 不影响恢复能力。
3. **资源侧 fencing**：Docker Provider 一期仅支持「接管时对旧容器执行 remove」（利用容器名绑定校验），能力矩阵在 ResourceManager 内声明，无能力 → 安全策略 = 终止重建。
4. **Session 并发**：一期采用 Session 级串行（同 Session 新 Execution 创建时若有 running 前驱 → 排队，复用现有 FIFO `_schedule_next_pending` 思路），并发策略后续放开。
5. **ExecutionAttempt**：按提案 §3.4 采用 Execution 元数据（`attempt_no` 字段），不建集合。

---

## 7. 风险与回滚

| 风险 | 缓解 |
|---|---|
| Mongo 事务在现有部署不可用（standalone） | E1 即引入部署检查 + degraded 标记（#62 同口径 fail-closed） |
| lease_duration 与 visibility_timeout 参数错配导致双跑窗口 | 参数成对配置 + 单测断言 `lease > visibility_timeout`；fencing 是最后防线 |
| 双写期新旧状态漂移 | E3 对账脚本进 CI（nightly 对比 Task.checkpoint vs Manifest） |
| chat 进程内 Worker 与 Celery Worker 行为不一致 | 两者共用同一 RuntimeAdapter 接口，进程内只是"本地 Dispatcher"特例 |
| 事件写放大 | seq 计数器在 execution 文档上（热点可控）；events 按需裁剪 payload（提案 §3.9 引用化） |

每个 E* PR 的回滚 = config 切回旧读路径 + 新集合只停写不删（保留对账与再切换能力）。

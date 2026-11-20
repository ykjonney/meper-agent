# 执行域架构设计（Implementation Architecture）— v2

> 依据：`docs/EXECUTION-MODEL-PROPOSAL.md`（#64 修订草案）+ 2026-11-20 架构审查意见（#64 comment）。
> 本文将提案的对象模型与协议**落位到本代码库**：模块划分、代码落位、组件交互、现有接缝改造点、PR 切分。
> 提案是"什么与为什么"，本文是"在哪里与怎么做"。冲突时以提案与审查意见为准。
>
> v2 变更（相对 v1，均来自审查）：
> ① 事务前提改 fail-closed，新增 E0 阶段（Mongo 单节点 RS + 事务能力检测）；
> ② fencing 升级为**事务级写冲突**（执行事实事务先碰 Execution 主记录）；
> ③ Lease 与 Celery visibility_timeout 解耦（短租约参数）；
> ④ 新增持久化 dispatch_state，扫描协议分三类；
> ⑤ Chat resume 复用原 Execution（区分四种执行场景）；
> ⑥ Docker Provider 一期如实声明**无资源侧 fencing**；
> ⑦ EventWriter 修正 ReturnDocument.AFTER 与 partial unique index；
> ⑧ 实施顺序采纳 E0–E9。

---

## 1. 总体架构

```text
┌─ API 层 (app/api/v1) ─────────── 不感知执行域内部，只调 ExecutionService ─┐
│                                                                          │
│  app/services/                       app/engine/                          │
│  ┌──────────────────────┐           ┌───────────────────────────────┐    │
│  │ ExecutionService     │──────────>│ WorkflowRuntimeAdapter         │    │
│  │ (编排入口/查询投影)    │           │ ChatRuntimeAdapter   (独立切换) │    │
│  │ TaskService(瘦身)     │           │ SubagentAdapter(harness 侧)    │    │
│  └──────┬───────────────┘           └───────────┬───────────────────┘    │
│         v                                       v                        │
│  app/engine/execution/  ◄── 全部执行事实写入的唯一通道                      │
│  ┌─────────────────────────────────────────────────────────────────┐     │
│  │ ExecutionRepository   ← 事务级 fencing：每个写事务先碰主记录        │     │
│  │ LeaseManager          ← CAS 接管 / 心跳 / 释放（与 Celery 解耦）    │     │
│  │ EventWriter           ← 事务内原子 seq + append + 通知钩子          │     │
│  │ CheckpointCoordinator ← LangGraph先落库→验证→Manifest 事务提交      │     │
│  │ ToolLedger(Mongo实现)  ← 注入 harness 的 SideEffectLedger 协议      │     │
│  │ ResourceManager       ← ResourceBinding 租约/回收                  │     │
│  │ RecoverySupervisor    ← 三类扫描：待派发 / 过期接管 / 活跃防重       │     │
│  └─────────────────────────────────────────────────────────────────┘     │
│         │                                  │                              │
│         v                                  v                              │
│  Dispatcher 接口 ──> CeleryDispatcher      harness (包内协议,不 import app) │
└──────────────────────────────────────────────────────────────────────────┘
```

四条铁律（v2 新增第 4 条）：

1. **执行事实写入只经 `ExecutionRepository`**——它是唯一带 fencing 的写入通道，业务代码直接写执行集合视为违规。
2. **状态变更 + 事件同事务**——`emit` 只作为事务组成部分存在。
3. **harness 不感知 Mongo**——协议在 harness 定义，实现由 app 注入（可独立发布边界不变）。
4. **每个执行事实写事务必须先对 Execution 主记录做带 token 条件的写**（`$inc write_version`）——这是 fencing 的真正执行面：takeover 与旧 Worker 事务在**同一文档**上形成 Mongo 写冲突，二者只可能有一个提交成功。只在子集合写入时过滤 token 不构成防并发（Mongo 事务写冲突以文档为单位）。

---

## 2. 代码落位

### 2.1 新增：`backend/app/engine/execution/`（执行域核心包）

```text
app/engine/execution/
├── __init__.py          # 对外只暴露 ExecutionService 级入口
├── models.py            # Execution/Step/CheckpointManifest/ExecutionEvent/
│                        # ToolInvocation/ResourceBinding + dispatch_state 枚举
├── collections.py       # 集合名常量 + ensure_indexes()（含 partial unique index）
├── repository.py        # ExecutionRepository：事务级 fencing 写入通道
├── lease.py             # LeaseManager：acquire/renew/takeover/release（CAS）
├── events.py            # EventWriter：seq 原子分配（ReturnDocument.AFTER）+ 事务追加
├── checkpoint.py        # CheckpointCoordinator：两阶段提交协议封装
├── recovery.py          # RecoverySupervisor：三类扫描 + 接管 + 恢复编排
├── dispatcher.py        # Dispatcher Protocol + CeleryDispatcher（写 dispatch_state）
└── resource.py          # ResourceManager：binding 登记 / 租约 / 回收 / 能力矩阵
```

### 2.2 harness 侧新增（协议，无实现）

```text
packages/harness/src/agent_flow_harness/
├── ledger.py            # SideEffectLedger Protocol（不变）
├── execution_context.py # ExecutionIdentity contextvar（不变）
└── (改造) tools/…       # 工具执行链走 ledger 钩子；同时持久化原始 Tool Call 意图
```

装配点 `app/core/execution_runtime.py`：lifespan 与 `worker_process_init` 各自初始化；**事务能力检测失败（生产）→ 拒绝启动**（fail-closed，与 #62 同口径）。开发环境如需 standalone Mongo，必须显式配置 `EXECUTION_DURABLE=false`——此时执行域以**无恢复保证**模式运行，健康检查明示 non-durable，不得对外承诺恢复能力。

### 2.3 现有代码改造点（接缝清单）

| 现有位置 | 改造 | 阶段 |
|---|---|---|
| `deploy/docker-compose.yml` + `release/docker-compose.yml` | Mongo 改单节点 Replica Set（`--replSet rs0` + init 健康检查 + 就绪等待） | **E0** |
| `app/models/task.py` | `Checkpoint`/`timeline`/`variables` 标记 deprecated（读兼容），`version` 收窄为业务字段乐观锁 | E1 |
| `app/engine/workflow/engine.py` | checkpoint 写点收敛到 CheckpointCoordinator（双写）；恢复入口切读 Manifest | E4→E6 |
| `app/engine/workflow/node_executor.py:794` | thread_id 改经 ExecutionIdentity 登记 | E6 |
| `app/services/agent_execution_service.py` | **四种场景分流**（见 §4）；SSE 改订阅 ExecutionEvent 游标 | E7 |
| `app/services/session_service.py:242` | chat thread 归 Execution 登记 | E7 |
| `harness subagents/delegate.py` | Child Execution（先同步可查询，异步化归 #72） | E9 |
| `app/workers/tasks/running_task_scan.py` | 迁移为 RecoverySupervisor 扫描（保留对账一阶段） | E3 |
| `app/workers/tasks/maintenance.py` | 资源回收改按 ResourceBinding 扫描 | E8 |
| `app/workers/celery_app.py` | beat 增执行域扫描任务；**workflow task 的 `acks_late=False` 覆盖保持不变**（恢复不依赖 Celery 重投递，见 §3.2） | E3 |

---

## 3. 组件设计（v2 修订处标 ◆）

### 3.1 部署前提与 fail-closed ◆

- 部署基线：Mongo **必须**以 Replica Set 形态运行（单节点 RS 即满足多文档事务）。
- 启动时事务能力探测（建临时集合→开事务写→回滚）；生产探测失败 = 拒绝启动。
- 开发 standalone：仅当显式 `EXECUTION_DURABLE=false` 时允许启动，health 明示 non-durable，恢复协议整体禁用（不写 Manifest/账本，行为退化为现状语义）。
- `/health` 增执行域字段：backend 形态、事务能力、durable 开关、初始化错误。

### 3.2 LeaseManager ◆（与 Celery 解耦）

```python
acquire(execution_id, owner) / heartbeat / takeover(CAS, token+1) / release
```

参数起点（压测后调）：**heartbeat 10–15s，Lease TTL 45–60s，RecoverySupervisor 扫描 5–10s**。

理由：Celery 不是统一恢复时钟——workflow task 显式 `acks_late=False`（不重投递），chat 不经 Celery。Lease 只表达执行所有权；发现与接管一律由 RecoverySupervisor 扫描承担。进程崩溃后的接管延迟 ≈ TTL + 扫描间隔 ≈ 1 分钟内。

### 3.3 EventWriter ◆

- seq 分配：`find_one_and_update(..., {"$inc": {"event_seq_counter": 1}}, return_document=ReturnDocument.AFTER)`——**必须 AFTER**，默认 BEFORE 会拿到旧计数。
- seq 分配与事件插入同事务，且该事务先对主记录 `$inc write_version`（铁律 4）——seq 分配同样受 fencing 保护。
- `event_key` 去重用 **partial unique index**（compound sparse 不适用，`execution_id` 恒存在）：

```javascript
db.execution_events.createIndex(
  { execution_id: 1, event_key: 1 },
  { unique: true, partialFilterExpression: { event_key: { $type: "string" } } }
)
```

- 通知：事务提交后经 Notifier 协议发 Redis（仅通知）；消费一律读 `execution_events` 游标。

### 3.4 CheckpointCoordinator（两阶段提交，不变）

Graph Checkpoint 落库 → 读回验证取精确 identity → 同事务提交 Manifest + Step 边界 + Event（该事务同样先碰主记录）。允许孤儿 Graph Checkpoint，由清理任务回收。

### 3.5 ToolLedger ◆（补充：调用意图持久化）

在 v1 的 prepare→in_progress→终态协议之上新增：**prepare 时持久化原始 Tool Call 意图**（完整调用参数 + request_digest + tool_call_id）。理由：恢复续跑时模型重新生成的 `tool_call_id` 不保证与崩溃前一致，账本裁决与结果回放必须以**已持久化的原始意图**为准，不能假设重生成 ID 稳定。

### 3.6 RecoverySupervisor 与 DispatchState ◆

Execution 主记录新增持久化派发状态：

```json
{
  "dispatch_state": "pending|dispatched|in_progress|done",
  "dispatch_attempts": 0,
  "next_dispatch_at": "timestamp",
  "last_dispatch_at": null
}
```

三类扫描（互斥条件）：

1. `status=queued && dispatch_state=pending`（或 `next_dispatch_at <= now` 的重试）→ 派发；
2. `status=running && lease.expires_at < now` → takeover（token+1）后派发接管；
3. `status=running && lease 活跃` → **跳过**（防重复启动）。

不建独立 outbox 集合，但派发状态持久化 + 可验证扫描协议 = 事实上的 outbox 语义；投递失败按 `next_dispatch_at` 指数退避重试。

### 3.7 Dispatcher ◆

`dispatch(execution_id)` 落 `dispatch_state=dispatched`（与创建 Execution 同事务）→ 投 Celery；扫描兜底闭合投递丢失。

---

## 4. Chat 四种执行场景 ◆（修正 v1 的"每轮创建"一刀切）

| 场景 | Execution 处理 |
|---|---|
| 新用户 turn | 创建新 Execution（trigger=chat） |
| interrupted Execution resume（ask_clarification 恢复等） | **复用原 Execution** |
| Worker crash recovery | **复用原 Execution**（takeover 续跑） |
| 用户要求整体重跑 | 创建新 Execution，`retry_of_execution_id` 关联旧执行 |

Session 并发（审查追问项）：一期串行采用**原子认领 turn sequence**——Execution 创建时 `find_one_and_update` 对 Session 文档 `$inc turn_seq` 取序号，运行中前驱未完成时新 Execution 排队（queued），不用"查询是否有 running 前驱"的竞态写法。

## 5. 资源侧 fencing 的诚实声明 ◆

Docker Provider 一期**不具备资源侧 fencing**：数据库 token 约束不到 Docker Daemon，remove 容器 ≠ 撤销旧 Worker 控制能力。一期策略：

- 安全复用（reattach）的前提 = 确认旧持有进程已终止（lease 过期 + worker 心跳消失 + 进程存活探测）；
- 无法确认 → **隔离重建**（新容器 + workspace 重挂接），旧容器标记 quarantine 由回收任务处理；
- ResourceManager 维护 Provider 能力矩阵；真正的资源侧 fencing（凭证撤销/受控代理/generation 校验）归 #63/#69 的 Controller 演进。

---

## 6. 其余落地裁定（吸收审查追问）

1. **`committed_step_ids` 捕获语义**：Manifest 提交事务内读取 Step 集合 `status ∈ {succeeded}` 且 `step_seq <= 水位` 的快照写入——捕获时刻 = Manifest 事务的快照读，与提交边界一致；长 Loop 数组增长问题在 E4 评估独立 StepSnapshot 集合。
2. **Task 投影规则**：Task 用户可见状态 = 该 Task 最新活跃（非终态优先，否则最新终态）Execution 的状态投影，投影在状态迁移事件中刷新。
3. **Event TTL**：不预设 365d；E2 阶段先无 TTL + 量级观测，保留策略待审计/重放/合规要求明确后定（恢复能力不依赖事件，见 v1 §6.2 不变）。
4. **Adapter 独立性**：ChatRuntimeAdapter 不依赖 Workflow 切读完成——两者只共享 ExecutionRepository/EventWriter/Lease 原语，切换顺序解耦（对应实施顺序 E6/E7 分开）。

## 7. PR 切分（采纳审查顺序）◆

| PR | 内容 |
|---|---|
| **E0** | Mongo 单节点 RS（deploy+release compose）+ 事务能力探测 + 生产 fail-closed + health 字段 |
| E1 | models + collections(索引) + repository(事务级 fencing) + lease |
| E2 | EventWriter（AFTER/partial index/游标读） |
| E3 | dispatch_state + Dispatcher + RecoverySupervisor 三类扫描 |
| E4 | CheckpointCoordinator + workflow 双写 + 对账脚本 |
| E5 | harness ledger 协议 + ToolLedger + 调用意图持久化 + UNKNOWN 裁决（#71） |
| E6 | Workflow 恢复切读 Manifest |
| E7 | Chat 纳入 Execution + SSE 游标（#66，四场景分流） |
| E8 | ResourceManager + maintenance 迁移（#68） |
| E9 | Subagent Child Execution（#72 一期） |

每 PR 带回滚开关与数据迁移；E5 起才有行为切换。

## 8. 风险与回滚（更新）

| 风险 | 缓解 |
|---|---|
| 事务级 fencing 的写冲突误伤（高并发同 Execution） | 同一 Execution 事实写入天然串行（单 Worker 持有），冲突只在 takeover 竞态出现——正是要防的场景 |
| 短 TTL 心跳风暴（大量并发 Execution） | 心跳批量聚合（每 Worker 进程一条协程统一续约）；TTL 压测后放宽 |
| 双写期状态漂移 | 对账脚本 nightly CI |
| Mongo RS 化的存量部署迁移 | E0 提供迁移 runbook（standalone → 单节点 RS 有官方零停机路径）；release 包首次升级窗口说明 |
| chat 进程内 Worker 与 Celery 行为不一致 | 共用 RuntimeAdapter 接口，进程内 = 本地 Dispatcher 特例 |

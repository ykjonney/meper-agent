"""执行域数据模型（#64 提案 §3 的直译，架构 v2 §2.1）。

对应集合见 ``collections.py``。模型只描述结构，写入通道一律经
``repository.ExecutionRepository``（事务级 fencing）。
"""
from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.models.base import generate_id, utc_now

# ── 状态域 ────────────────────────────────────────────────────────────


class ExecutionStatus(StrEnum):
    """Execution 业务状态（提案 §4.1；与 Lease 状态机分离）。"""

    CREATED = "created"
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    WAITING_INPUT = "waiting_input"
    EXPIRED = "expired"


EXECUTION_TERMINAL_STATUSES = frozenset(
    {
        ExecutionStatus.SUCCEEDED,
        ExecutionStatus.FAILED,
        ExecutionStatus.CANCELLED,
        ExecutionStatus.TIMED_OUT,
        ExecutionStatus.EXPIRED,
    }
)


class StepStatus(StrEnum):
    """Step 状态（提案 §3.6）。Step 是执行单元进度的唯一事实源。"""

    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    WAITING = "waiting"
    CANCELLED = "cancelled"


class DispatchState(StrEnum):
    """Execution 的持久化派发状态（架构 v2 §3.6——扫描协议分三类）。"""

    PENDING = "pending"          # 尚未投递（首投或重试等待）
    DISPATCHED = "dispatched"    # 已投递，等待 worker 认领
    IN_PROGRESS = "in_progress"  # worker 已认领（持 lease 推进中）
    DONE = "done"                # 派发闭环完成（执行终态后置）


class LedgerStatus(StrEnum):
    """ToolInvocation 账本状态（提案 §3.8；UNKNOWN 显式建模）。"""

    PREPARED = "prepared"
    IN_PROGRESS = "in_progress"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNKNOWN = "unknown"
    COMPENSATION_PENDING = "compensation_pending"
    COMPENSATED = "compensated"


class ResourceLifecycleState(StrEnum):
    ATTACHED = "attached"
    DETACHED = "detached"
    QUARANTINED = "quarantined"   # 一期无资源侧 fencing：旧持有者无法确认终止时隔离
    RELEASED = "released"


# ── 触发源 ────────────────────────────────────────────────────────────


class ExecutionTrigger(StrEnum):
    CHAT = "chat"
    WORKFLOW = "workflow"
    SCHEDULE = "schedule"
    SUBAGENT = "subagent"
    RETRY = "retry"


# ── 内嵌结构 ──────────────────────────────────────────────────────────


class LeaseInfo(BaseModel):
    """Worker 所有权（提案 §3.5）——fencing token 的宿主。

    token 归属 Execution、单调递增、不得回退或复用；所有执行事实写入
    都必须经 ``repository`` 的事务级 fencing 校验。
    """

    owner: str
    lease_id: str = Field(default_factory=lambda: generate_id("lease"))
    fencing_token: int
    heartbeat_at: datetime = Field(default_factory=utc_now)
    expires_at: datetime


class GraphThread(BaseModel):
    """LangGraph thread 的显式登记（消灭散落调用点的字符串约定）。"""

    thread_id: str
    namespace: str = ""
    purpose: str  # 如 chat-main / node:{node_id} / subagent:{agent_id}


class DispatchInfo(BaseModel):
    """持久化派发状态（架构 v2 §3.6）。"""

    state: DispatchState = DispatchState.PENDING
    attempts: int = 0
    next_dispatch_at: datetime | None = None
    last_dispatch_at: datetime | None = None


# ── 主对象 ────────────────────────────────────────────────────────────


class Execution(BaseModel):
    """一次逻辑执行（提案 §3.3）。

    - ``execution_id`` 在恢复过程中保持不变；worker 接管/崩溃不新建。
    - 业务整体重试 → 新 Execution，``retry_of_execution_id`` 关联。
    - ``write_version`` 是事务级 fencing 的冲突点：每个执行事实写事务
      先对它 ``$inc``（带 token 条件），takeover 也改同一文档——新旧
      事务因此在同一文档上形成 Mongo 写冲突（铁律 4）。
    - ``event_seq_counter`` 是事件序号的原子分配器（同事务 ``$inc``，
      ReturnDocument.AFTER）。
    """

    id: str = Field(alias="_id", default_factory=lambda: generate_id("exec"))
    task_id: str | None = None
    session_id: str | None = None
    trigger: ExecutionTrigger
    parent_execution_id: str | None = None
    retry_of_execution_id: str | None = None

    status: ExecutionStatus = ExecutionStatus.CREATED
    attempt_no: int = 1  # ExecutionAttempt 概念以元数据承载（提案 §3.4/§10.5）

    lease: LeaseInfo | None = None
    write_version: int = 0
    event_seq_counter: int = 0
    checkpoint_seq_counter: int = 0  # Manifest 序号的原子分配器（同事务 $inc）

    graph_threads: list[GraphThread] = Field(default_factory=list)
    dispatch: DispatchInfo = Field(default_factory=DispatchInfo)
    config_snapshot_ref: str | None = None

    created_at: datetime = Field(default_factory=utc_now)
    started_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"populate_by_name": True}


class Step(BaseModel):
    """执行单元（提案 §3.6）：workflow node / agent turn / 其他可恢复阶段。

    Step 状态是进度的权威来源；``parent_step_id`` 表达嵌套。
    """

    id: str = Field(alias="_id", default_factory=lambda: generate_id("step"))
    execution_id: str
    parent_step_id: str | None = None
    step_seq: int
    kind: str  # workflow_node / agent_turn / …（开放域，按触发源扩展）
    status: StepStatus = StepStatus.PENDING
    attempt: int = 1
    idempotency_key: str  # 稳定：{execution_id}:{step 身份}，恢复不重生成
    payload_ref: str | None = None  # 大内容走引用（提案 §3.9）
    error: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None

    model_config = {"populate_by_name": True}


class CheckpointManifest(BaseModel):
    """跨引擎恢复 Manifest（提案 §3.7）——不复制 LangGraph State。

    - ``graph_checkpoint_id`` 精确定位 Graph Checkpoint（仅 thread_id 不足）。
    - ``committed_step_ids`` 捕获时刻 = 本 Manifest 提交事务的快照读，
      与提交边界一致（架构 v2 §6.1）；长 Loop 的数组增长问题 E4 评估
      独立 StepSnapshot。
    - 提交顺序：Graph Checkpoint 落库 → 读回验证 → 本 Manifest 事务提交
      （CheckpointCoordinator 在 E4 实现，模型先行定义）。
    """

    id: str = Field(alias="_id", default_factory=lambda: generate_id("ckpt"))
    execution_id: str
    checkpoint_seq: int
    step_id: str | None = None
    committed_step_ids: list[str] = Field(default_factory=list)
    # 对齐旧 Checkpoint.kind 域 + 终态：pause|progress|cancel|complete
    kind: str = "pause"
    # Graph Checkpoint 精确引用：agent 中断边界必填；纯 workflow 边界
    # （loop 轮间/节点取消）无 LangGraph 状态 → None，恢复定位靠 step 快照。
    graph_thread_id: str | None = None
    graph_checkpoint_ns: str = ""
    graph_checkpoint_id: str | None = None
    fencing_token: int
    config_snapshot_ref: str | None = None
    created_at: datetime = Field(default_factory=utc_now)

    model_config = {"populate_by_name": True}


class ExecutionEvent(BaseModel):
    """append-only 执行事件（提案 §3.9）——执行过程的可靠事实源。

    ``seq`` 由 Repository 在同事务内 ``$inc`` 分配（原子）；
    ``event_key`` 供可重试写入去重（partial unique index）。
    """

    id: str = Field(alias="_id", default_factory=lambda: generate_id("evt"))
    execution_id: str
    seq: int
    type: str  # 如 step.completed / execution.takeover / tool.unknown
    schema_version: int = 1
    producer: str  # workflow-runtime / chat-runtime / supervisor / system
    event_key: str | None = None  # 幂等键：None 则不参与唯一约束
    correlation_id: str | None = None
    causation_id: str | None = None
    occurred_at: datetime = Field(default_factory=utc_now)
    recorded_at: datetime = Field(default_factory=utc_now)
    payload: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True}


class ToolInvocation(BaseModel):
    """外部副作用账本（提案 §3.8）。

    ``prepared`` 时即持久化**原始调用意图**（完整参数摘要 + digest +
    tool_call_id）——恢复裁决与回放以持久化意图为准，不假设模型重生成
    的 tool_call_id 稳定（架构 v2 §3.5）。
    """

    id: str = Field(alias="_id", default_factory=lambda: generate_id("tinv"))
    execution_id: str
    step_id: str
    tool_call_id: str
    tool_name: str
    tool_version: str | None = None
    idempotency_key: str  # {execution_id}:{step_id}:{tool_call_id}，恢复期稳定
    request_digest: str  # sha256:…（参数摘要，回放三匹配校验之一）
    request_intent: dict[str, Any] = Field(default_factory=dict)  # 原始调用意图
    status: LedgerStatus = LedgerStatus.PREPARED
    external_reference: str | None = None
    result_ref: str | None = None
    retry_count: int = 0
    error: str | None = None
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None

    model_config = {"populate_by_name": True}


class ResourceBinding(BaseModel):
    """Execution 与资源的显式关联（提案 §3.10）——替换路径/容器名推断。

    一期 Docker Provider 无资源侧 fencing：无法确认旧持有者终止时
    ``lifecycle_state`` 置 quarantined 并隔离重建（架构 v2 §5）。
    """

    id: str = Field(alias="_id", default_factory=lambda: generate_id("rbind"))
    execution_id: str
    resource_type: str  # sandbox / workspace / browser
    resource_id: str
    provider: str  # docker / local / …
    provider_resource_id: str | None = None
    fencing_token: int = 0
    lifecycle_state: ResourceLifecycleState = ResourceLifecycleState.ATTACHED
    recovery_policy: str = "reattach_or_recreate"
    lease_expires_at: datetime | None = None
    created_at: datetime = Field(default_factory=utc_now)

    model_config = {"populate_by_name": True}

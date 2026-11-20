"""执行域核心包（Execution Domain, #64 / PR #73）。

分层（依赖自上而下）：
- ``models``      纯数据模型（Execution/Step/CheckpointManifest/Event/…）
- ``collections`` 集合名 + 索引定义
- ``repository``  唯一受控写入通道（事务级 fencing，铁律 4）
- ``lease``       LeaseManager（acquire/heartbeat/takeover/release CAS）

铁律（docs/EXECUTION-ARCHITECTURE.md §1）：
1. 执行事实写入只经 ExecutionRepository；
2. 状态变更 + 事件同事务；
3. （harness 侧协议由 E5 引入）
4. 每个执行事实写事务先对 Execution 主记录做带 token 条件的写。
"""
from app.engine.execution.models import (
    CheckpointManifest,
    Execution,
    ExecutionEvent,
    ExecutionStatus,
    LeaseInfo,
    ResourceBinding,
    Step,
    StepStatus,
    ToolInvocation,
)
from app.engine.execution.repository import ExecutionRepository, LeaseLostError

__all__ = [
    "CheckpointManifest",
    "Execution",
    "ExecutionEvent",
    "ExecutionRepository",
    "ExecutionStatus",
    "LeaseInfo",
    "LeaseLostError",
    "ResourceBinding",
    "Step",
    "StepStatus",
    "ToolInvocation",
]

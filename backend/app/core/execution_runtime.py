"""执行域运行时前提检查 —— E0（#64 / PR #73）。

Durable Execution 依赖 MongoDB 多文档事务（Replica Set 形态；单节点 RS 即可，
standalone 不支持）。启动时探测事务能力并执行 fail-closed 策略：

- ``EXECUTION_DURABLE=true``（默认）且探测失败 → **拒绝启动**（生产/开发
  一致：开发环境用 standalone Mongo 必须显式 ``EXECUTION_DURABLE=false``，
  不能把无事务模式当作有恢复保证的运行方式）。
- ``EXECUTION_DURABLE=false`` → 允许启动，执行域以 non-durable 模式运行，
  /health 明示无恢复保证；生产环境启用该模式时打 error 级日志提醒。

探测方式：在专用临时集合上开启事务写入后 abort——事务能正常开启并提交
abort 即具备能力；异常携带错误信息归因（standalone 报 "Transaction numbers
are only allowed on a replica set member or mongos"）。探测不落任何数据。

健康暴露：``get_status()`` 供 /health 输出执行域字段（backend 形态、事务
能力、durable 开关、初始化错误）。
"""
from __future__ import annotations

from dataclasses import dataclass

from loguru import logger

from app.core.config import settings
from app.models.base import utc_now

# 探测用临时集合（同一事务内写两个集合，覆盖"跨集合"语义；结束后即删）
_PROBE_COLLECTIONS = ("__txn_probe_a__", "__txn_probe_b__")


@dataclass
class ExecutionRuntimeStatus:
    """执行域运行前提的健康快照（/health 投影）。"""

    # 是否承诺 durable execution（EXECUTION_DURABLE 开关）
    durable: bool
    # 事务能力探测结果；None = 尚未执行探测（如启动早期 / 探测自身失败）
    transactions_ok: bool | None
    # Mongo 部署形态："replica_set" | "standalone" | None（探测失败时）
    backend_type: str | None
    # 初始化错误信息（探测失败的原因）
    error: str | None


# 进程级状态：启动检查完成后只读。worker 进程（worker_process_init）与
# FastAPI lifespan 各自初始化一份。
_status: ExecutionRuntimeStatus | None = None


def get_status() -> ExecutionRuntimeStatus:
    """返回当前进程的执行域状态（未初始化时返回 unknown 快照）。"""
    if _status is None:
        return ExecutionRuntimeStatus(
            durable=settings.EXECUTION_DURABLE,
            transactions_ok=None,
            backend_type=None,
            error="not initialized",
        )
    return _status


def as_health_dict() -> dict[str, object]:
    """/health 用的执行域字段（保持平坦结构便于探针解析）。"""
    s = get_status()
    return {
        "execution_durable": s.durable,
        "execution_transactions_ok": s.transactions_ok,
        "execution_mongo_backend": s.backend_type,
        "execution_error": s.error,
    }


async def probe_transaction_capability() -> tuple[bool, str | None]:
    """探测 MongoDB 多文档事务能力（#75 修正：提交 + 唯一 ID 精确清理）。

    事务 CM 正常退出即自动提交——在退出后调 abort 已太晚（会把支持事务
    的 RS 误判为不支持，或留下已提交的脏数据）。因此改为：

    1. 事务内跨两个集合写入带 ``probe_id``（每次探测唯一）的文档；
    2. CM 退出（提交成功）→ 具备事务能力；
    3. 清理只 ``delete_many({"probe_id": 本次})``——绝不 drop 共享集合，
       也不影响其他进程的并发探测；
    4. 清理失败单独记录日志，**不覆盖**事务能力的真实结论。

    Returns:
        (True, None) 具备能力；(False, 归因信息) 不具备。
    """
    from uuid import uuid4

    from app.db.mongodb import get_database

    probe_id = f"probe-{uuid4().hex}"
    db = get_database()
    error: str | None = None
    try:
        # CM 正常退出 = commit；standalone 会在首个写操作抛
        # "Transaction numbers are only allowed on a replica set member…
        async with (
            await db.client.start_session() as session,
            session.start_transaction(),
        ):
            for name in _PROBE_COLLECTIONS:
                await db.get_collection(name).insert_one(
                    {"probe_id": probe_id, "ts": utc_now()}, session=session
                )
    except Exception as exc:  # noqa: BLE001 - 归因信息本身就是要返回的内容
        error = f"{type(exc).__name__}: {exc}"

    # 精确清理：只删本次 probe_id 的文档（并发探测互不影响）。
    # 清理失败不改变事务能力结论（#75：二者必须区分）。
    for name in _PROBE_COLLECTIONS:
        try:
            await db.get_collection(name).delete_many({"probe_id": probe_id})
        except Exception as exc:  # noqa: BLE001 - 清理是尽力而为
            logger.warning(
                "execution_probe_cleanup_failed collection={} error={}",
                name,
                exc,
            )
    return error is None, error


async def _detect_backend_type() -> str | None:
    """hello() 判定部署形态：setName 存在 = 副本集成员。"""
    from app.db.mongodb import get_database

    try:
        hello = await get_database().command("hello")
        return "replica_set" if hello.get("setName") else "standalone"
    except Exception:  # noqa: BLE001 - 连不上时让事务探测给最终结论
        return None


async def check_execution_runtime() -> ExecutionRuntimeStatus:
    """启动检查入口（lifespan / worker_process_init 调用）。

    fail-closed：EXECUTION_DURABLE=true 且探测失败时抛 RuntimeError 阻止
    启动——服务不能以"持久化执行可用"的状态带病上线（与 #62 checkpointer
    fail-closed 同口径）。
    """
    global _status  # noqa: PLW0603 - 进程级单例，仅启动时写一次

    backend_type = await _detect_backend_type()
    ok, error = await probe_transaction_capability()

    status = ExecutionRuntimeStatus(
        durable=settings.EXECUTION_DURABLE,
        transactions_ok=ok,
        backend_type=backend_type,
        error=error,
    )

    if not settings.EXECUTION_DURABLE:
        # 显式关闭 durable：允许启动，但必须可见、可告警。
        if settings.APP_ENV == "production":
            logger.error(
                "execution_durable_disabled_in_production "
                "hint=recovery guarantees are OFF — dev-only switch"
            )
        else:
            logger.warning("execution_durable_disabled recovery_guarantees=off")
        _status = status
        return status

    if not ok:
        # fail-closed：不降级、不带病启动。
        raise RuntimeError(
            "Execution durable mode requires MongoDB multi-document transactions "
            f"but the probe failed (backend={backend_type!r}, error={error!r}). "
            "Deploy MongoDB as a Replica Set (single-node is sufficient — see "
            "deploy/docker-compose.yml mongo service) or explicitly set "
            "EXECUTION_DURABLE=false for a dev-only, non-recoverable mode."
        )

    logger.info(
        "execution_runtime_ready durable=True backend={} transactions=True",
        backend_type,
    )
    _status = status
    return status

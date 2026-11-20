"""执行域 worker 入口（E3 骨架，E6/E7 Adapter 注册 runner 后成型）。

被 Dispatcher 投递的 Celery 任务：认领 lease → 标记 in_progress →
按 trigger 查找已注册的 Runner 执行。重复投递由 ``LeaseManager.acquire``
的 CAS 互斥（输家安静退出）——Celery 消息不是执行身份。

E3 阶段尚无注册 Runner：任务会**诚实失败**（failed + 明确错误事件），
不会静默吞掉或假装执行成功。
"""
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

from app.workers.celery_app import celery_app
from app.workers.loop import run_async

# Runner 协议：按 trigger 注册（E6 workflow / E7 chat）。参数为
# (execution_doc, lease)——runner 内部经 repository 带token写事实。
Runner = Callable[[dict[str, Any], Any], Awaitable[None]]

_RUNNERS: dict[str, Runner] = {}


def register_runner(trigger: str, runner: Runner) -> None:
    """Adapter 注册入口（E6/E7 调用；后注册覆盖先注册并告警）。"""
    if trigger in _RUNNERS:
        logger.warning("execution_runner_replaced trigger={}", trigger)
    _RUNNERS[trigger] = runner


def get_runner(trigger: str) -> Runner | None:
    return _RUNNERS.get(trigger)


@celery_app.task(name="app.workers.tasks.execution_run.run_execution")
def run_execution(execution_id: str) -> dict[str, Any]:
    """执行入口：认领 → in_progress → runner（或诚实失败）。"""
    return run_async(_run_async(execution_id))


async def _run_async(execution_id: str) -> dict[str, Any]:
    import os

    from app.engine.execution.lease import LeaseLostError, LeaseManager
    from app.engine.execution.models import ExecutionEvent
    from app.engine.execution.repository import ExecutionRepository

    repo = ExecutionRepository()
    lm = LeaseManager(repo)
    owner = f"worker:{os.getpid()}"

    doc = await repo.get_execution(execution_id)
    if doc is None:
        logger.warning("execution_run_not_found execution={}", execution_id)
        return {"outcome": "not_found"}

    try:
        lease = await lm.acquire(execution_id, owner)
    except LeaseLostError:
        # 重复投递的输家：lease 已被持有（CAS 互斥），安静退出。
        logger.info("execution_run_lease_held execution={}", execution_id)
        return {"outcome": "lease_held"}

    trigger = doc.get("trigger", "")
    runner = get_runner(trigger)
    try:
        async with repo.transaction(execution_id, expected_token=lease.fencing_token) as txn:
            await txn.append_event(
                ExecutionEvent(
                    execution_id=execution_id,
                    seq=0,
                    type="execution.started",
                    producer="worker",
                    payload={"owner": owner, "trigger": trigger},
                )
            )
            await txn.update_execution(
                {
                    "$set": {
                        "status": "running",
                        "started_at": doc.get("started_at"),
                        "dispatch.state": "in_progress",
                    }
                }
            )

        if runner is None:
            # E3 骨架：无 runner 即诚实失败——可见、可诊断、不留僵尸。
            async with repo.transaction(
                execution_id, expected_token=lease.fencing_token
            ) as txn:
                await txn.append_event(
                    ExecutionEvent(
                        execution_id=execution_id,
                        seq=0,
                        type="execution.failed",
                        producer="worker",
                        payload={"reason": f"no runner registered for trigger={trigger!r}"},
                    )
                )
                await txn.update_execution(
                    {"$set": {"status": "failed", "completed_at": _now_iso()}}
                )
            await lm.release(execution_id, lease.fencing_token)
            return {"outcome": "no_runner", "trigger": trigger}

        await runner(doc, lease)
        return {"outcome": "ran"}

    except LeaseLostError:
        # 执行中被接管：停止推进（提案 §5.2 zombie 协议）。
        logger.warning("execution_run_fenced_midway execution={}", execution_id)
        return {"outcome": "fenced"}

    except Exception as exc:  # noqa: BLE001 - 记录可恢复中断，不伪造终态
        # Runner 的普通异常不等同于“没有发生外部副作用”：工具/远端请求
        # 可能已成功但结果尚未持久化。这里不标记 failed、不释放 lease，
        # 也不立即重跑；记录中断事实后让 lease 自然过期，由 Supervisor
        # 接管。后续恢复必须由 ToolLedger 对 UNKNOWN 副作用作裁决。
        try:
            async with repo.transaction(
                execution_id, expected_token=lease.fencing_token
            ) as txn:
                await txn.append_event(
                    ExecutionEvent(
                        execution_id=execution_id,
                        seq=0,
                        type="execution.worker_error",
                        producer="worker",
                        payload={
                            "error_type": type(exc).__name__,
                            "error": str(exc)[:2000],
                            "recovery": "await_lease_expiry_and_supervisor_takeover",
                        },
                    )
                )
        except LeaseLostError:
            # 原 lease 已失效，不能再以旧 token 写诊断事件。
            logger.warning("execution_worker_error_after_fencing execution={}", execution_id)
        except Exception:
            # 记录事件本身失败不能覆盖 Runner 原始异常；lease 仍会自然过期。
            logger.exception("execution_worker_error_event_failed execution={}", execution_id)
        logger.exception("execution_runner_failed execution={}", execution_id)
        raise


def _now_iso() -> str:
    from app.models.base import utc_now

    return utc_now().isoformat()

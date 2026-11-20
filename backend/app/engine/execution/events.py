"""EventWriter 通知层（E2，#64/PR #73）——Redis 只做实时通知，不是事实源。

铁律 2 的另一半：事件与状态同事务提交；提交**成功后**才发通知——
通知丢失必须无损（消费端一律走 ``repository.read_events`` 游标补齐，
Redis 通知只是"该去读了"的提示）。这与现有 event_bridge 的
Celery→FastAPI 事件桥语义一致，但通道独立（execution 域专用 pub/sub）。

扩展点：``Notifier`` 是协议——生产用 ``RedisNotifier``，测试/开发可注
``NoopNotifier`` 或内存实现（单测断言用 ``CollectingNotifier``）。
"""
from __future__ import annotations

from typing import Protocol

from loguru import logger

# execution 域通知通道名：按 execution 分通道，订阅端可精确订阅单个执行。
EXECUTION_NOTIFY_CHANNEL = "agentflow:execution:{execution_id}"


class Notifier(Protocol):
    """事务提交后的事件通知协议（fire-and-forget，失败不重试）。"""

    async def notify(self, execution_id: str, last_seq: int) -> None: ...


class NoopNotifier:
    """开发/测试默认：不发通知（消费端靠游标轮询也能工作）。"""

    async def notify(self, execution_id: str, last_seq: int) -> None:  # noqa: ARG002
        return None


class CollectingNotifier:
    """单测用：收集通知供断言。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    async def notify(self, execution_id: str, last_seq: int) -> None:
        self.calls.append((execution_id, last_seq))


class RedisNotifier:
    """生产实现：publish 最新 seq 到 execution 通道。

    载荷只带 last_seq（最大已提交序号）——订阅端收到后从自己的游标
    ``read_events(after_seq=cursor)`` 补齐，天然容忍通知乱序/丢失/重复。
    Redis 异常只告警：通知通道不可用不影响执行事实（事实已在 Mongo）。
    """

    async def notify(self, execution_id: str, last_seq: int) -> None:
        try:
            from app.db.redis import get_redis_client

            client = await get_redis_client()
            await client.publish(
                EXECUTION_NOTIFY_CHANNEL.format(execution_id=execution_id),
                str(last_seq),
            )
        except Exception as exc:  # noqa: BLE001 - 通知尽力而为，不反噬执行
            logger.warning(
                "execution_notify_failed execution={} last_seq={} error={}",
                execution_id,
                last_seq,
                exc,
            )


# 进程级注入点（lifespan / worker_process_init 各自装配；默认 Noop）。
_notifier: Notifier = NoopNotifier()


def set_notifier(notifier: Notifier) -> None:
    """注入通知实现（装配点调用；测试里可随时替换）。"""
    global _notifier  # noqa: PLW0603 - 进程级单例
    _notifier = notifier


def get_notifier() -> Notifier:
    return _notifier


async def notify_committed(execution_id: str, last_seq: int) -> None:
    """事务提交成功后的通知入口（repository 调用）。"""
    await _notifier.notify(execution_id, last_seq)

"""Dispatcher —— 执行工作投递抽象（E3，架构 v2 §3.7 / 提案 §7.1）。

Celery 只是**投递机制**，不是执行状态事实源：dispatch 与 Execution 创建
同事务落 ``dispatch_state``，投递本身可失败可重试——丢失由
RecoverySupervisor 扫描兜底闭合（等价 outbox 语义，不建独立集合）。

Dispatcher 协议为未来替换调度后端保留空间（提案 §7.3）。
"""
from __future__ import annotations

from typing import Protocol

from loguru import logger

# 投递目标任务名（worker 侧执行入口，E6/E7 的 Adapter 注册 runner）
EXECUTION_RUN_TASK = "app.workers.tasks.execution_run.run_execution"


class Dispatcher(Protocol):
    """投递执行工作。实现必须幂等——重复投递由 lease acquire CAS 互斥。"""

    async def dispatch(self, execution_id: str) -> None: ...


class CeleryDispatcher:
    """生产实现：投 Celery 任务。

    不把 Celery Task ID 当执行身份（提案 §7.1）——execution_id 是唯一
    键，worker 侧经 LeaseManager.acquire 认领，重复消息自然互斥。
    投递异常上抛由调用方（RecoverySupervisor）按 dispatch 退避重试。
    """

    async def dispatch(self, execution_id: str) -> None:
        from app.workers.celery_app import celery_app

        result = celery_app.send_task(EXECUTION_RUN_TASK, args=[execution_id])
        logger.info(
            "execution_dispatched execution={} celery_task={}",
            execution_id,
            result.id,
        )


class NoopDispatcher:
    """测试/本地开发：不真投递（扫描逻辑单测用）。"""

    def __init__(self) -> None:
        self.dispatched: list[str] = []

    async def dispatch(self, execution_id: str) -> None:
        self.dispatched.append(execution_id)


_dispatcher: Dispatcher = CeleryDispatcher()


def set_dispatcher(dispatcher: Dispatcher) -> None:
    """注入投递实现（装配点/测试用）。"""
    global _dispatcher  # noqa: PLW0603 - 进程级单例
    _dispatcher = dispatcher


def get_dispatcher() -> Dispatcher:
    return _dispatcher

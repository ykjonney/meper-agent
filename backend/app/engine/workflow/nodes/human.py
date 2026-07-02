"""HumanNodeExecutor — pauses execution and waits for human approval.

When a workflow reaches a Human node:
1. Task transitions to ``waiting_human`` status
2. A timeout monitor is scheduled (if ``timeout_ms`` configured)
3. Execution waits for an external intervention (approve/reject/skip)
4. On timeout, executes the configured ``timeout_action``
"""
from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from loguru import logger

from app.engine.workflow.node_executor import BaseNodeExecutor, NodeResult
from app.models.task import TaskStatus
from app.services.task_service import TaskService


class HumanNodeExecutor(BaseNodeExecutor):
    """Pause workflow execution for human approval.

    Config::

        {
            "title": "审批质检报告",
            "description": "请审核以下质检数据...",
            "options": ["approve", "reject"],
            "timeout_ms": 300000,        # 5 minutes
            "timeout_action": "auto_skip", # auto_approve | auto_reject | auto_skip | fail
            "assignee": "user_xxx"         # optional: specific user
        }
    """

    async def execute(self, variables: dict[str, Any]) -> NodeResult:
        raw_title = self.node_config.get("title", "人工审批")
        raw_description = self.node_config.get("description", "")

        # 解析 title/description 里的变量引用 {{node.field}}，让审批人能看到
        # 上游节点的实际输出（如诊断结果、告警详情），而非固定的字面文案。
        from app.engine.workflow.expression import ExpressionEngine

        engine = ExpressionEngine(variables)
        title = self._resolve_to_str(engine, raw_title)
        description = self._resolve_to_str(engine, raw_description)

        # 系统固定提供 approve/reject 选项，当 options 为空时使用默认值
        options = self.node_config.get("options") or ["approve", "reject"]

        # 前端传入 timeout_minutes，后端统一转换为 ms
        timeout_ms = self.node_config.get("timeout_ms", 0)
        if not timeout_ms:
            timeout_minutes = self.node_config.get("timeout_minutes", 0)
            timeout_ms = int(timeout_minutes) * 60 * 1000 if timeout_minutes else 0

        timeout_action = self.node_config.get("timeout_action", "fail")

        logger.info(
            "human_node_waiting",
            node_id=self.node_id,
            title=title,
            timeout_ms=timeout_ms,
        )

        # Return result indicating the task needs human intervention.
        # The WorkflowEngine will detect the waiting_human status and
        # pause execution until an intervention is received.
        return NodeResult(
            success=True,
            output={
                "status": "waiting_human",
                "title": title,
                "description": description,
                "options": options,
                "timeout_ms": timeout_ms,
                "timeout_action": timeout_action,
                "node_id": self.node_id,
            },
        )

    @staticmethod
    def _resolve_to_str(engine: "ExpressionEngine", raw: Any) -> str:
        """把模板值解析为字符串，供审批展示。

        - 非字符串原样返回（转 str）。
        - 字符串经 ExpressionEngine 解析变量引用；若解析出 dict/list（上游返回
          JSON 的常见情况），归一化为 JSON 文本，避免审批描述里出现 Python
          repr（单引号、True 大写）。
        """
        if not isinstance(raw, str):
            return str(raw)
        if not raw:
            return ""
        resolved = engine.resolve(raw)
        if resolved is None:
            return ""
        if isinstance(resolved, (dict, list)):
            import json

            return json.dumps(resolved, ensure_ascii=False, default=str)
        return str(resolved)


class HumanTimeoutMonitor:
    """Background monitor for Human node timeouts.

    Starts a background task per human node that waits for the
    configured timeout, then executes the timeout action if the
    Task is still in ``waiting_human`` status.
    """

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}

    async def start_monitor(
        self,
        task_id: str,
        node_id: str,
        timeout_ms: int,
        timeout_action: str,
    ) -> None:
        """Start a timeout monitor for a human node.

        Args:
            task_id: The Task ID.
            node_id: The Human node ID.
            timeout_ms: Timeout in milliseconds.
            timeout_action: Action on timeout (auto_approve, auto_reject, auto_skip, fail).
        """
        if timeout_ms <= 0:
            return  # No timeout configured

        key = f"{task_id}_{node_id}"

        # Cancel existing monitor if any
        await self.cancel_monitor(task_id, node_id)

        self._tasks[key] = asyncio.create_task(
            self._monitor(task_id, node_id, timeout_ms / 1000, timeout_action),
        )
        logger.debug("human_timeout_monitor_started", task_id=task_id, node_id=node_id, timeout_s=timeout_ms / 1000)

    async def cancel_monitor(self, task_id: str, node_id: str) -> None:
        """Cancel a timeout monitor."""
        key = f"{task_id}_{node_id}"
        existing = self._tasks.pop(key, None)
        if existing is not None and not existing.done():
            existing.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await existing

    async def _monitor(
        self,
        task_id: str,
        node_id: str,
        timeout_s: float,
        timeout_action: str,
    ) -> None:
        """Wait for timeout and execute the action."""
        try:
            await asyncio.sleep(timeout_s)

            # Check if Task is still waiting_human
            doc = await TaskService.get_task(task_id)
            if doc is None or doc.get("status") != TaskStatus.WAITING_HUMAN.value:
                return  # Already handled

            logger.warning(
                "human_node_timeout",
                task_id=task_id,
                node_id=node_id,
                action=timeout_action,
            )

            # Execute timeout action
            action_map = {
                "auto_approve": TaskStatus.RUNNING,
                "auto_reject": TaskStatus.FAILED,
                "auto_skip": TaskStatus.RUNNING,
                "fail": TaskStatus.FAILED,
            }

            target_status = action_map.get(timeout_action)
            if target_status is None:
                target_status = TaskStatus.FAILED

            await TaskService.transition_task(
                task_id=task_id,
                to_status=target_status,
                triggered_by="system",
                triggered_by_type="system",
                timeline_event_type="timeout",
                timeline_data={
                    "node_id": node_id,
                    "timeout_action": timeout_action,
                    "message": f"Human 节点超时，执行 {timeout_action}",
                },
            )

        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("human_timeout_monitor_error", error=str(exc))


# Module-level singleton
_human_timeout_monitor = HumanTimeoutMonitor()


def get_human_timeout_monitor() -> HumanTimeoutMonitor:
    """Return the process-level HumanTimeoutMonitor singleton."""
    return _human_timeout_monitor

"""WorkflowEngine — DAG-based workflow executor.

Handles:
- Loading workflow definition (nodes + edges)
- DAG topological sort and execution order
- Node executor dispatch (Strategy pattern)
- Gateway conditional branching
- Parallel branch execution
- Variable pool management
- Task state transitions and timeline events
- Checkpoint save/restore for Human node pause/resume
"""
from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import Any

from loguru import logger

from app.engine.workflow.expression import ExpressionEngine
from app.engine.workflow.node_executor import NodeResult, get_node_executor
from app.engine.workflow.variable_pool import VariablePool
from app.models.task import Checkpoint, TaskStatus, utc_now
from app.services.task_service import TaskService


class WorkflowEngine:
    """Core workflow execution engine.

    Usage::

        engine = WorkflowEngine()
        result = await engine.execute_task(task_doc, workflow_doc)
    """

    def __init__(self) -> None:
        self._task_id: str = ""
        self._pool: VariablePool | None = None
        self._nodes: list[dict[str, Any]] = []
        self._node_map: dict[str, dict[str, Any]] = {}
        self._edges: list[dict[str, Any]] = []
        self._out_edges: dict[str, list[dict[str, Any]]] = {}  # source -> edges
        self._in_edges: dict[str, list[dict[str, Any]]] = {}  # target -> edges
        self._completed_nodes: set[str] = set()
        self._branch_scope: dict[str, dict[str, Any]] = {}  # branch_id -> isolated variables

    # ── Public API ──

    async def run_and_persist(self, task_id: str) -> dict[str, Any]:
        """Load task & workflow, execute, and persist results back to Task.

        This is the high-level entry point meant to be called from TaskService
        after creating a new Task.

        Distinguishes between first-time execution and resume from checkpoint:
        - If task has a checkpoint → calls `resume_from_checkpoint`
        - Otherwise → calls `execute_task` (full workflow from start)

        Args:
            task_id: The Task ID to execute.

        Returns:
            Final variable pool snapshot.
        """
        from app.db.mongodb import get_database

        db = get_database()

        # Fetch task
        task_doc = await db["tasks"].find_one({"_id": task_id})
        if task_doc is None:
            logger.error("run_and_persist_task_not_found", task_id=task_id)
            return {}

        workflow_id = task_doc.get("workflow_id", "")
        if not workflow_id:
            logger.error("run_and_persist_no_workflow", task_id=task_id)
            return {}

        # Fetch workflow definition
        workflow_doc = await db["workflows"].find_one({"_id": workflow_id})
        if workflow_doc is None:
            logger.error("run_and_persist_workflow_not_found", task_id=task_id, workflow_id=workflow_id)
            return {}

        # Check if resuming from checkpoint
        if task_doc.get("checkpoint"):
            logger.info("run_and_persist_resuming", task_id=task_id)
            final_output = await self.resume_from_checkpoint(task_id)
        else:
            # Execute from scratch
            final_output = await self.execute_task(task_doc, workflow_doc)

        # Persist final output to Task.output
        try:
            await db["tasks"].update_one(
                {"_id": task_id},
                {"$set": {"output": final_output, "updated_at": utc_now()}},
            )
        except Exception as exc:
            logger.error("run_and_persist_output_save_failed", task_id=task_id, error=str(exc))

        return final_output

    async def execute_task(
        self,
        task_doc: dict[str, Any],
        workflow_doc: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a Task against a Workflow definition.

        Args:
            task_doc: Task MongoDB document.
            workflow_doc: Workflow definition with ``nodes`` and ``edges``.

        Returns:
            Final variable pool snapshot (or partial snapshot on failure).
        """
        self._task_id = task_doc["_id"]
        self._nodes = workflow_doc.get("nodes", [])
        self._node_map = {n["node_id"]: n for n in self._nodes}
        self._edges = workflow_doc.get("edges", [])

        # Build edge index
        self._out_edges.clear()
        self._in_edges.clear()
        for edge in self._edges:
            src = edge["source"]
            tgt = edge["target"]
            self._out_edges.setdefault(src, []).append(edge)
            self._in_edges.setdefault(tgt, []).append(edge)

        # Back-fill next_nodes from legacy edges (backward compat)
        self._migrate_edges_to_next_nodes()

        # Initialise variable pool
        self._pool = VariablePool(initial={"input": task_doc.get("input", {})})
        self._completed_nodes.clear()

        # Mark Task as running
        await TaskService.transition_task(
            task_id=self._task_id,
            to_status=TaskStatus.RUNNING,
            triggered_by="system",
            triggered_by_type="system",
            timeline_event_type="started",
        )

        try:
            # Find start node(s) — nodes with no incoming edges
            start_nodes = self._find_start_nodes()
            if not start_nodes:
                raise ValueError("工作流没有 start 节点")

            # Execute from each start node
            for start_id in start_nodes:
                await self._execute_node(start_id)

            # Mark Task as completed
            final_output = self._pool.get_all()
            await TaskService.transition_task(
                task_id=self._task_id,
                to_status=TaskStatus.COMPLETED,
                triggered_by="system",
                triggered_by_type="system",
                timeline_event_type="completed",
                timeline_data={"output": final_output},
            )

            return final_output

        except WorkflowPausedError:
            # Graceful pause — not an error, return current state.
            logger.info("workflow_paused", task_id=self._task_id)
            return self._pool.get_all() if self._pool else {}

        except Exception as exc:
            logger.error("workflow_execution_failed", task_id=self._task_id, error=str(exc))

            # Mark Task as failed — wrap in try/except so even if the
            # transition itself raises (e.g. version conflict due to
            # concurrent access), the task doesn't get stuck in RUNNING.
            try:
                await TaskService.transition_task(
                    task_id=self._task_id,
                    to_status=TaskStatus.FAILED,
                    triggered_by="system",
                    triggered_by_type="system",
                    timeline_event_type="failed",
                    timeline_data={"error": str(exc)},
                    error_info={
                        "node_id": getattr(exc, "node_id", None),
                        "node_type": getattr(exc, "node_type", None),
                        "error_message": str(exc),
                        "error_code": "WORKFLOW_EXECUTION_ERROR",
                    },
                )
            except Exception as transition_exc:
                # If transition_task itself fails, at least append a
                # timeline event so there is a record in the DB.
                logger.error(
                    "workflow_failed_transition_failed",
                    task_id=self._task_id,
                    transition_error=str(transition_exc),
                    original_error=str(exc),
                )
                try:
                    from app.db.mongodb import get_database
                    from app.models.task import TimelineEvent
                    from app.models.task import utc_now as _utc_now

                    await get_database()["tasks"].update_one(
                        {"_id": self._task_id},
                        {
                            "$push": {
                                "timeline": TimelineEvent(
                                    timestamp=_utc_now(),
                                    event_type="failed_transition_error",
                                    data={
                                        "original_error": str(exc),
                                        "transition_error": str(transition_exc),
                                        "error_code": "WORKFLOW_EXECUTION_ERROR",
                                    },
                                    actor="system",
                                ).model_dump()
                            },
                            "$set": {"updated_at": _utc_now()},
                        },
                    )
                except Exception:
                    logger.exception(
                        "workflow_failed_timeline_append_failed",
                        task_id=self._task_id,
                    )

            return self._pool.get_all() if self._pool else {}

    async def resume_from_checkpoint(self, task_id: str) -> dict[str, Any]:
        """Resume workflow execution from a saved checkpoint.

        Called after a Human node intervention (approve/skip) or after
        server restart when a task is still in waiting_human status.

        Steps:
        1. Load task + workflow from DB
        2. Restore _completed_nodes and _pool from checkpoint
        3. Find downstream nodes of the paused Human node
        4. Continue execution from those downstream nodes
        5. On completion → COMPLETED + clear checkpoint
        6. On encountering another human → WorkflowPausedError (new checkpoint saved)
        7. On error → FAILED
        """
        from app.db.mongodb import get_database

        db = get_database()

        # Load task
        task_doc = await db["tasks"].find_one({"_id": task_id})
        if task_doc is None:
            logger.error("resume_checkpoint_task_not_found", task_id=task_id)
            return {}

        checkpoint_data = task_doc.get("checkpoint")
        if not checkpoint_data:
            logger.error("resume_checkpoint_not_found", task_id=task_id)
            return {}

        # Load workflow
        workflow_id = task_doc.get("workflow_id", "")
        workflow_doc = await db["workflows"].find_one({"_id": workflow_id})
        if workflow_doc is None:
            logger.error("resume_checkpoint_workflow_not_found", task_id=task_id, workflow_id=workflow_id)
            return {}

        # Initialize engine state
        self._task_id = task_id
        self._nodes = workflow_doc.get("nodes", [])
        self._node_map = {n["node_id"]: n for n in self._nodes}
        self._edges = workflow_doc.get("edges", [])

        # Build edge index
        self._out_edges.clear()
        self._in_edges.clear()
        for edge in self._edges:
            src = edge["source"]
            tgt = edge["target"]
            self._out_edges.setdefault(src, []).append(edge)
            self._in_edges.setdefault(tgt, []).append(edge)

        # Back-fill next_nodes from legacy edges
        self._migrate_edges_to_next_nodes()

        # Restore state from checkpoint
        paused_node_id = checkpoint_data.get("paused_at_node", "")
        self._completed_nodes = set(checkpoint_data.get("completed_nodes", []))
        # Add the paused human node to completed (it was approved/skipped)
        self._completed_nodes.add(paused_node_id)

        # Restore variable pool
        variable_snapshot = checkpoint_data.get("variable_snapshot", {})
        self._pool = VariablePool(initial=variable_snapshot)

        logger.info(
            "resume_from_checkpoint",
            task_id=task_id,
            paused_node=paused_node_id,
            completed_count=len(self._completed_nodes),
        )

        try:
            # Find downstream nodes of the paused human node
            downstream = self._get_downstream_nodes(paused_node_id)

            if not downstream:
                # No downstream nodes — workflow is complete
                logger.info("resume_checkpoint_no_downstream", task_id=task_id)
                final_output = self._pool.get_all()
                await TaskService.transition_task(
                    task_id=task_id,
                    to_status=TaskStatus.COMPLETED,
                    triggered_by="system",
                    triggered_by_type="system",
                    timeline_event_type="completed",
                    timeline_data={"output": final_output, "resumed_from_checkpoint": True},
                )
                # Clear checkpoint
                await db["tasks"].update_one(
                    {"_id": task_id},
                    {"$set": {"checkpoint": None, "updated_at": utc_now()}},
                )
                return final_output

            # Execute from downstream nodes
            for next_node_id in downstream:
                await self._execute_node(next_node_id)

            # Workflow completed successfully
            final_output = self._pool.get_all()
            await TaskService.transition_task(
                task_id=task_id,
                to_status=TaskStatus.COMPLETED,
                triggered_by="system",
                triggered_by_type="system",
                timeline_event_type="completed",
                timeline_data={"output": final_output, "resumed_from_checkpoint": True},
            )
            # Clear checkpoint
            await db["tasks"].update_one(
                {"_id": task_id},
                {"$set": {"checkpoint": None, "updated_at": utc_now()}},
            )
            return final_output

        except WorkflowPausedError:
            # Encountered another human node — new checkpoint already saved
            logger.info("resume_checkpoint_paused_again", task_id=task_id)
            return self._pool.get_all() if self._pool else {}

        except Exception as exc:
            logger.error("resume_checkpoint_failed", task_id=task_id, error=str(exc))
            try:
                await TaskService.transition_task(
                    task_id=task_id,
                    to_status=TaskStatus.FAILED,
                    triggered_by="system",
                    triggered_by_type="system",
                    timeline_event_type="failed",
                    timeline_data={"error": str(exc), "resumed_from_checkpoint": True},
                    error_info={
                        "node_id": getattr(exc, "node_id", None),
                        "node_type": getattr(exc, "node_type", None),
                        "error_message": str(exc),
                        "error_code": "WORKFLOW_RESUME_ERROR",
                    },
                )
            except Exception as transition_exc:
                logger.error(
                    "resume_checkpoint_failed_transition_failed",
                    task_id=task_id,
                    transition_error=str(transition_exc),
                    original_error=str(exc),
                )
            return self._pool.get_all() if self._pool else {}

    def _get_downstream_nodes(self, node_id: str) -> list[str]:
        """Get downstream node IDs of a given node.

        Prefers config.next_nodes, falls back to legacy edges.
        """
        node = self._node_map.get(node_id)
        if node is None:
            return []

        config = node.get("config", {})
        next_nodes = config.get("next_nodes")
        if next_nodes:
            return [nxt["target"] for nxt in next_nodes if nxt.get("target")]

        # Fallback to legacy edges
        outgoing = self._out_edges.get(node_id, [])
        return [edge["target"] for edge in outgoing if edge.get("target")]

    # ── Internal: DAG execution ──

    def _find_start_nodes(self) -> list[str]:
        """Find start nodes — nodes with type == 'start'.

        Previously relied on "no incoming edges" heuristic; now uses the
        explicit node type so that even isolated / mis-wired start nodes
        are correctly identified.
        """
        return [n["node_id"] for n in self._nodes if n.get("type") == "start"]

    def _find_end_nodes(self) -> list[str]:
        """Find end nodes — nodes with type == 'end'."""
        return [n["node_id"] for n in self._nodes if n.get("type") == "end"]

    def _migrate_edges_to_next_nodes(self) -> None:
        """Back-fill ``config.next_nodes`` from legacy ``edges``.

        For each ordinary node (start / agent / tool / end / human / subflow)
        that does *not* yet have ``next_nodes`` in its config, derive the list
        from matching outgoing edges in ``self._edges``.

        Gateway and parallel nodes manage their own routing internally
        (``conditions[].target`` / ``branches[].start_node``) and are skipped.
        """
        _skip_types = {"gateway", "parallel"}

        for node in self._nodes:
            if node.get("type") in _skip_types:
                continue
            config = node.setdefault("config", {})
            if config.get("next_nodes"):
                # Already has next_nodes — nothing to do
                continue
            node_id = node["node_id"]
            next_nodes: list[dict[str, Any]] = []
            for edge in self._out_edges.get(node_id, []):
                next_nodes.append({
                    "target": edge["target"],
                    "label": edge.get("label", ""),
                    "condition": edge.get("condition"),
                })
            if next_nodes:
                config["next_nodes"] = next_nodes

    async def _execute_node(self, node_id: str) -> NodeResult | None:
        """Execute a single node and its downstream dependencies.

        Returns the node result, or ``None`` if already executed / skipped.
        """
        if node_id in self._completed_nodes:
            return None

        node = self._node_map.get(node_id)
        if node is None:
            logger.warning("node_not_found", node_id=node_id)
            return None

        node_type = node.get("type", "")
        node_config = node.get("config", {})

        # Record node start in timeline
        await TaskService.append_timeline_event(
            task_id=self._task_id,
            event_type="node_start",
            data={"node_id": node_id, "node_type": node_type},
        )

        # Get executor
        executor = get_node_executor(node_type, node_id, node_config)

        # Resolve config expressions before execution
        variables = self._pool.get_all() if self._pool else {}
        engine = ExpressionEngine(variables)

        # Execute
        result = await executor.execute(variables)

        if result.success:
            # Store output in variable pool
            if self._pool is not None:
                self._pool.set(node_id, result.output)

            self._completed_nodes.add(node_id)

            # Record node complete
            await TaskService.append_timeline_event(
                task_id=self._task_id,
                event_type="node_complete",
                data={"node_id": node_id, "node_type": node_type, "output_summary": _summarise_output(result.output)},
            )

            # Handle human: transition to waiting_human and pause execution
            if node_type == "human" and result.output.get("status") == "waiting_human":
                await TaskService.transition_task(
                    task_id=self._task_id,
                    to_status=TaskStatus.WAITING_HUMAN,
                    triggered_by="system",
                    triggered_by_type="system",
                    timeline_event_type="waiting_human",
                    timeline_data={
                        "node_id": node_id,
                        "title": result.output.get("title", ""),
                        "description": result.output.get("description", ""),
                    },
                )

                # Save checkpoint to DB for later resume
                timeout_ms = result.output.get("timeout_ms", 0)
                timeout_action = result.output.get("timeout_action", "fail")
                timeout_deadline = None
                if timeout_ms > 0:
                    timeout_deadline = utc_now() + timedelta(milliseconds=timeout_ms)

                checkpoint = Checkpoint(
                    paused_at_node=node_id,
                    completed_nodes=list(self._completed_nodes),
                    variable_snapshot=self._pool.snapshot() if self._pool else {},
                    human_context={
                        "node_id": node_id,
                        "title": result.output.get("title", ""),
                        "description": result.output.get("description", ""),
                        "options": result.output.get("options", []),
                        "timeout_ms": timeout_ms,
                        "timeout_action": timeout_action,
                    },
                    timeout_deadline=timeout_deadline,
                    timeout_action=timeout_action,
                )

                from app.db.mongodb import get_database
                db = get_database()
                await db["tasks"].update_one(
                    {"_id": self._task_id},
                    {
                        "$set": {
                            "checkpoint": checkpoint.model_dump(mode="json"),
                            "variables": self._pool.snapshot() if self._pool else {},
                            "updated_at": utc_now(),
                        }
                    },
                )
                logger.info(
                    "checkpoint_saved",
                    task_id=self._task_id,
                    node_id=node_id,
                    timeout_deadline=str(timeout_deadline),
                )

                # Start timeout monitor
                if timeout_ms > 0:
                    from app.engine.workflow.nodes.human import (
                        get_human_timeout_monitor,
                    )
                    await get_human_timeout_monitor().start_monitor(
                        task_id=self._task_id,
                        node_id=node_id,
                        timeout_ms=timeout_ms,
                        timeout_action=timeout_action,
                    )

                # Stop execution — wait for external intervention
                raise WorkflowPausedError(
                    node_id=node_id,
                    node_type=node_type,
                    message=f"等待人工审批: {result.output.get('title', '')}",
                )

            # Handle gateway: follow selected branch only
            if node_type == "gateway" and result.selected_branch:
                await self._execute_node(result.selected_branch)
                return result

            # Handle parallel: execute all branch start nodes
            if node_type == "parallel":
                start_nodes = result.output.get("start_nodes", {})
                join_strategy = result.output.get("join_strategy", "all")
                join_count = result.output.get("join_count")
                branch_ids = result.output.get("branches", [])

                coros = [self._execute_node(sn) for sn in start_nodes.values() if sn]

                if join_strategy == "any":
                    # any: wait for first completion, cancel the rest
                    tasks = [asyncio.ensure_future(c) for c in coros]
                    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for t in pending:
                        t.cancel()
                    list(done)  # consume results
                elif join_strategy == "n-of-m" and join_count and join_count > 0:
                    # n-of-m: wait until join_count branches complete
                    tasks = [asyncio.ensure_future(c) for c in coros]
                    done_tasks: set[asyncio.Task] = set()
                    pending_tasks = set(tasks)
                    while len(done_tasks) < join_count and pending_tasks:
                        newly_done, pending_tasks = await asyncio.wait(
                            pending_tasks, return_when=asyncio.FIRST_COMPLETED,
                        )
                        done_tasks.update(newly_done)
                    for t in pending_tasks:
                        t.cancel()
                    list(done_tasks)
                else:
                    # all (default): wait for all branches
                    await asyncio.gather(*coros, return_exceptions=True)

                logger.debug(
                    "parallel_complete",
                    node_id=node_id,
                    branches=len(branch_ids),
                    join_strategy=join_strategy,
                )
                return result

            # Follow outgoing edges — prefer config.next_nodes, fallback to legacy edges
            next_nodes = node_config.get("next_nodes")
            if next_nodes:
                # New path: read from node config
                for nxt in next_nodes:
                    target_id = nxt["target"]
                    condition = nxt.get("condition")
                    if condition:
                        cond_result = engine.resolve_bool(condition)
                        if not cond_result:
                            continue
                    await self._execute_node(target_id)
            else:
                # Legacy fallback: read from workflow-level edges
                outgoing = self._out_edges.get(node_id, [])
                for edge in outgoing:
                    target_id = edge["target"]
                    condition = edge.get("condition")
                    if condition:
                        cond_result = engine.resolve_bool(condition)
                        if not cond_result:
                            continue
                    await self._execute_node(target_id)

        else:
            # Node failed — propagate error
            self._completed_nodes.add(node_id)
            await TaskService.append_timeline_event(
                task_id=self._task_id,
                event_type="node_failed",
                data={
                    "node_id": node_id,
                    "node_type": node_type,
                    "error": result.error_message,
                },
            )
            raise WorkflowNodeError(
                node_id=node_id,
                node_type=node_type,
                message=result.error_message,
            )

        return result


def _summarise_output(output: dict[str, Any], max_len: int = 200) -> str:
    """Create a short summary of a node's output for timeline logging."""
    text = str(output)
    if len(text) > max_len:
        return text[:max_len] + "..."
    return text


class WorkflowNodeError(Exception):
    """Raised when a workflow node execution fails."""

    def __init__(self, node_id: str, node_type: str, message: str) -> None:
        self.node_id = node_id
        self.node_type = node_type
        super().__init__(message)


class WorkflowPausedError(Exception):
    """Raised when a workflow pauses for human intervention (not an error)."""

    def __init__(self, node_id: str, node_type: str, message: str) -> None:
        self.node_id = node_id
        self.node_type = node_type
        self.pause_message = message
        super().__init__(message)

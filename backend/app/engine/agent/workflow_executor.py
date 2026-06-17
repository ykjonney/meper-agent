"""Task management tools — injected as built-in tools for all Agents.

These tools allow the Agent to query, create, and manage workflow
Tasks.  They are always available to every Agent alongside built-in
tools (bash, read, write).

All tools are async functions decorated with ``@tool`` so LangChain
calls them via ``ainvoke`` inside the REACT loop.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Any

from langchain_core.tools import BaseTool, tool
from loguru import logger
from pydantic import BeforeValidator

from app.models.task import TaskStatus
from app.services.task_service import TaskService

# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

_SERIALISER_KWARGS: dict[str, Any] = {
    "ensure_ascii": False,
    "default": str,
}


def _to_json(obj: Any) -> str:
    """Serialize *obj* to a JSON string safe for LLM consumption."""
    return json.dumps(obj, **_SERIALISER_KWARGS)


# ---------------------------------------------------------------------------
# LLM params coercion — LLMs sometimes pass dict params as a JSON string.
# The schema still exposes ``dict`` so the LLM isn't confused, but we
# transparently parse a JSON string if we receive one.
# ---------------------------------------------------------------------------


def _coerce_params_dict(value: Any) -> dict[str, Any] | None:
    """Accept dict / JSON string / None and normalise to dict | None.

    Raises ``ValueError`` if the string isn't valid JSON or parses to a
    non-dict (list, scalar, etc.).
    """
    if value is None:
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"params 不是合法的 JSON 字符串: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError(
                f"params 必须是 dict，实际解析为 {type(parsed).__name__}"
            )
        return parsed
    raise ValueError(
        f"params 类型错误：期望 dict 或 JSON 字符串，收到 {type(value).__name__}"
    )


# Type alias used in @tool signatures.  Pydantic resolves the
# BeforeValidator at validation time; the exposed JSON Schema still
# declares ``object`` (plus ``null``), so the LLM sees the same shape.
ParamsDict = Annotated[dict[str, Any] | None, BeforeValidator(_coerce_params_dict)]


def _from_json(s: str) -> Any:
    """Parse a JSON string, returning the raw string on failure."""
    try:
        return json.loads(s)
    except (json.JSONDecodeError, TypeError):
        return s


def _serialise_dt(dt: Any) -> str:
    """Serialize a datetime-like value to ISO string."""
    if dt is None:
        return ""
    if isinstance(dt, datetime):
        return dt.isoformat()
    return str(dt)


def _sanitise_task(doc: dict) -> dict:
    """Strip internal fields from a Task document."""
    result: dict[str, Any] = {
        "task_id": doc["_id"],
        "workflow_id": doc.get("workflow_id", ""),
        "status": doc.get("status", ""),
        "created_by": doc.get("created_by", ""),
        "created_at": _serialise_dt(doc.get("created_at")),
        "updated_at": _serialise_dt(doc.get("updated_at")),
    }
    # Add output for completed tasks, error for failed tasks
    if doc.get("output"):
        result["output"] = doc["output"]
    if doc.get("error"):
        err = doc["error"]
        result["error"] = (
            err.get("error_message", str(err)) if isinstance(err, dict) else str(err)
        )
    return result


# ---------------------------------------------------------------------------
# Task query / management tools
# ---------------------------------------------------------------------------


@tool
async def task_query(task_id: str) -> str:
    """Query the current execution status and output of a Task.

    Args:
        task_id: ID of the task to query (returned by workflow tools).
    """
    try:
        doc = await TaskService.get_task(task_id)
        if doc is None:
            return _to_json({"error": f"Task {task_id} 不存在"})
        data = _sanitise_task(doc)
        data["type"] = "task_result"
        return _to_json(data)
    except Exception as exc:
        logger.error("task_query_error", task_id=task_id, error=str(exc))
        return _to_json({"error": f"查询 Task 失败: {exc}"})


@tool
async def task_list(
    status: str = "",
    workflow_id: str = "",
    page: int = 1,
    page_size: int = 20,
) -> str:
    """List Tasks with optional filters.

    Args:
        status: Filter by status (pending, running, waiting_human,
            completed, failed, cancelled).  Empty string means all.
        workflow_id: Optional workflow template ID filter.
        page: Page number (1-based).
        page_size: Items per page (max 100).
    """
    try:
        status_enum = None
        if status:
            try:
                status_enum = TaskStatus(status)
            except ValueError:
                return _to_json({"error": f"无效的状态: {status}"})

        docs, total = await TaskService.list_tasks(
            page=page,
            page_size=min(page_size, 100),
            status=status_enum,
            workflow_id=workflow_id or None,
        )

        return _to_json({
            "items": [_sanitise_task(d) for d in docs],
            "total": total,
            "page": page,
            "page_size": min(page_size, 100),
        })
    except Exception as exc:
        logger.error("task_list_error", error=str(exc))
        return _to_json({"error": f"查询 Task 列表失败: {exc}"})


async def _intervene(
    task_id: str,
    action: str,
    reason: str = "",
    version: int = 0,
) -> str:
    """Core intervene logic (shared by task_intervene and cancel_task)."""
    try:
        if version <= 0:
            doc = await TaskService.get_task(task_id)
            if doc is None:
                return _to_json({"error": f"Task {task_id} 不存在"})
            version = doc.get("version", 1)

        action_map: dict[str, TaskStatus] = {
            "approve": TaskStatus.RUNNING,
            "reject": TaskStatus.FAILED,
            "cancel": TaskStatus.CANCELLED,
            "resume": TaskStatus.RUNNING,
            "retry": TaskStatus.PENDING,
        }

        target_status = action_map.get(action)
        if target_status is None:
            return _to_json({
                "error": f"无效的 intervention action: {action}",
                "valid_actions": list(action_map.keys()),
            })

        updated = await TaskService.transition_task(
            task_id=task_id,
            to_status=target_status,
            triggered_by="agent",
            triggered_by_type="agent",
            timeline_event_type=f"intervene_{action}",
            timeline_data={"action": action, "reason": reason},
        )

        logger.info("task_intervened", task_id=task_id, action=action)
        return _to_json({
            "task_id": updated["_id"],
            "status": updated["status"],
            "version": updated.get("version", 0),
            "action": action,
            "message": f"Task {task_id} 已执行 {action} 操作，当前状态: {updated['status']}",
        })
    except Exception as exc:
        logger.error("task_intervene_error", task_id=task_id, action=action, error=str(exc))
        return _to_json({"error": f"干预 Task 失败: {exc}"})


@tool
async def task_intervene(
    task_id: str,
    action: str,
    reason: str = "",
    version: int = 0,
) -> str:
    """Intervene in a running or waiting_human Task.

    Actions:
    - ``approve`` — Approve a waiting_human task (resumes execution)
    - ``reject`` — Reject and fail a waiting_human task
    - ``cancel`` — Cancel a pending/running/waiting_human task
    - ``resume`` — Resume execution (from waiting_human)
    - ``retry`` — Retry a failed task (resets to pending)

    Args:
        task_id: The task to intervene on.
        action: One of: approve, reject, cancel, resume, retry.
        reason: Human-readable reason for the intervention.
        version: Expected version for optimistic locking (0 = auto-detect).
    """
    return await _intervene(
        task_id=task_id, action=action, reason=reason, version=version
    )


@tool
async def cancel_task(task_id: str, reason: str = "") -> str:
    """Cancel a pending, running, or waiting_human Task.

    Shortcut for ``task_intervene(task_id, "cancel", reason)``.

    Args:
        task_id: The task to cancel.
        reason: Optional reason for cancellation.
    """
    return await _intervene(task_id=task_id, action="cancel", reason=reason)


async def get_task_timeline(task_id: str) -> str:
    """Get the full timeline of events for a Task.

    The timeline records every state transition, node execution start/
    completion/failure, and human intervention.  Useful for diagnosing
    what happened during workflow execution.

    Args:
        task_id: ID of the task to inspect.
    """
    try:
        doc = await TaskService.get_task(task_id)
        if doc is None:
            return _to_json({"error": f"Task {task_id} 不存在"})

        timeline = doc.get("timeline", [])
        sanitised = [
            {
                "timestamp": _serialise_dt(e.get("timestamp")),
                "event_type": e.get("event_type", ""),
                "data": e.get("data", {}),
                "actor": e.get("actor", ""),
            }
            for e in timeline
        ]

        return _to_json({
            "task_id": task_id,
            "current_status": doc.get("status", ""),
            "events": sanitised,
            "event_count": len(sanitised),
        })
    except Exception as exc:
        logger.error("get_task_timeline_error", task_id=task_id, error=str(exc))
        return _to_json({"error": f"获取 Task 时间线失败: {exc}"})


@tool
async def update_task_variables(task_id: str, variables: str, version: int = 0) -> str:
    """Update the variable pool of a running Task.

    Use this to inject intermediate results or modify execution context
    while a workflow is running.

    Args:
        task_id: The task whose variables to update.
        variables: JSON string of key-value pairs to merge into the
            task's variable pool (e.g. ``'{"checked_by": "Alice"}'``).
        version: Expected version for optimistic locking (0 = auto-detect).
    """
    try:
        parsed = _from_json(variables)
        if not isinstance(parsed, dict):
            return _to_json({"error": "variables 必须是 JSON 对象"})

        if version <= 0:
            doc = await TaskService.get_task(task_id)
            if doc is None:
                return _to_json({"error": f"Task {task_id} 不存在"})
            version = doc.get("version", 1)

        updated = await TaskService.update_variables(
            task_id=task_id,
            variables=parsed,
            version=version,
            triggered_by="agent",
        )

        return _to_json({
            "task_id": updated["_id"],
            "version": updated.get("version", 0),
            "message": f"Task {task_id} 变量已更新",
        })
    except Exception as exc:
        logger.error("update_task_variables_error", task_id=task_id, error=str(exc))
        return _to_json({"error": f"更新 Task 变量失败: {exc}"})


# ---------------------------------------------------------------------------
# Workflow proposal tool — shows a confirmation card to the user
# ---------------------------------------------------------------------------


@tool
async def propose_workflow(
    workflow_name: str,
    params: ParamsDict = None,
) -> str:
    """Propose a workflow to the user by showing a confirmation card.

    Looks up the workflow by name and returns structured info for the
    frontend to render as a confirmation card.  Does NOT create a Task.

    After calling this, just tell the user you found a suitable workflow
    — the system will handle the rest.

    Only call ``dispatch_workflow`` when the user explicitly confirms
    (e.g. says '确认', '好的', '是的').

    Args:
        workflow_name: The name or ID of the workflow to propose.
        params: Input parameters to show in the proposal (optional).
    """
    from app.services.workflow_registry_service import WorkflowRegistryService

    try:
        entry = await WorkflowRegistryService.get_by_name(workflow_name)
        if entry is None:
            entry = await WorkflowRegistryService.get_by_workflow_id(workflow_name)
        if entry is None:
            return _to_json({
                "error": f"工作流 '{workflow_name}' 不存在",
                "available_workflows": [],
            })

        return _to_json({
            "type": "workflow_proposal",
            "workflow_name": entry.get("name", workflow_name),
            "workflow_description": entry.get("description", ""),
            "input_preview": dict(params) if params else {},
            "has_human_node": entry.get("has_human_node", False),
        })
    except Exception as exc:
        logger.error(
            "propose_workflow_error",
            workflow_name=workflow_name,
            error=str(exc),
        )
        return _to_json({"error": f"提议工作流失败: {exc}"})


# ---------------------------------------------------------------------------
# Workflow dispatch — creates a Task after user confirms
# ---------------------------------------------------------------------------


@tool
async def dispatch_workflow(
    workflow_name: str,
    params: ParamsDict = None,
) -> str:
    """Create and dispatch a workflow Task.

    IMPORTANT: Only call this AFTER the user has explicitly confirmed
    they want to proceed (e.g. said '好的', '是的', '确认').

    Looks up the workflow by name, creates a Task, and returns the
    ``task_id``.  After creating the Task, just inform the user and
    stop — do NOT call ``task_query`` unless the user asks about
    progress.

    Args:
        workflow_name: The name of the workflow to dispatch.
        params: Input parameters for the workflow as a dict (optional).
    """
    from app.services.workflow_registry_service import WorkflowRegistryService

    try:
        entry = await WorkflowRegistryService.get_by_name(workflow_name)
        if entry is None:
            entry = await WorkflowRegistryService.get_by_workflow_id(workflow_name)
        if entry is None:
            return _to_json({
                "error": f"工作流 '{workflow_name}' 不存在",
                "available_workflows": [],
            })

        input_data = dict(params) if params else {}
        doc = await TaskService.create_task(
            workflow_id=entry.get("workflow_id") or entry.get("_id", ""),
            input_data=input_data,
            created_by="agent",
            created_by_type="agent",
        )

        result: dict[str, Any] = {
            "type": "task_created",
            "task_id": doc["_id"],
            "workflow_id": doc.get("workflow_id", ""),
            "workflow_name": entry.get("name", workflow_name),
            "workflow_description": entry.get("description", ""),
            "status": doc.get("status", "pending"),
            "has_human_node": entry.get("has_human_node", False),
            "message": (
                f"工作流 '{entry.get('name', workflow_name)}' 已触发，"
                f"Task {doc['_id']} 已创建。"
            ),
        }
        return _to_json(result)
    except Exception as exc:
        logger.error(
            "dispatch_workflow_error",
            workflow_name=workflow_name,
            error=str(exc),
        )
        return _to_json({"error": f"触发工作流失败: {exc}"})


# ---------------------------------------------------------------------------
# Tool list — exported for builder.py injection as built-in tools
# ---------------------------------------------------------------------------

_TASK_TOOLS: list[BaseTool] = [
    propose_workflow,
    dispatch_workflow,
    task_query,
    task_list,
    task_intervene,
    cancel_task,
    update_task_variables,
]

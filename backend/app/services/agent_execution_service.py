"""Agent execution service — business orchestration for invoke/stream/resume.

Encapsulates the session management, message persistence, prompt assembly,
and harness execution that was previously inlined in the API endpoints.
The API layer (agents.py) delegates here for all execution-related flows.
"""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

from langchain_core.messages import SystemMessage
from loguru import logger

from app.core.config import settings
from app.core.errors import NotFoundError, ValidationError
from app.engine.agent.builder import build_system_prompt
from app.schemas.execution import ExecutionRequest, ExecutionResponse, ResumeRequest
from app.services.agent_service import AgentService
from app.services.file_rendering import (
    render_attachments_block,
    render_files_by_ids,
    render_files_by_paths,
)
from app.services.message_converters import (
    extract_final_answer,
    messages_to_timeline_entries,
    safe_json,
)
from app.services.session_service import MessageService, SessionService


class AgentExecutionService:
    """Orchestrates agent execution: session, persistence, prompt, harness."""

    # ------------------------------------------------------------------
    # Invoke (synchronous)
    # ------------------------------------------------------------------

    @staticmethod
    async def invoke(
        agent_id: str,
        body: ExecutionRequest,
        user_id: str,
        *,
        external_call_chain: list[str] | None = None,
    ) -> ExecutionResponse:
        """Execute an agent synchronously and persist the result.

        Returns an ExecutionResponse with the agent's output text.
        """
        from app.engine.harness_integration import invoke as harness_invoke

        exec_doc = await AgentService.get_agent(agent_id)
        if exec_doc is None:
            raise NotFoundError(code="AGENT_NOT_FOUND", message=f"Agent {agent_id} 不存在")

        session_id = await _resolve_session(agent_id, body, user_id)
        request_id = str(uuid.uuid4())
        call_chain = [*(external_call_chain or []), agent_id]

        # Build messages (system prompt + user input with file attachments)
        system_text = await _build_system_prompt_checked(exec_doc)
        user_content = await _build_user_content(body, user_id, session_id)
        initial_messages = _assemble_messages(system_text, user_content)

        # Legacy migration records
        legacy_records = await _load_legacy_records(session_id, body.input)

        initial_state = _build_initial_state(
            agent_id, session_id, user_id, request_id, call_chain,
            external_call_chain, initial_messages,
        )

        result = await harness_invoke(
            exec_doc, initial_state,
            enable_thinking=body.enable_thinking,
            legacy_records=legacy_records,
        )

        # Extract output + persist agent message
        output_text = extract_final_answer(result.get("messages", []))
        timeline = messages_to_timeline_entries(
            result.get("messages", []), enable_thinking=body.enable_thinking,
        )
        await MessageService.add_message(
            session_id=session_id, role="agent", timeline_entries=timeline,
        )

        return ExecutionResponse(
            output=output_text,
            execution_path=result.get("execution_path", "unknown"),
            request_id=request_id,
            agent_id=agent_id,
            session_id=session_id,
            step_count=result.get("step_count", 0),
        )

    # ------------------------------------------------------------------
    # Stream (SSE)
    # ------------------------------------------------------------------

    @staticmethod
    async def stream(
        agent_id: str,
        body: ExecutionRequest,
        user_id: str,
        *,
        external_call_chain: list[str] | None = None,
    ) -> tuple[asyncio.Queue, str, str]:
        """Start a streaming agent execution in the background.

        Returns (event_queue, request_id, session_id). The caller wraps
        the queue into a StreamingResponse. The background task pushes
        SSE-formatted events and persists the agent message on completion.
        """
        from app.engine.harness_integration import stream as harness_stream

        exec_doc = await AgentService.get_agent(agent_id)
        if exec_doc is None:
            raise NotFoundError(code="AGENT_NOT_FOUND", message=f"Agent {agent_id} 不存在")

        session_id = await _resolve_session(agent_id, body, user_id)
        request_id = str(uuid.uuid4())
        call_chain = [*(external_call_chain or []), agent_id]

        system_text = await _build_system_prompt_checked(exec_doc)

        event_queue: asyncio.Queue[str | None] = asyncio.Queue()
        collected_timeline: list[dict] = []

        async def _on_event(event: dict) -> None:
            collected_timeline.append(event)
            await event_queue.put(f"data: {safe_json(event)}\n\n")

        async def _run():
            user_content = await _build_user_content(body, user_id, session_id)
            initial_messages = _assemble_messages(system_text, user_content)
            legacy_records = await _load_legacy_records(session_id, body.input)

            initial_state = _build_initial_state(
                agent_id, session_id, user_id, request_id, call_chain,
                external_call_chain, initial_messages, execution_path="react",
            )
            try:
                result = await harness_stream(
                    exec_doc, initial_state,
                    on_event=_on_event,
                    enable_thinking=body.enable_thinking,
                    legacy_records=legacy_records,
                )
                logger.info(
                    "agent_stream_completed",
                    agent_id=agent_id, request_id=request_id,
                    step_count=result.get("step_count", 0),
                )
            except Exception as exc:
                logger.error("agent_stream_error", agent_id=agent_id, request_id=request_id, error=str(exc))
                logger.exception("agent_stream_error_traceback")
                await event_queue.put(f"data: {safe_json({'type': 'error', 'content': str(exc)})}\n\n")
            finally:
                await _persist_agent_message(session_id, collected_timeline)
                await event_queue.put(
                    f"data: {safe_json({'done': True, 'request_id': request_id, 'session_id': session_id})}\n\n"
                )
                await event_queue.put(None)

        asyncio.create_task(_run())
        return event_queue, request_id, session_id

    # ------------------------------------------------------------------
    # Resume (SSE, after interrupt)
    # ------------------------------------------------------------------

    @staticmethod
    async def resume(
        agent_id: str,
        body: ResumeRequest,
        user_id: str,
    ) -> tuple[asyncio.Queue, str, str]:
        """Resume an interrupted agent and stream the continued execution."""
        from app.engine.harness_integration import resume as harness_resume

        exec_doc = await AgentService.get_agent(agent_id)
        if exec_doc is None:
            raise NotFoundError(code="AGENT_NOT_FOUND", message=f"Agent {agent_id} 不存在")

        request_id = str(uuid.uuid4())
        session_id = body.session_id

        await MessageService.add_message(
            session_id=session_id, role="user", content=body.answer,
        )

        event_queue: asyncio.Queue[str | None] = asyncio.Queue()
        collected_timeline: list[dict] = []

        async def _on_event(event: dict) -> None:
            collected_timeline.append(event)
            await event_queue.put(f"data: {safe_json(event)}\n\n")

        async def _run():
            state = {
                "messages": [], "agent_id": agent_id,
                "session_id": session_id, "user_id": user_id,
            }
            try:
                await harness_resume(
                    exec_doc, state, _on_event, body.answer,
                    enable_thinking=body.enable_thinking,
                )
            except Exception as exc:
                logger.error("agent_resume_error", agent_id=agent_id, error=str(exc))
                logger.exception("agent_resume_error_traceback")
                await event_queue.put(f"data: {safe_json({'type': 'error', 'content': str(exc)})}\n\n")
            finally:
                await _persist_agent_message(
                    session_id, collected_timeline, extra_filter_types=("interrupt",),
                )
                await event_queue.put(
                    f"data: {safe_json({'done': True, 'request_id': request_id, 'session_id': session_id})}\n\n"
                )
                await event_queue.put(None)

        asyncio.create_task(_run())
        return event_queue, request_id, session_id


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_TRANSIENT_EVENT_TYPES = ("text_delta", "thinking_delta", "tool_call_start")


async def _resolve_session(agent_id: str, body: ExecutionRequest, user_id: str) -> str:
    """Resolve or create a session, then persist the user message."""
    session_id = body.session_id or ""
    if not session_id:
        session_doc = await SessionService.create_session(
            user_id=user_id, agent_id=agent_id, title=body.input[:200],
        )
        session_id = session_doc["_id"]
    await MessageService.add_message(
        session_id=session_id, role="user",
        content=body.input, file_ids=body.file_ids or None,
    )
    return session_id


async def _build_system_prompt_checked(exec_doc: dict) -> str:
    """Build system prompt, raising ValidationError on slot issues."""
    try:
        return await build_system_prompt(exec_doc)
    except ValueError as exc:
        raise ValidationError(code="AGENT_PROMPT_SLOT_MISSING", message=str(exc)) from exc


async def _build_user_content(body: ExecutionRequest, user_id: str, session_id: str) -> str:
    """Embed uploaded file contents into the user message text."""
    user_content = body.input
    try:
        if body.file_ids:
            blocks = await render_files_by_ids(body.file_ids)
            if blocks:
                user_content += render_attachments_block(blocks)
        elif body.file_paths:
            from app.engine.tool.workspace import WorkspaceManager
            ws = WorkspaceManager.get_workspace(user_id, session_id)
            blocks = await render_files_by_paths(body.file_paths, ws.root)
            if blocks:
                user_content += render_attachments_block(blocks)
    except Exception:
        pass
    return user_content


def _assemble_messages(system_text: str, user_content: str) -> list:
    """Build the initial messages list (System + User)."""
    messages: list = []
    if system_text:
        messages.append(SystemMessage(content=system_text, id="sys"))
    messages.append({"role": "user", "content": user_content})
    return messages


async def _load_legacy_records(session_id: str, current_input: str) -> list[dict]:
    """Load legacy history records for thread migration (if enabled)."""
    if not session_id or not settings.MIGRATE_LEGACY_SESSIONS:
        return []
    try:
        records = await MessageService.list_messages(session_id)
        return [
            r for r in records
            if r.get("content") != current_input or r.get("role") != "user"
        ]
    except Exception:
        return []


def _build_initial_state(
    agent_id: str,
    session_id: str,
    user_id: str,
    request_id: str,
    call_chain: list[str],
    external_chain: list[str] | None,
    messages: list,
    execution_path: str = "",
) -> dict[str, Any]:
    return {
        "messages": messages,
        "agent_id": agent_id,
        "execution_path": execution_path,
        "request_id": request_id,
        "tool_results": {},
        "step_count": 0,
        "error": None,
        "call_chain": call_chain,
        "current_depth": len(external_chain or []),
        "session_id": session_id,
        "user_id": user_id,
    }


async def _persist_agent_message(
    session_id: str,
    collected_timeline: list[dict],
    *,
    extra_filter_types: tuple[str, ...] = (),
) -> None:
    """Filter transient events and persist the agent message."""
    filter_types = _TRANSIENT_EVENT_TYPES + extra_filter_types
    persistence_timeline = [
        e for e in collected_timeline
        if e.get("type") not in filter_types
    ]
    if persistence_timeline:
        try:
            await MessageService.add_message(
                session_id=session_id, role="agent",
                timeline_entries=persistence_timeline,
            )
        except Exception as exc:
            logger.error("agent_stream_persist_error", error=str(exc))


__all__ = ["AgentExecutionService"]

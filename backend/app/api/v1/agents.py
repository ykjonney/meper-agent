"""Agent API endpoints — CRUD operations for Agent lifecycle management."""
from fastapi import APIRouter, Depends, Header, Query

from app.core.errors import NotFoundError, ValidationError
from app.core.security import get_current_user, require_any_role
from app.engine.agent.builder import build_system_prompt
from app.models.agent import AgentStatus
from app.models.compat import resolve_skill_ids
from app.schemas.agent import (
    AgentCreate,
    AgentListResponse,
    AgentResponse,
    AgentUpdate,
)
from app.schemas.execution import (
    ExecutionRequest,
    ExecutionResponse,
    PreviewRequest,
    PreviewResponse,
)
from app.schemas.user import UserResponse
from app.services.agent_service import AgentService

router = APIRouter(
    prefix="/agents",
    tags=["agents"],
    dependencies=[Depends(get_current_user)],
)


def _history_to_langchain_messages(records: list[dict]) -> list:
    """Convert persisted session messages to LangChain message objects.

    Reconstructs tool_call → tool_result → final_answer sequences from
    ``timeline_entries`` so the LLM sees full multi-turn context including
    previous tool invocations and workflow previews.
    """
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

    result: list = []
    call_idx = 0

    for record in records:
        role = record.get("role", "")
        content = record.get("content", "")
        timeline = record.get("timeline_entries", [])

        if role == "user":
            if content:
                result.append(HumanMessage(content=content))
        elif role == "agent":
            if not timeline:
                # Plain text-only response (before timeline support)
                if content:
                    result.append(AIMessage(content=content))
                continue

            # Reconstruct from timeline entries in order
            for entry in timeline:
                etype = entry.get("type", "")
                if etype == "tool_call":
                    call_idx += 1
                    tid = f"history_call_{call_idx}"
                    result.append(
                        AIMessage(
                            content="",
                            tool_calls=[{
                                "name": entry.get("tool_name", ""),
                                "args": entry.get("args", {}),
                                "id": tid,
                            }],
                        )
                    )
                elif etype == "tool_result":
                    tid = f"history_call_{call_idx}"
                    result.append(
                        ToolMessage(
                            content=entry.get("content", ""),
                            tool_call_id=tid,
                        )
                    )
                elif etype == "final_answer":
                    result.append(
                        AIMessage(content=entry.get("content", ""))
                    )
                # thinking entries are skipped — they're informational only

    return result


def _doc_to_response(doc: dict) -> AgentResponse:
    """Convert a raw MongoDB document to AgentResponse."""
    # Backward compat: old docs may still have nested llm_config
    llm_config = doc.get("llm_config") or {}
    default_model = doc.get("default_model") or llm_config.get("default_model", "")
    max_retry = doc.get("max_retry") if "max_retry" in doc else llm_config.get("max_retry", 3)

    return AgentResponse(
        id=doc["_id"],
        name=doc["name"],
        description=doc.get("description", ""),
        prompt_slots=doc.get("prompt_slots", {}),
        skill_ids=resolve_skill_ids(doc),
        mcp_connection_ids=doc.get("mcp_connection_ids", []),
        builtin_config=doc.get("builtin_config", []),
        workflow_ids=doc.get("workflow_ids", []),
        knowledge_base_ids=doc.get("knowledge_base_ids", []),
        default_model=default_model,
        max_retry=max_retry,
        status=AgentStatus(doc["status"]),
        created_at=doc["created_at"],
        updated_at=doc["updated_at"],
    )


@router.get(
    "",
    response_model=AgentListResponse,
    summary="List all Agents",
    responses={
        403: {"description": "Forbidden — viewer+ role required"},
    },
)
async def list_agents(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    name: str | None = Query(None, description="Filter by name (substring)"),
    status: AgentStatus | None = Query(None, description="Filter by status"),
    _: UserResponse = Depends(require_any_role("admin", "developer", "operator", "viewer")),
) -> AgentListResponse:
    """List all Agents with pagination and optional filtering."""
    items, total = await AgentService.list_agents(
        page=page,
        page_size=page_size,
        name=name,
        status=status.value if status else None,
    )

    agents = [_doc_to_response(doc) for doc in items]
    return AgentListResponse(items=agents, total=total, page=page, page_size=page_size)


@router.post(
    "",
    response_model=AgentResponse,
    status_code=201,
    summary="Create a new Agent",
    responses={
        403: {"description": "Forbidden — developer+ role required"},
        409: {"description": "Agent name conflict"},
        422: {"description": "Validation error"},
    },
)
async def create_agent(
    body: AgentCreate,
    _: UserResponse = Depends(require_any_role("admin", "developer")),
) -> AgentResponse:
    """Create a new Agent in draft status."""
    doc = await AgentService.create_agent(
        name=body.name,
        description=body.description,
    )
    return _doc_to_response(doc)


@router.get(
    "/{agent_id}",
    response_model=AgentResponse,
    summary="Get Agent details",
    responses={
        403: {"description": "Forbidden — viewer+ role required"},
        404: {"description": "Agent not found"},
    },
)
async def get_agent(
    agent_id: str,
    _: UserResponse = Depends(require_any_role("admin", "developer", "operator", "viewer")),
) -> AgentResponse:
    """Get an Agent by its ID."""
    from app.core.errors import NotFoundError

    doc = await AgentService.get_agent(agent_id)
    if doc is None:
        raise NotFoundError(
            code="AGENT_NOT_FOUND",
            message=f"Agent {agent_id} 不存在",
        )

    return _doc_to_response(doc)


@router.put(
    "/{agent_id}",
    response_model=AgentResponse,
    summary="Update an Agent",
    responses={
        403: {"description": "Forbidden — developer+ role required"},
        404: {"description": "Agent not found"},
        409: {"description": "Name conflict or agent is published (immutable)"},
        422: {"description": "Validation error"},
    },
)
async def update_agent(
    agent_id: str,
    body: AgentUpdate,
    _: UserResponse = Depends(require_any_role("admin", "developer")),
) -> AgentResponse:
    """Update an Agent's configuration.

    **Published agents are immutable** — returns 409 if the agent
    status is ``published``. Use duplicate or archive first.
    """
    from app.core.errors import NotFoundError

    doc = await AgentService.update_agent(
        agent_id=agent_id,
        name=body.name,
        description=body.description,
        prompt_slots=body.prompt_slots,
        skill_ids=body.skill_ids,
        mcp_connection_ids=body.mcp_connection_ids,
        builtin_config=body.builtin_config,
        workflow_ids=body.workflow_ids,
        knowledge_base_ids=body.knowledge_base_ids,
        default_model=body.default_model,
        max_retry=body.max_retry,
    )
    if doc is None:
        raise NotFoundError(
            code="AGENT_NOT_FOUND",
            message=f"Agent {agent_id} 不存在",
        )

    return _doc_to_response(doc)


@router.post(
    "/{agent_id}/publish",
    response_model=AgentResponse,
    summary="Publish an Agent",
    responses={
        403: {"description": "Forbidden — developer+ role required"},
        404: {"description": "Agent not found"},
    },
)
async def publish_agent(
    agent_id: str,
    _: UserResponse = Depends(require_any_role("admin", "developer")),
) -> AgentResponse:
    """Publish an Agent (draft/archived → published)."""
    from app.core.errors import NotFoundError

    doc = await AgentService.publish_agent(agent_id)
    if doc is None:
        raise NotFoundError(
            code="AGENT_NOT_FOUND",
            message=f"Agent {agent_id} 不存在",
        )

    return _doc_to_response(doc)


@router.post(
    "/{agent_id}/archive",
    response_model=AgentResponse,
    summary="Archive an Agent",
    responses={
        403: {"description": "Forbidden — developer+ role required"},
        404: {"description": "Agent not found"},
    },
)
async def archive_agent(
    agent_id: str,
    _: UserResponse = Depends(require_any_role("admin", "developer")),
) -> AgentResponse:
    """Archive an Agent (published → archived)."""
    from app.core.errors import NotFoundError

    doc = await AgentService.archive_agent(agent_id)
    if doc is None:
        raise NotFoundError(
            code="AGENT_NOT_FOUND",
            message=f"Agent {agent_id} 不存在",
        )

    return _doc_to_response(doc)


@router.post(
    "/{agent_id}/duplicate",
    response_model=AgentResponse,
    status_code=201,
    summary="Duplicate an Agent",
    responses={
        403: {"description": "Forbidden — developer+ role required"},
        404: {"description": "Agent not found"},
        409: {"description": "Name conflict — cannot generate unique name"},
    },
)
async def duplicate_agent(
    agent_id: str,
    _: UserResponse = Depends(require_any_role("admin", "developer")),
) -> AgentResponse:
    """Duplicate an Agent. New Agent is always draft."""
    doc = await AgentService.duplicate_agent(agent_id)
    return _doc_to_response(doc)


@router.post(
    "/{agent_id}/preview",
    response_model=PreviewResponse,
    summary="Preview Agent prompt & tools (dry-run)",
    responses={
        403: {"description": "Forbidden — developer+ role required"},
        404: {"description": "Agent not found"},
    },
)
async def preview_agent(
    agent_id: str,
    body: PreviewRequest | None = None,
    _: UserResponse = Depends(require_any_role("admin", "developer")),
) -> PreviewResponse:
    """Preview the fully assembled prompt and tools for an Agent.

    Does **not** invoke the LLM. Returns the exact system prompt,
    message list, and resolved tool definitions that would be sent
    to the model — useful for debugging Agent configuration.
    """
    from app.core.errors import NotFoundError
    from app.engine.agent.builder import preview_agent as _preview_agent
    from app.schemas.execution import ToolPreview

    if body is None:
        body = PreviewRequest()

    doc = await AgentService.get_agent(agent_id)
    if doc is None:
        raise NotFoundError(
            code="AGENT_NOT_FOUND",
            message=f"Agent {agent_id} 不存在",
        )

    result = await _preview_agent(
        agent=doc,
        user_input=body.input,
        enable_thinking=body.enable_thinking,
    )

    tools = [ToolPreview(**t) for t in result["tools"]]

    return PreviewResponse(
        agent_id=agent_id,
        agent_name=doc.get("name", ""),
        model=result["model"],
        system_prompt=result["system_prompt"],
        messages=result["messages"],
        tools=tools,
        tool_summary=result["tool_summary"],
    )


@router.post(
    "/{agent_id}/invoke",
    response_model=ExecutionResponse,
    summary="Invoke an Agent (sync)",
    responses={
        332: {"description": "Forbidden — viewer+ role required"},
        404: {"description": "Agent not found"},
        504: {"description": "Execution timeout (>30s)"},
    },
)
async def invoke_agent(
    agent_id: str,
    body: ExecutionRequest,
    x_call_chain: str | None = Header(None, alias="X-Call-Chain"),
    user: UserResponse = Depends(require_any_role("admin", "developer", "operator", "viewer")),
) -> ExecutionResponse:
    """Invoke an Agent synchronously."""
    import json
    import uuid

    from app.core.errors import NotFoundError
    from app.engine.agent.builder import build_agent_graph
    from app.services.session_service import SessionService

    exec_doc = await AgentService.get_agent(agent_id)
    if exec_doc is None:
        raise NotFoundError(
            code="AGENT_NOT_FOUND",
            message=f"Agent {agent_id} 不存在",
        )

    # Parse optional external call chain from header
    external_chain: list[str] = []
    if x_call_chain:
        try:
            parsed = json.loads(x_call_chain)
            if isinstance(parsed, list):
                external_chain = [str(e) for e in parsed if isinstance(e, str)]
        except (json.JSONDecodeError, TypeError):
            external_chain = []

    call_chain = [*external_chain, agent_id]

    # Resolve or create a session, then persist the user message
    session_id = body.session_id or ""
    if not session_id:
        session_doc = await SessionService.create_session(
            user_id=user.id,
            agent_id=agent_id,
            title=body.input[:200],
        )
        session_id = session_doc["_id"]

    from app.services.session_service import MessageService

    await MessageService.add_message(
        session_id=session_id,
        role="user",
        content=body.input,
    )

    request_id = str(uuid.uuid4())
    graph = await build_agent_graph(exec_doc, enable_thinking=body.enable_thinking)
    config = {"configurable": {"thread_id": session_id}}

    # Build system prompt with tool declarations
    from langchain_core.messages import SystemMessage

    system_text = await build_system_prompt(exec_doc)

    initial_messages: list = []
    if system_text:
        initial_messages.append(SystemMessage(content=system_text))
    initial_messages.append({"role": "user", "content": body.input})

    initial_state = {
        "messages": initial_messages,
        "agent_id": agent_id,
        "execution_path": "",
        "request_id": request_id,
        "tool_results": {},
        "step_count": 0,
        "error": None,
        "call_chain": call_chain,
        "current_depth": len(external_chain),
        "session_id": session_id,
        "user_id": user.id,
    }
    result = await graph.ainvoke(initial_state, config=config)

    # Extract the final answer text from the last AIMessage
    output_text = _extract_final_answer(result.get("messages", []))

    # Persist the agent message (text + structured timeline events)
    timeline_entries = _messages_to_timeline_entries(
        result.get("messages", []),
        enable_thinking=body.enable_thinking,
    )
    await MessageService.add_message(
        session_id=session_id,
        role="agent",
        content=output_text,
        timeline_entries=timeline_entries,
    )

    return ExecutionResponse(
        output=output_text,
        execution_path=result.get("execution_path", "unknown"),
        request_id=request_id,
        agent_id=agent_id,
        session_id=session_id,
        step_count=result.get("step_count", 0),
    )


@router.post(
    "/{agent_id}/stream",
    summary="Invoke an Agent (SSE stream)",
    responses={
        403: {"description": "Forbidden — viewer+ role required"},
        404: {"description": "Agent not found"},
    },
)
async def stream_agent(
    agent_id: str,
    body: ExecutionRequest,
    x_call_chain: str | None = Header(None, alias="X-Call-Chain"),
    user: UserResponse = Depends(require_any_role("admin", "developer", "operator", "viewer")),
):
    """Invoke an Agent and stream results via Server-Sent Events."""
    import json
    import uuid

    from fastapi.responses import StreamingResponse

    from app.core.errors import NotFoundError
    from app.engine.agent.builder import run_agent_streaming
    from app.services.session_service import MessageService, SessionService

    exec_doc = await AgentService.get_agent(agent_id)
    if exec_doc is None:
        raise NotFoundError(
            code="AGENT_NOT_FOUND",
            message=f"Agent {agent_id} 不存在",
        )

    # Parse optional external call chain from header
    external_chain: list[str] = []
    if x_call_chain:
        try:
            parsed = json.loads(x_call_chain)
            if isinstance(parsed, list):
                external_chain = [str(e) for e in parsed if isinstance(e, str)]
        except (json.JSONDecodeError, TypeError):
            external_chain = []

    call_chain = [*external_chain, agent_id]

    # Resolve or create a session, then persist the user message
    session_id = body.session_id or ""
    if not session_id:
        session_doc = await SessionService.create_session(
            user_id=user.id,
            agent_id=agent_id,
            title=body.input[:200],
        )
        session_id = session_doc["_id"]

    await MessageService.add_message(
        session_id=session_id,
        role="user",
        content=body.input,
    )

    request_id = str(uuid.uuid4())

    # Build system prompt with tool declarations (Skills + MCP + Builtin + Workflow)
    from langchain_core.messages import SystemMessage

    try:
        system_text = await build_system_prompt(exec_doc)
    except ValueError as exc:
        raise ValidationError(
            code="AGENT_PROMPT_SLOT_MISSING",
            message=str(exc),
        ) from exc

    # Queues for SSE events and final state
    import asyncio

    from loguru import logger as _logger

    event_queue: asyncio.Queue[str | None] = asyncio.Queue()

    # Accumulate events for message persistence
    collected_timeline: list[dict] = []
    collected_text_parts: list[str] = []

    async def _on_event(event: dict) -> None:
        """Callback: push REACT executor events to the SSE queue."""
        collected_timeline.append(event)
        if event.get("type") == "final_answer_delta":
            collected_text_parts.append(event.get("content", ""))
        elif event.get("type") == "final_answer":
            # Final answer not collected as text (already in deltas) but
            # kept in timeline for non-streaming clients / history replay
            pass
        await event_queue.put(f"data: {_safe_json(event)}\n\n")

    async def _run_agent():
        """Background task: execute the streaming REACT loop."""
        initial_messages_stream: list = []
        if system_text:
            initial_messages_stream.append(SystemMessage(content=system_text))

        # Load session history so the LLM sees previous turns
        if session_id:
            try:
                history_records = await MessageService.list_messages(session_id)
                # Filter out the message we just added (current user input)
                history_records = [
                    r for r in history_records
                    if r.get("content") != body.input or r.get("role") != "user"
                ]
                history_msgs = _history_to_langchain_messages(history_records)
                initial_messages_stream.extend(history_msgs)
            except Exception:
                pass  # History loading is best-effort

        initial_messages_stream.append({"role": "user", "content": body.input})

        initial_state = {
            "messages": initial_messages_stream,
            "agent_id": agent_id,
            "execution_path": "react",
            "request_id": request_id,
            "tool_results": {},
            "step_count": 0,
            "error": None,
            "call_chain": call_chain,
            "current_depth": len(external_chain),
            "session_id": session_id,
            "user_id": user.id,
        }
        try:
            result = await run_agent_streaming(
                exec_doc, initial_state,
                on_event=_on_event,
                enable_thinking=body.enable_thinking,
            )
            _logger.info(
                "agent_stream_completed",
                agent_id=agent_id,
                request_id=request_id,
                step_count=result.get("step_count", 0),
            )
        except Exception as exc:
            _logger.error(
                "agent_stream_error",
                agent_id=agent_id,
                request_id=request_id,
                error=str(exc),
            )
            await event_queue.put(
                f"data: {_safe_json({'type': 'error', 'content': str(exc)})}\n\n"
            )
        finally:
            # Persist the agent message
            agent_text = "".join(collected_text_parts) if collected_text_parts else ""
            # Deduplicate timeline: keep only consolidated events (not deltas)
            persistence_timeline = [
                e for e in collected_timeline
                if e.get("type") not in ("final_answer_delta", "thinking_delta")
            ]
            if agent_text or persistence_timeline:
                try:
                    await MessageService.add_message(
                        session_id=session_id,
                        role="agent",
                        content=agent_text,
                        timeline_entries=persistence_timeline,
                    )
                except Exception as exc:
                    _logger.error("agent_stream_persist_error", error=str(exc))
            # Signal stream end
            await event_queue.put(
                f"data: {_safe_json({'done': True, 'request_id': request_id, 'session_id': session_id})}\n\n"
            )
            await event_queue.put(None)  # sentinel

    async def _event_stream():
        """SSE generator: yields events from the queue."""
        # Start agent execution in background
        task = asyncio.create_task(_run_agent())
        try:
            while True:
                item = await event_queue.get()
                if item is None:
                    break
                yield item
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Request-Id": request_id,
            "X-Session-Id": session_id,
        },
    )


def _safe_json(obj) -> str:
    """Safely serialize to JSON, falling back to ``str()``."""
    import json

    try:
        return json.dumps(obj, default=str, ensure_ascii=False)
    except Exception:
        return str(obj)


def _extract_final_answer(messages: list) -> str:
    """Extract the final answer text from the message list.

    Finds the last AIMessage with textual content (no tool_calls)
    and returns its content string.
    """
    from langchain_core.messages import AIMessage

    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content and not msg.tool_calls:
            return _safe_str(msg.content)
    # Fallback: return the last message's string representation
    return str(messages[-1]) if messages else ""


def _messages_to_timeline_entries(
    messages: list,
    enable_thinking: bool = False,
) -> list[dict]:
    """Build structured timeline entries for message persistence."""
    return _messages_to_sse_events(messages, enable_thinking=enable_thinking)


def _messages_to_sse_events(
    messages: list,
    enable_thinking: bool = False,
) -> list[dict]:
    """Convert a list of LangChain messages into structured SSE event dicts."""
    from langchain_core.messages import AIMessage, ToolMessage

    events: list[dict] = []
    for msg in messages:
        if isinstance(msg, AIMessage):
            thinking_parts: list[str] = []
            text_parts: list[str] = []

            for piece in _iter_content_blocks(msg):
                ptype = piece.get("type")
                if ptype == "thinking" and enable_thinking:
                    t = piece.get("thinking") or ""
                    if t:
                        thinking_parts.append(_safe_str(t))
                elif ptype == "text":
                    t = piece.get("text") or ""
                    if t:
                        text_parts.append(_safe_str(t))

            for t in thinking_parts:
                events.append({"type": "thinking", "content": t})

            if msg.tool_calls:
                for tc in msg.tool_calls:
                    events.append({
                        "type": "tool_call",
                        "tool_name": tc.get("name", ""),
                        "args": tc.get("args", {}),
                    })

            if msg.tool_calls:
                pass
            elif text_parts:
                events.append({
                    "type": "final_answer",
                    "content": "\n".join(text_parts),
                })
            elif isinstance(msg.content, str) and msg.content.strip():
                events.append({
                    "type": "final_answer",
                    "content": msg.content,
                })

        elif isinstance(msg, ToolMessage):
            events.append({
                "type": "tool_result",
                "tool_name": msg.name or "",
                "content": _safe_str(msg.content),
            })

    return events


def _iter_content_blocks(msg) -> list[dict]:
    """Yield content pieces as dicts with a ``type`` key."""
    blocks: list[dict] = []

    content = getattr(msg, "content", None)

    if isinstance(content, str):
        if content.strip():
            blocks.append({"type": "text", "text": content})
    elif isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                blocks.append(item)
            elif isinstance(item, str) and item.strip():
                blocks.append({"type": "text", "text": item})
            else:
                btype = getattr(item, "type", None)
                if btype == "thinking":
                    blocks.append({
                        "type": "thinking",
                        "thinking": getattr(item, "thinking", ""),
                        "signature": getattr(item, "signature", ""),
                    })
                elif btype == "text":
                    blocks.append({
                        "type": "text",
                        "text": getattr(item, "text", ""),
                    })
                elif btype:
                    blocks.append({"type": btype, **{
                        k: getattr(item, k) for k in ("text", "thinking", "content")
                        if hasattr(item, k)
                    }})

    cb = getattr(msg, "content_blocks", None)
    if cb and not any(b.get("type") == "thinking" for b in blocks):
        for item in cb:
            btype = getattr(item, "type", None)
            if btype == "thinking":
                blocks.insert(0, {
                    "type": "thinking",
                    "thinking": getattr(item, "thinking", ""),
                })
            elif btype == "text" and not any(b.get("type") == "text" for b in blocks):
                blocks.append({
                    "type": "text",
                    "text": getattr(item, "text", ""),
                })

    return blocks


def _safe_str(value) -> str:
    """Coerce any LangChain scalar/value into a plain string."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8")
        except (UnicodeDecodeError, AttributeError):
            return repr(value)
    if isinstance(value, (dict, list)):
        import json
        try:
            return json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            return str(value)
    for field in ("text", "content", "thinking", "value"):
        v = getattr(value, field, None)
        if isinstance(v, str):
            return v
    return str(value)


@router.delete(
    "/{agent_id}",
    status_code=204,
    summary="Delete an Agent",
    responses={
        403: {"description": "Forbidden — developer+ role required"},
        404: {"description": "Agent not found"},
    },
)
async def delete_agent(
    agent_id: str,
    _: UserResponse = Depends(require_any_role("admin", "developer")),
) -> None:
    """Delete an Agent by ID. Checks for active references."""
    from app.core.errors import NotFoundError

    deleted = await AgentService.delete_agent(agent_id)
    if not deleted:
        raise NotFoundError(
            code="AGENT_NOT_FOUND",
            message=f"Agent {agent_id} 不存在",
        )

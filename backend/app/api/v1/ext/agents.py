"""External API — Agent resource discovery and invocation."""
import asyncio

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.api.v1.ext import auth_and_rate_limit
from app.core.auth_apikey import ApiKeyPrincipal
from app.core.errors import NotFoundError
from app.models.agent import AgentStatus
from app.schemas.execution import ExecutionRequest, ResumeRequest
from app.schemas.ext_api import (
    ExtAgentCapabilities,
    ExtAgentListResponse,
    ExtAgentResponse,
    ExtInvokeRequest,
    ExtInvokeResponse,
    ExtResumeRequest,
)
from app.services.agent_execution_service import AgentExecutionService
from app.services.agent_service import AgentService

router = APIRouter(tags=["external-agents"])


def _doc_to_ext_response(doc: dict) -> ExtAgentResponse:
    """Convert an internal Agent document to external response format."""
    llm_config = doc.get("llm_config") or {}
    default_model = doc.get("default_model") or llm_config.get("default_model", "")

    # Resolve tool names from skill_ids (simplified — use IDs as names for now)
    from app.models.compat import resolve_skill_ids
    skill_ids = resolve_skill_ids(doc)

    return ExtAgentResponse(
        id=doc["_id"],
        name=doc["name"],
        description=doc.get("description", ""),
        capabilities=ExtAgentCapabilities(
            tools=skill_ids,
            workflow_ids=doc.get("workflow_ids", []),
        ),
        default_model=default_model,
        status=doc["status"],
    )


# ---------------------------------------------------------------------------
# Resource discovery
# ---------------------------------------------------------------------------


@router.get(
    "/agents",
    response_model=ExtAgentListResponse,
    summary="List accessible Agents",
)
async def list_agents(
    page: int = 1,
    page_size: int = 20,
    principal: ApiKeyPrincipal = Depends(auth_and_rate_limit),
) -> ExtAgentListResponse:
    """List published Agents accessible to this API Key.

    Results are filtered by the Key's ``bindings.agents``.
    Empty bindings = all published Agents.
    """
    principal.require_scope("agents:read")

    # Fetch all published agents
    items, total = await AgentService.list_agents(
        page=page,
        page_size=page_size,
        status=AgentStatus.PUBLISHED.value,
    )

    # Filter by bindings
    allowed_ids = principal.bindings.get("agents", [])
    if allowed_ids:
        items = [d for d in items if d["_id"] in allowed_ids]
        # Recalculate total for filtered results
        if len(items) < page_size:
            total = len(items)

    return ExtAgentListResponse(
        items=[_doc_to_ext_response(d) for d in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/agents/{agent_id}",
    response_model=ExtAgentResponse,
    summary="Get Agent details",
)
async def get_agent(
    agent_id: str,
    principal: ApiKeyPrincipal = Depends(auth_and_rate_limit),
) -> ExtAgentResponse:
    """Get Agent details. Requires ``agents:read`` scope and binding access."""
    principal.require_scope("agents:read")
    principal.require_agent_access(agent_id)

    doc = await AgentService.get_agent(agent_id)
    if doc is None or doc.get("status") != AgentStatus.PUBLISHED.value:
        raise NotFoundError(code="AGENT_NOT_FOUND", message="Agent not found")

    return _doc_to_ext_response(doc)


# ---------------------------------------------------------------------------
# Invocation
# ---------------------------------------------------------------------------


@router.post(
    "/agents/{agent_id}/invoke",
    response_model=ExtInvokeResponse,
    summary="Invoke Agent (synchronous)",
)
async def invoke_agent(
    agent_id: str,
    body: ExtInvokeRequest,
    principal: ApiKeyPrincipal = Depends(auth_and_rate_limit),
) -> ExtInvokeResponse:
    """Invoke an Agent synchronously.

    The Agent processes the message and returns its text response.
    If the Agent triggers a Workflow Task, the task_ids are returned
    for the caller to poll via ``GET /ext/tasks/{task_id}``.
    """
    principal.require_scope("agents:invoke")
    principal.require_agent_access(agent_id)

    # Map external request to internal ExecutionRequest
    exec_request = ExecutionRequest(
        input=body.message,
        session_id=body.session_id,
    )

    result = await AgentExecutionService.invoke(
        agent_id=agent_id,
        body=exec_request,
        user_id=f"{principal.owner_user_id}:{body.visitor_id}" if body.visitor_id else principal.owner_user_id,
    )

    # Extract task_ids from execution result (if any workflow was triggered)
    # The ExecutionResponse doesn't currently include task_ids — for now return empty.
    # TODO: enhance ExecutionResponse to include task_ids from agent execution.
    return ExtInvokeResponse(
        session_id=result.session_id,
        request_id=result.request_id,
        reply=result.output,
        task_ids=[],
        files=[],
    )


@router.post(
    "/agents/{agent_id}/invoke/stream",
    summary="Invoke Agent (SSE stream)",
)
async def stream_agent(
    agent_id: str,
    body: ExtInvokeRequest,
    principal: ApiKeyPrincipal = Depends(auth_and_rate_limit),
) -> StreamingResponse:
    """Invoke an Agent and stream results via Server-Sent Events."""
    principal.require_scope("agents:invoke")
    principal.require_agent_access(agent_id)

    exec_request = ExecutionRequest(
        input=body.message,
        session_id=body.session_id,
    )

    event_queue, request_id, session_id = await AgentExecutionService.stream(
        agent_id=agent_id,
        body=exec_request,
        user_id=f"{principal.owner_user_id}:{body.visitor_id}" if body.visitor_id else principal.owner_user_id,
    )

    async def _event_stream():
        task = asyncio.current_task()
        try:
            while True:
                item = await event_queue.get()
                if item is None:
                    break
                yield item
        finally:
            if task and not task.done():
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


@router.post(
    "/agents/{agent_id}/invoke/resume",
    summary="Resume interrupted Agent (SSE stream)",
)
async def resume_agent(
    agent_id: str,
    body: ExtResumeRequest,
    principal: ApiKeyPrincipal = Depends(auth_and_rate_limit),
) -> StreamingResponse:
    """Resume an Agent that was interrupted (ask_clarification)."""
    principal.require_scope("agents:invoke")
    principal.require_agent_access(agent_id)

    resume_request = ResumeRequest(
        session_id=body.session_id,
        answer=body.answer,
    )

    event_queue, request_id, session_id = await AgentExecutionService.resume(
        agent_id=agent_id,
        body=resume_request,
        user_id=f"{principal.owner_user_id}:{body.visitor_id}" if body.visitor_id else principal.owner_user_id,
    )

    async def _event_stream():
        task = asyncio.current_task()
        try:
            while True:
                item = await event_queue.get()
                if item is None:
                    break
                yield item
        finally:
            if task and not task.done():
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

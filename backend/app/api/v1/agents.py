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
    ResumeRequest,
)
from app.schemas.user import UserResponse
from app.services.agent_service import AgentService

router = APIRouter(
    prefix="/agents",
    tags=["agents"],
    dependencies=[Depends(get_current_user)],
)


# ---------------------------------------------------------------------------
# File attachment rendering — shared by stream / invoke / history paths
# ---------------------------------------------------------------------------

# 单文件注入的最大字符数；与 file_validator.MAX_CONTENT_CHARS 对齐。
_MAX_ATTACHMENT_CHARS = 50_000

# 被视为"文本文件"的 MIME 类型前缀（这些类型才尝试注入内容）。
_TEXT_MIME_PREFIXES = ("text/", "application/json", "application/xml")
_TEXT_MIME_EXACT = {
    "application/javascript", "application/typescript",
    "application/x-yaml", "application/x-sh", "application/sql",
}


def _is_text_mime(mime_type: str, filename: str) -> bool:
    """判断文件是否应视为文本（可安全注入到 LLM 上下文）。"""
    if not mime_type or mime_type == "application/octet-stream":
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        return ext in {
            ".txt", ".md", ".json", ".yaml", ".yml", ".xml", ".html",
            ".csv", ".tsv", ".py", ".js", ".ts", ".jsx", ".tsx",
            ".sh", ".sql", ".log", ".rst", ".toml", ".ini",
        }
    if mime_type in _TEXT_MIME_EXACT:
        return True
    return any(mime_type.startswith(p) for p in _TEXT_MIME_PREFIXES)


def _render_single_file(
    *, file_id: str, name: str, size: int, mime_type: str, content: str | None,
    truncated: bool = False, unavailable_reason: str | None = None,
) -> str:
    """渲染单个附件为结构化 XML 块（与 file_validator.FileVariableValue 同格式）。"""
    import html as _html
    attrs = (
        f'id="{file_id}" '
        f'name="{_html.escape(str(name))}" '
        f'size="{size}" '
        f'mime_type="{_html.escape(str(mime_type))}"'
    )
    if content is None:
        note = unavailable_reason or "content unavailable"
        return f"<file {attrs}>\n[{_html.escape(note)}]\n</file>"
    if truncated:
        return (
            f"<file {attrs}>\n"
            f"{content}\n"
            f"[... truncated at {_MAX_ATTACHMENT_CHARS} chars ...]\n"
            f"</file>"
        )
    return f"<file {attrs}>\n{content}\n</file>"


def _render_attachments_block(file_blocks: list[str]) -> str:
    """把多个 <file> 块包成 <attachments> 并加提示尾巴。"""
    if not file_blocks:
        return ""
    inner = "\n".join(file_blocks)
    return (
        "\n\n<attachments>\n"
        f"{inner}\n"
        "</attachments>\n\n"
        "提示：如需将附件传给 workflow 的 file 类型参数，使用 <file> 标签的 id 属性值 "
        "（例如 'file_01ABC...'）作为参数值。"
    )


async def _render_files_by_ids(file_ids: list[str]) -> list[str]:
    """根据 file_id 列表加载文件，返回渲染好的 <file> 字符串列表。"""
    if not file_ids:
        return []
    from app.services.file_service import FileService
    from app.services.file_storage import LocalFileStorage

    file_svc = FileService(storage=LocalFileStorage())
    blocks: list[str] = []
    for fid in file_ids:
        try:
            loaded = await file_svc.load_content(fid)
        except Exception:
            continue
        if loaded is None:
            continue
        fref, data = loaded
        if not _is_text_mime(fref.mime_type, fref.name):
            blocks.append(_render_single_file(
                file_id=fref.id, name=fref.name, size=fref.size,
                mime_type=fref.mime_type, content=None,
                unavailable_reason=f"binary file ({fref.mime_type})",
            ))
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            blocks.append(_render_single_file(
                file_id=fref.id, name=fref.name, size=fref.size,
                mime_type=fref.mime_type, content=None,
                unavailable_reason="UTF-8 decode failed",
            ))
            continue
        truncated = len(text) > _MAX_ATTACHMENT_CHARS
        if truncated:
            text = text[:_MAX_ATTACHMENT_CHARS]
        blocks.append(_render_single_file(
            file_id=fref.id, name=fref.name, size=fref.size,
            mime_type=fref.mime_type, content=text, truncated=truncated,
        ))
    return blocks


async def _render_files_by_paths(
    file_paths: list[str], workspace_root,
) -> list[str]:
    """Fallback：只有路径时的降级渲染（无 file_id / size / mime_type）。"""
    if not file_paths:
        return []
    from pathlib import Path as _Path

    blocks: list[str] = []
    input_dir = _Path(workspace_root) / "input"
    for rel_path in file_paths:
        abs_path = (input_dir / rel_path).resolve()
        if not str(abs_path).startswith(str(input_dir.resolve())):
            continue
        if not abs_path.is_file():
            continue
        try:
            stat = abs_path.stat()
            data = abs_path.read_bytes()
        except OSError:
            continue
        # 猜测 mime_type
        import mimetypes
        mime, _ = mimetypes.guess_type(abs_path.name)
        mime = mime or "application/octet-stream"
        if not _is_text_mime(mime, abs_path.name):
            blocks.append(_render_single_file(
                file_id="", name=rel_path, size=stat.st_size,
                mime_type=mime, content=None,
                unavailable_reason=f"binary file ({mime})",
            ))
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            blocks.append(_render_single_file(
                file_id="", name=rel_path, size=stat.st_size,
                mime_type=mime, content=None,
                unavailable_reason="UTF-8 decode failed",
            ))
            continue
        truncated = len(text) > _MAX_ATTACHMENT_CHARS
        if truncated:
            text = text[:_MAX_ATTACHMENT_CHARS]
        blocks.append(_render_single_file(
            file_id="", name=rel_path, size=stat.st_size,
            mime_type=mime, content=text, truncated=truncated,
        ))
    return blocks




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
        file_ids=body.file_ids or None,
    )

    request_id = str(uuid.uuid4())
    # Build system prompt with tool declarations
    from langchain_core.messages import SystemMessage

    from app.core.config import settings

    system_text = await build_system_prompt(exec_doc)

    # checkpointer 模式:SystemMessage 用固定 id 覆盖,只喂本轮增量
    initial_messages: list = []
    if system_text:
        initial_messages.append(SystemMessage(content=system_text, id="sys"))

    # Build user message with file attachments
    user_content = body.input
    try:
        if body.file_ids:
            blocks = await _render_files_by_ids(body.file_ids)
            if blocks:
                user_content += _render_attachments_block(blocks)
        elif body.file_paths:
            from app.engine.tool.workspace import WorkspaceManager
            ws = WorkspaceManager.get_workspace(user.id, session_id)
            blocks = await _render_files_by_paths(body.file_paths, ws.root)
            if blocks:
                user_content += _render_attachments_block(blocks)
    except Exception:
        pass  # File embedding is best-effort

    initial_messages.append({"role": "user", "content": user_content})

    # Load legacy history records (for migration only)
    legacy_records: list[dict] = []
    if session_id and settings.MIGRATE_LEGACY_SESSIONS:
        try:
            from app.services.session_service import MessageService
            legacy_records = await MessageService.list_messages(session_id)
            legacy_records = [
                r for r in legacy_records
                if r.get("content") != body.input or r.get("role") != "user"
            ]
        except Exception:
            pass

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
    if settings.USE_HARNESS_ENGINE:
        from app.engine.harness_integration import invoke

        result = await invoke(
            exec_doc, initial_state,
            enable_thinking=body.enable_thinking,
            legacy_records=legacy_records,
        )
    else:
        graph = await build_agent_graph(exec_doc, enable_thinking=body.enable_thinking)
        config = {"configurable": {"thread_id": session_id}}
        result = await graph.ainvoke(initial_state, config=config)

    # Extract the final answer text from the last AIMessage (for the HTTP
    # response only — agent messages no longer store a top-level content).
    output_text = _extract_final_answer(result.get("messages", []))

    # Persist the agent message — full trace in timeline_entries, no content.
    timeline_entries = _messages_to_timeline_entries(
        result.get("messages", []),
        enable_thinking=body.enable_thinking,
    )
    await MessageService.add_message(
        session_id=session_id,
        role="agent",
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
        file_ids=body.file_ids or None,
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

    # Accumulate events for message persistence (agent messages store their
    # full execution trace in timeline_entries — no top-level content field).
    collected_timeline: list[dict] = []

    async def _on_event(event: dict) -> None:
        """Callback: push REACT executor events to the SSE queue."""
        collected_timeline.append(event)
        await event_queue.put(f"data: {_safe_json(event)}\n\n")

    async def _run_agent():
        """Background task: execute the streaming REACT loop."""
        from app.core.config import settings

        # checkpointer 模式:端点只喂本轮增量(System+User)。
        # 历史由 checkpointer 从 thread 自动恢复。
        # SystemMessage 用固定 id="sys" 每轮覆盖(避免非连续 system 累积)。
        # 老session兼容:MIGRATE_LEGACY_SESSIONS=True 时传 legacy_records 给 run_chat。
        initial_messages_stream: list = []
        if system_text:
            initial_messages_stream.append(SystemMessage(content=system_text, id="sys"))

        # Load legacy history records (for migration only, not fed to LLM)
        legacy_records: list[dict] = []
        if session_id and settings.MIGRATE_LEGACY_SESSIONS:
            try:
                legacy_records = await MessageService.list_messages(session_id)
                # Filter out the message we just added (current user input)
                legacy_records = [
                    r for r in legacy_records
                    if r.get("content") != body.input or r.get("role") != "user"
                ]
            except Exception:
                pass  # best-effort

        # Build user message content — embed uploaded file contents directly
        user_content = body.input
        try:
            if body.file_ids:
                blocks = await _render_files_by_ids(body.file_ids)
                if blocks:
                    user_content += _render_attachments_block(blocks)
            elif body.file_paths:
                from app.engine.tool.workspace import WorkspaceManager
                ws = WorkspaceManager.get_workspace(user.id, session_id)
                blocks = await _render_files_by_paths(body.file_paths, ws.root)
                if blocks:
                    user_content += _render_attachments_block(blocks)
        except Exception:
            pass  # File embedding is best-effort

        initial_messages_stream.append({"role": "user", "content": user_content})

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
            if settings.USE_HARNESS_ENGINE:
                from app.engine.harness_integration import stream
                result = await stream(
                    exec_doc, initial_state,
                    on_event=_on_event,
                    enable_thinking=body.enable_thinking,
                    legacy_records=legacy_records,
                )
            else:
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
            _logger.exception("agent_stream_error_traceback")

            await event_queue.put(
                f"data: {_safe_json({'type': 'error', 'content': str(exc)})}\n\n"
            )
        finally:
            # Persist the agent message — no top-level content; the full
            # execution trace (text blocks, tool calls, thinking) is stored
            # in timeline_entries. Delta/start events are transient and
            # filtered out before persistence.
            persistence_timeline = [
                e for e in collected_timeline
                if e.get("type") not in ("text_delta", "thinking_delta", "tool_call_start")
            ]
            if persistence_timeline:
                try:
                    await MessageService.add_message(
                        session_id=session_id,
                        role="agent",
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


@router.post(
    "/{agent_id}/resume",
    summary="Resume an interrupted Agent (SSE stream)",
    responses={
        403: {"description": "Forbidden — viewer+ role required"},
        404: {"description": "Agent not found"},
    },
)
async def resume_agent(
    agent_id: str,
    body: ResumeRequest,
    user: UserResponse = Depends(require_any_role("admin", "developer", "operator", "viewer")),
):
    """Resume an agent that was paused via interrupt (ask_clarification).

    Streams the continued execution via SSE, same event format as /stream.
    """
    import asyncio
    import uuid

    from fastapi.responses import StreamingResponse

    from app.services.session_service import MessageService

    exec_doc = await AgentService.get_agent(agent_id)
    if exec_doc is None:
        raise NotFoundError(
            code="AGENT_NOT_FOUND",
            message=f"Agent {agent_id} 不存在",
        )

    request_id = str(uuid.uuid4())
    session_id = body.session_id

    # Persist the user's answer as a user message
    await MessageService.add_message(
        session_id=session_id,
        role="user",
        content=body.answer,
    )

    event_queue: asyncio.Queue[str | None] = asyncio.Queue()
    collected_timeline: list[dict] = []

    async def _on_event(event: dict) -> None:
        collected_timeline.append(event)
        await event_queue.put(f"data: {_safe_json(event)}\n\n")

    async def _run_resume():
        from loguru import logger as _logger

        from app.engine.harness_integration import resume as resume_exec

        # Build a minimal state for resolve_harness_context (session/user identity)
        state = {
            "messages": [],
            "agent_id": agent_id,
            "session_id": session_id,
            "user_id": user.id,
        }
        try:
            await resume_exec(
                exec_doc, state, _on_event, body.answer,
                enable_thinking=body.enable_thinking,
            )
        except Exception as exc:
            _logger.error("agent_resume_error", agent_id=agent_id, error=str(exc))
            _logger.exception("agent_resume_error_traceback")
            await event_queue.put(
                f"data: {_safe_json({'type': 'error', 'content': str(exc)})}\n\n"
            )
        finally:
            persistence_timeline = [
                e for e in collected_timeline
                if e.get("type") not in ("text_delta", "thinking_delta", "tool_call_start", "interrupt")
            ]
            if persistence_timeline:
                try:
                    await MessageService.add_message(
                        session_id=session_id,
                        role="agent",
                        timeline_entries=persistence_timeline,
                    )
                except Exception as exc:
                    _logger.error("agent_resume_persist_error", error=str(exc))
            await event_queue.put(
                f"data: {_safe_json({'done': True, 'request_id': request_id, 'session_id': session_id})}\n\n"
            )
            await event_queue.put(None)

    async def _event_stream():
        task = asyncio.create_task(_run_resume())
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

            # Text block — emitted before tool calls (matches REACT semantics:
            # the LLM produces text + tool_calls in a single AIMessage).
            if text_parts:
                events.append({"type": "text", "content": "\n".join(text_parts)})
            elif isinstance(msg.content, str) and msg.content.strip() and not msg.tool_calls:
                events.append({"type": "text", "content": msg.content})

            if msg.tool_calls:
                for tc in msg.tool_calls:
                    events.append({
                        "type": "tool_call",
                        "tool_name": tc.get("name", ""),
                        "args": tc.get("args", {}),
                        "id": tc.get("id", ""),
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

    deleted = await AgentService.delete_agent(agent_id)
    if not deleted:
        raise NotFoundError(
            code="AGENT_NOT_FOUND",
            message=f"Agent {agent_id} 不存在",
        )

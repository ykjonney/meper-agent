"""Session API endpoints — chat conversation management."""
from fastapi import APIRouter, Depends, Query

from app.core.errors import NotFoundError
from app.core.security import get_current_user
from app.schemas.session import (
    MessageResponse,
    SessionCreate,
    SessionDetailResponse,
    SessionListResponse,
    SessionResponse,
)
from app.schemas.user import UserResponse
from app.services.session_service import MessageService, SessionService

router = APIRouter(
    prefix="/sessions",
    tags=["sessions"],
    dependencies=[Depends(get_current_user)],
)


def _doc_to_response(doc: dict) -> SessionResponse:
    """Convert a raw MongoDB document to SessionResponse."""
    return SessionResponse(
        _id=doc["_id"],
        user_id=doc["user_id"],
        agent_id=doc["agent_id"],
        title=doc.get("title", ""),
        status=doc.get("status", "active"),
        message_count=doc.get("message_count", 0),
        created_at=doc.get("created_at", ""),
        updated_at=doc.get("updated_at", ""),
    )


def _msg_to_response(doc: dict) -> MessageResponse:
    """Convert a raw MongoDB document to MessageResponse."""
    return MessageResponse(
        _id=doc["_id"],
        session_id=doc["session_id"],
        role=doc["role"],
        content=doc.get("content", ""),
        timeline_entries=doc.get("timeline_entries", []),
        created_at=doc.get("created_at", ""),
    )


@router.post(
    "",
    status_code=201,
    summary="Create a new session",
)
async def create_session(
    body: SessionCreate,
    user: UserResponse = Depends(get_current_user),
) -> SessionResponse:
    """Create a new chat session for the current user."""
    doc = await SessionService.create_session(
        user_id=user.id,
        agent_id=body.agent_id,
        title=body.title or "",
    )
    return _doc_to_response(doc)


@router.get(
    "",
    summary="List user sessions",
)
async def list_sessions(
    agent_id: str | None = Query(None, description="Filter by agent ID"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    user: UserResponse = Depends(get_current_user),
) -> SessionListResponse:
    """List sessions for the current user, optionally filtered by agent."""
    items, total = await SessionService.list_sessions(
        user_id=user.id,
        agent_id=agent_id,
        page=page,
        page_size=page_size,
    )
    return SessionListResponse(
        items=[_doc_to_response(d) for d in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get(
    "/{session_id}",
    summary="Get session detail with messages",
)
async def get_session(
    session_id: str,
    user: UserResponse = Depends(get_current_user),
) -> SessionDetailResponse:
    """Get a session and all its messages."""
    session_doc = await SessionService.get_session(session_id)
    if session_doc is None:
        raise NotFoundError(
            code="SESSION_NOT_FOUND",
            message=f"Session {session_id} 不存在",
        )

    # Verify ownership
    if session_doc["user_id"] != user.id:
        raise NotFoundError(
            code="SESSION_NOT_FOUND",
            message=f"Session {session_id} 不存在",
        )

    messages = await MessageService.list_messages(session_id)
    return SessionDetailResponse(
        session=_doc_to_response(session_doc),
        messages=[_msg_to_response(m) for m in messages],
    )


@router.delete(
    "/{session_id}",
    status_code=204,
    summary="Delete a session",
)
async def delete_session(
    session_id: str,
    user: UserResponse = Depends(get_current_user),
) -> None:
    """Delete a session and all its messages."""
    session_doc = await SessionService.get_session(session_id)
    if session_doc is None:
        raise NotFoundError(
            code="SESSION_NOT_FOUND",
            message=f"Session {session_id} 不存在",
        )

    if session_doc["user_id"] != user.id:
        raise NotFoundError(
            code="SESSION_NOT_FOUND",
            message=f"Session {session_id} 不存在",
        )

    await SessionService.delete_session(session_id)

"""Session and Message API schemas (request/response validation)."""
from pydantic import BaseModel, Field


class SessionCreate(BaseModel):
    """Request body for creating a new session."""

    agent_id: str = Field(..., min_length=1, description="Agent ID to bind to this session")
    title: str | None = Field(default=None, max_length=200, description="Optional session title")


class SessionResponse(BaseModel):
    """Session data returned in API responses."""

    id: str = Field(..., alias="_id")
    user_id: str
    agent_id: str
    title: str
    status: str
    message_count: int
    created_at: str
    updated_at: str

    model_config = {"populate_by_name": True}


class SessionListResponse(BaseModel):
    """Paginated session list response."""

    items: list[SessionResponse]
    total: int
    page: int
    page_size: int


class MessageResponse(BaseModel):
    """Message data returned in API responses."""

    id: str = Field(..., alias="_id")
    session_id: str
    role: str
    content: str
    timeline_entries: list[dict] = []
    created_at: str

    model_config = {"populate_by_name": True}


class SessionDetailResponse(BaseModel):
    """Session detail with messages."""

    session: SessionResponse
    messages: list[MessageResponse]

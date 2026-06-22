"""File management schemas for API responses."""
from pydantic import BaseModel, Field


class FileRefResponse(BaseModel):
    """File reference response schema."""

    id: str = Field(..., alias="_id")
    owner_user_id: str
    storage_key: str
    name: str
    size: int
    mime_type: str
    sha256: str
    origin_kind: str
    origin_id: str
    status: str
    created_at: str
    updated_at: str

    model_config = {
        "populate_by_name": True,
        "from_attributes": True,
    }


class FileRefListResponse(BaseModel):
    """Paginated file list response."""

    items: list[FileRefResponse]
    total: int
    page: int
    page_size: int


class FileUsageResponse(BaseModel):
    """File usage response schema."""

    id: str = Field(..., alias="_id")
    file_id: str
    consumer_kind: str
    consumer_id: str
    granted_at: str
    expires_at: str | None = None

    model_config = {
        "populate_by_name": True,
        "from_attributes": True,
    }

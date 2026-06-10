"""Base model utilities - ULID generation, common timestamps."""
from datetime import UTC, datetime

from ulid import ULID


def generate_id(resource: str) -> str:
    """Generate a ULID-based ID: `{resource}_{ulid}`.

    Example: `agent_01HXYZABCDEF...`
    """
    return f"{resource}_{ULID()}"


def utc_now() -> datetime:
    """Current UTC datetime (timezone-aware)."""
    return datetime.now(UTC)


class BaseModel:
    """Mixin for MongoDB-backed models.

    Provides:
    - ID generation with the appropriate resource prefix
    - Standard `created_at` / `updated_at` timestamps
    """

    @staticmethod
    def new_id(resource: str) -> str:
        return generate_id(resource)

    @staticmethod
    def now() -> datetime:
        return utc_now()

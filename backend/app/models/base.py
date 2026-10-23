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

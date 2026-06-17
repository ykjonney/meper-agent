"""Backward-compatibility helpers for legacy field migrations.

Centralises ``tool_ids → skill_ids`` resolution so that each consumer
only needs a single function call instead of duplicated fallback logic.
"""
from __future__ import annotations


def resolve_skill_ids(doc: dict) -> list[str]:
    """Return the effective skill IDs from a MongoDB agent document.

    Prefers ``skill_ids`` when present and non-empty; falls back to
    the legacy ``tool_ids`` field for documents created before the
    migration.

    Args:
        doc: Raw MongoDB agent document.

    Returns:
        List of tool/skill ID strings (never ``None``).
    """
    skill_ids = doc.get("skill_ids") or []
    if not skill_ids:
        skill_ids = doc.get("tool_ids") or []
    return list(skill_ids)

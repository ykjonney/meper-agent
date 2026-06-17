"""WorkflowRegistryService — CRUD for published workflow templates.

Agents search this registry to find workflows they can instantiate
as Tasks.  Workflows are published here by the Workflow Editor /
Version Management flows (Stories 4-1, 4-6).
"""
from __future__ import annotations

from typing import Any

from loguru import logger
from pymongo import ReturnDocument

from app.core.errors import ConflictError, NotFoundError
from app.db.mongodb import get_database
from app.models.base import utc_now
from app.models.workflow_registry import WorkflowRegistryEntry


class WorkflowRegistryService:
    """Service layer for the workflow registry."""

    COLLECTION = "workflow_registry"

    @staticmethod
    def _collection():
        return get_database()[WorkflowRegistryService.COLLECTION]

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    @staticmethod
    async def register(
        name: str,
        description: str,
        input_schema: dict[str, Any] | None = None,
        workflow_id: str = "",
        has_human_node: bool = False,
        version: str = "1.0",
        tags: list[str] | None = None,
    ) -> dict:
        """Register a published workflow template.

        Args:
            name: Human-readable workflow name.
            description: What this workflow does.
            input_schema: JSON Schema for input parameters.
            workflow_id: Reference to the original workflow template.
            has_human_node: Whether this workflow contains human approval nodes.
            version: Workflow version string.
            tags: Search tags.

        Returns:
            Registered document.

        Raises:
            ConflictError: If a workflow with the same name already exists.
        """
        # Check duplicate name
        existing = await WorkflowRegistryService._collection().find_one({"name": name})
        if existing:
            raise ConflictError(
                code="WORKFLOW_ALREADY_REGISTERED",
                message=f"工作流 '{name}' 已注册",
                details={"name": name},
            )

        entry = WorkflowRegistryEntry(
            name=name,
            description=description,
            input_schema=input_schema or {},
            workflow_id=workflow_id,
            has_human_node=has_human_node,
            version=version,
            tags=tags or [],
        )

        doc = entry.model_dump(by_alias=True)
        result = await WorkflowRegistryService._collection().insert_one(doc)

        logger.info("workflow_registered", name=name, entry_id=entry.id)
        return await WorkflowRegistryService._collection().find_one(
            {"_id": result.inserted_id}
        )

    @staticmethod
    async def get_by_id(entry_id: str) -> dict | None:
        """Get a registry entry by its ID."""
        return await WorkflowRegistryService._collection().find_one({"_id": entry_id})

    @staticmethod
    async def get_by_workflow_id(workflow_id: str) -> dict | None:
        """Get a registry entry by the original workflow template ID."""
        return await WorkflowRegistryService._collection().find_one(
            {"workflow_id": workflow_id}
        )

    @staticmethod
    async def get_by_name(name: str) -> dict | None:
        """Get a registry entry by workflow name."""
        return await WorkflowRegistryService._collection().find_one({"name": name})

    @staticmethod
    async def search(
        query: str,
        limit: int = 20,
    ) -> list[dict]:
        """Search for published workflows by name, description, or tags.

        Uses MongoDB ``$text`` search if a text index exists, otherwise
        falls back to regex matching.

        Args:
            query: Search terms.
            limit: Maximum results.

        Returns:
            List of matching registry documents.
        """
        col = WorkflowRegistryService._collection()

        # Try text search first (requires text index)
        indexes = await col.index_information()
        has_text_index = any(
            idx.get("key", [["_id", 1]])[0][0] == "_fts"
            for idx in indexes.values()
        )

        if has_text_index and query.strip():
            cursor = col.find(
                {"$text": {"$search": query}, "published": True},
                {"score": {"$meta": "textScore"}},
            ).sort([("score", {"$meta": "textScore"})]).limit(limit)
        else:
            # Fallback: regex search
            pattern = query.strip()
            if pattern:
                cursor = col.find({
                    "published": True,
                    "$or": [
                        {"name": {"$regex": pattern, "$options": "i"}},
                        {"description": {"$regex": pattern, "$options": "i"}},
                        {"tags": {"$regex": pattern, "$options": "i"}},
                    ],
                }).limit(limit)
            else:
                cursor = col.find({"published": True}).limit(limit)

        return await cursor.to_list(length=limit)

    @staticmethod
    async def list_all(
        page: int = 1,
        page_size: int = 20,
        published_only: bool = True,
    ) -> tuple[list[dict], int]:
        """List all registry entries with pagination."""
        query = {"published": True} if published_only else {}
        cursor = (
            WorkflowRegistryService._collection()
            .find(query)
            .sort("name", 1)
            .skip((page - 1) * page_size)
            .limit(page_size)
        )
        items = await cursor.to_list(length=page_size)
        total = await WorkflowRegistryService._collection().count_documents(query)
        return items, total

    @staticmethod
    async def unregister(entry_id: str) -> bool:
        """Remove a workflow from the registry.

        Returns:
            True if removed, False if not found.
        """
        result = await WorkflowRegistryService._collection().delete_one(
            {"_id": entry_id}
        )
        if result.deleted_count:
            logger.info("workflow_unregistered", entry_id=entry_id)
            return True
        return False

    @staticmethod
    async def update(
        entry_id: str,
        updates: dict[str, Any],
    ) -> dict:
        """Update a registry entry.

        Args:
            entry_id: Registry entry ID.
            updates: Fields to update.

        Returns:
            Updated document.

        Raises:
            NotFoundError: If entry not found.
        """
        # Prevent changing the ID
        updates.pop("_id", None)
        updates.pop("id", None)

        updated = await WorkflowRegistryService._collection().find_one_and_update(
            {"_id": entry_id},
            {"$set": {**updates, "updated_at": utc_now()}},
            return_document=ReturnDocument.AFTER,
        )

        if updated is None:
            raise NotFoundError(
                code="WORKFLOW_NOT_FOUND",
                message=f"工作流注册条目 {entry_id} 不存在",
                details={"entry_id": entry_id},
            )

        return updated

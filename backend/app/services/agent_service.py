"""Agent business logic — CRUD operations and version management."""
from __future__ import annotations

import re

from loguru import logger

from app.core.errors import ConflictError, ValidationError
from app.db.mongodb import get_database
from app.models.agent import Agent, AgentStatus


class AgentService:
    """Service layer for Agent operations."""

    COLLECTION = "agents"

    @staticmethod
    def _collection():
        return get_database()[AgentService.COLLECTION]

    # ------------------------------------------------------------------
    # CRUD operations
    # ------------------------------------------------------------------

    @staticmethod
    async def create_agent(
        name: str,
        description: str = "",
        system_prompt: str = "",
        saved_system_prompts: list[dict] | None = None,
        tool_ids: list[str] | None = None,
        skill_ids: list[str] | None = None,
        mcp_connection_ids: list[str] | None = None,
        builtin_config: list[str] | None = None,
        workflow_ids: list[str] | None = None,
        knowledge_base_ids: list[str] | None = None,
        llm_config: dict | None = None,
    ) -> dict:
        """Create a new Agent in draft status. (AC1)

        Args:
            name: Agent name.
            description: Optional description.
            system_prompt: Optional active system prompt.
            saved_system_prompts: Optional list of saved prompt templates.
            tool_ids: Deprecated — use skill_ids instead.
            skill_ids: Optional list of bound Skill tool IDs.
            mcp_connection_ids: Optional list of bound MCP connection IDs.
            builtin_config: Optional list of enabled built-in tool names.
            workflow_ids: Optional list of bound workflow IDs.
            knowledge_base_ids: Optional list of bound knowledge base IDs.
            llm_config: Optional model configuration dict.

        Returns:
            Created Agent MongoDB document.

        Raises:
            ValidationError: If name is empty or duplicates detected.
        """
        # Name uniqueness check
        existing = await AgentService._collection().find_one({"name": name})
        if existing is not None:
            raise ConflictError(
                code="AGENT_NAME_CONFLICT",
                message=f"Agent 名称 '{name}' 已被占用",
                details={"field": "name"},
            )

        # Backward compat: use tool_ids as fallback for skill_ids
        resolved_skill_ids = skill_ids if skill_ids is not None else (tool_ids or [])
        from app.models.agent import SavedPrompt

        resolved_prompts = []
        if saved_system_prompts:
            for p in saved_system_prompts:
                resolved_prompts.append(SavedPrompt(**p))
        elif system_prompt:
            resolved_prompts.append(
                SavedPrompt(content=system_prompt, is_active=True)
            )

        agent = Agent(
            name=name,
            description=description,
            system_prompt=system_prompt,
            saved_system_prompts=resolved_prompts,
            tool_ids=resolved_skill_ids,
            skill_ids=resolved_skill_ids,
            mcp_connection_ids=mcp_connection_ids or [],
            builtin_config=builtin_config or [],
            workflow_ids=workflow_ids or [],
            knowledge_base_ids=knowledge_base_ids or [],
            llm_config=llm_config or {
                "default_model": "",
                "temperature": 0.7,
                "max_retry": 3,
            },
            status=AgentStatus.DRAFT,
        )

        doc = {
            "_id": agent.id,
            "name": agent.name,
            "description": agent.description,
            "system_prompt": agent.system_prompt,
            "saved_system_prompts": [p.model_dump() for p in agent.saved_system_prompts],
            "tool_ids": agent.tool_ids,
            "skill_ids": agent.skill_ids,
            "mcp_connection_ids": agent.mcp_connection_ids,
            "builtin_config": agent.builtin_config,
            "workflow_ids": agent.workflow_ids,
            "knowledge_base_ids": agent.knowledge_base_ids,
            "llm_config": agent.llm_config,
            "status": agent.status.value,
            "version": agent.version,
            "created_at": agent.created_at,
            "updated_at": agent.updated_at,
        }

        try:
            await AgentService._collection().insert_one(doc)
        except Exception as exc:
            from pymongo.errors import DuplicateKeyError

            if isinstance(exc, DuplicateKeyError):
                raise ConflictError(
                    code="AGENT_CREATE_CONFLICT",
                    message=f"Agent 名称 '{name}' 已被占用",
                ) from exc
            raise ValidationError(
                code="AGENT_CREATE_FAILED",
                message="Agent 创建失败，请稍后重试",
            ) from exc

        logger.info(
            "agent_created",
            agent_id=agent.id,
            agent_name=agent.name,
        )
        return doc

    @staticmethod
    async def get_agent(agent_id: str) -> dict | None:
        """Get an Agent by ID. (AC3)

        Args:
            agent_id: The Agent's ID.

        Returns:
            Agent document or None if not found.
        """
        return await AgentService._collection().find_one({"_id": agent_id})

    @staticmethod
    async def list_agents(
        page: int = 1,
        page_size: int = 20,
        name: str | None = None,
        status: str | None = None,
    ) -> tuple[list[dict], int]:
        """List Agents with pagination and optional filtering. (AC2)

        Args:
            page: Page number (1-based).
            page_size: Items per page (max 100).
            name: Optional name substring filter (case-insensitive).
            status: Optional status filter (draft/published/archived).

        Returns:
            Tuple of (agent_docs, total_count).
        """
        col = AgentService._collection()
        filter_query: dict = {}
        if name:
            filter_query["name"] = {"$regex": re.escape(name), "$options": "i"}
        if status:
            filter_query["status"] = status

        total = await col.count_documents(filter_query)
        cursor = (
            col.find(filter_query)
            .sort("updated_at", -1)
            .skip((page - 1) * page_size)
            .limit(page_size)
        )
        items = await cursor.to_list(length=page_size)
        return items, total

    @staticmethod
    async def update_agent(
        agent_id: str,
        name: str,
        description: str = "",
        system_prompt: str = "",
        saved_system_prompts: list[dict] | None = None,
        tool_ids: list[str] | None = None,
        skill_ids: list[str] | None = None,
        mcp_connection_ids: list[str] | None = None,
        builtin_config: list[str] | None = None,
        workflow_ids: list[str] | None = None,
        knowledge_base_ids: list[str] | None = None,
        llm_config: dict | None = None,
        status: str | None = None,
    ) -> dict | None:
        """Update an existing Agent. (AC4)

        Performs full replacement update. Auto-increments version only when published.

        Args:
            agent_id: The Agent's ID.
            name: New name.
            description: New description.
            system_prompt: New active system prompt.
            saved_system_prompts: New saved prompt templates list.
            tool_ids: Deprecated — use skill_ids instead.
            skill_ids: New Skill tool IDs.
            mcp_connection_ids: New MCP connection IDs.
            builtin_config: New built-in tool whitelist.
            workflow_ids: New workflow IDs.
            knowledge_base_ids: New knowledge base IDs.
            llm_config: New model config.
            status: Optional new status. None preserves existing status.

        Returns:
            Updated Agent document, or None if not found.

        Raises:
            ValidationError: If name conflicts with another Agent.
        """
        col = AgentService._collection()

        existing_doc = await col.find_one({"_id": agent_id})
        if existing_doc is None:
            return None

        # Check name uniqueness (exclude self)
        name_conflict = await col.find_one(
            {"name": name, "_id": {"$ne": agent_id}}
        )
        if name_conflict is not None:
            raise ConflictError(
                code="AGENT_NAME_CONFLICT",
                message=f"Agent 名称 '{name}' 已被占用",
                details={"field": "name"},
            )

        from app.models.base import utc_now
        from app.models.agent import AgentStatus

        now_iso = utc_now().isoformat()

        # Only increment version when the agent is published.
        # Draft/archived edits should not bump version since they
        # are not used in active conversations.
        existing_status = existing_doc.get("status")
        is_published = existing_status == AgentStatus.PUBLISHED.value
        new_version = existing_doc.get("version", 1) + (1 if is_published else 0)

        # Preserve existing status when not explicitly provided
        status_value = status if status is not None else existing_status

        # Backward compat: use tool_ids as fallback for skill_ids
        resolved_skill_ids = skill_ids if skill_ids is not None else (tool_ids or [])

        set_fields: dict = {
            "name": name,
            "description": description,
            "system_prompt": system_prompt,
            "saved_system_prompts": saved_system_prompts or [],
            "tool_ids": resolved_skill_ids,
            "skill_ids": resolved_skill_ids,
            "mcp_connection_ids": mcp_connection_ids or [],
            "builtin_config": builtin_config or [],
            "workflow_ids": workflow_ids or [],
            "knowledge_base_ids": knowledge_base_ids or [],
            "llm_config": llm_config or {
                "default_model": "",
                "temperature": 0.7,
                "max_retry": 3,
            },
            "status": status_value,
            "version": new_version,
            "updated_at": now_iso,
        }

        await col.update_one({"_id": agent_id}, {"$set": set_fields})

        logger.info(
            "agent_updated",
            agent_id=agent_id,
            new_version=new_version,
        )

        updated = await AgentService.get_agent(agent_id)
        return updated

    @staticmethod
    async def delete_agent(agent_id: str) -> bool:
        """Delete an Agent by ID. (AC5)

        Checks that the Agent is not referenced by active tasks.
        Since Task data model does not exist yet, this is a placeholder
        check that logs a warning.

        Args:
            agent_id: The Agent's ID.

        Returns:
            True if deleted, False if not found.
        """
        col = AgentService._collection()

        existing_doc = await col.find_one({"_id": agent_id})
        if existing_doc is None:
            return False

        # TODO(Story 6.x): Add active Task reference check when
        # Task data model is implemented. For now, only warn.
        if existing_doc.get("status") == AgentStatus.PUBLISHED.value:
            # Placeholder: in the future, check Task collection
            # for any Task referencing this Agent
            logger.warning(
                "agent_delete_published",
                agent_id=agent_id,
                message="删除已发布的 Agent，请确保没有活跃 Task 引用",
            )

        result = await col.delete_one({"_id": agent_id})
        if result.deleted_count > 0:
            logger.info(
                "agent_deleted",
                agent_id=agent_id,
                agent_name=existing_doc.get("name"),
            )
            return True
        return False

    # ------------------------------------------------------------------
    # Model config operations
    # ------------------------------------------------------------------

    @staticmethod
    async def update_model_config(
        agent_id: str,
        default_model: str = "",
        temperature: float = 0.7,
        max_retry: int = 3,
    ) -> dict | None:
        """Update only the Agent's model configuration. (AC4)

        Only touches the ``llm_config`` field; other fields are untouched.
        Auto-increments ``version`` so new conversations use the new config
        while existing conversations keep the old one (AC5).

        Args:
            agent_id: The Agent's ID.
            default_model: Default LLM model ID.
            temperature: Model temperature (0.0-2.0).
            max_retry: Max retry count.

        Returns:
            Updated Agent document, or None if not found.
        """
        col = AgentService._collection()

        existing_doc = await col.find_one({"_id": agent_id})
        if existing_doc is None:
            return None

        from app.models.base import utc_now
        from app.models.agent import AgentStatus

        now_iso = utc_now().isoformat()

        existing_status = existing_doc.get("status")
        is_published = existing_status == AgentStatus.PUBLISHED.value
        new_version = existing_doc.get("version", 1) + (1 if is_published else 0)

        new_llm_config = {
            "default_model": default_model,
            "temperature": temperature,
            "max_retry": max_retry,
        }

        await col.update_one(
            {"_id": agent_id},
            {
                "$set": {
                    "llm_config": new_llm_config,
                    "version": new_version,
                    "updated_at": now_iso,
                }
            },
        )

        logger.info(
            "agent_model_config_updated",
            agent_id=agent_id,
            new_version=new_version,
        )

        updated = await AgentService.get_agent(agent_id)
        return updated

    # ------------------------------------------------------------------
    # Lifecycle operations (publish / archive / duplicate)
    # ------------------------------------------------------------------

    @staticmethod
    async def publish_agent(agent_id: str) -> dict | None:
        """Publish an Agent (draft/archived → published). Auto-increments version.

        Args:
            agent_id: The Agent's ID.

        Returns:
            Updated Agent document, or None if not found.
        """
        col = AgentService._collection()

        existing_doc = await col.find_one({"_id": agent_id})
        if existing_doc is None:
            return None

        from app.models.base import utc_now

        now_iso = utc_now().isoformat()
        new_version = existing_doc.get("version", 1) + 1

        await col.update_one(
            {"_id": agent_id},
            {
                "$set": {
                    "status": AgentStatus.PUBLISHED.value,
                    "version": new_version,
                    "updated_at": now_iso,
                }
            },
        )

        logger.info(
            "agent_published",
            agent_id=agent_id,
            new_version=new_version,
        )

        return await AgentService.get_agent(agent_id)

    @staticmethod
    async def archive_agent(agent_id: str) -> dict | None:
        """Archive an Agent (published → archived). Auto-increments version.

        Args:
            agent_id: The Agent's ID.

        Returns:
            Updated Agent document, or None if not found.
        """
        col = AgentService._collection()

        existing_doc = await col.find_one({"_id": agent_id})
        if existing_doc is None:
            return None

        from app.models.base import utc_now

        now_iso = utc_now().isoformat()
        new_version = existing_doc.get("version", 1) + 1

        await col.update_one(
            {"_id": agent_id},
            {
                "$set": {
                    "status": AgentStatus.ARCHIVED.value,
                    "version": new_version,
                    "updated_at": now_iso,
                }
            },
        )

        logger.info(
            "agent_archived",
            agent_id=agent_id,
            new_version=new_version,
        )

        return await AgentService.get_agent(agent_id)

    @staticmethod
    async def duplicate_agent(agent_id: str) -> dict:
        """Duplicate an Agent with a unique name. New Agent is always draft.

        Copies all configuration fields (system_prompt, tool_ids,
        workflow_ids, knowledge_base_ids, llm_config) but resets
        status to draft and version to 1.

        Args:
            agent_id: The source Agent's ID.

        Returns:
            The newly created Agent document.

        Raises:
            NotFoundError: If source Agent does not exist.
            ConflictError: If a unique name cannot be generated.
        """
        from app.core.errors import NotFoundError

        col = AgentService._collection()

        source = await col.find_one({"_id": agent_id})
        if source is None:
            raise NotFoundError(
                code="AGENT_NOT_FOUND",
                message=f"Agent {agent_id} 不存在",
            )

        # Generate unique name: {original}_copy, {original}_copy_2, ...
        base_name = f"{source['name']}_copy"
        new_name = base_name
        counter = 2
        while await col.find_one({"name": new_name}):
            new_name = f"{base_name}_{counter}"
            counter += 1
            if counter > 100:
                raise ConflictError(
                    code="AGENT_DUPLICATE_NAME_CONFLICT",
                    message="无法生成唯一名称，请手动创建",
                )

        return await AgentService.create_agent(
            name=new_name,
            description=source.get("description", ""),
            system_prompt=source.get("system_prompt", ""),
            saved_system_prompts=source.get("saved_system_prompts", None),
            tool_ids=source.get("tool_ids", []),
            skill_ids=source.get("skill_ids", None),
            mcp_connection_ids=source.get("mcp_connection_ids", []),
            builtin_config=source.get("builtin_config", []),
            workflow_ids=source.get("workflow_ids", []),
            knowledge_base_ids=source.get("knowledge_base_ids", []),
            llm_config=source.get("llm_config"),
        )

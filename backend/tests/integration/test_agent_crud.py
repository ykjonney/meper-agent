"""Integration tests for Agent CRUD against real MongoDB.

Verifies the AgentService operations work correctly with
actual database reads and writes.
"""
import pytest
from app.core.errors import ConflictError
from app.services.agent_service import AgentService

pytestmark = pytest.mark.integration


class TestCreateAgent:
    """AgentService.create_agent integration tests."""

    async def test_create_agent_succeeds(
        self,
        mock_agent_collection: None,  # noqa: ARG002
    ) -> None:
        """AC1: Create an Agent with all fields."""
        doc = await AgentService.create_agent(
            name="Test Agent",
            description="A test agent",
            prompt_slots={"role": "You are helpful."},
            skill_ids=["tool_001"],
            workflow_ids=["wf_001"],
        )
        assert doc["_id"].startswith("agent_")
        assert doc["name"] == "Test Agent"
        assert doc["status"] == "draft"
        assert doc["description"] == "A test agent"
        assert doc["skill_ids"] == ["tool_001"]
        assert doc["workflow_ids"] == ["wf_001"]
        assert doc["prompt_slots"] == {"role": "You are helpful."}

    async def test_create_agent_defaults(
        self,
        mock_agent_collection: None,  # noqa: ARG002
    ) -> None:
        """AC1: Minimal Agent creation uses sensible defaults."""
        doc = await AgentService.create_agent(name="Minimal Agent")
        assert doc["prompt_slots"] == {}
        assert doc["skill_ids"] == []
        assert doc["workflow_ids"] == []
        assert doc["knowledge_base_ids"] == []
        assert doc["default_model"] == ""

    async def test_create_agent_duplicate_name(
        self,
        mock_agent_collection: None,  # noqa: ARG002
    ) -> None:
        """AC1: Duplicate name raises ValidationError."""
        await AgentService.create_agent(name="Unique Name")
        with pytest.raises(ConflictError) as exc:
            await AgentService.create_agent(name="Unique Name")
        assert "AGENT_NAME_CONFLICT" in exc.value.code

    async def test_create_agent_after_delete_same_name(
        self,
        mock_agent_collection: None,  # noqa: ARG002
    ) -> None:
        """AC1: After deleting, the same name can be reused."""
        doc = await AgentService.create_agent(name="Reusable")
        await AgentService.delete_agent(doc["_id"])
        doc2 = await AgentService.create_agent(name="Reusable")
        assert doc2["name"] == "Reusable"

    async def test_create_agent_with_categorized_fields(
        self,
        mock_agent_collection: None,  # noqa: ARG002
    ) -> None:
        """AC1: Create Agent with skill_ids, mcp_connection_ids, builtin_config."""
        doc = await AgentService.create_agent(
            name="Categorized Agent",
            skill_ids=["skill_001", "skill_002"],
            mcp_connection_ids=["mcp_001"],
            builtin_config=["bash", "read"],
        )
        assert doc["skill_ids"] == ["skill_001", "skill_002"]
        assert doc["mcp_connection_ids"] == ["mcp_001"]
        assert doc["builtin_config"] == ["bash", "read"]


class TestGetAgent:
    """AgentService.get_agent integration tests."""

    async def test_get_agent_by_id(
        self,
        mock_agent_collection: None,  # noqa: ARG002
    ) -> None:
        """AC3: Get an Agent by its ID."""
        created = await AgentService.create_agent(name="Findable Agent")
        fetched = await AgentService.get_agent(created["_id"])
        assert fetched is not None
        assert fetched["name"] == "Findable Agent"

    async def test_get_agent_not_found(
        self,
        mock_agent_collection: None,  # noqa: ARG002
    ) -> None:
        """AC3: Non-existent ID returns None."""
        doc = await AgentService.get_agent("agent_NONEXIST")
        assert doc is None


class TestListAgents:
    """AgentService.list_agents integration tests."""

    async def test_list_agents_empty(
        self,
        mock_agent_collection: None,  # noqa: ARG002
    ) -> None:
        """AC2: Empty collection returns empty list."""
        items, total = await AgentService.list_agents()
        assert total == 0
        assert items == []

    async def test_list_agents_pagination(
        self,
        mock_agent_collection: None,  # noqa: ARG002
    ) -> None:
        """AC2: Pagination returns correct slice."""
        for i in range(5):
            await AgentService.create_agent(name=f"Agent {i}")

        items, total = await AgentService.list_agents(page=1, page_size=2)
        assert total == 5
        assert len(items) == 2

        items2, _ = await AgentService.list_agents(page=2, page_size=2)
        assert len(items2) == 2

        items3, _ = await AgentService.list_agents(page=3, page_size=2)
        assert len(items3) == 1

    async def test_list_agents_filter_by_name(
        self,
        mock_agent_collection: None,  # noqa: ARG002
    ) -> None:
        """AC2: Name filter returns matching agents."""
        await AgentService.create_agent(name="Production Agent")
        await AgentService.create_agent(name="Staging Agent")
        await AgentService.create_agent(name="Debug Helper")

        items, total = await AgentService.list_agents(name="Agent")
        assert total == 2  # "Production Agent", "Staging Agent"

    async def test_list_agents_filter_by_status(
        self,
        mock_agent_collection: None,  # noqa: ARG002
    ) -> None:
        """AC2: Status filter returns correct subset."""
        # Agents are created as "draft" by default
        await AgentService.create_agent(name="Draft Agent")

        items, total = await AgentService.list_agents(status="draft")
        assert total == 1

        items2, total2 = await AgentService.list_agents(status="published")
        assert total2 == 0


class TestUpdateAgent:
    """AgentService.update_agent integration tests."""

    async def test_update_agent_all_fields(
        self,
        mock_agent_collection: None,  # noqa: ARG002
    ) -> None:
        """AC4: Full update replaces all specified fields."""
        created = await AgentService.create_agent(
            name="Original",
            description="Original description",
        )

        updated = await AgentService.update_agent(
            agent_id=created["_id"],
            name="Updated",
            description="New description",
            prompt_slots={"role": "New prompt"},
            skill_ids=["tool_001"],
            workflow_ids=[],
        )
        assert updated is not None
        assert updated["name"] == "Updated"
        assert updated["description"] == "New description"
        assert updated["prompt_slots"] == {"role": "New prompt"}

    async def test_update_agent_not_found(
        self,
        mock_agent_collection: None,  # noqa: ARG002
    ) -> None:
        """AC4: Non-existent Agent returns None."""
        result = await AgentService.update_agent(
            agent_id="agent_NONEXIST",
            name="Ghost",
        )
        assert result is None

    async def test_update_agent_name_conflict(
        self,
        mock_agent_collection: None,  # noqa: ARG002
    ) -> None:
        """AC4: Duplicate name raises ValidationError."""
        await AgentService.create_agent(name="Existing")
        created = await AgentService.create_agent(name="To Rename")

        with pytest.raises(ConflictError) as exc:
            await AgentService.update_agent(
                agent_id=created["_id"],
                name="Existing",
            )
        assert "AGENT_NAME_CONFLICT" in exc.value.code

    async def test_update_agent_preserves_unchanged_fields(
        self,
        mock_agent_collection: None,  # noqa: ARG002
    ) -> None:
        """AC4: Update correctly sets all specified fields."""
        created = await AgentService.create_agent(
            name="Original",
            description="Desc",
            prompt_slots={"role": "Prompt"},
            skill_ids=["t1"],
            workflow_ids=["w1"],
            knowledge_base_ids=["k1"],
        )
        updated = await AgentService.update_agent(
            agent_id=created["_id"],
            name="Original",
            description="Desc",
            prompt_slots={"role": "Prompt"},
            skill_ids=["t1"],
            workflow_ids=["w1"],
            knowledge_base_ids=["k1"],
        )
        assert updated is not None
        assert updated["name"] == "Original"
        assert updated["description"] == "Desc"

    async def test_update_agent_categorized_fields(
        self,
        mock_agent_collection: None,  # noqa: ARG002
    ) -> None:
        """AC4: Update preserves categorized fields correctly."""
        created = await AgentService.create_agent(
            name="Categorized Update",
            skill_ids=["skill_001"],
            mcp_connection_ids=["mcp_001"],
            builtin_config=["bash"],
        )
        updated = await AgentService.update_agent(
            agent_id=created["_id"],
            name="Categorized Update",
            description="Updated",
            prompt_slots={},
            skill_ids=["skill_002", "skill_003"],
            mcp_connection_ids=["mcp_002"],
            builtin_config=["read", "write"],
            workflow_ids=[],
            knowledge_base_ids=[],
        )
        assert updated is not None
        assert updated["skill_ids"] == ["skill_002", "skill_003"]
        assert updated["mcp_connection_ids"] == ["mcp_002"]
        assert updated["builtin_config"] == ["read", "write"]


class TestDuplicateAgent:
    """AgentService.duplicate_agent integration tests."""

    async def test_duplicate_copies_categorized_fields(
        self,
        mock_agent_collection: None,  # noqa: ARG002
    ) -> None:
        """Duplicate copies skill_ids, mcp_connection_ids, builtin_config."""
        original = await AgentService.create_agent(
            name="Original Agent",
            skill_ids=["skill_001"],
            mcp_connection_ids=["mcp_001"],
            builtin_config=["bash", "read"],
            workflow_ids=["wf_001"],
            knowledge_base_ids=["kb_001"],
        )
        duplicate = await AgentService.duplicate_agent(original["_id"])
        assert duplicate["name"] == "Original Agent_copy"
        assert duplicate["skill_ids"] == ["skill_001"]
        assert duplicate["mcp_connection_ids"] == ["mcp_001"]
        assert duplicate["builtin_config"] == ["bash", "read"]
        assert duplicate["workflow_ids"] == ["wf_001"]
        assert duplicate["knowledge_base_ids"] == ["kb_001"]
        assert duplicate["status"] == "draft"

    async def test_duplicate_legacy_tool_ids_doc(
        self,
        mock_agent_collection: None,  # noqa: ARG002
    ) -> None:
        """Duplicate of old Agent doc (only tool_ids, no skill_ids) copies correctly."""
        # Simulate a legacy document by directly inserting into the collection
        legacy_doc = {
            "_id": "agent_legacy_001",
            "name": "Legacy Doc Agent",
            "description": "",
            "system_prompt": "",
            "saved_system_prompts": [],
            "tool_ids": ["t1", "t2"],
            # No skill_ids field — simulates pre-migration doc
            "mcp_connection_ids": [],
            "builtin_config": [],
            "workflow_ids": [],
            "knowledge_base_ids": [],
            "llm_config": {"default_model": "", "temperature": 0.7, "max_retry": 3},  # legacy backward compat
            "status": "draft",
            "version": 1,
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        }
        await AgentService._collection().insert_one(legacy_doc)

        duplicate = await AgentService.duplicate_agent("agent_legacy_001")
        assert duplicate["name"] == "Legacy Doc Agent_copy"
        assert duplicate["skill_ids"] == ["t1", "t2"]


class TestDeleteAgent:
    """AgentService.delete_agent integration tests."""

    async def test_delete_agent_succeeds(
        self,
        mock_agent_collection: None,  # noqa: ARG002
    ) -> None:
        """AC5: Delete removes the Agent."""
        created = await AgentService.create_agent(name="Delete Me")
        assert await AgentService.get_agent(created["_id"]) is not None

        deleted = await AgentService.delete_agent(created["_id"])
        assert deleted is True
        assert await AgentService.get_agent(created["_id"]) is None

    async def test_delete_agent_not_found(
        self,
        mock_agent_collection: None,  # noqa: ARG002
    ) -> None:
        """AC5: Non-existent Agent returns False."""
        result = await AgentService.delete_agent("agent_NONEXIST")
        assert result is False

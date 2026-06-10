"""Tests for the Agent model — field backward compatibility."""

from app.models.agent import Agent, AgentStatus


class TestAgentModel:
    """Agent model unit tests."""

    def test_skill_ids_populated_from_tool_ids(self) -> None:
        """When tool_ids has data and skill_ids is empty, skill_ids should mirror tool_ids."""
        agent = Agent(name="Test Agent", tool_ids=["t1", "t2"])
        assert agent.skill_ids == ["t1", "t2"]

    def test_skill_ids_takes_precedence(self) -> None:
        """When both tool_ids and skill_ids are provided, skill_ids is used as-is."""
        agent = Agent(
            name="Test Agent",
            tool_ids=["old_t1"],
            skill_ids=["new_s1"],
        )
        assert agent.skill_ids == ["new_s1"]

    def test_skill_ids_empty_when_tool_ids_empty(self) -> None:
        """When neither field has data, both are empty."""
        agent = Agent(name="Test Agent")
        assert agent.skill_ids == []
        assert agent.tool_ids == []

    def test_new_fields_default_to_empty(self) -> None:
        """New categorized fields default to empty lists."""
        agent = Agent(name="Test Agent")
        assert agent.mcp_connection_ids == []
        assert agent.builtin_config == []

    def test_full_construction_with_new_fields(self) -> None:
        """Agent can be constructed with all new categorized fields."""
        agent = Agent(
            name="Full Agent",
            description="Has all fields",
            system_prompt="You are helpful.",
            skill_ids=["skill_001"],
            mcp_connection_ids=["mcp_001"],
            builtin_config=["bash", "read"],
            workflow_ids=["wf_001"],
            knowledge_base_ids=["kb_001"],
            llm_config={"default_model": "gpt-4", "temperature": 0.5, "max_retry": 5},
            status=AgentStatus.PUBLISHED,
        )
        assert agent.skill_ids == ["skill_001"]
        assert agent.mcp_connection_ids == ["mcp_001"]
        assert agent.builtin_config == ["bash", "read"]
        assert agent.status == AgentStatus.PUBLISHED

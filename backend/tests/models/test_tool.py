"""Tests for the Tool data model."""
from app.models.tool import SkillFile, Tool, ToolStatus


class TestToolStatus:
    """ToolStatus enum tests."""

    def test_values(self) -> None:
        assert ToolStatus.DRAFT == "draft"
        assert ToolStatus.ACTIVE == "active"
        assert ToolStatus.INACTIVE == "inactive"


class TestToolModel:
    """Tool Pydantic model tests."""

    def test_default_values(self) -> None:
        tool = Tool(name="test-tool")
        assert tool.name == "test-tool"
        assert tool.description == ""
        assert tool.input_schema == {}
        assert tool.output_schema == {}
        assert tool.instructions == ""
        assert tool.source == "markdown"
        assert tool.source_file == ""
        assert tool.status == ToolStatus.DRAFT
        assert tool.version == 1
        assert tool.tags == []
        assert tool.created_at != ""
        assert tool.updated_at != ""

    def test_id_format(self) -> None:
        tool = Tool(name="test")
        assert tool.id.startswith("tool_")

    def test_id_alias(self) -> None:
        tool = Tool(name="test")
        dump = tool.model_dump(by_alias=True)
        assert "_id" in dump
        assert dump["_id"].startswith("tool_")

    def test_name_required(self) -> None:
        import pytest

        with pytest.raises(Exception):
            Tool()  # type: ignore[call-arg]

    def test_name_length_limit(self) -> None:
        import pytest

        with pytest.raises(Exception):
            Tool(name="")

    def test_full_construction(self) -> None:
        tool = Tool(
            name="query-device",
            description="Query device status",
            input_schema={"type": "object", "properties": {"id": {"type": "string"}}},
            output_schema={"type": "object"},
            instructions="## Usage\nQuery device status by ID.",
            source="markdown",
            source_file="query-device.md",
            status=ToolStatus.ACTIVE,
            tags=["mes", "device"],
        )
        assert tool.name == "query-device"
        assert tool.status == ToolStatus.ACTIVE
        assert tool.tags == ["mes", "device"]
        assert "id" in tool.input_schema["properties"]

    def test_files_default_empty(self) -> None:
        """Legacy tools have empty files list."""
        tool = Tool(name="legacy-tool")
        assert tool.files == []

    def test_files_with_skill_files(self) -> None:
        """Tool with directory-based Skill files."""
        tool = Tool(
            name="my-skill",
            files=[
                SkillFile(path="SKILL.md", content="# Skill", size=7),
                SkillFile(path="step-01.md", content="# Step", size=6),
            ],
        )
        assert len(tool.files) == 2
        assert tool.files[0].path == "SKILL.md"
        assert tool.files[1].content == "# Step"

    def test_files_serialization(self) -> None:
        """files field serializes correctly via model_dump."""
        tool = Tool(
            name="skill-pkg",
            files=[SkillFile(path="SKILL.md", content="content", size=7)],
        )
        dump = tool.model_dump(by_alias=True)
        assert isinstance(dump["files"], list)
        assert dump["files"][0]["path"] == "SKILL.md"
        assert dump["files"][0]["content"] == "content"

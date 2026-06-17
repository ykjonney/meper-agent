"""Tests for the Markdown Skill parser."""
import pytest
from app.engine.tool.skill_parser import (
    ParsedSkill,
    ParsedSkillDirectory,
    SkillParseError,
    _params_to_json_schema,
    _returns_to_json_schema,
    parse_skill_directory,
    parse_skill_markdown,
)

# ---------------------------------------------------------------------------
# Sample Skill Markdown files
# ---------------------------------------------------------------------------

SKILL_BASIC = """\
---
name: query-device-status
description: 查询 MES 系统中的设备实时状态数据
---

# 详细说明

通过 MES API 查询指定设备的实时状态。
"""

SKILL_WITH_PARAMS = """\
---
name: query-device
description: Query device status
parameters:
  - name: device_id
    type: string
    description: 设备 ID
    required: true
  - name: fields
    type: array
    items:
      type: string
    description: 查询字段列表
    required: false
    default: ["status"]
returns:
  type: object
  description: 设备状态
  properties:
    status:
      type: string
---

# Body

## Example

查询设备状态。
"""

SKILL_INVALID_YAML = """\
---
name: test
  description: broken indentation
    extra: [unclosed
---

body
"""

SKILL_NO_FRONTMATTER = """\
# This is plain markdown
No frontmatter here.
"""

SKILL_MISSING_NAME = """\
---
description: missing name field
---
body
"""

SKILL_MISSING_DESC = """\
---
name: test
---
body
"""


# ---------------------------------------------------------------------------
# parse_skill_markdown
# ---------------------------------------------------------------------------


class TestParseSkillMarkdown:
    """parse_skill_markdown tests."""

    def test_basic_skill(self) -> None:
        result = parse_skill_markdown(SKILL_BASIC, "basic.md")
        assert isinstance(result, ParsedSkill)
        assert result.name == "query-device-status"
        assert result.description == "查询 MES 系统中的设备实时状态数据"
        assert "详细说明" in result.instructions
        assert "MES API" in result.instructions

    def test_with_params(self) -> None:
        result = parse_skill_markdown(SKILL_WITH_PARAMS, "params.md")
        assert result.name == "query-device"
        assert result.description == "Query device status"

        # input_schema
        props = result.input_schema["properties"]
        assert "device_id" in props
        assert props["device_id"]["type"] == "string"
        assert props["device_id"]["description"] == "设备 ID"
        assert "fields" in props
        assert props["fields"]["type"] == "array"
        assert props["fields"]["default"] == ["status"]
        assert result.input_schema["required"] == ["device_id"]

        # output_schema
        assert result.output_schema["type"] == "object"
        assert result.output_schema["description"] == "设备状态"

    def test_body_extraction(self) -> None:
        result = parse_skill_markdown(SKILL_WITH_PARAMS, "params.md")
        assert result.instructions.startswith("# Body")
        assert "Example" in result.instructions

    def test_missing_frontmatter_raises(self) -> None:
        with pytest.raises(SkillParseError) as exc_info:
            parse_skill_markdown(SKILL_NO_FRONTMATTER, "plain.md")
        assert "frontmatter" in exc_info.value.detail.lower()
        assert exc_info.value.filename == "plain.md"

    def test_invalid_yaml_raises(self) -> None:
        with pytest.raises(SkillParseError) as exc_info:
            parse_skill_markdown(SKILL_INVALID_YAML, "invalid.md")
        assert "yaml" in exc_info.value.detail.lower()

    def test_missing_name_raises(self) -> None:
        with pytest.raises(SkillParseError) as exc_info:
            parse_skill_markdown(SKILL_MISSING_NAME, "no_name.md")
        assert "name" in exc_info.value.detail

    def test_missing_description_raises(self) -> None:
        with pytest.raises(SkillParseError) as exc_info:
            parse_skill_markdown(SKILL_MISSING_DESC, "no_desc.md")
        assert "description" in exc_info.value.detail

    def test_filename_in_error(self) -> None:
        try:
            parse_skill_markdown(SKILL_NO_FRONTMATTER, "special.md")
        except SkillParseError as exc:
            assert exc.filename == "special.md"
            assert "special.md" in str(exc)

    def test_empty_params_returns_empty_object_schema(self) -> None:
        result = parse_skill_markdown(SKILL_BASIC, "basic.md")
        assert result.input_schema["type"] == "object"
        assert result.input_schema["properties"] == {}

    def test_empty_returns_default_string_schema(self) -> None:
        result = parse_skill_markdown(SKILL_BASIC, "basic.md")
        assert result.output_schema["type"] == "string"


# ---------------------------------------------------------------------------
# _params_to_json_schema
# ---------------------------------------------------------------------------


class TestParamsToJsonSchema:
    """_params_to_json_schema tests."""

    def test_empty_list(self) -> None:
        schema = _params_to_json_schema([])
        assert schema == {"type": "object", "properties": {}}

    def test_non_list(self) -> None:
        schema = _params_to_json_schema("not a list")  # type: ignore[arg-type]
        assert schema == {"type": "object", "properties": {}}

    def test_with_required(self) -> None:
        params = [
            {"name": "id", "type": "string", "required": True},
            {"name": "opt", "type": "string", "required": False},
        ]
        schema = _params_to_json_schema(params)
        assert schema["required"] == ["id"]

    def test_default_type_is_string(self) -> None:
        params = [{"name": "x"}]
        schema = _params_to_json_schema(params)
        assert schema["properties"]["x"]["type"] == "string"

    def test_skips_entries_without_name(self) -> None:
        params = [{"name": "valid", "type": "string"}, {"type": "no-name"}]
        schema = _params_to_json_schema(params)
        assert "valid" in schema["properties"]
        assert len(schema["properties"]) == 1

    def test_preserves_enum(self) -> None:
        params = [{"name": "color", "type": "string", "enum": ["red", "blue"]}]
        schema = _params_to_json_schema(params)
        assert schema["properties"]["color"]["enum"] == ["red", "blue"]


# ---------------------------------------------------------------------------
# _returns_to_json_schema
# ---------------------------------------------------------------------------


class TestReturnsToJsonSchema:
    """_returns_to_json_schema tests."""

    def test_empty_returns_default(self) -> None:
        schema = _returns_to_json_schema({})
        assert schema == {"type": "string"}

    def test_non_dict_returns_default(self) -> None:
        schema = _returns_to_json_schema("not dict")  # type: ignore[arg-type]
        assert schema["type"] == "string"

    def test_with_type_and_description(self) -> None:
        ret = {"type": "object", "description": "Result data"}
        schema = _returns_to_json_schema(ret)
        assert schema["type"] == "object"
        assert schema["description"] == "Result data"

    def test_preserves_properties(self) -> None:
        ret = {"type": "object", "properties": {"status": {"type": "string"}}}
        schema = _returns_to_json_schema(ret)
        assert "properties" in schema
        assert "status" in schema["properties"]

    def test_preserves_items(self) -> None:
        ret = {"type": "array", "items": {"type": "string"}}
        schema = _returns_to_json_schema(ret)
        assert schema["items"] == {"type": "string"}


# ---------------------------------------------------------------------------
# parse_skill_directory
# ---------------------------------------------------------------------------


SKILL_MD_CONTENT = """\
---
name: my-skill
description: A test skill directory
---

# My Skill

This is the main skill instructions.
"""

STEP_01_CONTENT = """\
# Step 01

First step instructions.
"""


def _make_file_map(
    files: dict[str, str], prefix: str = "my-skill"
) -> dict[str, str]:
    """Helper to build file_map with directory prefix."""
    return {f"{prefix}/{k}": v for k, v in files.items()}


class TestParseSkillDirectory:
    """parse_skill_directory tests."""

    def test_basic_directory(self) -> None:
        file_map = _make_file_map({
            "SKILL.md": SKILL_MD_CONTENT,
            "step-01.md": STEP_01_CONTENT,
        })
        result = parse_skill_directory(file_map)
        assert isinstance(result, ParsedSkillDirectory)
        assert result.parsed.name == "my-skill"
        assert result.parsed.description == "A test skill directory"
        assert len(result.files) == 2

    def test_skill_md_is_in_files(self) -> None:
        file_map = _make_file_map({"SKILL.md": SKILL_MD_CONTENT})
        result = parse_skill_directory(file_map)
        paths = [f.path for f in result.files]
        assert "SKILL.md" in paths

    def test_file_sizes(self) -> None:
        file_map = _make_file_map({
            "SKILL.md": SKILL_MD_CONTENT,
            "step-01.md": "hello",
        })
        result = parse_skill_directory(file_map)
        size_map = {f.path: f.size for f in result.files}
        assert size_map["step-01.md"] == 5  # len("hello")

    def test_nested_paths(self) -> None:
        file_map = _make_file_map({
            "SKILL.md": SKILL_MD_CONTENT,
            "steps/step-01.md": STEP_01_CONTENT,
            "templates/template.md": "# Template",
        })
        result = parse_skill_directory(file_map)
        paths = [f.path for f in result.files]
        assert "steps/step-01.md" in paths
        assert "templates/template.md" in paths

    def test_missing_skill_md_raises(self) -> None:
        file_map = _make_file_map({"step-01.md": STEP_01_CONTENT})
        with pytest.raises(SkillParseError) as exc_info:
            parse_skill_directory(file_map)
        assert "SKILL.md" in exc_info.value.detail

    def test_empty_directory_raises(self) -> None:
        with pytest.raises(SkillParseError) as exc_info:
            parse_skill_directory({})
        assert "空目录" in exc_info.value.detail

    def test_path_traversal_raises(self) -> None:
        file_map = {"../etc/passwd": "hacked"}
        with pytest.raises(SkillParseError):
            parse_skill_directory(file_map)

    def test_absolute_path_raises(self) -> None:
        file_map = {"/etc/passwd": "hacked"}
        with pytest.raises(SkillParseError):
            parse_skill_directory(file_map)

    def test_file_not_in_directory_raises(self) -> None:
        file_map = {"standalone.md": SKILL_MD_CONTENT}
        with pytest.raises(SkillParseError):
            parse_skill_directory(file_map)

    def test_mixed_directories_raises(self) -> None:
        file_map = {
            "dir-a/SKILL.md": SKILL_MD_CONTENT,
            "dir-b/other.md": STEP_01_CONTENT,
        }
        with pytest.raises(SkillParseError):
            parse_skill_directory(file_map)

    def test_explicit_directory_name(self) -> None:
        file_map = {
            "custom-dir/SKILL.md": SKILL_MD_CONTENT,
            "custom-dir/extra.md": "extra",
        }
        result = parse_skill_directory(file_map, directory_name="custom-dir")
        assert result.parsed.name == "my-skill"
        paths = [f.path for f in result.files]
        assert "SKILL.md" in paths
        assert "extra.md" in paths

    def test_explicit_directory_name_mismatch_raises(self) -> None:
        file_map = {
            "other-dir/SKILL.md": SKILL_MD_CONTENT,
        }
        with pytest.raises(SkillParseError):
            parse_skill_directory(file_map, directory_name="custom-dir")

    def test_invalid_skill_md_raises(self) -> None:
        file_map = _make_file_map({
            "SKILL.md": "# No frontmatter here",
        })
        with pytest.raises(SkillParseError):
            parse_skill_directory(file_map)

    def test_instructions_preserved(self) -> None:
        file_map = _make_file_map({"SKILL.md": SKILL_MD_CONTENT})
        result = parse_skill_directory(file_map)
        assert "My Skill" in result.parsed.instructions
        assert "main skill instructions" in result.parsed.instructions

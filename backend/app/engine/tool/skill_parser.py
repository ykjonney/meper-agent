"""Markdown Skill parser — YAML frontmatter + body → ParsedSkill.

Standard Skill file format::

    ---
    name: tool-name
    description: What this tool does
    parameters:
      - name: device_id
        type: string
        description: 设备 ID
        required: true
      - name: fields
        type: array
        items:
          type: string
        description: 查询字段
        required: false
        default: ["status"]
    returns:
      type: object
      description: 设备状态
      properties:
        status:
          type: string
    ---

    # 详细说明

    工具的 Markdown 使用说明和示例...
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import yaml

FRONTMATTER_PATTERN = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)", re.DOTALL)


@dataclass
class ParsedSkill:
    """Result of parsing a Markdown Skill file."""

    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    instructions: str = ""


@dataclass
class SkillFileEntry:
    """A single file entry in a Skill directory package."""

    path: str  # 相对路径，如 'SKILL.md' 或 'steps/step-01.md'
    content: str
    size: int


@dataclass
class ParsedSkillDirectory:
    """Result of parsing a Skill directory (multi-file package)."""

    parsed: ParsedSkill  # SKILL.md 解析结果
    files: list[SkillFileEntry]  # 所有文件列表（包括 SKILL.md）


class SkillParseError(Exception):
    """Raised when a Markdown Skill file cannot be parsed."""

    def __init__(self, filename: str, detail: str):
        self.filename = filename
        self.detail = detail
        super().__init__(f"{filename}: {detail}")


def parse_skill_markdown(content: str, filename: str = "") -> ParsedSkill:
    """Parse a Markdown Skill file into a :class:`ParsedSkill`.

    Args:
        content: Raw file content (UTF-8 string).
        filename: Source filename (for error messages).

    Returns:
        Parsed skill data (name, description, schemas, instructions).

    Raises:
        SkillParseError: When frontmatter is missing, YAML is invalid,
            or required fields (``name`` / ``description``) are absent.
    """
    match = FRONTMATTER_PATTERN.match(content)
    if not match:
        raise SkillParseError(
            filename,
            "Missing YAML frontmatter — file must start with '---' delimiters",
        )

    yaml_block, body = match.groups()

    try:
        meta = yaml.safe_load(yaml_block) or {}
    except yaml.YAMLError as exc:
        raise SkillParseError(filename, f"Invalid YAML: {exc}") from exc

    if not isinstance(meta, dict):
        raise SkillParseError(
            filename,
            f"Frontmatter must be a YAML mapping, got {type(meta).__name__}",
        )

    name = meta.get("name")
    description = meta.get("description")

    if not name or not isinstance(name, str):
        raise SkillParseError(filename, "Missing or invalid required field: 'name'")
    if not description or not isinstance(description, str):
        raise SkillParseError(
            filename, "Missing or invalid required field: 'description'"
        )

    input_schema = _params_to_json_schema(meta.get("parameters", []))
    output_schema = _returns_to_json_schema(meta.get("returns", {}))

    return ParsedSkill(
        name=name.strip(),
        description=description.strip(),
        input_schema=input_schema,
        output_schema=output_schema,
        instructions=body.strip(),
    )


def _params_to_json_schema(params: Any) -> dict[str, Any]:
    """Convert frontmatter ``parameters`` array to a JSON Schema object.

    Each entry must have ``name`` and ``type``; ``description``,
    ``required``, ``default``, ``items`` are optional.

    Returns:
        JSON Schema dict like::

            {"type": "object", "properties": {...}, "required": [...]}
    """
    if not isinstance(params, list) or not params:
        return {"type": "object", "properties": {}}

    properties: dict[str, Any] = {}
    required: list[str] = []

    for p in params:
        if not isinstance(p, dict):
            continue
        pname = p.get("name")
        if not pname or not isinstance(pname, str):
            continue  # skip malformed entries

        prop: dict[str, Any] = {
            "type": p.get("type", "string"),
            "description": p.get("description", ""),
        }

        # Preserve extra JSON Schema hints when present
        if "items" in p:
            prop["items"] = p["items"]
        if "default" in p:
            prop["default"] = p["default"]
        if "enum" in p:
            prop["enum"] = p["enum"]

        properties[pname] = prop

        if p.get("required"):
            required.append(pname)

    schema: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        schema["required"] = required
    return schema


def _returns_to_json_schema(returns: Any) -> dict[str, Any]:
    """Convert frontmatter ``returns`` object to a JSON Schema dict."""
    if not isinstance(returns, dict) or not returns:
        return {"type": "string"}

    schema: dict[str, Any] = {
        "type": returns.get("type", "string"),
        "description": returns.get("description", ""),
    }
    if "properties" in returns:
        schema["properties"] = returns["properties"]
    if "items" in returns:
        schema["items"] = returns["items"]
    return schema


def parse_skill_directory(
    file_map: dict[str, str], directory_name: str = ""
) -> ParsedSkillDirectory:
    """Parse a Skill directory package into a :class:`ParsedSkillDirectory`.

    A Skill directory is a package of files with a mandatory ``SKILL.md``
    entry point.  All files are stored in the ``files`` list.

    Args:
        file_map: Mapping of filename → raw content (UTF-8 string).
            Keys are paths like ``"my-skill/SKILL.md"`` or
            ``"my-skill/steps/step-01.md"``.
        directory_name: Optional directory name to strip from paths.
            If provided, paths are trimmed to be relative to the directory.

    Returns:
        ParsedSkillDirectory with the parsed SKILL.md and file list.

    Raises:
        SkillParseError: If SKILL.md is missing, invalid, or required fields
            are absent.  Also raised if file paths contain ``..`` or start
            with ``/`` (security check).
    """
    # Step 1: Validate and normalize paths
    normalized_files: dict[str, str] = {}
    common_prefix: str | None = None

    for full_path, content in file_map.items():
        # Security check: reject path traversal
        if ".." in full_path or full_path.startswith("/"):
            raise SkillParseError(
                full_path,
                "路径不合法：不允许包含 '..' 或以 '/' 开头",
            )

        # Extract directory name from first path segment
        parts = full_path.split("/")
        if len(parts) < 2:
            raise SkillParseError(
                full_path,
                "文件必须位于目录内（路径格式：dir-name/file.ext）",
            )

        # Auto-detect common prefix if not provided
        if common_prefix is None:
            common_prefix = parts[0]

        # Strip common prefix to get relative paths
        if directory_name:
            # Explicit directory name provided
            if not full_path.startswith(f"{directory_name}/"):
                raise SkillParseError(
                    full_path,
                    f"文件不属于指定目录：{directory_name}",
                )
            rel_path = full_path[len(directory_name) + 1 :]
        else:
            # Use auto-detected prefix
            if not full_path.startswith(f"{common_prefix}/"):
                raise SkillParseError(
                    full_path,
                    "所有文件必须属于同一个目录",
                )
            rel_path = full_path[len(common_prefix) + 1 :]

        normalized_files[rel_path] = content

    if not normalized_files:
        raise SkillParseError(
            directory_name or "<unknown>",
            "空目录：没有找到任何文件",
        )

    # Step 2: Find and parse SKILL.md
    skill_md_content = normalized_files.get("SKILL.md")
    if not skill_md_content:
        raise SkillParseError(
            directory_name or "<unknown>",
            "缺少入口文件：SKILL.md（必须位于目录根）",
        )

    parsed_skill = parse_skill_markdown(skill_md_content, "SKILL.md")

    # Step 3: Build file list with sizes
    files: list[SkillFileEntry] = []
    for path, content in normalized_files.items():
        size = len(content.encode("utf-8"))
        files.append(SkillFileEntry(path=path, content=content, size=size))

    return ParsedSkillDirectory(parsed=parsed_skill, files=files)


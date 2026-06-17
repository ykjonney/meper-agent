"""Tool API endpoints — Markdown Skill upload + CRUD for the unified tool pool."""
from __future__ import annotations

from collections import defaultdict
from fastapi import APIRouter, Depends, File, Query, UploadFile
from loguru import logger

from app.core.security import get_current_user, require_any_role
from app.engine.tool.skill_fs import list_skill_files
from app.schemas.tool import (
    BuiltinToolResponse,
    SkillFileResponse,
    SkillFileTreeResponse,
    SkillFileUpdate,
    SkillFileTreeNode,
    ToolListResponse,
    ToolResponse,
    ToolUpdate,
    ToolUploadErrorItem,
    ToolUploadResponse,
)
from app.schemas.user import UserResponse
from app.services.tool_service import ToolService, MAX_FILE_SIZE, MAX_DIRECTORY_SIZE

router = APIRouter(
    prefix="/tools",
    tags=["tools"],
    dependencies=[Depends(get_current_user)],
)


@router.get(
    "/builtin",
    response_model=list[BuiltinToolResponse],
    summary="List built-in tools",
    responses={403: {"description": "Forbidden — viewer+ role required"}},
)
async def list_builtin_tools(
    _: UserResponse = Depends(require_any_role("admin", "developer", "operator", "viewer")),
) -> list[BuiltinToolResponse]:
    """Return the static list of built-in tools (bash / read / write).

    These tools are always available to every Agent and are not stored
    in the database.
    """
    from app.engine.agent.builtin_tools import _BUILTIN_TOOL_REGISTRY

    return [
        BuiltinToolResponse(
            name=name,
            description=tool.description or "",
            parameters=(
                tool.args_schema.schema()
                if hasattr(tool, "args_schema") and tool.args_schema
                else {}
            ),
        )
        for name, tool in _BUILTIN_TOOL_REGISTRY.items()
    ]


def _doc_to_response(doc: dict) -> ToolResponse:
    """Convert a raw MongoDB document to ToolResponse.

    Files are read from disk (Skill filesystem) rather than the
    ``files`` field which is no longer stored in MongoDB.
    """
    name = doc.get("name", "")
    disk_files = list_skill_files(name) if name else []

    files = [
        SkillFileResponse(
            path=f["path"],
            content="",  # Content not loaded for list views
            size=f.get("size", 0),
        )
        for f in disk_files
    ]
    return ToolResponse(
        id=doc["_id"],
        name=doc["name"],
        description=doc.get("description", ""),
        input_schema=doc.get("input_schema", {}),
        output_schema=doc.get("output_schema", {}),
        instructions=doc.get("instructions", ""),
        source=doc.get("source", "markdown"),
        source_file=doc.get("source_file", ""),
        mcp_connection_id=doc.get("mcp_connection_id", ""),
        version=doc.get("version", 1),
        tags=doc.get("tags", []),
        files=files,
        created_at=doc.get("created_at", ""),
        updated_at=doc.get("updated_at", ""),
    )


@router.post(
    "/upload",
    response_model=ToolUploadResponse,
    summary="Upload Markdown Skill file(s) or directory",
    responses={
        403: {"description": "Forbidden — developer+ role required"},
        413: {"description": "File too large (>1MB) or directory too large (>10MB)"},
    },
)
async def upload_tools(
    files: list[UploadFile] = File(..., description="Skill Markdown 文件（支持多文件/文件夹上传）"),
    _: UserResponse = Depends(require_any_role("admin", "developer")),
) -> ToolUploadResponse:
    """Upload one or more Markdown Skill files to register tools. (AC3)

    Supports two modes:

    1. **Directory mode**: Files grouped by directory name (e.g., ``my-skill/SKILL.md``).
       Each directory must contain a ``SKILL.md`` entry point. All files in the
       directory are stored as a single Tool document with ``files`` field populated.

    2. **Single-file mode**: Standalone ``.md`` files (legacy compatibility).

    Each file/directory is parsed independently — successful ones register
    tools, failed ones are collected into ``errors``.  Name conflicts
    are reported as errors (no overwrite).
    """
    from app.core.errors import ConflictError, ValidationError
    from app.engine.tool.skill_parser import SkillParseError, parse_skill_directory, parse_skill_markdown

    # Group files by directory prefix
    dir_groups: dict[str, dict[str, str]] = defaultdict(dict)
    single_files: list[tuple[str, UploadFile]] = []

    for f in files:
        filename = f.filename or ""
        if not filename:
            continue

        parts = filename.split("/")
        if len(parts) >= 2 and parts[0]:
            # Directory mode: my-skill/SKILL.md
            dir_name = parts[0]
            dir_groups[dir_name][filename] = ""  # Will fill after reading
            single_files.append((filename, f))
        else:
            # Single file mode
            single_files.append((filename, f))

    # Read all file contents
    file_contents: dict[str, str] = {}
    for filename, f in single_files:
        try:
            content_bytes = await f.read()
        except Exception as exc:  # pragma: no cover - defensive
            file_contents[filename] = f"__read_error__: {exc}"
            continue

        if len(content_bytes) > MAX_FILE_SIZE:
            file_contents[filename] = f"__size_error__: {len(content_bytes)}"
            continue

        file_contents[filename] = content_bytes.decode("utf-8")

    created: list[ToolResponse] = []
    errors: list[ToolUploadErrorItem] = []

    # Process directory groups
    processed_dirs: set[str] = set()
    for filename, content in file_contents.items():
        parts = filename.split("/")
        if len(parts) < 2 or not parts[0]:
            continue

        dir_name = parts[0]
        if dir_name in processed_dirs:
            continue

        # Collect all files for this directory
        dir_files = {
            fn: file_contents[fn]
            for fn in file_contents
            if fn.startswith(f"{dir_name}/")
        }

        # Check if any file had read/size error
        error_file = next(
            ((fn, content) for fn, content in dir_files.items() if content.startswith("__")),
            None,
        )
        if error_file:
            fn, err_content = error_file
            if err_content.startswith("__read_error__"):
                errors.append(ToolUploadErrorItem(filename=fn, error=err_content.replace("__read_error__: ", "")))
            elif err_content.startswith("__size_error__"):
                errors.append(
                    ToolUploadErrorItem(
                        filename=fn,
                        error=f"文件过大（>1MB）：{err_content.replace('__size_error__: ', '')} bytes",
                    )
                )
            processed_dirs.add(dir_name)
            continue

        # Check total directory size
        total_bytes = sum(len(c.encode("utf-8")) for c in dir_files.values())
        if total_bytes > MAX_DIRECTORY_SIZE:
            errors.append(
                ToolUploadErrorItem(
                    filename=dir_name,
                    error=f"目录总大小（{total_bytes} bytes）超过上限（{MAX_DIRECTORY_SIZE} bytes）",
                )
            )
            processed_dirs.add(dir_name)
            continue

        # Parse directory
        try:
            parsed_dir = parse_skill_directory(dir_files, dir_name)
            doc = await ToolService.create_tool_from_directory(parsed_dir, dir_name)
            created.append(_doc_to_response(doc))
            processed_dirs.add(dir_name)
        except SkillParseError as exc:
            errors.append(ToolUploadErrorItem(filename=dir_name, error=exc.detail))
            processed_dirs.add(dir_name)
        except (ConflictError, ValidationError) as exc:
            errors.append(ToolUploadErrorItem(filename=dir_name, error=str(exc)))
            processed_dirs.add(dir_name)
        except Exception as exc:
            logger.error("tool_directory_upload_failed", dir_name=dir_name, error=str(exc))
            errors.append(ToolUploadErrorItem(filename=dir_name, error=f"创建失败: {exc}"))
            processed_dirs.add(dir_name)

    # Process single files (non-directory)
    for filename, content in file_contents.items():
        if "/" in filename:  # Skip files already processed as directories
            continue

        if content.startswith("__read_error__"):
            errors.append(ToolUploadErrorItem(filename=filename, error=content.replace("__read_error__: ", "")))
            continue
        if content.startswith("__size_error__"):
            errors.append(
                ToolUploadErrorItem(
                    filename=filename,
                    error=f"文件过大（>1MB）：{content.replace('__size_error__: ', '')} bytes",
                )
            )
            continue

        try:
            parsed = parse_skill_markdown(content, filename)
        except SkillParseError as exc:
            errors.append(ToolUploadErrorItem(filename=filename, error=exc.detail))
            continue
        except UnicodeDecodeError as exc:
            errors.append(
                ToolUploadErrorItem(filename=filename, error=f"编码错误（非 UTF-8）：{exc}")
            )
            continue

        try:
            doc = await ToolService.create_tool_from_parsed(parsed, source_file=filename)
            created.append(_doc_to_response(doc))
        except ConflictError:
            errors.append(
                ToolUploadErrorItem(
                    filename=filename,
                    error=f"工具名称 '{parsed.name}' 已被占用",
                )
            )
        except Exception as exc:
            logger.error("tool_upload_failed", filename=filename, error=str(exc))
            errors.append(ToolUploadErrorItem(filename=filename, error=f"创建失败: {exc}"))

    logger.info(
        "tools_uploaded",
        total_files=len(files),
        created_count=len(created),
        error_count=len(errors),
        directory_count=len(processed_dirs),
    )

    return ToolUploadResponse(created=created, errors=errors)


@router.get(
    "",
    response_model=ToolListResponse,
    summary="List tools",
    responses={403: {"description": "Forbidden — viewer+ role required"}},
)
async def list_tools(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(20, ge=1, le=100, description="Items per page"),
    name: str | None = Query(None, description="Filter by name (substring)"),
    source: str | None = Query(None, description="Filter by source (markdown / mcp / builtin)"),
    mcp_connection_id: str | None = Query(None, description="Filter by MCP connection ID"),
    _: UserResponse = Depends(require_any_role("admin", "developer", "operator", "viewer")),
) -> ToolListResponse:
    """List all tools with pagination and optional filtering. (AC4)"""
    items, total = await ToolService.list_tools(
        page=page,
        page_size=page_size,
        name=name,
        source=source,
        mcp_connection_id=mcp_connection_id,
    )

    tools = [_doc_to_response(doc) for doc in items]
    return ToolListResponse(
        items=tools, total=total, page=page, page_size=page_size
    )


@router.get(
    "/{tool_id}",
    response_model=ToolResponse,
    summary="Get tool details",
    responses={
        403: {"description": "Forbidden — viewer+ role required"},
        404: {"description": "Tool not found"},
    },
)
async def get_tool(
    tool_id: str,
    _: UserResponse = Depends(require_any_role("admin", "developer", "operator", "viewer")),
) -> ToolResponse:
    """Get a Tool by its ID. (AC4)"""
    from app.core.errors import NotFoundError

    doc = await ToolService.get_tool(tool_id)
    if doc is None:
        raise NotFoundError(
            code="TOOL_NOT_FOUND",
            message=f"工具 {tool_id} 不存在",
        )

    return _doc_to_response(doc)


@router.get(
    "/{tool_id}/files",
    response_model=SkillFileTreeResponse,
    summary="Get tool file tree",
    responses={
        403: {"description": "Forbidden — viewer+ role required"},
        404: {"description": "Tool not found"},
    },
)
async def get_tool_files(
    tool_id: str,
    _: UserResponse = Depends(require_any_role("admin", "developer", "operator", "viewer")),
) -> SkillFileTreeResponse:
    """Get the file tree structure for a directory-based Tool.

    Returns a hierarchical tree of files/directories.  Legacy single-file
    tools return an empty list.
    """
    from app.core.errors import NotFoundError

    tree_nodes = await ToolService.get_tool_files(tool_id)
    if tree_nodes is None:
        raise NotFoundError(
            code="TOOL_NOT_FOUND",
            message=f"工具 {tool_id} 不存在",
        )

    # Convert dicts to Pydantic nodes
    def _dict_to_node(d: dict) -> SkillFileTreeNode:
        children = d.get("children")
        return SkillFileTreeNode(
            key=d["key"],
            title=d["title"],
            is_leaf=d.get("is_leaf", True),
            children=[_dict_to_node(c) for c in children] if children else None,
            size=d.get("size", 0),
        )

    nodes = [_dict_to_node(d) for d in tree_nodes]
    return SkillFileTreeResponse(tool_id=tool_id, files=nodes)


@router.get(
    "/{tool_id}/files/{file_path:path}",
    summary="Get tool file content",
    responses={
        403: {"description": "Forbidden — viewer+ role required"},
        404: {"description": "Tool or file not found"},
    },
)
async def get_tool_file_content(
    tool_id: str,
    file_path: str,
    _: UserResponse = Depends(require_any_role("admin", "developer", "operator", "viewer")),
) -> SkillFileResponse:
    """Get a single file's content from a Tool.

    Supports viewing and editing individual files within a Skill directory.
    """
    from app.core.errors import NotFoundError

    file_data = await ToolService.get_tool_file_content(tool_id, file_path)
    if file_data is None:
        raise NotFoundError(
            code="FILE_NOT_FOUND",
            message=f"文件 {file_path} 在工具 {tool_id} 中不存在",
        )

    return SkillFileResponse(
        path=file_data["path"],
        content=file_data["content"],
        size=file_data.get("size", 0),
    )


@router.put(
    "/{tool_id}/files/{file_path:path}",
    response_model=SkillFileResponse,
    summary="Update tool file content",
    responses={
        403: {"description": "Forbidden — developer+ role required"},
        404: {"description": "Tool or file not found"},
    },
)
async def update_tool_file(
    tool_id: str,
    file_path: str,
    body: SkillFileUpdate,
    _: UserResponse = Depends(require_any_role("admin", "developer")),
) -> SkillFileResponse:
    """Update a single file's content in a Tool.

    If the updated file is ``SKILL.md``, the Tool's name/description/
    instructions are also updated by re-parsing the frontmatter.
    """
    from app.core.errors import NotFoundError

    updated = await ToolService.update_tool_file(tool_id, file_path, body.content)
    if updated is None:
        raise NotFoundError(
            code="FILE_NOT_FOUND",
            message=f"文件 {file_path} 在工具 {tool_id} 中不存在",
        )

    return SkillFileResponse(
        path=updated["path"],
        content=updated["content"],
        size=updated.get("size", 0),
    )


@router.put(
    "/{tool_id}",
    response_model=ToolResponse,
    summary="Update a tool",
    responses={
        403: {"description": "Forbidden — developer+ role required"},
        404: {"description": "Tool not found"},
    },
)
async def update_tool(
    tool_id: str,
    body: ToolUpdate,
    _: UserResponse = Depends(require_any_role("admin", "developer")),
) -> ToolResponse:
    """Update a Tool's editable fields (tags). Auto-increments version. (AC5)"""
    from app.core.errors import NotFoundError

    doc = await ToolService.update_tool(
        tool_id=tool_id,
        tags=body.tags,
    )
    if doc is None:
        raise NotFoundError(
            code="TOOL_NOT_FOUND",
            message=f"工具 {tool_id} 不存在",
        )

    return _doc_to_response(doc)


@router.delete(
    "/{tool_id}",
    status_code=204,
    summary="Delete a tool",
    responses={
        403: {"description": "Forbidden — developer+ role required"},
        404: {"description": "Tool not found"},
        409: {"description": "Tool is referenced by one or more Agents"},
    },
)
async def delete_tool(
    tool_id: str,
    _: UserResponse = Depends(require_any_role("admin", "developer")),
) -> None:
    """Delete a Tool by ID. Checks for Agent references. (AC5)"""
    from app.core.errors import NotFoundError

    deleted = await ToolService.delete_tool(tool_id)
    if not deleted:
        raise NotFoundError(
            code="TOOL_NOT_FOUND",
            message=f"工具 {tool_id} 不存在",
        )

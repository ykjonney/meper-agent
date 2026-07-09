"""File attachment rendering — shared by stream / invoke / history paths.

Renders uploaded files as structured XML blocks that get embedded into the
LLM context so the agent can see file contents without a separate tool call.
"""
from __future__ import annotations

_MAX_ATTACHMENT_CHARS = 50_000

_TEXT_MIME_PREFIXES = ("text/", "application/json", "application/xml")
_TEXT_MIME_EXACT = {
    "application/javascript", "application/typescript",
    "application/x-yaml", "application/x-sh", "application/sql",
}


def _is_text_mime(mime_type: str, filename: str) -> bool:
    """判断文件是否应视为文本（可安全注入到 LLM 上下文）。"""
    if not mime_type or mime_type == "application/octet-stream":
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        return ext in {
            ".txt", ".md", ".json", ".yaml", ".yml", ".xml", ".html",
            ".csv", ".tsv", ".py", ".js", ".ts", ".jsx", ".tsx",
            ".sh", ".sql", ".log", ".rst", ".toml", ".ini",
        }
    if mime_type in _TEXT_MIME_EXACT:
        return True
    return any(mime_type.startswith(p) for p in _TEXT_MIME_PREFIXES)


def _render_single_file(
    *, file_id: str, name: str, size: int, mime_type: str, content: str | None,
    truncated: bool = False, unavailable_reason: str | None = None,
) -> str:
    """渲染单个附件为结构化 XML 块。"""
    import html as _html
    attrs = (
        f'id="{file_id}" '
        f'name="{_html.escape(str(name))}" '
        f'size="{size}" '
        f'mime_type="{_html.escape(str(mime_type))}"'
    )
    if content is None:
        note = unavailable_reason or "content unavailable"
        return f"<file {attrs}>\n[{_html.escape(note)}]\n</file>"
    if truncated:
        return (
            f"<file {attrs}>\n"
            f"{content}\n"
            f"[... truncated at {_MAX_ATTACHMENT_CHARS} chars ...]\n"
            f"</file>"
        )
    return f"<file {attrs}>\n{content}\n</file>"


def render_attachments_block(file_blocks: list[str]) -> str:
    """把多个 <file> 块包成 <attachments> 并加提示尾巴。"""
    if not file_blocks:
        return ""
    inner = "\n".join(file_blocks)
    return (
        "\n\n<attachments>\n"
        f"{inner}\n"
        "</attachments>\n\n"
        "提示：如需将附件传给 workflow 的 file 类型参数，使用 <file> 标签的 id 属性值 "
        "（例如 'file_01ABC...'）作为参数值。"
    )


async def render_files_by_ids(file_ids: list[str]) -> list[str]:
    """根据 file_id 列表加载文件，返回渲染好的 <file> 字符串列表。"""
    if not file_ids:
        return []
    from app.services.file_service import FileService
    from app.services.file_storage import LocalFileStorage

    file_svc = FileService(storage=LocalFileStorage())
    blocks: list[str] = []
    for fid in file_ids:
        try:
            loaded = await file_svc.load_content(fid)
        except Exception:
            continue
        if loaded is None:
            continue
        fref, data = loaded
        if not _is_text_mime(fref.mime_type, fref.name):
            blocks.append(_render_single_file(
                file_id=fref.id, name=fref.name, size=fref.size,
                mime_type=fref.mime_type, content=None,
                unavailable_reason=f"binary file ({fref.mime_type})",
            ))
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            blocks.append(_render_single_file(
                file_id=fref.id, name=fref.name, size=fref.size,
                mime_type=fref.mime_type, content=None,
                unavailable_reason="UTF-8 decode failed",
            ))
            continue
        truncated = len(text) > _MAX_ATTACHMENT_CHARS
        if truncated:
            text = text[:_MAX_ATTACHMENT_CHARS]
        blocks.append(_render_single_file(
            file_id=fref.id, name=fref.name, size=fref.size,
            mime_type=fref.mime_type, content=text, truncated=truncated,
        ))
    return blocks


async def render_files_by_paths(
    file_paths: list[str], workspace_root,
) -> list[str]:
    """Fallback：只有路径时的降级渲染（无 file_id / size / mime_type）。"""
    if not file_paths:
        return []
    from pathlib import Path as _Path

    blocks: list[str] = []
    input_dir = _Path(workspace_root) / "input"
    for rel_path in file_paths:
        abs_path = (input_dir / rel_path).resolve()
        if not str(abs_path).startswith(str(input_dir.resolve())):
            continue
        if not abs_path.is_file():
            continue
        try:
            stat = abs_path.stat()
            data = abs_path.read_bytes()
        except OSError:
            continue
        import mimetypes
        mime, _ = mimetypes.guess_type(abs_path.name)
        mime = mime or "application/octet-stream"
        if not _is_text_mime(mime, abs_path.name):
            blocks.append(_render_single_file(
                file_id="", name=rel_path, size=stat.st_size,
                mime_type=mime, content=None,
                unavailable_reason=f"binary file ({mime})",
            ))
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            blocks.append(_render_single_file(
                file_id="", name=rel_path, size=stat.st_size,
                mime_type=mime, content=None,
                unavailable_reason="UTF-8 decode failed",
            ))
            continue
        truncated = len(text) > _MAX_ATTACHMENT_CHARS
        if truncated:
            text = text[:_MAX_ATTACHMENT_CHARS]
        blocks.append(_render_single_file(
            file_id="", name=rel_path, size=stat.st_size,
            mime_type=mime, content=text, truncated=truncated,
        ))
    return blocks


__all__ = [
    "render_attachments_block",
    "render_files_by_ids",
    "render_files_by_paths",
]

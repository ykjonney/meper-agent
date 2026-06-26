"""File variable validator for workflow StartNodeExecutor.

验证工作流启动节点的文件类型输入变量：
- FileRef 存在性
- allowed_extensions 约束
- max_size_mb 约束
- multiple 约束

验证通过后返回 :class:`FileVariableValue` 实例（或 list）。
FileVariableValue 是 dict 子类，包含文件元信息 + 内容；
Jinja2 渲染时通过 ``__str__`` 自动输出结构化 XML 格式，
让下游 Agent 节点无需特殊写法即可看到完整的附件信息。
"""
from __future__ import annotations

import html
from typing import Any

from loguru import logger

from app.models.file_library import FileRef


# ── 文件内容注入配置 ─────────────────────────────────────────────
# 注入到变量池的单文件内容最大字符数；超出则截断并附加提示。
# 50K 字符 ≈ 12K-25K tokens，对大多数 LLM 上下文窗口友好。
MAX_CONTENT_CHARS = 50_000

# 被视为"文本文件"的 MIME 类型前缀 / 完整值 —— 只有这些类型会尝试注入内容。
_TEXT_MIME_PREFIXES = ("text/", "application/json", "application/xml")
_TEXT_MIME_EXACT = {
    "application/javascript",
    "application/typescript",
    "application/x-yaml",
    "application/x-sh",
    "application/sql",
    "application/graphql",
    "application/ld+json",
    "application/manifest+json",
}
# 常见文本扩展名（兜底：mime_type 为 octet-stream 时按扩展名判断）
_TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".rst",
    ".json", ".jsonl", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf",
    ".xml", ".html", ".htm", ".xhtml", ".svg", ".css", ".scss", ".less",
    ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
    ".py", ".pyi", ".rb", ".go", ".rs", ".java", ".kt", ".scala", ".c",
    ".cpp", ".h", ".hpp", ".cs", ".swift", ".php", ".lua", ".r", ".sql",
    ".sh", ".bash", ".zsh", ".fish", ".ps1", ".bat", ".cmd",
    ".csv", ".tsv", ".log", ".diff", ".patch", ".env",
    ".dockerfile", ".makefile", ".cmake",
}


def _get_file_service():
    """延迟导入 FileService，避免循环依赖。"""
    from app.services.file_service import FileService
    from app.services.file_storage import LocalFileStorage

    return FileService(storage=LocalFileStorage())


class FileVariableValue(dict):
    """文件变量的运行时表示 —— dict 子类，自定义 ``__str__``。

    字段：
    - ``file_id`` / ``name`` / ``size`` / ``mime_type`` / ``storage_key``: 元信息
    - ``content``: 文本内容（截断后）或占位说明
    - ``truncated``: 是否被截断
    - ``content_unavailable_reason``: 内容不可用原因（二进制 / 解码失败 / 超大）

    Jinja2 模板里 ``{{ var }}`` 会调用 ``__str__``，输出结构化 XML 块，
    让 LLM 一眼就能识别出这是一个文件附件及其 ID / 内容。
    """

    def __str__(self) -> str:
        fid = self.get("file_id", "")
        name = self.get("name", "")
        size = self.get("size", 0)
        mime = self.get("mime_type", "")
        content = self.get("content")
        truncated = self.get("truncated", False)
        reason = self.get("content_unavailable_reason")

        attrs = f'id="{fid}" name="{html.escape(str(name))}" size="{size}" mime_type="{html.escape(str(mime))}"'
        if content is None:
            note = reason or "content unavailable"
            return f"<file {attrs}>\n[{html.escape(note)}]\n</file>"
        if truncated:
            return (
                f"<file {attrs}>\n"
                f"{content}\n"
                f"[... truncated at {MAX_CONTENT_CHARS} chars; use `read` tool with storage_key for full content ...]\n"
                f"</file>"
            )
        return f"<file {attrs}>\n{content}\n</file>"

    # JSON/BSON 序列化时保持普通 dict 行为（不含 content 的大文本进 MongoDB 时要小心）
    # 这里不重载，让上游按需裁剪 content 字段再持久化。


def _is_text_mime(mime_type: str, filename: str) -> bool:
    """判断文件是否应视为文本（可安全注入内容到 LLM 上下文）。"""
    if not mime_type or mime_type == "application/octet-stream":
        # 兜底：按扩展名判断
        ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        return ext in _TEXT_EXTENSIONS
    if mime_type in _TEXT_MIME_EXACT:
        return True
    return any(mime_type.startswith(p) for p in _TEXT_MIME_PREFIXES)


def _file_ref_to_dict(fref: FileRef) -> dict[str, Any]:
    """将 FileRef 转为下游节点可用的元信息 dict（不含 content）。"""
    return {
        "file_id": fref.id,
        "name": fref.name,
        "size": fref.size,
        "mime_type": fref.mime_type,
        "storage_key": fref.storage_key,
    }


def _check_extension(filename: str, allowed_extensions: list[str]) -> str | None:
    """检查文件扩展名是否在允许列表中。

    Returns:
        None 表示通过；str 表示错误消息。
    """
    if not allowed_extensions:
        return None
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    allowed_lower = [e.lower() for e in allowed_extensions]
    if ext not in allowed_lower:
        return f"文件 {filename} 扩展名 {ext!r} 不在允许列表 {allowed_extensions}"
    return None


def _check_size(fref: FileRef, max_size_mb: float | None) -> str | None:
    """检查文件大小是否超限。

    Returns:
        None 表示通过；str 表示错误消息。
    """
    if max_size_mb is None:
        return None
    max_bytes = max_size_mb * 1024 * 1024
    if fref.size > max_bytes:
        return f"文件 {fref.name} 大小 {fref.size} 字节超过限制 {max_size_mb}MB（{int(max_bytes)} 字节）"
    return None


async def validate_file_variable(
    value: str | list[str],
    var_def: dict[str, Any],
) -> tuple[FileVariableValue | list[FileVariableValue] | None, str | None]:
    """验证文件变量并返回 :class:`FileVariableValue`（含文件内容）。

    Args:
        value: FileRef ID 字符串或 ID 列表
        var_def: 变量定义，约束从 ``constraints`` 子字典读取

    Returns:
        ``(resolved, error)`` — resolved 为 None 表示验证失败；
        单文件返回 FileVariableValue，多文件（multiple=True）返回 list[FileVariableValue]。
    """
    constraints = var_def.get("constraints") if isinstance(var_def.get("constraints"), dict) else {}
    allowed_ext: list[str] = constraints.get("allowed_extensions") or []
    max_size_mb: float | None = constraints.get("max_size_mb")
    multiple: bool = bool(constraints.get("multiple", False))

    # 规范化为列表
    if isinstance(value, str):
        ids = [value]
    elif isinstance(value, list):
        ids = value
    else:
        return None, f"文件变量值应为 FileRef ID 字符串或列表，收到 {type(value).__name__}"

    if not multiple and len(ids) > 1:
        return None, "此变量不允许多文件输入"

    file_svc = _get_file_service()
    resolved: list[FileVariableValue] = []
    for fid in ids:
        if not isinstance(fid, str):
            return None, f"FileRef ID 应为字符串，收到 {type(fid).__name__}"
        fref = await file_svc.get(fid)
        if fref is None:
            return None, f"文件 {fid!r} 不存在"
        # 扩展名检查
        ext_err = _check_extension(fref.name, allowed_ext)
        if ext_err:
            return None, ext_err
        # 大小检查
        size_err = _check_size(fref, max_size_mb)
        if size_err:
            return None, size_err
        # 构造 FileVariableValue（含文件内容）
        fvv = await _build_file_variable_value(fref, file_svc)
        resolved.append(fvv)

    if multiple:
        return resolved, None
    return resolved[0] if resolved else None, None


async def _build_file_variable_value(
    fref: FileRef, file_svc: Any,
) -> FileVariableValue:
    """从 FileRef 构造 FileVariableValue，尝试加载文件内容。

    文本文件：读取 UTF-8 内容，超长截断并标记 truncated。
    二进制文件 / 读取失败：不设置 content，记录原因。
    """
    base = _file_ref_to_dict(fref)
    fvv = FileVariableValue(base)

    # 判断是否为文本文件
    if not _is_text_mime(fref.mime_type, fref.name):
        fvv["content_unavailable_reason"] = (
            f"binary file ({fref.mime_type}); use `read` tool with storage_key to access"
        )
        return fvv

    # 读取内容
    try:
        loaded = await file_svc.load_content(fref.id)
    except Exception as exc:
        logger.warning(
            "file_variable_content_load_failed",
            file_id=fref.id, error=str(exc),
        )
        fvv["content_unavailable_reason"] = f"content load failed: {exc}"
        return fvv

    if loaded is None:
        fvv["content_unavailable_reason"] = "file not found in storage"
        return fvv

    _, data = loaded
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        # 声明为文本类型但实际非 UTF-8 → 按二进制处理
        fvv["content_unavailable_reason"] = "UTF-8 decode failed; file may be binary"
        return fvv

    # 截断超长内容
    if len(text) > MAX_CONTENT_CHARS:
        fvv["content"] = text[:MAX_CONTENT_CHARS]
        fvv["truncated"] = True
    else:
        fvv["content"] = text
        fvv["truncated"] = False

    return fvv

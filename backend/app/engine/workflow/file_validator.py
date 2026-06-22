"""File variable validator for workflow StartNodeExecutor.

验证工作流启动节点的文件类型输入变量：
- FileRef 存在性
- allowed_extensions 约束
- max_size_mb 约束
- multiple 约束

验证通过后返回解析后的文件元信息 dict（或 list[dict]）。
"""
from __future__ import annotations

from typing import Any

from loguru import logger

from app.models.file_library import FileRef


def _get_file_service():
    """延迟导入 FileService，避免循环依赖。"""
    from app.services.file_service import FileService
    from app.services.file_storage import LocalFileStorage

    return FileService(storage=LocalFileStorage())


def _file_ref_to_dict(fref: FileRef) -> dict[str, Any]:
    """将 FileRef 转为下游节点可用的元信息 dict。"""
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
) -> tuple[dict[str, Any] | list[dict[str, Any]] | None, str | None]:
    """验证文件变量并返回解析后的文件元信息。

    Args:
        value: FileRef ID 字符串或 ID 列表
        var_def: 变量定义，约束从 ``constraints`` 子字典读取

    Returns:
        ``(resolved, error)`` — resolved 为 None 表示验证失败；
        单文件返回 dict，多文件（multiple=True）返回 list[dict]。
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
    resolved: list[dict[str, Any]] = []
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
        resolved.append(_file_ref_to_dict(fref))

    if multiple:
        return resolved, None
    return resolved[0] if resolved else None, None

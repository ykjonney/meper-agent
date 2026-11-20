"""view_image —— 内置图片回看工具，按 file_id 把历史图片重新载入上下文。

多模态图片只在注入当轮以 image_url 块存在；旧轮图片会被 harness 压缩层
降级为可回取占位（formatter 由 harness_integration.context 注入）。本工具
是"回取"的落地：按 file_id 读 FileRef → 降采样/光栅化 → 返回多模态
content blocks（LangChain ToolMessage.content 支持 list）——工具结果对
模型可见当轮，之后同样被降级，需要时再调（每字节的可见性都有价格）。

与 parse_file 同构的安全模型：workspace context 拿 user_id/session_id，
FileRef 必须属于当前用户且 origin_id == 当前 session（对话附件）——防止
工具被诱导读取任意库内文件。
"""

from __future__ import annotations

from langchain_core.tools import BaseTool, tool


def _err(msg: str) -> str:
    """返回友好错误文本（不抛异常，让 agent 能读懂并修正）。"""
    return f"[view_image] {msg}"


@tool
async def view_image(file_id: str | None = None, path: str | None = None) -> list[dict] | str:
    """Load an image for visual inspection — by chat-attachment id OR by workspace path.

    Two modes (provide exactly one):
    - ``file_id``: re-view an image previously attached to this chat —
      stale images are degraded out of context with a placeholder like
      "[图片 xx 已移出上下文,可用 view_image(file_id=...) 查看]". Get the
      id from the <file> tag or the [IMAGE ...] marker.
    - ``path``: view an image file in the workspace (e.g. a chart you just
      generated — "output/chart.png"). Use this to visually verify images
      you created.

    Args:
        file_id: File id from the <attachments> block / [IMAGE] marker
            (starts with "file_").
        path: Workspace-relative path of an image file (tmp/ or output/).
    """
    if bool(file_id) == bool(path):
        return _err("请提供 file_id 或 path 之一（不要同时提供或都不提供）")

    from app.engine.agent.builtin_tools import _get_workspace

    workspace = _get_workspace()
    if workspace is None:
        return _err("当前无工作区上下文，无法查看图片")

    if path is not None:
        return await _view_workspace_image(workspace, path)

    # ── file_id 模式：会话附件回看（所有权 + session 归属校验）────────
    session_id = workspace.session_id
    if not session_id:
        return _err("当前非对话会话上下文，无法回看历史图片")

    from app.services.file_service import FileService
    from app.services.file_storage import LocalFileStorage

    loaded = await FileService(storage=LocalFileStorage()).load_content(file_id)
    if loaded is None:
        return _err(f"图片不存在：{file_id}")
    fref, data = loaded
    if fref.owner_user_id != workspace.user_id:
        return _err(f"文件 {file_id} 不属于当前用户，无权访问")
    if fref.origin_id != session_id:
        return _err(f"文件 {file_id} 不是当前会话的附件，无权访问")
    return _render_image_bytes(file_id or "", fref.name, data, fref.mime_type or "")


async def _view_workspace_image(workspace, path: str) -> list[dict] | str:
    """workspace 路径模式：查看 agent 自产图片（layout 白名单校验）。"""
    try:
        from app.engine.tool.workspace import layout_for_workspace

        resolved = layout_for_workspace(workspace).resolve_read(path).host
    except PermissionError as exc:
        return _err(str(exc))
    if not resolved.is_file():
        return _err(f"图片不存在：{path}")
    try:
        data = resolved.read_bytes()
    except OSError as exc:
        return _err(f"读取失败：{path}（{exc}）")
    return _render_image_bytes("", path, data, "")


def _render_image_bytes(file_id: str, name: str, data: bytes, declared_mime: str) -> list[dict] | str:
    """嗅探/降采样/编码为多模态 content blocks（两条模式共用尾部）。"""
    from app.services.file_rendering import (
        downscale_image_bytes,
        rasterize_svg,
        sniff_image_mime,
    )

    mime = sniff_image_mime(data, declared_mime)
    if not mime:
        return _err(f"文件 {name} 不是图片（{declared_mime or '未知类型'}）")
    if mime == "image/svg+xml":
        png = rasterize_svg(data)
        if png is None:
            return _err(f"SVG 渲染失败：{name}（其源码已在附件清单中）")
        data = png
        mime = "image/png"
    else:
        from app.core.config import settings

        res = downscale_image_bytes(
            data,
            max_edge=settings.IMAGE_MAX_EDGE,
            max_size=settings.IMAGE_MAX_SIZE_BYTES,
        )
        if res is None:
            return _err(f"图片处理失败或超出大小限制：{name}")
        data, mime = res

    import base64

    b64 = base64.b64encode(data).decode()
    # 标记块与 image_url 块成对——harness 降级图片时靠它反查 file_id/name,
    # 与 file_rendering.build_multimodal_content 的结构保持一致。
    # 纯文本主模型收不到图块(兼容网关静默丢弃)——图片语义转化由模型按需
    # 调用专门的多模态工具完成(平台不做自动转化,因为无法预知模型能力)。
    return [
        {"type": "text", "text": f'[IMAGE file_id="{file_id}" name="{name}"]'},
        {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
    ]



# ---------------------------------------------------------------------------
# Tool list — exported for context.py injection (builtin_config 白名单过滤)
# ---------------------------------------------------------------------------

_IMAGE_TOOLS: list[BaseTool] = [view_image]

# name → tool 实例查找表：/tools/builtin 端点、context 注入、builder prompt 声明
# 三处共用（harness BUILTIN_TOOLS 取不到 app 层工具，需补此表查找）。
IMAGE_TOOL_BY_NAME: dict[str, BaseTool] = {t.name: t for t in _IMAGE_TOOLS}

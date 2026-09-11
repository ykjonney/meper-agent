"""User-token ContextVar — MCP 工具调用时透传终端用户身份。

宿主在每次 Agent 执行前 set_user_token_context(token)，MCP 工具的
interceptor 内部 get_user_token_context() 读取。

新模型（mcp-credential-broker）下：
- ``user_token``：通用 token 原文（标识用途，不直接透传给 MCP）。
- ``token_record_id``：mcp_token_credentials._id，兑换器查绑定的 key。
  外部路径（/ext/*）才 set；内部路径（平台 JWT 测试）不 set，interceptor
  自然降级用 connection 静态凭证。
- ``external_required``：本次执行是否来自外部终端用户（fail-closed 守卫）。
  为 True 时 MCP 调用必须以终端用户身份兑换凭证——身份或兑换器缺失
  一律拒绝，绝不静默回退内部静态凭证（否则外部用户会借平台级凭证
  跨权限访问数据）。由宿主在身份事实源（如任务文档）判定后设置。

设计：token 仅在 ContextVar 生命周期内（单次请求）存在，不写入
Redis、不写日志、不入库。未设置（内部路径/平台用户调用）时返回
None，loader 此时应使用 MCP connection 的静态凭证。
"""
from __future__ import annotations

import contextvars

_user_token_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "mcp_user_token", default=None
)

# 通用 token 记录 id（外部路径才 set，内部路径保持 None）
_token_record_id_ctx: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "mcp_token_record_id", default=None
)

# 外部执行守卫标志（宿主判定"本次执行属于外部终端用户"后 set）
_external_required_ctx: contextvars.ContextVar[bool] = contextvars.ContextVar(
    "mcp_external_required", default=False
)


def set_user_token_context(token: str | None) -> "contextvars.Token[str | None]":
    """设置当前请求的 user_token。返回 Token 用于 reset。"""
    return _user_token_ctx.set(token)


def reset_user_token_context(token: "contextvars.Token[str | None]") -> None:
    """恢复到 set 之前的状态（用 set 返回的 Token）。"""
    _user_token_ctx.reset(token)


def get_user_token_context() -> str | None:
    """读取当前请求的 user_token。未设置返回 None（内部路径/平台用户）。"""
    return _user_token_ctx.get()


def set_token_record_id_context(
    record_id: str | None,
) -> "contextvars.Token[str | None]":
    """设置当前请求的 token_record_id（外部路径）。返回 Token 用于 reset。"""
    return _token_record_id_ctx.set(record_id)


def reset_token_record_id_context(token: "contextvars.Token[str | None]") -> None:
    """恢复到 set 之前的状态（用 set 返回的 Token）。"""
    _token_record_id_ctx.reset(token)


def get_token_record_id_context() -> str | None:
    """读取当前请求的 token_record_id。未设置返回 None（内部路径）。"""
    return _token_record_id_ctx.get()


def set_external_required_context(
    required: bool,
) -> "contextvars.Token[bool]":
    """声明本次执行是否来自外部终端用户（fail-closed 守卫）。返回 Token 用于 reset。"""
    return _external_required_ctx.set(required)


def reset_external_required_context(token: "contextvars.Token[bool]") -> None:
    """恢复到 set 之前的状态（用 set 返回的 Token）。"""
    _external_required_ctx.reset(token)


def get_external_required_context() -> bool:
    """读取外部执行守卫标志。未设置返回 False（内部路径）。"""
    return _external_required_ctx.get()


__all__ = [
    "set_user_token_context",
    "reset_user_token_context",
    "get_user_token_context",
    "set_token_record_id_context",
    "reset_token_record_id_context",
    "get_token_record_id_context",
    "set_external_required_context",
    "reset_external_required_context",
    "get_external_required_context",
]

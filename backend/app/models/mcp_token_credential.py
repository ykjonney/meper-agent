"""MCP token credential data model — 终端用户的通用 token + 各 MCP 绑定凭证。

admin 为终端用户创建一条记录：填用户名称 + 绑定 N 个 MCP（每个填 token 或
用户名密码）。MEPER 生成一个通用 token（``meper_`` 前缀），用户拿它通过 client
调 agent；agent 调 MCP 前，兑换器用记录 id 查出该用户对该 MCP 的绑定凭证，
替换 MCP 调用的凭证。

凭证值用 ``enc:`` 前缀 + AES-256-GCM 加密（复用 ``app.core.crypto``）。
``auth_type`` 决定凭证怎么进 HTTP 头（复用 ``mcp_client._build_headers``）。

详见 docs/planning-artifacts/mcp-credential-broker-design.md。
"""
from __future__ import annotations

from enum import StrEnum


class McpTokenStatus(StrEnum):
    """通用 token 记录的生命周期状态。"""

    ACTIVE = "active"
    DISABLED = "disabled"


class McpCredentialType(StrEnum):
    """单个 MCP 绑定的凭证形态。"""

    TOKEN = "token"        # 用户填的是目标 MCP 的 token，运行时直传
    PASSWORD = "password"  # 用户填的是账密，运行时先 POST login_url 换 session


class McpAuthType(StrEnum):
    """兑换出的凭证怎么放进 HTTP 头（对齐 MCP connection 的 auth_type）。"""

    NONE = "none"
    API_KEY = "api_key"
    BEARER_TOKEN = "bearer_token"
    BASIC = "basic"


# 通用 token 的前缀（对齐 API Key 的 af_live_ 风格）
TOKEN_PREFIX = "meper_"

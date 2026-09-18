"""MCP 凭证错误类型 — harness 侧结构化错误定义。

app 层的 CredentialResolver 在凭证问题时抛出携带 app 信息的结构化错误
（``McpCredentialUnbound`` / ``McpCredentialInvalid``），拦截器据此生成
带机器可读标记的 isError 结果并引导 LLM 调 ``request_app_authorization``：

- ``McpCredentialUnbound``（UNBOUND）：用户未绑定该应用的凭证；
- ``McpCredentialInvalid``（INVALID）：已绑定但凭证失效——典型场景是
  用户在外部系统改了密码/用户名，存储的账密兑换 session 失败。身份
  映射（external_identities）不受影响，更新凭证即可恢复；
- ``McpAppUnavailable``（UNAVAILABLE）：应用登录端点不可用（5xx/超时/
  连接失败）——非凭证问题，不引导授权更新（重输密码解决不了），
  提示稍后重试；
- ``McpCredentialForbidden``（FORBIDDEN）：MCP 未挂载到任何授权应用，
  外部用户不得以平台静态凭证代用（fail-closed，防跨权限访问）。
  无可授权的 app，不引导授权，联系管理员挂应用或从 Agent 解绑。

定义在 harness（可独立发布库）——app 层实现 resolver 时 import 它，
不引入 app.* 依赖。
"""
from __future__ import annotations


class McpCredentialError(Exception):
    """MCP 凭证问题基类。

    Attributes:
        reason: 机器可读错误类别（拦截器写进 JSON 标记的值）。
        app_id: 相关应用 id。
        app_name: 应用显示名（供前端授权卡片渲染）。
        server_name: 触发的 MCP server 名。
        detail: 人类可读细节（如登录失败原因）。
    """

    reason = "UNBOUND"

    def __init__(
        self,
        app_id: str,
        app_name: str,
        server_name: str,
        detail: str = "",
    ) -> None:
        self.app_id = app_id
        self.app_name = app_name
        self.server_name = server_name
        self.detail = detail
        message = f"credential {self.reason} for app {app_id} ({server_name})"
        if detail:
            message = f"{message}: {detail}"
        super().__init__(message)


class McpCredentialUnbound(McpCredentialError):
    """用户未绑定目标 MCP 所属应用的凭证。"""

    reason = "UNBOUND"


class McpCredentialInvalid(McpCredentialError):
    """已绑定但凭证失效（密码/用户名被修改，兑换 session 失败）。

    身份映射不受影响（sub 以稳定用户 ID 为锚），更新绑定凭证即可恢复。
    """

    reason = "INVALID"


class McpAppUnavailable(McpCredentialError):
    """应用登录端点不可用（5xx/超时/连接失败）。

    凭证本身未必有问题——不引导用户重新授权（前端 parseUnboundMarker
    只认 UNBOUND/INVALID，UNAVAILABLE 不渲染授权卡），提示稍后重试。
    """

    reason = "UNAVAILABLE"


class McpCredentialForbidden(McpCredentialError):
    """MCP 未挂载到任何授权应用，外部用户不可用。

    认证型连接必须挂到应用走用户授权；外部终端用户的调用不得回退
    平台静态凭证（跨权限访问风险，与拦截器 fail-closed 守卫同源）。
    无可授权的 app——app_id/app_name 为空，提示文案带 server_name，
    不引导授权更新（前端 marker 过滤只认 UNBOUND/INVALID）。
    """

    reason = "FORBIDDEN"


__all__ = [
    "McpCredentialError",
    "McpCredentialUnbound",
    "McpCredentialInvalid",
    "McpAppUnavailable",
    "McpCredentialForbidden",
]

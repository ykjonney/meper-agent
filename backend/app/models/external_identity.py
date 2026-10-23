"""External identity mapping — sub composition for MongoDB identity docs.

Maps an external sub (``{app_id}:{identity_key}`` — application-namespaced)
to a platform user. This enables cross-application access: regardless of
which application context the request carries, identities bound by the
same platform user all resolve to the same platform_user_id, whose
``user_mcp_credentials`` holds credential bindings per application.
"""


def compose_sub(app_id: str, identity_key: str) -> str:
    """Combine application id and identity key into a globally unique sub.

    The application id namespaces the identity — same-named accounts in
    different applications (e.g. two systems both having an "admin")
    never collide.

    身份锚点 v4.2：``identity_key`` 优先为 introspection 的稳定用户 ID
    （RFC 7666 ``sub``，用户改名不变），无则退回登录名。登录名/密码属于
    可变"凭证"，不作为身份锚——改名/改密后身份映射不漂移，仅存的账密
    变旧（兑换 session 失败时引导用户更新凭证）。

    This rule is shared between:
    - binding time: compose_sub(app_id, 绑定时的 identity_key)
    - runtime: compose_sub(app_id, introspection 的 sub/username)
    """
    return f"{app_id}:{identity_key}"

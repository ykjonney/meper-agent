"""UserCredentialResolver — app 层实现的 MCP 凭证兑换器（v4）。

harness 的 _user_token_interceptor（外部路径）调本类的 resolve()，按
(platform_user_id, server_name) 查出该用户在该 MCP 所属应用的绑定凭证。

v4 改造（vs v3）：
- server_name → conn_id → 反查 applications（mcp_connection_ids 包含该 conn）
- 凭证查 user_mcp_credentials.app_bindings[app_id]
- login_config 从应用上取
- session 缓存 key 为 (platform_user_id, app_id)
- 注入方式用连接自己的 auth_type + auth_config.header_name

v5 增补（公共 MCP 放行）：
- conn.auth_type == "none"：连接无认证，直接放行（不反查应用/不查绑定）
- conn 不属于任何应用：无授权单元，用平台静态凭证（auth_config）放行
- 两者返回的凭证经 harness loader._cred_to_headers 转 headers；为空时
  loader 裸透传 handler（loader.py `if not headers` 分支）
"""
from __future__ import annotations

from typing import Any

import httpx
from loguru import logger


class UserCredentialResolver:
    """app 层凭证兑换器实现（注入 harness 的 CredentialResolver 位）。"""

    async def resolve(
        self,
        platform_user_id: str,
        server_name: str,
    ) -> dict[str, Any] | None:
        """查 + 解密当前用户在目标 MCP 的绑定凭证。

        Returns:
            解密后的凭证对象（含 auth_type + session token），或 None（未授权）。
        """
        if not platform_user_id or not server_name:
            return None

        # 1. server_name → mcp_connection（auth_type + auth_config 用于注入）
        conn = await self._get_connection_by_name(server_name)
        if not conn:
            logger.warning(
                "mcp_credential_resolve_conn_not_found",
                server_name=server_name,
                platform_user_id=platform_user_id,
            )
            return None

        # 2. 公共 MCP 放行（v5）——无认证连接不反查应用、不查绑定：
        #    凭证经 _cred_to_headers 转 headers，auth_type=none 得空
        #    headers，loader 走裸透传分支。
        auth_type = conn.get("auth_type", "none")
        if auth_type == "none":
            logger.info(
                "mcp_public_access",
                server_name=server_name,
                conn_id=conn["_id"],
                auth_type=auth_type,
            )
            return {"auth_type": "none"}

        # 3. conn_id → 反查应用（授权单元）
        from app.services.application_service import ApplicationService

        app = await ApplicationService.find_by_mcp_connection(conn["_id"])
        if not app:
            # 不挂任何应用 = 公共 MCP：无授权单元，用平台静态凭证放行
            # （auth_config 为空时同样裸透传）。info 留审计痕迹。
            logger.info(
                "mcp_public_access",
                server_name=server_name,
                conn_id=conn["_id"],
                auth_type=auth_type,
                static_credentials=True,
            )
            return {"auth_type": auth_type, **(conn.get("auth_config") or {})}

        # 4. 查用户对该应用的授权
        from app.services.user_mcp_credential_service import (
            UserMcpCredentialService,
        )

        binding = await UserMcpCredentialService.get_binding(
            platform_user_id, app["_id"]
        )
        if not binding:
            # 未授权该应用 → 结构化错误（携带 app_id/app_name），拦截器
            # 据此生成带标记的错误结果并引导 LLM 走 request_app_authorization
            from agent_flow_harness.mcp.errors import McpCredentialUnbound

            raise McpCredentialUnbound(
                app_id=app["_id"],
                app_name=app.get("name", app["_id"]),
                server_name=server_name,
            )

        # 5. 查/换 session（Redis 缓存）。登录失败（账密被用户在外部系统
        #    改掉等）→ 结构化 INVALID 错误：身份映射不受影响（sub 以稳定
        #    用户 ID 为锚），拦截器据此引导用户在聊天内更新授权凭证。
        from agent_flow_harness.mcp.errors import McpCredentialInvalid

        try:
            session = await self._get_or_exchange_session(
                platform_user_id, app, binding
            )
        except PermissionError as exc:
            raise McpCredentialInvalid(
                app_id=app["_id"],
                app_name=app.get("name", app["_id"]),
                server_name=server_name,
                detail=str(exc),
            ) from exc
        if not session:
            return None

        # 6. 按连接的 auth_type 注入 session（header_name 从 auth_config 取）
        auth_config = conn.get("auth_config") or {}
        return {
            "auth_type": conn.get("auth_type", "bearer_token"),
            "token": session,
            "header_name": auth_config.get("header_name", "X-API-Key"),
        }

    # ------------------------------------------------------------------
    # session 查/换（带 Redis 缓存）
    # ------------------------------------------------------------------

    @staticmethod
    async def _get_or_exchange_session(
        platform_user_id: str,
        app: dict[str, Any],
        binding: dict[str, Any],
    ) -> str | None:
        """查 Redis 缓存，miss 则用 app.login_config + 账密换 session。"""
        from app.services.user_mcp_credential_service import (
            get_cached_session,
            set_cached_session,
        )

        app_id = app["_id"]

        # 1. 查缓存
        cached = await get_cached_session(platform_user_id, app_id)
        if cached:
            return cached

        # 2. miss → 用 login_config 换 session
        login_config = app.get("login_config") or {}
        if not login_config.get("login_url"):
            logger.warning(
                "mcp_credential_login_config_missing",
                app_id=app_id,
            )
            return None

        username = binding.get("username", "")
        password = binding.get("password", "")
        session_token = await UserCredentialResolver._do_login(
            login_config, username, password
        )

        # 3. 写缓存
        ttl = int(login_config.get("session_ttl", 3600))
        await set_cached_session(platform_user_id, app_id, session_token, ttl)

        return session_token

    @staticmethod
    async def _do_login(
        login_config: dict[str, Any],
        username: str,
        password: str,
    ) -> str:
        """按 login_config POST 登录端点，按 token_jsonpath 取 session token。"""
        login_url = login_config["login_url"]
        method = login_config.get("method", "POST").upper()
        username_field = login_config.get("username_field", "username")
        password_field = login_config.get("password_field", "password")
        token_jsonpath = login_config.get("token_jsonpath", "data.token")

        body = {username_field: username, password_field: password}

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.request(method, login_url, json=body)
            resp.raise_for_status()
            data = resp.json()

        # 校验登录是否成功
        if isinstance(data, dict) and data.get("success") is False:
            msg = data.get("message") or data.get("msg") or data.get("error") or "未知错误"
            raise PermissionError(f"登录失败：{msg}")

        # 按 jsonpath 取 session token
        current: Any = data
        for part in token_jsonpath.split("."):
            if isinstance(current, dict) and part in current:
                current = current[part]
            else:
                raise PermissionError(
                    f"登录响应未找到 token 路径 {token_jsonpath}"
                )
        if not current:
            raise PermissionError("登录响应 token 为空")
        return str(current)

    # ------------------------------------------------------------------
    # DB 辅助查询
    # ------------------------------------------------------------------

    @staticmethod
    async def _get_connection_by_name(server_name: str) -> dict[str, Any] | None:
        """按 name 查 mcp_connections（取 _id + auth_type + auth_config）。"""
        from app.db.mongodb import get_database

        db = get_database()
        return await db["mcp_connections"].find_one(
            {"name": server_name},
            {"_id": 1, "auth_type": 1, "auth_config": 1},
        )

"""Mock 接入方系统 — client 自助授权本地 E2E 测试用。

模拟**两个**"外部应用"，提供平台侧所需的端点：

**系统 A（key 应用，演示应用 E2E 绑定它）**
- ``POST /introspect``：RFC 7666 token 校验（ApiKey.introspect_url 指向这里）
- ``POST /login``：账密验证 + session 签发（login_config 指向这里）

**系统 B（跨应用授权测试用，演示应用 B 绑定它）**
- ``POST /b/login``：B 系统自己的账密验证（独立用户表）
  ——key 应用 A 的用户在聊天中被 Agent 调到 B 的工具时，
  授权卡里填的是 B 系统的账密（跨应用 username 自由填写）

响应结构统一对齐 login_config 默认值：``token_jsonpath=data.token``、
``userid_jsonpath=userId``（稳定用户 ID，改名不变）。

管理端点（模拟外部系统事件）：``/admin/password``、``/admin/rename``、
``/admin/token``、``GET /admin/users``，body 里 ``system`` 可选
``"a"``（默认）/``"b"``。

运行：``cd backend && uv run python scripts/mock_partner.py``（默认 :9101）
系统 A 用户：zhangsan/secret123（u_10086）、lisi/pass456（u_10087）
系统 B 用户：wangwu/pass789（u_20001）、sunqiu/pass000（u_20002）
内置 token：888b8fc5-a31c-405a-b7da-3cc48cbd8487 → zhangsan（A，即
embed-demo.html 里预填的那个）
"""
from __future__ import annotations

import secrets
from typing import Any

import uvicorn
from fastapi import FastAPI, Form
from pydantic import BaseModel

# Form 仍被 /introspect 使用（RFC 7666 要求 form-encoded）

app = FastAPI(title="Mock Partner")

# system -> username -> {password, user_id}
SYSTEMS: dict[str, dict[str, dict[str, str]]] = {
    "a": {
        "zhangsan": {"password": "secret123", "user_id": "u_10086"},
        "lisi": {"password": "pass456", "user_id": "u_10087"},
    },
    "b": {
        "wangwu": {"password": "pass789", "user_id": "u_20001"},
        "sunqiu": {"password": "pass000", "user_id": "u_20002"},
    },
}
# token -> (system, username)。B 不是 key 应用，不需要 token——只有 A 有。
TOKENS: dict[str, tuple[str, str]] = {
    "888b8fc5-a31c-405a-b7da-3cc48cbd8487": ("a", "zhangsan"),
}
# 已签发的 session token（login 成功后记录，仅用于观察）
SESSIONS: dict[str, str] = {}


def _do_login(system: str, username: str, password: str) -> dict[str, Any]:
    """两个系统共用的账密验证 + session 签发。"""
    user = SYSTEMS[system].get(username)
    if not user or user["password"] != password:
        return {"success": False, "message": "用户名或密码错误"}

    session_token = f"sess-{secrets.token_hex(8)}"
    SESSIONS[session_token] = f"{system}:{username}"
    return {
        "success": True,
        "userId": user["user_id"],
        "data": {"token": session_token},
    }


# ── 系统 A（key 应用）────────────────────────────────────────────────


@app.post("/introspect")
async def introspect(token: str = Form(...)) -> dict[str, Any]:
    """RFC 7666 token 校验（只有 key 应用 A 需要）。"""
    entry = TOKENS.get(token)
    if not entry:
        return {"active": False}
    system, username = entry
    user = SYSTEMS[system].get(username)
    if user is None:
        return {"active": False}
    return {
        "active": True,
        "sub": user["user_id"],  # 稳定用户 ID（改名不变）
        "username": username,
        "exp": 9999999999,
    }


class LoginBody(BaseModel):
    """平台 _verify_credentials 按 login_config 发的 JSON 体
    （字段名可配 username_field/password_field，默认 username/password）。"""

    username: str
    password: str


@app.post("/login")
async def login(body: LoginBody) -> dict[str, Any]:
    """系统 A 账密验证。"""
    return _do_login("a", body.username, body.password)


# ── 系统 B（跨应用授权测试）──────────────────────────────────────────


@app.post("/b/login")
async def login_b(body: LoginBody) -> dict[str, Any]:
    """系统 B 账密验证——跨应用授权卡提交的账密到这里验证。"""
    return _do_login("b", body.username, body.password)


# ── 管理端点（模拟外部系统事件，测试用）───────────────────────────────


class _SystemBody(BaseModel):
    username: str
    system: str = "a"  # "a" / "b"


class PasswordChange(_SystemBody):
    new_password: str


@app.post("/admin/password")
async def change_password(body: PasswordChange) -> dict[str, Any]:
    """改密码 → 平台存档账密变旧 → 下次兑换 session 失败 → INVALID 卡。"""
    users = SYSTEMS.get(body.system, {})
    if body.username not in users:
        return {"success": False, "message": "用户不存在"}
    users[body.username]["password"] = body.new_password
    return {
        "success": True,
        "system": body.system,
        "username": body.username,
        "password": body.new_password,
    }


class Rename(_SystemBody):
    new_username: str


@app.post("/admin/rename")
async def rename_user(body: Rename) -> dict[str, Any]:
    """改用户名 → user_id（sub/登录响应 userId）不变 → 身份不漂移。"""
    users = SYSTEMS.get(body.system, {})
    if body.username not in users:
        return {"success": False, "message": "用户不存在"}
    if body.new_username in users:
        return {"success": False, "message": "新用户名已被占用"}

    users[body.new_username] = users.pop(body.username)
    for token, (system, name) in list(TOKENS.items()):
        if system == body.system and name == body.username:
            TOKENS[token] = (system, body.new_username)
    return {
        "success": True,
        "system": body.system,
        "old_username": body.username,
        "new_username": body.new_username,
        "user_id": users[body.new_username]["user_id"],  # 不变
    }


class TokenIssue(_SystemBody):
    pass


@app.post("/admin/token")
async def issue_token(body: TokenIssue) -> dict[str, Any]:
    """给系统 A 某用户签发一个新 token（换用户测试时写进 embed-demo.html）。"""
    if body.system != "a":
        return {"success": False, "message": "只有系统 A（key 应用）需要 token"}
    if body.username not in SYSTEMS["a"]:
        return {"success": False, "message": "用户不存在"}
    token = str(secrets.uuid4())
    TOKENS[token] = ("a", body.username)
    return {"success": True, "token": token, "username": body.username}


@app.get("/admin/users")
async def list_users() -> dict[str, Any]:
    return {"systems": SYSTEMS, "tokens": TOKENS, "sessions": SESSIONS}


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=9101, log_level="info")

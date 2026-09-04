"""种子脚本 — client 自助授权本地 E2E 测试数据。

配合 ``scripts/mock_partner.py``（模拟接入方系统 A/B）与
``scripts/mock_mcp.py``（两个 MCP 实例）使用，创建：

1. 应用 A「演示应用（E2E）」：login → mock 系统 A /login；
   API Key：introspect → mock /introspect，绑定应用 A
   （完整 af_live_ key 只在创建时打印一次，需粘进 embed-demo.html）
2. （--second-app）应用 B「演示应用 B」：login → mock 系统 B /b/login，
   无 introspection（跨应用授权测试——用户在 A 的 client 里被 Agent
   调到 B 的工具时弹授权卡，填 B 系统的账密）
3. （--mcp-url / --mcp-b-url）MCP 连接挂到对应应用下——运行时授权卡
   （C2/C3）必需：Agent 得真的调到应用的 MCP 工具才会触发凭证解析

幂等：同名应用/同名 Key 已存在时跳过并复用（Key 只打印一次，重跑时
提示从库里看 prefix 或删除重建）。

用法：
    cd backend
    # 基础（首绑/面板/解绑可测）
    uv run python scripts/seed_e2e_auth.py
    # 完整（含跨应用）：mock_mcp 起两个实例（A:9102 order / B:9103 inventory）
    uv run python scripts/seed_e2e_auth.py --mcp-url http://127.0.0.1:9102/mcp --second-app
    uv run python scripts/seed_e2e_auth.py --reset         # 删除本脚本创建的数据
"""
from __future__ import annotations

import argparse
import asyncio
import sys

# 确保能 import app.*
sys.path.insert(0, ".")

APP_NAME = "演示应用（E2E）"
APP_B_NAME = "演示应用 B（E2E 跨应用）"
KEY_NAME = "e2e-embed-demo"
MOCK_BASE = "http://127.0.0.1:9101"
MOCK_MCP_A = "http://127.0.0.1:9102/mcp"
MOCK_MCP_B = "http://127.0.0.1:9103/mcp"


async def _first_admin_user_id() -> str:
    from app.db.mongodb import get_database

    db = get_database()
    admin = await db["users"].find_one(
        {}, {"_id": 1, "username": 1, "is_super_admin": 1, "role": 1},
    )
    if admin is None:
        print("❌ 平台没有任何用户——先创建管理员（见 create-admin 文档/CLI）")
        sys.exit(1)
    print(f"ℹ owner 用户: {admin['username']} ({admin['_id']})")
    return admin["_id"]


async def _ensure_mcp_conn(db, name: str, mcp_url: str) -> str:
    """幂等创建/查找 MCP 连接——走平台 service（_id 用 generate_id 字符串，
    手工 ObjectId 混用会导致 find_by_mcp_connection 查不到）。"""
    from app.services.mcp_connection_service import McpConnectionService

    existing = await db["mcp_connections"].find_one({"url": mcp_url})
    if existing is None:
        created = await McpConnectionService.create_connection({
            "name": name,
            "url": mcp_url,
            "protocol": "streamable-http",
            "auth_type": "none",
            "auth_config": {},
            "default_params": {},
        })
        print(f"✅ MCP 连接已创建: {name} ({created['_id']})")
        return created["_id"]
    print(f"ℹ MCP 连接已存在: {existing.get('name')} ({existing['_id']})")
    return str(existing["_id"])


async def _ensure_app(
    name: str, description: str, login_url: str, mcp_url: str | None, mcp_name: str
) -> dict:
    """幂等创建/刷新一个演示应用（login_config 指向 mock，可选挂 MCP）。"""
    from app.db.mongodb import get_database
    from app.services.application_service import ApplicationService
    db = get_database()

    existing_apps = await ApplicationService.list_applications()
    app_doc = next((a for a in existing_apps if a.get("name") == name), None)
    mcp_ids: list[str] = (
        list(app_doc.get("mcp_connection_ids") or []) if app_doc else []
    )
    if mcp_url:
        conn_id = await _ensure_mcp_conn(db, mcp_name, mcp_url)
        if conn_id not in mcp_ids:
            mcp_ids.append(conn_id)

    login_config = {
        "login_url": login_url,
        "method": "POST",
        "username_field": "username",
        "password_field": "password",
        "token_jsonpath": "data.token",
        # 默认 userId：mock 登录响应顶层返回稳定用户 ID
        "userid_jsonpath": "userId",
        "session_ttl": 300,  # E2E 用短 TTL，改密后很快触发 INVALID
    }
    payload = {
        "name": name,
        "description": description,
        "mcp_connection_ids": mcp_ids,
        "login_config": login_config,
    }
    if app_doc is None:
        app_doc = await ApplicationService.create_application(payload)
        print(f"✅ 应用已创建: {name} ({app_doc['_id']})")
    else:
        await ApplicationService.update_application(app_doc["_id"], payload)
        print(f"ℹ 应用已存在并刷新: {name} ({app_doc['_id']})")
    return app_doc


async def seed(mcp_url: str | None, second_app: bool, mcp_b_url: str | None) -> None:
    from app.db.mongodb import get_database
    from app.services.api_key_service import ApiKeyService

    db = get_database()
    owner_id = await _first_admin_user_id()

    # 1. 应用 A（key 应用）：login → mock 系统 A；MCP → mock_mcp 实例 A
    app_doc = await _ensure_app(
        name=APP_NAME,
        description="seed_e2e_auth.py 创建的测试应用（key 应用，系统 A）",
        login_url=f"{MOCK_BASE}/login",
        mcp_url=mcp_url,
        mcp_name="e2e-demo-mcp",
    )

    # 2. 应用 B（跨应用授权测试）：login → mock 系统 B；MCP → mock_mcp 实例 B
    if second_app:
        await _ensure_app(
            name=APP_B_NAME,
            description="seed_e2e_auth.py 创建的跨应用测试应用（系统 B）",
            login_url=f"{MOCK_BASE}/b/login",
            mcp_url=mcp_b_url,
            mcp_name="e2e-demo-mcp-b",
        )

    # 3. API Key（幂等：同名只提示；只绑应用 A——B 是被跨应用调用的目标）
    key_docs = db["api_keys"]
    existing_key = await key_docs.find_one({"name": KEY_NAME, "owner_user_id": owner_id})
    if existing_key is None:
        _, full_key = await ApiKeyService.create_api_key(
            name=KEY_NAME,
            owner_user_id=owner_id,
            scopes=["agents:read", "agents:invoke", "executions:read"],
            bindings={"agents": [], "workflows": []},
            rate_limit=120,
            introspect_url=f"{MOCK_BASE}/introspect",
            app_id=app_doc["_id"],
        )
        print("\n" + "=" * 64)
        print("✅ API Key 已创建（只在此时显示一次，粘贴进 embed-demo.html）：")
        print(f"   data-api-key=\"{full_key}\"")
        print("=" * 64 + "\n")
    else:
        print(
            f"ℹ API Key 已存在: {KEY_NAME} (prefix={existing_key.get('key_prefix')}…)\n"
            "   如需重新拿到完整 key：先 --reset 再跑本脚本"
        )

    print("完成。后续步骤见 docs/client-authorization-e2e.md")


async def reset() -> None:
    from app.db.mongodb import get_database

    db = get_database()
    for name in (APP_NAME, APP_B_NAME):
        app_doc = await db["applications"].find_one({"name": name})
        if app_doc:
            await db["api_keys"].delete_many({"app_id": app_doc["_id"]})
            await db["external_identities"].delete_many({
                "sub": {"$regex": f"^{app_doc['_id']}:"}
            })
            await db["applications"].delete_one({"_id": app_doc["_id"]})
            print(f"✅ 已删除应用 {name} 及其 API Key / 身份映射")
    await db["mcp_connections"].delete_many({
        "name": {"$in": ["e2e-demo-mcp", "e2e-demo-mcp-b"]}
    })
    print("✅ 已删除演示 MCP 连接")
    print("ℹ user_mcp_credentials 里的绑定残留不影响重跑（重绑会覆盖）")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mcp-url",
        default=None,
        help="应用 A 的 MCP 服务地址（运行时授权卡必需；默认留空）",
    )
    parser.add_argument(
        "--second-app",
        action="store_true",
        help="创建演示应用 B（跨应用授权测试；login 指向 mock 系统 B）",
    )
    parser.add_argument(
        "--mcp-b-url",
        default=None,
        help="应用 B 的 MCP 服务地址（默认 http://127.0.0.1:9103/mcp）",
    )
    parser.add_argument("--reset", action="store_true", help="删除本脚本创建的数据")
    args = parser.parse_args()

    if args.reset:
        asyncio.run(reset())
        return
    mcp_b_url = args.mcp_b_url or (MOCK_MCP_B if args.second_app else None)
    asyncio.run(seed(args.mcp_url, args.second_app, mcp_b_url))


if __name__ == "__main__":
    main()

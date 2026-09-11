"""UserToolService — 组织工具库治理模型测试（fake motor，不连真实 DB）。

ToB 治理流程锁定：
- 创建：tool:write 用户（API 门控），组织内名称唯一
- 状态机：submit → admin approve(published) → admin enable（三重校验）
- 开启校验：published + 定义完整 + org 凭证完整
- 工具级凭证：admin 配置（sensitive enc:），resolve_org_tool 解析返回明文
- 不可用（未开启/停用/未过审）→ 解析 None
- 官方工具同语义（is_tool_active + org_user_args + 启用校验含凭证）
"""
from __future__ import annotations

import pytest
from app.services.user_tool_service import UserToolError, UserToolService

# ---------------------------------------------------------------------------
# Fake motor（子集接口：insert/find/find_one/update_one/delete/count）
# ---------------------------------------------------------------------------


def _match(doc: dict, query: dict) -> bool:
    import re

    for key, cond in query.items():
        value = doc.get(key)
        if key == "$or":
            if not any(_match(doc, sub) for sub in cond):
                return False
            continue
        if key == "$and":
            if not all(_match(doc, sub) for sub in cond):
                return False
            continue
        if isinstance(cond, dict):
            if "$in" in cond and value not in cond["$in"]:
                return False
            if "$nin" in cond and value in cond["$nin"]:
                return False
            if "$regex" in cond:
                flags = 0
                if "$options" in cond and "i" in cond["$options"]:
                    flags |= re.IGNORECASE
                if not isinstance(value, str) or not re.search(cond["$regex"], value, flags):
                    return False
            if "$ne" in cond and value == cond["$ne"]:
                return False
            continue
        if value != cond:
            return False
    return True


def _apply_update(doc: dict, update: dict) -> None:
    for op, payload in update.items():
        if op == "$set":
            for k, v in payload.items():
                _set_path(doc, k, v)
        elif op == "$inc":
            for k, v in payload.items():
                cur = _get_path(doc, k) or 0
                _set_path(doc, k, cur + v)
        elif op == "$setOnInsert":
            pass


def _set_path(doc: dict, path: str, value) -> None:
    parts = path.split(".")
    cur = doc
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = value


def _get_path(doc: dict, path: str):
    cur = doc
    for p in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur


class FakeCursor:
    def __init__(self, docs: list[dict]):
        self.docs = docs

    def sort(self, *_a) -> FakeCursor:
        return self

    def limit(self, _n) -> FakeCursor:
        return self

    async def to_list(self, length=None) -> list[dict]:
        return [dict(d) for d in self.docs]


class FakeCol:
    def __init__(self):
        self.docs: list[dict] = []

    async def insert_one(self, doc: dict) -> None:
        self.docs.append(dict(doc))

    async def find_one(self, query: dict, projection: dict | None = None) -> dict | None:
        return next((dict(d) for d in self.docs if _match(d, query)), None)

    def find(self, query: dict, projection: dict | None = None) -> FakeCursor:
        return FakeCursor([d for d in self.docs if _match(d, query)])

    async def update_one(self, query: dict, update: dict, upsert: bool = False) -> None:
        for d in self.docs:
            if _match(d, query):
                _apply_update(d, update)
                return
        if upsert:
            merged = dict(query)
            _apply_update(merged, update)
            for k, v in update.get("$setOnInsert", {}).items():
                merged.setdefault(k, v)
            self.docs.append(merged)

    async def delete_one(self, query: dict) -> None:
        self.docs = [d for d in self.docs if not _match(d, query)]

    delete_many = delete_one

    async def count_documents(self, query: dict) -> int:
        return sum(1 for d in self.docs if _match(d, query))

    async def distinct(self, key: str, query: dict | None = None) -> list:
        docs = [d for d in self.docs if _match(d, query or {})]
        return list({d.get(key) for d in docs if d.get(key) is not None})


class FakeDB(dict):
    def __getitem__(self, key: str) -> FakeCol:
        if key not in self:
            super().__setitem__(key, FakeCol())
        return super().__getitem__(key)


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB()
    monkeypatch.setattr("app.services.user_tool_service.get_database", lambda: fake)
    monkeypatch.setattr("app.services.tool_service.get_database", lambda: fake)
    return fake


# ---------------------------------------------------------------------------
# 创建 / 名称唯一（组织级）
# ---------------------------------------------------------------------------


async def test_create_tool_success(db):
    doc = await UserToolService.create_tool(
        "u1", name="weather", description="天气查询", source="openapi",
        endpoint={"url": "https://api.x/{{user.unit}}"},
    )
    assert doc["status"] == "private"
    assert doc["enabled"] is False  # 治理：创建即不可用
    assert doc["org_user_args"] == {}


async def test_create_name_and_source_validation(db):
    with pytest.raises(UserToolError):
        await UserToolService.create_tool("u1", name="bad name!", source="openapi")
    with pytest.raises(UserToolError):
        await UserToolService.create_tool("u1", name="ok-name", source="mcp")


async def test_org_wide_name_uniqueness(db):
    """组织内名称唯一（不再按 owner 分命名空间）。"""
    await UserToolService.create_tool("u1", name="shared", source="code", code="def run(): pass")
    with pytest.raises(UserToolError):
        await UserToolService.create_tool("u2", name="shared", source="code")


async def test_name_variant_uniqueness(db):
    """同名变体拦截：工具对 Agent/LLM 即函数，send-email / send_email /
    SendEmail 视为同名（唯一性按归一化键判定）。"""
    await UserToolService.create_tool("u1", name="send-email", source="code", code="def run(): pass")
    for variant in ("send_email", "Send-Email", "SENDEMAIL"):
        with pytest.raises(UserToolError, match="同名"):
            await UserToolService.create_tool("u2", name=variant, source="code")


async def test_rename_variant_conflict(db):
    """改名同样按归一化查重（排除自身）。"""
    await UserToolService.create_tool("u1", name="send-email", source="code")
    other = await UserToolService.create_tool("u2", name="notify", source="code")
    with pytest.raises(UserToolError, match="同名"):
        await UserToolService.update_tool("u2", other["_id"], name="send_email")
    # 改回自身同名（归一化相同）不受影响
    doc = await UserToolService.update_tool("u2", other["_id"], name="Notify")
    assert doc["name"] == "Notify"


async def test_official_table_name_conflict(db):
    """跨表查重：官方 tools 表同名（变体）也拦截。"""
    await db["tools"].insert_one({"_id": "tool_x", "name": "Send_Email", "source": "code"})
    with pytest.raises(UserToolError, match="官方工具"):
        await UserToolService.create_tool("u1", name="send-email", source="code")


# ---------------------------------------------------------------------------
# code 依赖白名单（创建时前置反馈）
# ---------------------------------------------------------------------------


async def test_code_import_whitelist(db):
    """标准库与镜像预装包放行；未知依赖明确报错。"""
    ok = await UserToolService.create_tool(
        "u1", name="mailer", source="code",
        code="import smtplib, json\nfrom email.mime.text import MIMEText\n"
             "import requests\nfrom pandas import DataFrame\n"
             "def run() -> str:\n    return 'ok'\n",
    )
    assert ok["source"] == "code"

    with pytest.raises(UserToolError, match="torch"):
        await UserToolService.create_tool(
            "u1", name="dl-tool", source="code",
            code="import torch\ndef run() -> str:\n    return 'x'\n",
        )
    # update 同样拦截
    with pytest.raises(UserToolError, match="依赖不可用"):
        await UserToolService.update_tool(
            "u1", ok["_id"],
            code="import sklearn\ndef run() -> str:\n    return 'y'\n",
        )


async def test_code_syntax_and_size_validation(db):
    with pytest.raises(UserToolError, match="语法错误"):
        await UserToolService.create_tool("u1", name="bad", source="code", code="def run(:")
    with pytest.raises(UserToolError, match="代码过大"):
        await UserToolService.create_tool(
            "u1", name="big", source="code",
            code="# " + "x" * 65_000 + "\ndef run() -> str:\n    return ''\n",
        )


# ---------------------------------------------------------------------------
# openapi 参数表模型：位置定发送，schema 从参数表生成（唯一事实源）
# ---------------------------------------------------------------------------


async def test_openapi_params_table_generates_schemas(db):
    """参数表 → 运行参数（AI 填）+ 凭证参数（admin 配置，sensitive）。"""
    doc = await UserToolService.create_tool(
        "u1", name="api-tool", source="openapi",
        endpoint={
            "method": "GET",
            "url": "https://api.x.com/v1/items",
            "params": [
                {"name": "city", "in": "query", "description": "城市名", "required": True, "credential": False},
                {"name": "unit", "in": "query", "description": "", "required": False, "credential": False},
                {"name": "Authorization", "in": "header", "description": "认证", "required": True, "credential": True},
            ],
        },
        # 外部提交的 schema 应被参数表生成结果覆盖
        user_args_schema={"type": "object", "properties": {"stale": {"type": "string"}}},
        llm_args_schema={"type": "object", "properties": {"stale": {"type": "string"}}},
    )
    llm = doc["llm_args_schema"]
    assert set(llm["properties"]) == {"city", "unit"}
    assert llm["required"] == ["city"]
    user = doc["user_args_schema"]
    assert set(user["properties"]) == {"Authorization"}
    assert user["properties"]["Authorization"]["sensitive"] is True
    assert user["required"] == ["Authorization"]


async def test_openapi_params_validation(db):
    """参数名/位置/重名/Path 占位与 URL 引用一致性校验。"""
    with pytest.raises(UserToolError, match="未命名"):
        await UserToolService.create_tool("u1", name="v1", source="openapi",
            endpoint={"url": "https://x.com", "params": [{"name": " ", "in": "query"}]})
    with pytest.raises(UserToolError, match="重复"):
        await UserToolService.create_tool("u1", name="v2", source="openapi",
            endpoint={"url": "https://x.com", "params": [
                {"name": "a", "in": "query"}, {"name": "a", "in": "header"}]})
    with pytest.raises(UserToolError, match="位置无效"):
        await UserToolService.create_tool("u1", name="v3", source="openapi",
            endpoint={"url": "https://x.com", "params": [{"name": "a", "in": "cookie"}]})
    # URL 里的 {city} 必须有 Path 参数
    with pytest.raises(UserToolError, match="未在参数表声明"):
        await UserToolService.create_tool("u1", name="v4", source="openapi",
            endpoint={"url": "https://x.com/{city}", "params": [{"name": "city", "in": "query"}]})
    # Path 参数必须被 URL 引用
    with pytest.raises(UserToolError, match="未在 URL 中使用"):
        await UserToolService.create_tool("u1", name="v5", source="openapi",
            endpoint={"url": "https://x.com", "params": [{"name": "city", "in": "path"}]})
    # 合法的 Path 用法
    doc = await UserToolService.create_tool("u1", name="v6", source="openapi",
        endpoint={"url": "https://x.com/cities/{city}", "params": [{"name": "city", "in": "path", "required": True}]})
    assert doc["llm_args_schema"]["required"] == ["city"]


async def test_openapi_schemas_recalculated_on_update(db):
    """update 时按新参数表重算（外部提交的 schema 被覆盖）。"""
    doc = await UserToolService.create_tool("u1", name="api-tool2", source="openapi",
        endpoint={"url": "https://x.com", "params": [
            {"name": "k1", "in": "header", "credential": True}]})
    assert set(doc["user_args_schema"]["properties"]) == {"k1"}

    await UserToolService.update_tool("u1", doc["_id"],
        endpoint={"url": "https://x.com", "params": [
            {"name": "k1", "in": "header", "credential": True},
            {"name": "q1", "in": "query"},
        ]},
        # 试图借 update 提交自定义 schema——应被忽略
        user_args_schema={"type": "object", "properties": {"bad": {"type": "string"}}},
    )
    fresh = await UserToolService.get_tool(doc["_id"])
    assert set(fresh["user_args_schema"]["properties"]) == {"k1"}
    assert set(fresh["llm_args_schema"]["properties"]) == {"q1"}

    # 清空参数表 → 两个 schema 均为空
    await UserToolService.update_tool("u1", doc["_id"], endpoint={"url": "https://x.com", "params": []})
    fresh = await UserToolService.get_tool(doc["_id"])
    assert fresh["user_args_schema"] == {} and fresh["llm_args_schema"] == {}


# ---------------------------------------------------------------------------
# 治理状态机：submit → approve → 配凭证 → enable
# ---------------------------------------------------------------------------


async def _published_tool(db, owner="u1", name="pub-tool") -> str:
    doc = await UserToolService.create_tool(owner, name=name, source="code", code="def run(): return 1")
    await UserToolService.submit_for_review(owner, doc["_id"])
    await UserToolService.review_tool(doc["_id"], "approve", "admin1")
    return doc["_id"]


async def test_submit_review_flow(db):
    doc = await UserToolService.create_tool("u1", name="flow", source="code")
    with pytest.raises(UserToolError):
        await UserToolService.submit_for_review("u2", doc["_id"])  # 非 owner
    await UserToolService.submit_for_review("u1", doc["_id"])
    assert (await UserToolService.get_tool(doc["_id"]))["status"] == "submitted"

    await UserToolService.review_tool(doc["_id"], "reject", "admin1", reason="描述不清")
    fresh = await UserToolService.get_tool(doc["_id"])
    assert fresh["status"] == "private" and fresh["review_note"] == "描述不清"

    await UserToolService.submit_for_review("u1", doc["_id"])
    await UserToolService.review_tool(doc["_id"], "approve", "admin1")
    fresh = await UserToolService.get_tool(doc["_id"])
    assert fresh["status"] == "published" and fresh["enabled"] is False  # 过审≠可用


async def test_enable_requires_published_definition_and_args(db):
    """开启三重校验：published + 定义完整 + 凭证完整。"""
    # 未过审 → 拒绝
    draft = await UserToolService.create_tool("u1", name="draft-t", source="code", code="x")
    with pytest.raises(UserToolError):
        await UserToolService.enable_tool("admin1", draft["_id"], True)

    # 定义不完整（code 为空）→ 拒绝
    doc = await UserToolService.create_tool(
        "u1", name="no-code", source="code",
        user_args_schema={"properties": {"token": {"type": "string", "sensitive": True}}},
    )
    await UserToolService.submit_for_review("u1", doc["_id"])
    await UserToolService.review_tool(doc["_id"], "approve", "admin1")
    with pytest.raises(UserToolError) as exc:
        await UserToolService.enable_tool("admin1", doc["_id"], True)
    assert "code" in exc.value.message

    # 凭证未配置 → 拒绝（错误信息含缺失字段）
    await UserToolService.update_tool("u1", doc["_id"], code="def run(): pass")
    await UserToolService.submit_for_review("u1", doc["_id"])
    await UserToolService.review_tool(doc["_id"], "approve", "admin1")
    with pytest.raises(UserToolError) as exc:
        await UserToolService.enable_tool("admin1", doc["_id"], True)
    assert "token" in exc.value.message

    # 配齐凭证 → 可开启；resolve 返回解密后的工具级凭证
    await UserToolService.save_org_args("admin1", doc["_id"], {"token": "secret-tk"})
    stored = await UserToolService.get_tool(doc["_id"])
    assert stored["org_user_args"]["token"].startswith("enc:")  # sensitive 加密
    enabled_doc = await UserToolService.enable_tool("admin1", doc["_id"], True)
    assert enabled_doc["enabled"] is True

    resolved = await UserToolService.resolve_org_tool(doc["_id"])
    assert resolved is not None
    rdoc, rargs = resolved
    assert rdoc["_id"] == doc["_id"]
    assert rargs["token"] == "secret-tk"  # 运行时已解密


async def test_resolve_org_tool_unavailable_states(db):
    """不可用状态解析为 None：未开启 / 停用。"""
    tool_id = await _published_tool(db, name="res-t")
    assert await UserToolService.resolve_org_tool(tool_id) is None  # published 但未开启
    await UserToolService.save_org_args("admin1", tool_id, {})
    await UserToolService.enable_tool("admin1", tool_id, True)
    assert await UserToolService.resolve_org_tool(tool_id) is not None
    await UserToolService.enable_tool("admin1", tool_id, False)  # 停用
    assert await UserToolService.resolve_org_tool(tool_id) is None


async def test_update_published_resets_governance(db):
    """已发布工具编辑 → 回 private 且 enabled=False、凭证清空（需重新走流程）。"""
    tool_id = await _published_tool(db, name="upd-t")
    await UserToolService.save_org_args("admin1", tool_id, {"a": "1"})
    await UserToolService.enable_tool("admin1", tool_id, True)
    await UserToolService.update_tool("u1", tool_id, code="def run(): return 2")
    fresh = await UserToolService.get_tool(tool_id)
    assert fresh["status"] == "private"
    assert fresh["enabled"] is False
    assert fresh["org_user_args"] == {}


async def test_update_delete_admin_override(db):
    """admin 可编辑/删除他人工具（is_admin 覆盖）。"""
    tool_id = await _published_tool(db, owner="u1", name="adm-t")
    await UserToolService.update_tool("admin9", tool_id, description="改", is_admin=True)
    assert (await UserToolService.get_tool(tool_id))["description"] == "改"
    await UserToolService.delete_tool("admin9", tool_id, is_admin=True)
    assert await UserToolService.get_tool(tool_id) is None


# ---------------------------------------------------------------------------
# 官方工具同语义（is_tool_active + org 凭证 + 启用校验）
# ---------------------------------------------------------------------------


async def test_official_tool_governance(db):
    from app.core.errors import ValidationError
    from app.services.tool_service import ToolService

    # 默认 disabled；启用校验定义 + 凭证
    doc = await ToolService.create_custom_tool(
        name="off-api-x", description="", source="openapi", endpoint={},
        user_args_schema={"properties": {"key": {"type": "string", "sensitive": True}}},
    )
    assert doc["status"] == "disabled"
    with pytest.raises(ValidationError):
        await ToolService.set_tool_status(doc["_id"], "active")  # 缺 url + 凭证

    await ToolService._collection().update_one(
        {"_id": doc["_id"]}, {"$set": {"endpoint": {"url": "https://x"}}}
    )
    with pytest.raises(ValidationError):  # 仍缺凭证
        await ToolService.set_tool_status(doc["_id"], "active")

    await ToolService.save_org_args("admin1", doc["_id"], {"key": "k1"})
    active_doc = await ToolService.set_tool_status(doc["_id"], "active")
    assert active_doc["status"] == "active"

    # resolve_org_tool 对官方同样生效（解密 org 凭证）
    resolved = await UserToolService.resolve_org_tool(doc["_id"])
    assert resolved is not None and resolved[1]["key"] == "k1"

    # 存量无 status 字段视为 active；MCP 不受约束
    assert ToolService.is_tool_active({"source": "openapi"}) is True
    assert ToolService.is_tool_active({"source": "mcp", "status": "disabled"}) is True


# ---------------------------------------------------------------------------
# Agent 绑定解析（_resolve_custom_tools，治理语义）
# ---------------------------------------------------------------------------


async def test_resolve_custom_tools_with_enabled_uto(monkeypatch, db):
    """Agent 静态绑定 enabled 的 uto_ 工具：构建成功，凭证用工具级配置。"""
    from app.engine.harness_integration.context import _resolve_custom_tools

    tool_id = await _published_tool(db, name="bind-t")
    await UserToolService.save_org_args("admin1", tool_id, {"token": "tk"})
    await UserToolService.enable_tool("admin1", tool_id, True)

    captured: dict = {}

    async def fake_build(doc, *, user_args=None):
        captured.update(user_args or {})
        return object()

    monkeypatch.setattr("app.engine.tool.tool_builder.build_tool", fake_build)

    tools, errors = await _resolve_custom_tools({
        "custom_tools": [{"tool_id": tool_id, "user_args": {}}],
    })
    assert len(tools) == 1 and errors == []
    assert captured == {"token": "tk"}


async def test_resolve_custom_tools_skips_unenabled_uto(monkeypatch, db):
    """绑定未开启的 uto_ → 明确报错（不静默）。"""
    from app.engine.harness_integration.context import _resolve_custom_tools

    tool_id = await _published_tool(db, name="unenabled-t")  # published 未开启
    tools, errors = await _resolve_custom_tools({
        "custom_tools": [{"tool_id": tool_id, "user_args": {}}],
    })
    assert tools == []
    assert any("不可用" in e["error"] for e in errors)


async def test_resolve_custom_tools_skips_disabled_official(monkeypatch, db):
    from app.engine.harness_integration.context import _resolve_custom_tools
    from app.services.tool_service import ToolService

    doc = await ToolService.create_custom_tool(
        name="off-down", description="", source="code", code="def run(): pass", created_by="admin",
    )
    await ToolService.set_tool_status(doc["_id"], "disabled")
    tools, errors = await _resolve_custom_tools({
        "custom_tools": [{"tool_id": doc["_id"], "user_args": {}}],
    })
    assert tools == []
    assert any("停用" in e["error"] for e in errors)


# ---------------------------------------------------------------------------
# 组织库目录 + list_enabled_tools
# ---------------------------------------------------------------------------


async def test_list_enabled_tools_merges_official_and_user(db):
    from app.services.tool_service import ToolService

    await ToolService.create_custom_tool(
        name="off-en", description="", source="code", code="x", created_by="admin",
    )  # 默认 disabled → 不出现
    tool_id = await _published_tool(db, name="user-en")
    await UserToolService.save_org_args("admin1", tool_id, {})
    await UserToolService.enable_tool("admin1", tool_id, True)

    enabled = await UserToolService.list_enabled_tools()
    ids = [d["id"] for d in enabled]
    assert tool_id in ids


async def test_marketplace_shows_governance_state(db):
    """目录含未开启的 published 工具（可见性≠可用性），enabled 标记治理态。"""
    tool_id = await _published_tool(db, name="mk-t")
    items = await UserToolService.marketplace("u9")
    item = next(i for i in items if i["id"] == tool_id)
    assert item["enabled"] is False  # 未开启
    await UserToolService.save_org_args("admin1", tool_id, {})
    await UserToolService.enable_tool("admin1", tool_id, True)
    items = await UserToolService.marketplace("u9")
    item = next(i for i in items if i["id"] == tool_id)
    assert item["enabled"] is True


# ---------------------------------------------------------------------------
# 投票（组织内反馈信号）
# ---------------------------------------------------------------------------


async def test_vote_revote(db):
    tool_id = await _published_tool(db, name="vote-tool")
    await UserToolService.vote("u2", tool_id, 1)
    await UserToolService.vote("u3", tool_id, 1)
    await UserToolService.vote("u4", tool_id, -1)
    stats = (await UserToolService.get_tool(tool_id))["stats"]
    assert stats == {"load_count": 0, "up": 2, "down": 1}

    await UserToolService.vote("u4", tool_id, 1)  # 改票：down 回滚
    stats = (await UserToolService.get_tool(tool_id))["stats"]
    assert stats["up"] == 3 and stats["down"] == 0


async def test_marketplace_includes_own_drafts(db):
    """目录含 viewer 自己的非发布工具（草稿就地管理）；他人草稿不可见。"""
    mine = await UserToolService.create_tool("u1", name="my-draft", source="code", code="x")
    other = await UserToolService.create_tool("u2", name="other-draft", source="code", code="x")
    pub = await _published_tool(db, owner="u2", name="pub2")

    items = await UserToolService.marketplace("u1")
    ids = [i["id"] for i in items]
    assert mine["_id"] in ids       # 自己的草稿可见
    assert pub in ids               # published 可见
    assert other["_id"] not in ids  # 他人草稿不可见
    item = next(i for i in items if i["id"] == mine["_id"])
    assert item["is_own"] is True

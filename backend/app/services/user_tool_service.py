"""UserToolService — 组织工具库：治理状态机 + admin 开启配置（ToB 模型）。

工具是组织级资产，使用入口收敛为 Agent 静态绑定与工作流工具节点，
不存在个人池/个人凭证/会话注入。治理流程::

    tool:write 用户创建（private，组织内名称唯一）
      → submit → admin 审查（approve → published）
      → admin 配置工具级凭证（org_user_args，sensitive enc: 加密）
      → admin 开启（校验 published + 定义完整 + 凭证完整）
      → enabled 工具才可被 Agent 绑定 / 工作流直调

tools 表的存量 openapi/code 工具保留兼容读取（is_tool_active 同语义），
不再新增——新工具一律走本表。运行时统一解析入口 ``resolve_org_tool``：
按 tool_id 取可用工具及其（解密后的）工具级凭证。
"""
from __future__ import annotations

import contextlib
import re

from loguru import logger

from app.core.crypto import encrypt_secret
from app.db.mongodb import get_database
from app.models.base import generate_id, utc_now
from app.models.user_tool import (
    MARKET_TOOL_SOURCES,
    SANDBOX_PREINSTALLED_IMPORTS,
    TOOL_CODE_MAX_BYTES,
    TOOL_NAME_PATTERN,
)

_NAME_RE = re.compile(TOOL_NAME_PATTERN)


class UserToolError(Exception):
    """用户工具操作失败（API 层转 4xx）。"""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class UserToolService:
    """组织工具库存储与治理。全部静态方法，与 UserSkillService 同风格。"""

    COLLECTION = "user_tools"
    VOTE_COLLECTION = "tool_votes"

    # ------------------------------------------------------------------
    # 创建 / 编辑 / 删除（创建/编辑权限由 API 层 tool:write 门控）
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_name(name: str) -> str:
        if not _NAME_RE.match(name or ""):
            raise UserToolError(
                f"Invalid tool name '{name}'. Use letters/digits/dash/underscore, "
                f"max 64 chars, starting with a letter or digit."
            )
        return name

    @staticmethod
    def _name_key(name: str) -> str:
        """名称归一化键：小写并去掉 -/_ 分隔符。

        send-email / send_email / SendEmail 对 Agent/LLM 是同一个工具
        （工具即函数），变体重名会造成调用歧义——唯一性按归一化键判定。
        """
        return re.sub(r"[-_]+", "", name).lower()

    @staticmethod
    async def _ensure_name_available(name: str, exclude_id: str | None = None) -> None:
        """组织内名称唯一（归一化口径，跨 user_tools 与官方 tools 表）。"""
        key = UserToolService._name_key(name)
        dup = await UserToolService._col().find_one(
            {"name_key": key, "_id": {"$ne": exclude_id}} if exclude_id else {"name_key": key}
        )
        if dup is None:
            # 官方存量表无 name_key 字段——拉取候选本地归一化比对
            official_names = await get_database()["tools"].distinct(
                "name", {"source": {"$in": list(MARKET_TOOL_SOURCES)}}
            )
            dup_name = next(
                (n for n in official_names if UserToolService._name_key(n) == key), None
            )
            if dup_name is None:
                return
            raise UserToolError(
                f"工具名 '{name}' 与官方工具 '{dup_name}' 同名（组织内唯一，不区分大小写与 -/_ 变体）。"
            )
        raise UserToolError(
            f"工具名 '{name}' 与已有工具 '{dup['name']}' 同名（组织内唯一，不区分大小写与 -/_ 变体）。"
        )

    @staticmethod
    def _validate_code(code: str) -> None:
        """code 工具静态校验：尺寸上限 + 依赖白名单（标准库 + 镜像预装）。

        运行时防线是沙箱隔离；此校验在创建/编辑时前置反馈，避免
        「写完才发现依赖跑不了」。语法错误也在此拦截。
        """
        import ast
        import sys

        if len(code.encode("utf-8")) > TOOL_CODE_MAX_BYTES:
            raise UserToolError(
                f"代码过大（>{TOOL_CODE_MAX_BYTES // 1000}KB），请精简或改用 openapi 工具。"
            )
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            raise UserToolError(f"代码存在语法错误：{exc}") from exc

        allowed = SANDBOX_PREINSTALLED_IMPORTS | frozenset(sys.stdlib_module_names)
        unknown: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                unknown.update(
                    alias.name.split(".")[0] for alias in node.names
                    if alias.name.split(".")[0] not in allowed
                )
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                top = node.module.split(".")[0]
                if top not in allowed:
                    unknown.add(top)
        if unknown:
            raise UserToolError(
                f"依赖不可用：{('、'.join(sorted(unknown)))}。"
                "可用依赖 = Python 标准库及常用库"
                f"（{', '.join(sorted(SANDBOX_PREINSTALLED_IMPORTS))}）。"
            )

    @staticmethod
    def _validate_source(source: str) -> str:
        if source not in MARKET_TOOL_SOURCES:
            raise UserToolError(
                f"Unsupported tool source '{source}'. Tools support: {', '.join(MARKET_TOOL_SOURCES)}."
            )
        return source

    # openapi 参数位置（主流 HTTP 工具模型：参数声明一次，带位置标签）
    PARAM_POSITIONS = ("query", "header", "path", "body")

    @staticmethod
    def _validate_openapi_params(endpoint: dict) -> list[dict]:
        """校验参数表并返回规范化列表：每项 {name, in, description, required, credential}。

        参数只定义一次——位置决定发到哪（Query / 请求头 / URL Path / Body），
        勾「凭证」的由 admin 配置（加密），其余调用时由 AI 填值。
        """
        import re as _re

        params = endpoint.get("params") or []
        if not isinstance(params, list):
            raise UserToolError("参数表格式不正确（应为列表）。")
        seen: set[str] = set()
        for p in params:
            name = str(p.get("name") or "").strip()
            pos = str(p.get("in") or "query").strip()
            if not name:
                raise UserToolError("参数表存在未命名参数，请填写参数名或删除该行。")
            if not _re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", name):
                raise UserToolError(f"参数名「{name}」只能用字母、数字、下划线，且不能以数字开头。")
            if name in seen:
                raise UserToolError(f"参数名「{name}」重复。")
            seen.add(name)
            if pos not in UserToolService.PARAM_POSITIONS:
                raise UserToolError(f"参数「{name}」的位置无效（{pos}）。")
        # URL 中的 {xxx} Path 占位必须与 path 参数一一对应
        url = str(endpoint.get("url") or "")
        url_vars = set(_re.findall(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", url))
        path_params = {p["name"] for p in params if p.get("in") == "path"}
        missing = url_vars - path_params
        extra = path_params - url_vars
        if missing:
            raise UserToolError(f"URL 中的占位 {'、'.join(sorted(missing))} 未在参数表声明（位置选 Path）。")
        if extra:
            raise UserToolError(f"Path 参数 {'、'.join(sorted(extra))} 未在 URL 中使用（需写成 {{名称}}）。")
        return [
            {
                "name": str(p.get("name") or "").strip(),
                "in": str(p.get("in") or "query").strip(),
                "description": str(p.get("description") or ""),
                "required": bool(p.get("required")),
                "credential": bool(p.get("credential")),
            }
            for p in params
        ]

    @staticmethod
    def derive_openapi_schemas(endpoint: dict) -> tuple[dict, dict]:
        """从参数表生成 (llm_args_schema, user_args_schema)。

        非凭证参数 → 运行参数（AI 调用时填）；凭证参数 → 工具级凭证
        （sensitive 加密，admin 配置）。参数表是唯一事实源。
        """
        params = UserToolService._validate_openapi_params(endpoint or {})
        llm_props: dict = {}
        llm_required: list[str] = []
        user_props: dict = {}
        user_required: list[str] = []
        for p in params:
            if p["credential"]:
                user_props[p["name"]] = {
                    "type": "string", "sensitive": True,
                    "description": p["description"] or "接口凭证（加密存储，管理员配置）",
                }
                user_required.append(p["name"])
            else:
                llm_props[p["name"]] = {
                    "type": "string", "description": p["description"],
                }
                if p["required"]:
                    llm_required.append(p["name"])
        llm = {"type": "object", "properties": llm_props, "required": llm_required} if llm_props else {}
        user = {"type": "object", "properties": user_props, "required": user_required} if user_props else {}
        return llm, user

    @staticmethod
    async def create_tool(
        user_id: str,
        *,
        name: str,
        description: str = "",
        source: str,
        user_args_schema: dict | None = None,
        llm_args_schema: dict | None = None,
        endpoint: dict | None = None,
        code: str = "",
        output_schema: dict | None = None,
        tags: list[str] | None = None,
    ) -> dict:
        """创建工具（private）。组织内名称唯一——Agent 绑定/节点选择无歧义。"""
        name = UserToolService._validate_name(name)
        UserToolService._validate_source(source)
        if source == "code" and (code or "").strip():
            UserToolService._validate_code(code)
        if source == "openapi":
            # 参数表是唯一事实源——schema（运行参数 + 凭证）按参数表生成
            params = UserToolService._validate_openapi_params(endpoint or {})
            endpoint = {**(endpoint or {}), "params": params}
            llm_args_schema, user_args_schema = UserToolService.derive_openapi_schemas(endpoint)
        await UserToolService._ensure_name_available(name)

        tool_id = generate_id("uto")
        now = utc_now().isoformat()
        doc = {
            "_id": tool_id,
            "owner_user_id": user_id,
            "name": name,
            "name_key": UserToolService._name_key(name),
            "description": description or "",
            "source": source,
            "user_args_schema": user_args_schema or {},
            "llm_args_schema": llm_args_schema or {},
            "endpoint": endpoint or {},
            "code": code or "",
            "output_schema": output_schema or {},
            "status": "private",
            "enabled": False,
            "org_user_args": {},
            "derived_from": None,
            "stats": {"load_count": 0, "up": 0, "down": 0},
            "version": 1,
            "tags": tags or [],
            "created_at": now,
            "updated_at": now,
            "published_at": None,
            "approved_by": None,
        }
        await UserToolService._col().insert_one(doc)
        logger.info("user_tool_created", user_id=user_id, name=name, tool_id=tool_id, source=source)
        doc["id"] = tool_id
        return doc

    @staticmethod
    async def update_tool(
        user_id: str,
        tool_id: str,
        *,
        name: str | None = None,
        description: str | None = None,
        user_args_schema: dict | None = None,
        llm_args_schema: dict | None = None,
        endpoint: dict | None = None,
        code: str | None = None,
        output_schema: dict | None = None,
        tags: list[str] | None = None,
        is_admin: bool = False,
    ) -> dict:
        """编辑工具（owner 或 admin）。已发布的编辑后回 private 且关闭
        enabled——定义变更需重新审查与开启（凭证可能因 schema 变化失配）。"""
        doc = await UserToolService.get_tool(tool_id)
        if doc is None or (doc.get("owner_user_id") != user_id and not is_admin):
            raise UserToolError(f"Tool '{tool_id}' not found or not yours.")
        if doc.get("status") == "hidden":
            raise UserToolError("Hidden tools cannot be edited — contact an admin.")

        sets: dict = {"updated_at": utc_now().isoformat()}
        if name is not None and name != doc["name"]:
            UserToolService._validate_name(name)
            await UserToolService._ensure_name_available(name, exclude_id=tool_id)
            sets["name"] = name
            sets["name_key"] = UserToolService._name_key(name)
        if description is not None:
            sets["description"] = description
        if endpoint is not None:
            sets["endpoint"] = endpoint
        if llm_args_schema is not None:
            sets["llm_args_schema"] = llm_args_schema
        if doc.get("source") == "openapi":
            # 参数表是唯一事实源——schema 一律按参数表重算，不接受外部提交
            effective_ep = endpoint if endpoint is not None else (doc.get("endpoint") or {})
            llm_schema, user_schema = UserToolService.derive_openapi_schemas(effective_ep)
            sets["llm_args_schema"] = llm_schema
            sets["user_args_schema"] = user_schema
            if endpoint is not None:
                # 参数表规范化（去掉空行等脏数据）后回写
                sets["endpoint"] = {**endpoint, "params": UserToolService._validate_openapi_params(endpoint)}
        if code is not None:
            if code.strip():
                UserToolService._validate_code(code)
            sets["code"] = code
        if output_schema is not None:
            sets["output_schema"] = output_schema
        if tags is not None:
            sets["tags"] = tags

        if doc.get("status") in ("published", "submitted"):
            sets["status"] = "private"
        if doc.get("enabled"):
            sets["enabled"] = False
            sets["org_user_args"] = {}  # schema 可能变——凭证需重配

        await UserToolService._col().update_one(
            {"_id": tool_id},
            {"$set": sets, "$inc": {"version": 1}},
        )
        updated = await UserToolService.get_tool(tool_id) or doc
        updated["id"] = tool_id
        logger.info("user_tool_updated", user_id=user_id, tool_id=tool_id)
        return updated

    @staticmethod
    async def delete_tool(user_id: str, tool_id: str, *, is_admin: bool = False) -> None:
        doc = await UserToolService.get_tool(tool_id)
        if doc is None or (doc.get("owner_user_id") != user_id and not is_admin):
            raise UserToolError(f"Tool '{tool_id}' not found or not yours.")
        await UserToolService._col().delete_one({"_id": tool_id})
        await UserToolService._vote_col().delete_many({"tool_id": tool_id})
        logger.info("user_tool_deleted", user_id=user_id, tool_id=tool_id, name=doc.get("name"))

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------

    @staticmethod
    async def get_tool(tool_id: str) -> dict | None:
        doc = await UserToolService._col().find_one({"_id": tool_id})
        if doc is not None:
            doc["id"] = doc["_id"]
        return doc

    @staticmethod
    async def find_by_name(name: str) -> dict | None:
        """组织内按名称查重（归一化口径：-/_ 变体与大小写视为同名）。"""
        return await UserToolService._col().find_one(
            {"name_key": UserToolService._name_key(name)}
        )

    @staticmethod
    async def can_view(user_id: str, doc: dict) -> bool:
        """可见性：owner/admin 看全部；published 任何人可预览（目录）。"""
        return (
            doc.get("owner_user_id") == user_id
            or doc.get("status") == "published"
        )

    @staticmethod
    async def record_load(tool_id: str) -> None:
        """组织库调用计数（Agent/工作流构建成功即记）。"""
        if tool_id.startswith("tool_"):
            from app.services.tool_service import ToolService

            await ToolService._collection().update_one(
                {"_id": tool_id}, {"$inc": {"stats.load_count": 1}}
            )
            return
        await UserToolService._col().update_one(
            {"_id": tool_id}, {"$inc": {"stats.load_count": 1}}
        )

    # ------------------------------------------------------------------
    # 治理：发布审查 → 凭证配置 → 开启
    # ------------------------------------------------------------------

    @staticmethod
    async def submit_for_review(user_id: str, tool_id: str) -> dict:
        doc = await UserToolService.get_tool(tool_id)
        if doc is None or doc.get("owner_user_id") != user_id:
            raise UserToolError(f"Tool '{tool_id}' not found or not yours.")
        if doc.get("status") not in ("private", "hidden"):
            raise UserToolError(
                f"Tool status is '{doc.get('status')}' — only private tools can be submitted."
            )
        await UserToolService._col().update_one(
            {"_id": tool_id}, {"$set": {"status": "submitted", "updated_at": utc_now().isoformat()}}
        )
        doc["status"] = "submitted"
        return doc

    @staticmethod
    async def review_tool(tool_id: str, action: str, reviewer: str, reason: str = "") -> dict:
        """管理员审查：approve → published（仍未启用，需另行开启）；reject → private。"""
        doc = await UserToolService.get_tool(tool_id)
        if doc is None:
            raise UserToolError(f"Tool '{tool_id}' not found.")
        now = utc_now().isoformat()
        if action == "approve":
            await UserToolService._col().update_one(
                {"_id": tool_id},
                {"$set": {"status": "published", "published_at": now,
                          "approved_by": reviewer, "updated_at": now, "review_note": ""}},
            )
            doc["status"] = "published"
        elif action == "reject":
            await UserToolService._col().update_one(
                {"_id": tool_id},
                {"$set": {"status": "private", "updated_at": now, "review_note": reason[:500]}},
            )
            doc["status"] = "private"
        else:
            raise UserToolError(f"Unknown review action '{action}'.")
        logger.info("user_tool_reviewed", tool_id=tool_id, action=action, by=reviewer)
        return doc

    @staticmethod
    async def list_for_review(status: str = "submitted") -> list[dict]:
        docs = await UserToolService._col().find({"status": status}).sort("updated_at", 1).to_list(100)
        for d in docs:
            d["id"] = d["_id"]
        return docs

    @staticmethod
    async def _definition_gaps(doc: dict) -> list[str]:
        """定义完整性缺口：openapi 需 endpoint.url、code 需代码。"""
        missing: list[str] = []
        if doc.get("source") == "openapi" and not (doc.get("endpoint") or {}).get("url"):
            missing.append("endpoint.url")
        if doc.get("source") == "code" and not (doc.get("code") or "").strip():
            missing.append("code")
        return missing

    @staticmethod
    async def save_org_args(admin_id: str, tool_id: str, user_args: dict) -> None:
        """admin 配置工具级统一凭证（sensitive 加密；全使用点共用）。

        合并语义：提交中缺失的字段保留旧值——前端不回显 sensitive 明文，
        未改动的敏感字段不会出现在提交体里，旧密文必须原样保留。
        """
        doc = await UserToolService.get_tool(tool_id)
        if doc is None:
            raise UserToolError(f"Tool '{tool_id}' not found.")
        merged = {**(doc.get("org_user_args") or {}), **(user_args or {})}
        encrypted = await UserToolService.encrypt_user_args(tool_id, merged)
        await UserToolService._col().update_one(
            {"_id": tool_id},
            {"$set": {"org_user_args": encrypted, "updated_at": utc_now().isoformat()}},
        )
        logger.info("user_tool_org_args_saved", by=admin_id, tool_id=tool_id)

    @staticmethod
    async def enable_tool(admin_id: str, tool_id: str, enabled: bool) -> dict:
        """admin 开启/停用——开启是「可被使用」的唯一开关。

        开启三重校验：published（已过审）+ 定义完整 + 凭证完整
        （定义了 user_args_schema 的字段就必须在 org_user_args 配齐）。
        """
        doc = await UserToolService.get_tool(tool_id)
        if doc is None:
            raise UserToolError(f"Tool '{tool_id}' not found.")

        if enabled:
            if doc.get("status") != "published":
                raise UserToolError("仅审查通过（published）的工具可开启。")
            gaps = await UserToolService._definition_gaps(doc)
            if gaps:
                raise UserToolError(f"定义不完整，无法开启：缺少 {'、'.join(gaps)}")
            missing = UserToolService._local_args_missing(doc)
            if missing:
                raise UserToolError(
                    f"凭证未配置完整，无法开启——缺少：{'、'.join(missing)}。请先配置凭证。"
                )

        await UserToolService._col().update_one(
            {"_id": tool_id},
            {"$set": {"enabled": enabled, "updated_at": utc_now().isoformat()}},
        )
        logger.info("user_tool_enabled_changed", by=admin_id, tool_id=tool_id, enabled=enabled)
        doc["enabled"] = enabled
        return doc

    @staticmethod
    def _local_args_missing(doc: dict) -> list[str]:
        """对照 doc 自身 schema 检查 org_user_args 完整性（纯本地计算）。"""
        props = (doc.get("user_args_schema") or {}).get("properties") or {}
        args = doc.get("org_user_args") or {}
        return [
            key for key in props
            if not (isinstance(args.get(key), str) and args[key].strip())
        ]

    # ------------------------------------------------------------------
    # 运行时统一解析（Agent 绑定 / 工作流节点共用）
    # ------------------------------------------------------------------

    @staticmethod
    async def resolve_org_tool(tool_id: str) -> tuple[dict, dict] | None:
        """按 tool_id 解析「可用」的工具及其（解密后的）工具级凭证。

        - tool_*：官方工具（tools 表，is_tool_active 校验）
        - uto_*：组织库工具（published + enabled 校验）
        返回 (tool_doc, user_args)；不可用/不存在返回 None。
        """
        from app.engine.harness_integration.context import decrypt_user_args

        if not tool_id.startswith("uto_"):
            from app.services.tool_service import ToolService

            doc = await ToolService.get_tool(tool_id)
            if doc is None or not ToolService.is_tool_active(doc):
                return None
            return doc, decrypt_user_args(doc, doc.get("org_user_args") or {})

        doc = await UserToolService.get_tool(tool_id)
        if doc is None:
            return None
        if doc.get("status") != "published" or not doc.get("enabled"):
            return None
        return doc, decrypt_user_args(doc, doc.get("org_user_args") or {})

    @staticmethod
    async def list_enabled_tools() -> list[dict]:
        """可绑定/可直调的工具全集（官方 active + 组织库 published&enabled）——
        Agent 绑定与工作流节点的候选列表。

        返回含 llm_args_schema（运行参数定义）——工作流工具节点按此渲染
        结构化参数表单；org_user_args 等敏感字段不返回。
        """
        from app.services.tool_service import ToolService

        result: list[dict] = []
        official = await ToolService._collection().find({
            "source": {"$in": list(MARKET_TOOL_SOURCES)},
            "status": {"$nin": ["disabled"]},
        }).to_list(100)
        for d in official:
            d = dict(d)
            d["id"] = d["_id"]
            d["org"] = "official"
            d.pop("org_user_args", None)
            result.append(d)
        enabled = await UserToolService._col().find({
            "status": "published", "enabled": True,
        }).to_list(100)
        for d in enabled:
            d = dict(d)
            d["id"] = d["_id"]
            d["org"] = "user"
            d.pop("org_user_args", None)
            result.append(d)
        return result

    # ------------------------------------------------------------------
    # 组织工具库目录（原广场：浏览 + 审查态；无安装语义）
    # ------------------------------------------------------------------

    @staticmethod
    async def marketplace(viewer_id: str, q: str = "", limit: int = 50) -> list[dict]:
        """组织工具库目录（单卡片墙，无个人页面）：

        官方（active）+ 已发布用户工具 + **viewer 自己的非发布工具**
        （草稿/审核中——创建者在目录里就地管理）。官方在前。

        每项含 kind（official/user）、enabled（治理可用性）、
        作者显示名（创建者）、我的投票态。
        """
        query: dict = {"status": "published"}
        if q:
            query["$or"] = [
                {"name": {"$regex": q, "$options": "i"}},
                {"description": {"$regex": q, "$options": "i"}},
            ]
        user_docs = await (
            UserToolService._col().find(query)
            .sort([("stats.up", -1), ("stats.load_count", -1)])
            .limit(limit)
            .to_list(limit)
        )
        # viewer 自己的草稿/审核中（不在 published 主查询里；admin 看全部草稿）
        viewer_is_admin = False
        if viewer_id:
            viewer_doc = await get_database()["users"].find_one({"_id": viewer_id}, {"role": 1})
            viewer_is_admin = (viewer_doc or {}).get("role") == "admin"
        own_query: dict = (
            {} if viewer_is_admin
            else {"owner_user_id": viewer_id, "status": {"$nin": ["published"]}}
        )
        if q:
            own_query["$or"] = [
                {"name": {"$regex": q, "$options": "i"}},
                {"description": {"$regex": q, "$options": "i"}},
            ]
        own_docs = await (
            UserToolService._col().find(own_query).sort("updated_at", -1).limit(50).to_list(50)
        ) if (viewer_id or viewer_is_admin) else []
        # 去重（admin 视角 own 查询可能含 published 已在主列表）
        seen_ids = {d["_id"] for d in user_docs}
        user_docs += [d for d in own_docs if d["_id"] not in seen_ids]

        tool_query: dict = {
            "source": {"$in": list(MARKET_TOOL_SOURCES)},
            "status": {"$nin": ["disabled"]},
        }
        if q:
            tool_query["$and"] = [{"$or": [
                {"name": {"$regex": q, "$options": "i"}},
                {"description": {"$regex": q, "$options": "i"}},
            ]}]
        tool_docs = await get_database()["tools"].find(tool_query).to_list(limit)

        author_ids = list({d["owner_user_id"] for d in user_docs if d.get("owner_user_id")})
        author_ids += list({d["created_by"] for d in tool_docs if d.get("created_by")})
        name_by_id: dict[str, str] = {}
        if author_ids:
            users = await get_database()["users"].find(
                {"_id": {"$in": author_ids}}, {"username": 1, "nickname": 1}
            ).to_list(len(author_ids))
            name_by_id = {
                u["_id"]: (u.get("nickname") or u.get("username") or u["_id"]) for u in users
            }

        my_votes = {
            v["tool_id"]: int(v.get("value", 0) or 0)
            for v in await UserToolService._vote_col().find({"user_id": viewer_id}).to_list(200)
        } if viewer_id else {}

        def _decorate(d: dict, kind: str) -> dict:
            d = dict(d)
            d["kind"] = kind
            d["id"] = d["_id"]
            owner = d.get("owner_user_id") if kind == "user" else d.get("created_by", "")
            if kind == "user":
                d["author_name"] = name_by_id.get(owner, owner or "未知")
            else:
                d["author_name"] = name_by_id.get(owner, "官方") if owner else "官方"
            d["is_own"] = d.get("owner_user_id") == viewer_id if kind == "user" else False
            d["my_vote"] = my_votes.get(d["_id"], 0)
            stats = d.get("stats") or {}
            d["score"] = int(stats.get("up", 0) or 0) - int(stats.get("down", 0) or 0)
            # 治理可用性：官方看 status，用户工具看 enabled
            d["enabled"] = (
                (d.get("status") or "active") == "active" if kind == "official"
                else bool(d.get("enabled"))
            )
            return d

        officials = sorted(
            [_decorate(d, "official") for d in tool_docs],
            key=lambda x: (-x["score"], -int((x.get("stats") or {}).get("load_count", 0) or 0)),
        )
        users_list = [_decorate(d, "user") for d in user_docs]
        return officials + users_list

    # ------------------------------------------------------------------
    # fork / 收录 / 投票
    # ------------------------------------------------------------------

    @staticmethod
    async def fork(user_id: str, tool_id: str) -> dict:
        """复制已发布工具为自己的草稿（derived_from 溯源，可改后再走治理流程）。"""
        doc = await UserToolService.get_tool(tool_id)
        if doc is None:
            raise UserToolError(f"Tool '{tool_id}' not found.")
        if doc.get("owner_user_id") == user_id:
            raise UserToolError("This is already your own tool.")
        if doc.get("status") != "published":
            raise UserToolError(f"Tool '{tool_id}' is not published.")

        base_name = doc["name"]
        candidates = [base_name] + [f"{base_name}-fork{i}" for i in range(1, 50)]
        name: str | None = None
        for candidate in candidates:
            if not await UserToolService.find_by_name(candidate):
                name = candidate
                break
        if name is None:
            raise UserToolError("Could not derive a free name; please rename after forking.")

        created = await UserToolService.create_tool(
            user_id,
            name=name,
            description=doc.get("description", ""),
            source=doc.get("source", "openapi"),
            user_args_schema=doc.get("user_args_schema") or {},
            llm_args_schema=doc.get("llm_args_schema") or {},
            endpoint=doc.get("endpoint") or {},
            code=doc.get("code", ""),
            tags=list(doc.get("tags") or []),
        )
        await UserToolService._col().update_one(
            {"_id": created["_id"]},
            {"$set": {"derived_from": tool_id, "derived_from_name": base_name}},
        )
        created["derived_from"] = tool_id
        created["derived_from_name"] = base_name
        created["forked_as"] = name
        return created

    @staticmethod
    async def vote(user_id: str, tool_id: str, value: int) -> dict:
        """目录投票：一用户一票，改票回滚（组织内反馈信号）。"""
        if value not in (1, -1):
            raise UserToolError("Vote value must be 1 (up) or -1 (down).")

        col = UserToolService._vote_col()
        key = {"user_id": user_id, "tool_id": tool_id}
        existing = await col.find_one(key)
        old_value = int((existing or {}).get("value", 0) or 0)
        if old_value == value:
            return {"ok": True, "changed": False}

        async def _apply(delta_field: str, step: int) -> None:
            if tool_id.startswith("tool_"):
                from app.services.tool_service import ToolService

                await ToolService._collection().update_one(
                    {"_id": tool_id}, {"$inc": {delta_field: step}}
                )
            else:
                await UserToolService._col().update_one(
                    {"_id": tool_id}, {"$inc": {delta_field: step}}
                )

        if existing and old_value:
            await _apply("stats.up" if old_value == 1 else "stats.down", -1)
        await _apply("stats.up" if value == 1 else "stats.down", 1)

        now = utc_now().isoformat()
        await col.update_one(key, {"$set": {"value": value, "updated_at": now}}, upsert=True)
        return {"ok": True, "changed": True}

    # ------------------------------------------------------------------
    # 凭证加密（与官方工具/Agent 绑定归一化共用）
    # ------------------------------------------------------------------

    @staticmethod
    async def encrypt_user_args(tool_id: str, user_args: dict) -> dict:
        """加密 user_args 中标记 sensitive 的字段（enc: 前缀，已加密原样保留）。"""
        if not user_args:
            return {}
        if tool_id.startswith("uto_"):
            doc = await UserToolService.get_tool(tool_id)
        else:
            from app.services.tool_service import ToolService

            doc = await ToolService.get_tool(tool_id)
        props = ((doc or {}).get("user_args_schema") or {}).get("properties") or {}
        result = dict(user_args)
        for key, val in list(result.items()):
            if props.get(key, {}).get("sensitive") and isinstance(val, str) and val and not val.startswith("enc:"):
                with contextlib.suppress(Exception):
                    result[key] = f"enc:{encrypt_secret(val)}"
        return result

    # ------------------------------------------------------------------
    # collections
    # ------------------------------------------------------------------

    @staticmethod
    def _col():
        return get_database()[UserToolService.COLLECTION]

    @staticmethod
    def _vote_col():
        return get_database()[UserToolService.VOTE_COLLECTION]


__all__ = ["UserToolService", "UserToolError"]

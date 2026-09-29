"""spawn 工具 — agent 创建 agent（能力门控：agent.can_spawn_agents 手动开启）。

治理原则落地：
- draft 闸门：创建物为草稿态，人审发布（AGENT_PUBLISHED_IMMUTABLE 既有防线）
- 权限不放大：创建物 can_spawn_agents 恒为 False（最多一层，防递归繁殖）
- 审计：spawned_by_agent_id / spawned_by_session_id 落档可回溯
- 能力感知：list_capabilities 盘点平台能力（创建难点之首——知道系统有什么）

注入规则（context.py）：can_spawn_agents 开启时——
- chat  = list_capabilities + create_agent（直接创建路径）
- plan  = 仅 list_capabilities（create_agent 属变更操作，计划期剥离；
          计划模式的实验对照点：plan 下走 计划→批准→执行期 create_agent）
- workflow = 均不注入（无人值守不繁殖）
"""

from __future__ import annotations

import contextvars

from langchain_core.tools import BaseTool, StructuredTool

# ── 父 agent 上下文（resolve_harness_context set / release reset）──────
# 工具执行时拿不到 state.agent_id，经 contextvar 透传用于繁殖审计。
_current_agent_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "current_agent_id", default=""
)


def set_spawn_agent_context(agent_id: str) -> contextvars.Token:
    return _current_agent_id.set(agent_id)


def reset_spawn_agent_context(token: contextvars.Token) -> None:
    _current_agent_id.reset(token)


def _current_user_id() -> str:
    """当前用户（能力清单按用户可见范围过滤）——workspace 上下文取。"""
    try:
        from app.engine.agent.builtin_tools import _get_workspace

        ws = _get_workspace()
        return ws.user_id if ws else ""
    except Exception:
        return ""


def _is_platform_user() -> bool:
    """spawn 三工具仅平台用户可用——IM 渠道与外部终端用户不具备繁殖能力。

    判定依据（fail-closed，默认拒绝）：
    - channel: 前缀 → IM 渠道用户
    - workspace 无 user_id（外部/widget 路径）→ 外部用户
    - 其余 → 平台用户
    """
    user_id = _current_user_id()
    if not user_id:
        return False  # 无身份信息（外部路径）→ 拒绝
    from app.engine.user_skills.tools import is_channel_user

    return not is_channel_user(user_id)


async def _list_capabilities() -> str:
    """盘点平台当前可用的全部能力，供设计新 agent 时做能力分配。"""
    from app.db.mongodb import get_database

    db = get_database()
    lines: list[str] = []

    # 1) 内置工具（与运行时注入同源：_INJECTED_BUILTIN_TOOL_NAMES 查找链）
    try:
        from agent_flow_harness import BUILTIN_TOOLS

        from app.engine.agent.image_tool import IMAGE_TOOL_BY_NAME
        from app.engine.agent.parse_tool import PARSE_TOOL_BY_NAME
        from app.engine.agent.recall_tool import RECALL_TOOL_BY_NAME
        from app.engine.harness_integration.context import (
            _CONFIGURABLE_BUILTIN_TOOL_NAMES,
            _INJECTED_BUILTIN_TOOL_NAMES,
        )

        entries = []
        for name in _INJECTED_BUILTIN_TOOL_NAMES:
            tool = (
                BUILTIN_TOOLS.get(name)
                or PARSE_TOOL_BY_NAME.get(name)
                or IMAGE_TOOL_BY_NAME.get(name)
                or RECALL_TOOL_BY_NAME.get(name)
            )
            if tool is None:
                continue
            flag = "" if name in _CONFIGURABLE_BUILTIN_TOOL_NAMES else "（始终启用）"
            first = (tool.description or "").split("\n")[0][:80]
            desc = first + "…" if len((tool.description or "").split("\n")[0]) > 80 else first
            entries.append(f"- {name}{flag}：{desc}")
        lines.append("## 内置工具（builtin_config 可配）\n" + "\n".join(entries))
    except Exception:
        pass

    # 2) 工具目录（自定义 / MCP / 技能同住 tools 集合，按 source 分拣）。
    #    注意不过滤 status：MCP 镜像（source=mcp）与 skill（source=markdown）
    #    文档写入时没有 status 字段（mcp_connection_service / tool_service），
    #    按 status 查会把它们全部漏掉（已证 bug）。自定义工具的启停过滤
    #    按 tool_service 的约定（缺省即 active）在分拣后客户端判断。
    try:
        cursor = db["tools"].find(
            {},
            {"name": 1, "description": 1, "source": 1, "status": 1,
             "mcp_connection_id": 1},
        ).limit(300)
        docs = await cursor.to_list(length=200)
        custom = [
            d
            for d in docs
            if d.get("source") not in ("mcp", "markdown")
            and (d.get("status") or "active") == "active"
        ]
        mcp_docs = [d for d in docs if d.get("source") == "mcp"]
        skills = [d for d in docs if d.get("source") == "markdown"]
        # 描述分档截断 + 省略号（裸切会让描述看起来"坏了"）：
        # skill 描述承载"何时用"语义且数量少 → 放宽到 200；MCP 工具
        # 数量多（264 个实测）且中位 62 字符 → 120 控制清单总体积。
        def _desc(d: dict, limit: int) -> str:
            raw = (d.get("description") or "").strip().replace("\n", " ")
            return raw[:limit] + "…" if len(raw) > limit else raw

        def fmt(ds: list, limit: int = 120) -> str:
            return "\n".join(
                f"- {d.get('name','')}（id={d.get('_id','')}）：{_desc(d, limit)}"
                for d in ds[:40]
            )
        if custom:
            lines.append("## 自定义工具（tool_ids 绑定）\n" + fmt(custom))
        if mcp_docs:
            # 绑定粒度=连接（绑上=该连接全部工具注入）——按连接分组呈现，
            # id 给连接 id（可直接填 mcp_connection_ids），工具名列内联。
            conn_names: dict = {}
            try:
                async for c in db["mcp_connections"].find({}, {"name": 1}):
                    conn_names[c["_id"]] = c.get("name", "")
            except Exception:
                pass
            by_conn: dict[str, list] = {}
            for d in mcp_docs:
                by_conn.setdefault(d.get("mcp_connection_id", ""), []).append(d)
            mcp_lines = []
            for cid, tools in by_conn.items():
                mcp_lines.append(
                    f"- 连接「{conn_names.get(cid, cid[:16])}」（id={cid}，"
                    f"{len(tools)} 个工具；绑定后全部可用）："
                )
                for t in tools:
                    mcp_lines.append(f"    - {t.get('name','')}：{_desc(t, 80)}")
            lines.append(
                "## MCP 连接（绑定粒度=整连接，mcp_connection_ids 填连接 id；"
                "绑定后该连接全部工具可用）\n" + "\n".join(mcp_lines)
            )
        if skills:
            lines.append("## 技能（skill_ids 绑定）\n" + fmt(skills, limit=200))
    except Exception:
        pass

    # 3) 可用模型
    try:
        cursor = db["models"].find({}, {"name": 1, "model_id": 1}).limit(50)
        models = await cursor.to_list(length=50)
        if models:
            lines.append(
                "## 可用模型（model_ref）\n"
                + "\n".join(
                    f"- {m.get('name','')}（id={m.get('_id','')}，{m.get('model_id','')}）"
                    for m in models
                )
            )
    except Exception:
        pass

    if not lines:
        return "（能力盘点为空或查询失败——请直接告知用户平台暂无可用能力清单）"
    return "\n\n".join(lines)


async def _create_agent(
    name: str,
    description: str,
    system_prompt: str,
    builtin_config: list[str] | None = None,
    skill_ids: list[str] | None = None,
    mcp_connection_ids: list[str] | None = None,
    custom_tool_ids: list[str] | None = None,
    knowledge_base_ids: list[str] | None = None,
    model_ref: str = "",
) -> str:
    """创建新 agent（草稿态，需人工在平台审核发布后生效）。"""
    if not name.strip() or not system_prompt.strip():
        return "[create_agent] name 与 system_prompt 必填，请补全后重试。"
    if not _is_platform_user():
        return "[create_agent] 仅平台用户可创建 Agent——当前会话身份（渠道/外部）不具备此能力。"

    from app.db.mongodb import get_database
    from app.engine.agent.builtin_tools import _get_workspace
    from app.services.agent_service import AgentService

    # 连接 id 归一：绑定粒度是连接（mcp_connection_ids）。模型可能误填
    # 工具级 id（清单曾按工具列出）——按 tools 集合映射回所属连接；
    # 未知 id 直接报错回灌（防静默绑定失败）。
    if mcp_connection_ids:
        valid: list[str] = []
        unknown: list[str] = []
        conn_col = get_database()["mcp_connections"]
        tool_col = get_database()["tools"]
        for cid in dict.fromkeys(mcp_connection_ids):  # 去重保序
            if await conn_col.find_one({"_id": cid}, {"_id": 1}):
                if cid not in valid:
                    valid.append(cid)
                continue
            t = await tool_col.find_one({"_id": cid, "source": "mcp"}, {"mcp_connection_id": 1})
            if t and t.get("mcp_connection_id"):
                if t["mcp_connection_id"] not in valid:
                    valid.append(t["mcp_connection_id"])
                continue
            unknown.append(cid)
        if unknown:
            conns = await conn_col.find({}, {"name": 1}).to_list(length=50)
            hint = "；".join(f"{c.get('name','')}（id={c['_id']}）" for c in conns[:10])
            return (
                f"[create_agent] 以下 mcp_connection_ids 不存在：{unknown}。"
                f"绑定粒度是整连接（非单个工具）。可用连接：{hint}"
            )
        mcp_connection_ids = valid

    ws = _get_workspace()
    session_id = ws.session_id if ws else ""
    try:
        doc = await AgentService.create_agent(
            name=name.strip()[:100],
            description=(description or "").strip()[:500],
            # 五槽中 role/task 为对话执行必填槽——system_prompt 进角色定义槽
            prompt_slots={"role": system_prompt, "task": description or ""},
            builtin_config=builtin_config or [],
            skill_ids=skill_ids or [],
            mcp_connection_ids=mcp_connection_ids or [],
            custom_tool_ids=custom_tool_ids or [],
            knowledge_base_ids=knowledge_base_ids or [],
            default_model=model_ref or "",
            can_spawn_agents=False,  # 权限不放大：创建物不再拥有繁殖能力
            spawned_by_agent_id=_current_agent_id.get(),
            spawned_by_session_id=session_id,
        )
    except Exception as exc:  # noqa: BLE001 — 名称冲突等业务错误回灌模型
        return f"[create_agent] 创建失败：{exc}"

    aid = doc.get("_id", "")
    return (
        f"已创建草稿 agent「{name}」（id={aid}，状态=draft）。"
        "注意：草稿需用户在平台上审核并发布后才可被调用；"
        "请向用户说明可在 智能体列表 中查看、测试（实时试聊）与发布。"
    )


async def _test_agent(agent_id: str, input: str) -> str:
    """验收测试：以独立会话试跑指定 agent，返回其回复（由你判断是否达标）。"""
    from app.engine.agent.builtin_tools import _get_workspace
    from app.schemas.execution import ExecutionRequest
    from app.services.agent_execution_service import AgentExecutionService
    from app.services.agent_service import AgentService

    if not agent_id.strip() or not input.strip():
        return "[test_agent] agent_id 与 input 必填。"
    if agent_id == _current_agent_id.get():
        return "[test_agent] 不能测试自身（递归）。"
    if not _is_platform_user():
        return "[test_agent] 仅平台用户可测试 Agent。"

    ws = _get_workspace()
    user_id = ws.user_id if ws else ""
    doc = await AgentService.get_agent(agent_id)
    if doc is None:
        return f"[test_agent] agent {agent_id} 不存在。"
    if doc.get("status") == "archived":
        return f"[test_agent] agent「{doc.get('name')}」已归档，不可测试。"

    try:
        # 独立会话（invoke 的 session 缺省自动新建）——每次测试干净上下文；
        # display_text 标记验收会话，避免测试问题泄漏到会话标题。
        resp = await AgentExecutionService.invoke(
            agent_id,
            ExecutionRequest(input=input, display_text="[验收测试]"),
            user_id,
        )
    except Exception as exc:  # noqa: BLE001 — 失败回灌由母 agent 决定下一步
        return f"[test_agent] 执行失败：{exc}"

    output = (resp.output or "").strip()
    if len(output) > 2000:
        output = output[:2000] + "…（截断）"
    return f"被测 agent 回复（session={resp.session_id}，{resp.step_count} 步）：\n{output}"


_test_agent_tool = StructuredTool.from_function(
    _test_agent,
    name="test_agent",
    description=(
        "验收测试：用一个独立的干净会话试跑指定 agent（通常是你刚创建的草稿），"
        "返回其回复，由你对照验收标准判断是否达标。每次调用都是全新会话；"
        "请用有代表性的验收问题（含边界情形），通常测 2-5 个问题。"
    ),
    coroutine=_test_agent,
)

list_capabilities = StructuredTool.from_function(
    _list_capabilities,
    name="list_capabilities",
    description=(
        "盘点平台当前可用的全部能力：内置工具、自定义工具、MCP 工具、技能、"
        "可用模型。设计或创建新 agent 前必须先调用本工具做能力"
        "分配——不要臆造不存在的工具或模型 id。"
    ),
    coroutine=_list_capabilities,
)

create_agent_tool = StructuredTool.from_function(
    _create_agent,
    name="create_agent",
    description=(
        "创建一个新 agent（草稿态，需用户人工审核发布后才生效）。创建前应已用 "
        "list_capabilities 盘点能力并据此分配。system_prompt 写完整的角色定义"
        "（职责/边界/语气）；builtin_config 只用清单里存在的内置工具名；"
        "MCP 的绑定粒度是整连接——mcp_connection_ids 填清单 MCP 节里的连接 id"
        "（绑上=该连接全部工具可用），不要填单个工具名。"
    ),
    coroutine=_create_agent,
)

#: 查找表（context.py 门控注入用）。
LIST_CAPABILITIES_TOOL: BaseTool = list_capabilities
CREATE_AGENT_TOOL: BaseTool = create_agent_tool
TEST_AGENT_TOOL: BaseTool = _test_agent_tool

__all__ = [
    "CREATE_AGENT_TOOL",
    "LIST_CAPABILITIES_TOOL",
    "TEST_AGENT_TOOL",
    "create_agent_tool",
    "list_capabilities",
    "reset_spawn_agent_context",
    "set_spawn_agent_context",
]

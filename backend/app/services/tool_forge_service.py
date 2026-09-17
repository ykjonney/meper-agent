"""ToolForgeService — 工具工坊 agent（harness 小型 agent，流式对话）。

以 harness REACT 引擎驱动的专用 agent：LLM 自主完成「出草稿（submit_
definition）→ 生成用例（make_test_cases）→ 试跑（run_test）→ 失败自我
修订 → 通过后保存（save_tool）」的闭环；凭证缺口经 ``ask_clarification``
interrupt 问用户，前端凭证卡作答后 ``Command(resume)`` 续跑——用户全程
无需手动保存。

- 会话：进程内注册表（forge_id → _ForgeSession），InMemorySaver
  checkpointer——单 worker 部署语义；进程重启丢会话（重新生成即可），
  将来持久化换 Mongo saver 零改动迁移（checkpointer 参数化）。
- 治理不变：save_tool 走 create_tool/update_tool（admin 免审、owner 修改
  回 private 重审均由 service 层承担）；试跑凭证 ad hoc 不落库，且只允许
  来自用户答复（LLM 严禁虚构）。
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import StructuredTool
from langgraph.checkpoint.memory import MemorySaver
from loguru import logger
from pydantic import BaseModel, Field

from app.models.base import generate_id
from app.services.tool_generator import (
    _CODE_RULES,
    _DEFINITION_SPEC,
    _OPENAPI_RULES,
    normalize_definition,
)
from app.services.user_tool_service import UserToolError, UserToolService

_FORGE_TTL_SECONDS = 2 * 60 * 60
_RECURSION_LIMIT = 30

_SYSTEM_PROMPT = (
    "你是 Agent 平台的「工具工坊助手」，帮用户打造自定义工具。你有专用工具，"
    "自主完成「生成 → 测试 → 修正 → 保存」的完整闭环，用户不需要手动保存。\n\n"
    "【工作流程】\n"
    "1. 理解需求 → 产出完整工具定义（字段规则见下），调用 submit_definition "
    "提交——提交通过才有可测试的草稿；校验不过按返回错误修正后重新提交\n"
    "2. 主动测试：调用 make_test_cases 生成用例，再逐个 run_test。草稿含凭证"
    "参数（user_args_schema 非空）而你手中没有值时，先用 ask_clarification "
    "向用户索取（fields 按参数逐个列出，密码/密钥类注明敏感），拿到值后作为 "
    "run_test 的 user_args——**凭证值只能来自用户答复，严禁虚构**\n"
    "3. run_test 失败 → 分析错误、修订定义、重新 submit_definition 再测——"
    "在助手回复里自主迭代直到通过，不必请示用户\n"
    "4. 用例全部通过（或工具无运行参数无法测试、或用户明确说不用测）→ 调用 "
    "save_tool 保存，然后向用户汇报结果与工具状态\n"
    "5. 用户继续提修改意见 → 修订 → （执行逻辑变化时重新测试）→ 再次 "
    "save_tool 更新保存\n\n"
    "【交互原则】\n"
    "- **首次描述即生成，不追问配置细节**：凡属「因部署环境/账号而异」的信息"
    "（服务器地址、端口、协议选项、账号、密钥等）未知时，一律设计成参数而不是"
    "提问——需要管理员预先配置的进 user_args_schema（敏感值标 sensitive），"
    "调用时才确定的进 llm_args_schema；参数 description 写清用途、格式与常见"
    "取值示例\n"
    "- 需求本身不清晰（要做什么、核心行为有歧义、多种理解会产生本质不同的"
    "工具）时可用 ask_clarification 提问澄清；提问聚焦需求歧义，"
    "不问上一条已约定参数化的环境配置\n"
    "- 回复用简洁中文说明进展，不重复粘贴完整定义（用户界面有草稿卡）\n\n"
    "【submit_definition 的定义字段】\n" + _DEFINITION_SPEC + "\n\n"
    + _CODE_RULES + "\n\n" + _OPENAPI_RULES
)


class _ForgeSession:
    """一个工具工坊对话会话（graph + config + 草稿态）。"""

    def __init__(
        self,
        forge_id: str,
        user_id: str,
        is_admin: bool,
        mode: str,
        tool_id: str,
        model_id: str,
        system_prompt: str,
    ) -> None:
        self.forge_id = forge_id
        self.user_id = user_id
        self.is_admin = is_admin
        self.mode = mode  # create | edit
        self.tool_id = tool_id
        self.model_id = model_id
        self.current_draft: dict | None = None
        self.saved_tool_id = ""
        # 对话中用户给过的凭证值（ask_clarification 答复后记录，run_test 复用）
        self.known_user_args: dict = {}
        self.started = False
        self.busy = False
        self.created_at = time.monotonic()
        self.system_prompt = system_prompt
        self.agent_doc = {"_id": f"forge_{forge_id}", "name": "tool-forge"}
        self.graph: Any = None
        self.config: dict = {}
        self.tools: list = []


def _json(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def _cred_props(draft: dict) -> dict:
    return (draft.get("user_args_schema") or {}).get("properties") or {}


def _make_tools(session: _ForgeSession) -> list[StructuredTool]:
    """会话专属工具集（闭包捕获 session：草稿态/用户/保存模式）。"""

    class _DefinitionArgs(BaseModel):
        definition: dict = Field(..., description="完整工具定义 JSON 对象")

    class _RunTestArgs(BaseModel):
        params: dict = Field(
            default_factory=dict, description="运行参数取值（对应 llm_args_schema）"
        )
        user_args: dict = Field(
            default_factory=dict,
            description="凭证参数取值（只允许用户提供过的值）",
        )

    async def _submit_definition(definition: dict) -> str:
        try:
            draft = normalize_definition(definition)
        except UserToolError as exc:
            return _json({"ok": False, "error": exc.message, "hint": "修正后重新提交"})
        session.current_draft = draft
        return _json({
            "ok": True,
            "name": draft["name"],
            "source": draft["source"],
            "llm_params": list(draft["llm_args_schema"].get("properties") or {}),
            "cred_params": list(_cred_props(draft)),
        })

    async def _make_cases() -> str:
        if not session.current_draft:
            return _json({"ok": False, "error": "先 submit_definition 提交草稿"})
        from app.services.tool_tester import generate_cases

        try:
            out = await generate_cases(session.current_draft, session.model_id)
        except UserToolError as exc:
            return _json({"ok": False, "error": exc.message})
        return _json(out)

    async def _run_test(params: dict, user_args: dict) -> str:
        if not session.current_draft:
            return _json({"ok": False, "error": "先 submit_definition 提交草稿"})
        # 凭证预检：缺值直接引导向用户索取，不空跑沙箱
        merged = {**session.known_user_args, **(user_args or {})}
        cred_keys = list(_cred_props(session.current_draft))
        missing = [k for k in cred_keys if not str(merged.get(k, "")).strip()]
        if missing:
            return _json({
                "ok": False,
                "error": f"缺少凭证参数：{'、'.join(missing)}",
                "hint": "用 ask_clarification 向用户索取（fields 按参数逐个列出），拿到后重试",
            })
        session.known_user_args = merged
        from app.services.tool_tester import run_once

        try:
            out = await run_once(session.current_draft, params, merged)
        except UserToolError as exc:
            return _json({"ok": False, "error": exc.message})
        # 凭证已注入仍报缺凭证类错误 → 给出真实注入清单，防止 AI 误判
        # 「沙箱限制」（实际多为代码读取的 USER_ 名与参数名不一致）
        if not out.get("ok") and cred_keys:
            err = str(out.get("error") or "")
            if "凭证" in err or "USER_" in err or "environ" in err or "KeyError" in err:
                out["hint"] = (
                    "凭证已按参数名注入环境变量："
                    + "、".join(f"USER_{k}" for k in cred_keys)
                    + "。若代码读取的名字不在其中，是代码与参数名不一致——"
                    "修订代码（与 user_args_schema 参数名一致）后重新 submit_definition，"
                    "这不是沙箱限制"
                )
        return _json(out)

    async def _save_tool() -> str:
        if not session.current_draft:
            return _json({"ok": False, "error": "先 submit_definition 提交草稿"})
        d = session.current_draft
        try:
            if session.mode == "edit" and session.tool_id:
                doc = await UserToolService.update_tool(
                    session.user_id,
                    session.tool_id,
                    name=d["name"],
                    description=d["description"],
                    user_args_schema=d["user_args_schema"],
                    llm_args_schema=d["llm_args_schema"],
                    endpoint=d["endpoint"],
                    code=d["code"],
                    output_schema=d["output_schema"],
                    tags=d["tags"],
                    is_admin=session.is_admin,
                )
                note = (
                    "已更新保存" if session.is_admin
                    else "已更新保存（owner 修改功能性字段 → 回 private 待重新审核开启）"
                )
            else:
                doc = await UserToolService.create_tool(
                    session.user_id,
                    name=d["name"],
                    description=d["description"],
                    source=d["source"],
                    user_args_schema=d["user_args_schema"],
                    llm_args_schema=d["llm_args_schema"],
                    endpoint=d["endpoint"],
                    code=d["code"],
                    output_schema=d["output_schema"],
                    tags=d["tags"],
                    is_admin=session.is_admin,
                )
                note = (
                    "已保存且直接 published（admin 免审）" if session.is_admin
                    else "已保存为 private 草稿（需提交审核 → 管理员开启后可用）"
                )
        except UserToolError as exc:
            return _json({"ok": False, "error": exc.message, "hint": "如名称冲突，改名后重新提交并保存"})
        session.saved_tool_id = doc["_id"]
        return _json({"ok": True, "tool_id": doc["_id"], "status": doc.get("status"), "note": note})

    return [
        StructuredTool.from_function(
            _submit_definition,
            name="submit_definition",
            description="提交/更新当前工具定义草稿（参数为完整定义 JSON 对象）。先提交才能测试与保存。",
            args_schema=_DefinitionArgs,
            coroutine=_submit_definition,
        ),
        StructuredTool.from_function(
            _make_cases,
            name="make_test_cases",
            description="按当前草稿生成 2-3 个测试用例（仅 params 取值，不含凭证）。",
            coroutine=_make_cases,
        ),
        StructuredTool.from_function(
            _run_test,
            name="run_test",
            description="按当前草稿试跑一次（沙箱执行，不落库）。凭证参数需用户提供过。",
            args_schema=_RunTestArgs,
            coroutine=_run_test,
        ),
        StructuredTool.from_function(
            _save_tool,
            name="save_tool",
            description="保存当前草稿到工具库（新建或更新）。测试通过后调用，之后向用户汇报。",
            coroutine=_save_tool,
        ),
    ]


class ToolForgeService:
    """工具工坊 agent：会话管理 + 流式执行 + interrupt 恢复。"""

    _sessions: dict[str, _ForgeSession] = {}

    # ------------------------------------------------------------------
    # 会话管理
    # ------------------------------------------------------------------

    @staticmethod
    def _purge_expired() -> None:
        now = time.monotonic()
        expired = [
            fid for fid, s in ToolForgeService._sessions.items()
            if now - s.created_at > _FORGE_TTL_SECONDS
        ]
        for fid in expired:
            ToolForgeService._sessions.pop(fid, None)

    @staticmethod
    async def _create_session(
        user_id: str,
        *,
        is_admin: bool,
        model_id: str,
        mode: str,
        tool_id: str,
    ) -> _ForgeSession:
        from agent_flow_harness import build_agent_graph, build_config
        from agent_flow_harness.interaction import ask_clarification

        from app.services.tool_generator import ToolGeneratorService

        llm = await ToolGeneratorService._build_llm(model_id)

        system = _SYSTEM_PROMPT
        if mode == "edit" and tool_id:
            doc = await UserToolService.get_tool(tool_id)
            if doc is None or (doc.get("owner_user_id") != user_id and not is_admin):
                raise UserToolError(f"Tool '{tool_id}' not found or not yours.")
            seed = {
                "name": doc.get("name", ""),
                "description": doc.get("description", ""),
                "source": doc.get("source", ""),
                "llm_args_schema": doc.get("llm_args_schema") or {},
                "user_args_schema": doc.get("user_args_schema") or {},
                "endpoint": doc.get("endpoint") or {},
                "code": doc.get("code", ""),
                "output_schema": doc.get("output_schema") or {},
                "tags": doc.get("tags") or [],
            }
            system += (
                "\n\n【编辑模式】当前已保存的工具定义（用户要修改它，"
                "修订以它为基准）：\n```json\n"
                + json.dumps(seed, ensure_ascii=False, indent=2)
                + "\n```"
            )

        forge_id = generate_id("forge")
        session = _ForgeSession(
            forge_id, user_id, is_admin, mode, tool_id, model_id, system
        )
        session.tools = _make_tools(session) + [ask_clarification]
        session.graph = build_agent_graph(
            session.agent_doc,
            checkpointer=MemorySaver(),
            middleware=[],
            tools=session.tools,
        )
        session.config = build_config(
            session.agent_doc,
            llm,
            tools=session.tools,
            thread_id=forge_id,
            recursion_limit=_RECURSION_LIMIT,
        )
        ToolForgeService._sessions[forge_id] = session
        return session

    # ------------------------------------------------------------------
    # 流式执行
    # ------------------------------------------------------------------

    @staticmethod
    async def stream(
        user_id: str,
        *,
        message: str,
        model_id: str = "",
        mode: str = "create",
        tool_id: str = "",
        forge_id: str = "",
        is_admin: bool = False,
    ) -> tuple[asyncio.Queue, str]:
        """发起/续接一轮工坊对话，返回 (SSE 队列, forge_id)。"""
        ToolForgeService._purge_expired()
        if forge_id:
            session = ToolForgeService._sessions.get(forge_id)
            if session is None:
                raise UserToolError("工坊会话不存在或已过期（进程重启/超时），请重新开始")
            # 模型热切换：会话模型在创建时固化，续接时前端下拉换了模型
            # （model_id 非空且不同）→ 重建 LLM 注入 config，避免「选 A 用 B」
            new_model = model_id.strip()
            if new_model and new_model != session.model_id:
                from app.services.tool_generator import ToolGeneratorService

                session.config["configurable"]["llm"] = (
                    await ToolGeneratorService._build_llm(new_model)
                )
                session.model_id = new_model
        else:
            if not message.strip():
                raise UserToolError("消息不能为空")
            session = await ToolForgeService._create_session(
                user_id, is_admin=is_admin, model_id=model_id, mode=mode, tool_id=tool_id
            )
        if session.busy:
            raise UserToolError("上一轮还在执行中，请稍候")
        if not message.strip():
            raise UserToolError("消息不能为空")

        session.busy = True
        messages: list = (
            [SystemMessage(content=session.system_prompt), HumanMessage(content=message)]
            if not session.started
            else [HumanMessage(content=message)]
        )
        session.started = True
        state: dict[str, Any] = {
            "messages": messages,
            "agent_id": session.agent_doc["_id"],
            "execution_path": "react",
            "request_id": generate_id("req"),
            "tool_results": {},
            "step_count": 0,
            "error": None,
            "call_chain": [],
            "current_depth": 0,
            "session_id": session.forge_id,
            "user_id": session.user_id,
        }
        queue: asyncio.Queue = asyncio.Queue()
        asyncio.create_task(ToolForgeService._run(session, state, queue))
        return queue, session.forge_id

    @staticmethod
    async def resume(forge_id: str, answer: dict | str) -> asyncio.Queue:
        """恢复被 ask_clarification 暂停的会话（凭证/澄清答复）。"""
        session = ToolForgeService._sessions.get(forge_id)
        if session is None:
            raise UserToolError("工坊会话不存在或已过期，请重新开始")
        if session.busy:
            raise UserToolError("上一轮还在执行中，请稍候")

        from langgraph.types import Command

        # fields 表单答复聚合成 dict → JSON 字符串（工具结果干净可读）
        resume_value: dict | str = (
            json.dumps(answer, ensure_ascii=False) if isinstance(answer, dict) else answer
        )
        session.busy = True
        queue: asyncio.Queue = asyncio.Queue()
        asyncio.create_task(
            ToolForgeService._run(session, Command(resume=resume_value), queue)
        )
        return queue

    @staticmethod
    async def _run(session: _ForgeSession, entry: Any, queue: asyncio.Queue) -> None:
        """驱动 graph 并把 AppEvent 转 SSE 帧；结束补 done 帧附草稿/保存态。"""
        from app.engine.harness_integration.adapters import (
            ErrorEvent,
            stream_events_to_app_events,
        )

        async def _emit(event: Any) -> None:
            payload = event.model_dump()
            # ErrorEvent 后端字段是 message，前端 StreamEvent 期望 content
            # （与 agents 执行链的 _on_event_dict 转换同口径）
            if payload.get("type") == "error":
                payload["content"] = payload.get("message", "")
            await queue.put(f"data: {json.dumps(payload, ensure_ascii=False)}\n\n")

        try:
            event_stream = session.graph.astream_events(entry, config=session.config, version="v2")
            await stream_events_to_app_events(event_stream, _emit)
        except Exception as exc:  # noqa: BLE001 —— 任何执行异常都以事件收尾，不裸奔 500
            logger.warning("tool_forge_run_failed", forge_id=session.forge_id, error=str(exc))
            # source 是 Literal["llm","tool","graph"]——工坊执行异常归 graph
            await _emit(ErrorEvent(message=str(exc)[:300], source="graph"))
        finally:
            await queue.put(
                f"data: {json.dumps({'done': True, 'forge_id': session.forge_id, 'draft': session.current_draft, 'saved_tool_id': session.saved_tool_id}, ensure_ascii=False)}\n\n"
            )
            await queue.put(None)
            session.busy = False

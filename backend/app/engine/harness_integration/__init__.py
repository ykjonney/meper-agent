"""应用层 ↔ harness Integration Adapter(骨架)。

本模块确立"应用层如何调用 harness"的模式,是 session→thread 迁移的接线层。
当前仅签名 + TODO + 示例注释,未实际接线——agents.py/sessions.py 仍走旧路径,
待迁移切换后启用本模块。

三层架构:
    ① API 层 (FastAPI)         app/api/v1/*          只懂 HTTP + 业务语义
    ② Integration Adapter 层   app/engine/harness_*  本模块:应用层世界 ↔ harness
    ③ harness                  agent_flow_harness    纯净,不认 app.*

应用层调 harness 的契约收敛为两件事:
    - 装配: resolve_*() 把应用层对象(Session/Agent/workspace/model table)
            变成 harness 注入物(llm/tools/agent_doc/checkpointer)
    - 调用: build_agent_graph / build_config / stream_events_to_app_events /
            messages_to_app_events

本模块分三类函数:装配注入物 / 执行 / 输出转换。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from agent_flow_harness.adapters.app_event import AppEvent
    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.tools import BaseTool


# ===========================================================================
# ① 装配注入物(应用层世界 → harness)
# ===========================================================================


async def resolve_llm(agent: dict, *, enable_thinking: bool = False) -> BaseChatModel:
    """查 model table + 解密 API key,构建 LLM 客户端。

    委托现有 ``app.engine.llm_factory.get_llm_client`` 完成 model-table 查找与解密,
    返回的 BaseChatModel 注入 harness 的 ``build_config(llm=...)``。
    """
    from app.engine.llm_factory import get_llm_client

    return await get_llm_client(agent, enable_thinking=enable_thinking)


def resolve_tools(agent: dict) -> list[BaseTool]:
    """从 backend Agent 文档解析 **backend-only 工具**(task 工具)。

    注意:此处只返回 backend 独有的工具(workflow_executor._TASK_TOOLS)。
    harness 的文件工具(bash/read/write/glob/grep)、Skill、MCP 工具由
    ``resolve_harness_context`` 统一装配,因为它们依赖 sandbox / contextvar
    注入,与 workspace 强相关。
    """
    from app.engine.agent.builder import _resolve_execution_context  # noqa: F401
    from app.engine.agent.workflow_executor import _TASK_TOOLS

    return list(_TASK_TOOLS)


def resolve_guards(agent_doc: dict) -> list:
    """从 agent_doc["guards"] 配置实例化 Guard 列表。

    agent 文档若未配置 guards,返回空列表(graph 不挂 guard 节点)。
    """
    from agent_flow_harness import resolve_guards as _resolve_guards

    return _resolve_guards(agent_doc.get("guards")) if agent_doc.get("guards") else []


def resolve_middleware(agent_doc: dict) -> list:
    """从 agent_doc["middleware"] 配置实例化 Middleware 列表。

    默认始终挂 ``UsageMiddleware``(token 统计);agent 文档的 middleware
    配置作为额外补充。
    """
    from agent_flow_harness import UsageMiddleware, resolve_middleware

    middlewares = [UsageMiddleware()]
    if agent_doc.get("middleware"):
        middlewares.extend(resolve_middleware(agent_doc["middleware"]))
    return middlewares


def get_checkpointer() -> Any:
    """构造 MongoDBSaver 并注入 harness 单例。

    复用 backend 现有的 ``app.engine.checkpointer.get_checkpointer``(已封装
    PyMongo client + db_name)。harness 的 ``build_agent_graph`` 接受任意
    LangGraph checkpointer(鸭子类型),因此直接传入即可。
    """
    from app.engine.checkpointer import get_checkpointer as _backend_get_checkpointer

    return _backend_get_checkpointer()


def build_agent_doc(agent: dict) -> dict:
    """组装 agent_doc(_id/name + slots/guards/middleware 配置)。

    从 backend Agent 文档提取 harness 需要的配置子集。
    """
    return {
        "_id": agent.get("_id", "agent"),
        "name": agent.get("name", "agent"),
        "prompt_slots": agent.get("prompt_slots", {}),
        "guards": agent.get("guards", []),
        "middleware": agent.get("middleware", []),
        "tools": agent.get("tools", []),
    }



# ===========================================================================
# ② 执行(调用 harness)
# ===========================================================================


# --- 核心装配:把 backend 的 LLM/工具/sandbox/workspace 合并成 harness 注入物 ---
# 以下装配逻辑抽取自原 stream.py:run_agent_streaming_harness 的内联实现,
# 供 stream / invoke / workflow agent 节点三条路径复用,避免重复。

# backend 工具名 → 需要被 harness 等价物替换的(bash/read/write 等)
_BACKEND_BUILTIN_TOOLS_TO_REPLACE = {
    "bash", "read", "write", "write_to_output", "load_skill",
}


async def resolve_harness_context(
    agent: dict,
    state: dict,
    *,
    enable_thinking: bool = False,
    workspace: Any | None = None,
) -> dict:
    """装配 harness 执行所需的全部注入物,返回 dict 供 graph + config 使用。

    合并三层工具策略:
      ① backend-only 工具(task/工作流工具) — 来自 workflow_executor._TASK_TOOLS
      ② harness 文件工具(bash/read/write/glob/grep) — 委托 Sandbox
      ③ Skill(load_skill)+ MCP — harness SkillManager / McpToolLoader

    同时构造 sandbox、workspace contextvar、agent_doc、middlewares。

    Args:
        workspace: 可选,workflow agent 节点传入已创建的 task workspace。
            为 None 时(默认,stream/invoke 路径)从 state 的 session_id/user_id
            自动创建 session workspace。

    Returns:
        dict 含 keys: agent_doc, llm, tools, sandbox, sb_token, ws_token,
              middlewares, context_window
    """
    from pathlib import Path

    from agent_flow_harness import (
        SkillManager,
        UsageMiddleware,
    )
    from agent_flow_harness.sandbox import (
        DockerSandbox,
        DockerSandboxConfig,
        SandboxContext,
        set_sandbox_context,
    )
    from agent_flow_harness.tools.builtin import BUILTIN_TOOLS

    from app.core.config import settings
    from app.engine.agent.builder import _resolve_execution_context
    from app.engine.agent.builtin_tools import set_workspace_context
    from app.engine.agent.react_executor import _setup_workspace_context

    # 1. 复用 backend 现有的 LLM + tools + context_window
    ctx = await _resolve_execution_context(agent, enable_thinking=enable_thinking)

    # 2. 工具替换:过滤 backend 的 bash/read/write/load_skill/mcp,加入 harness 的
    harness_file_tools = [
        BUILTIN_TOOLS[name]
        for name in ("bash", "read", "write", "glob", "grep")
        if name in BUILTIN_TOOLS
    ]
    backend_only_tools = [
        t for t in ctx.tools
        if getattr(t, "name", "") not in _BACKEND_BUILTIN_TOOLS_TO_REPLACE
        and not getattr(t, "name", "").startswith(("mcp__", "mcp_"))
    ]
    all_tools = backend_only_tools + harness_file_tools

    # 3. Skill:用 harness SkillManager 替换 backend 的 load_skill
    skills_dir = Path(settings.SKILLS_CONTAINER_DIR).expanduser()
    skill_mgr = SkillManager(
        skills_dir=skills_dir,
        base_path_prefix=settings.SANDBOX_CONTAINER_SKILLS_DIR if settings.SANDBOX_ENABLED else None,
    )
    from app.models.compat import resolve_skill_ids

    skill_ids = resolve_skill_ids(agent)
    if skill_ids:
        from app.services.tool_service import ToolService

        skill_docs = await ToolService.get_tools_by_ids(skill_ids)
        allowed_names = {d.get("name") for d in skill_docs if d.get("name")}
        if allowed_names:
            skill_mgr.set_allowed(allowed_names)
            all_tools.append(skill_mgr.make_load_tool())

    # 4. MCP:用 harness McpToolLoader 替换 backend 的 MCP 工具
    mcp_connection_ids = agent.get("mcp_connection_ids") or []
    if mcp_connection_ids:
        from agent_flow_harness import McpConnectionConfig, McpToolLoader

        from app.services.mcp_connection_service import McpConnectionService

        mcp_configs: list[McpConnectionConfig] = []
        for conn_id in mcp_connection_ids:
            conn_doc = await McpConnectionService.get_connection(conn_id)
            if conn_doc:
                mcp_configs.append(McpConnectionConfig(
                    name=conn_doc.get("name", conn_id),
                    url=conn_doc.get("url", ""),
                    protocol=conn_doc.get("protocol", "streamable-http"),
                    auth_type=conn_doc.get("auth_type", "none"),
                    auth_config=conn_doc.get("auth_config") or {},
                    timeout=conn_doc.get("timeout", 30),
                    default_params=conn_doc.get("default_params") or {},
                ))
        if mcp_configs:
            mcp_loader = McpToolLoader()
            mcp_tools = await mcp_loader.load_tools(mcp_configs)
            all_tools.extend(mcp_tools)

    # 5. 构造最小 agent_doc
    agent_doc = {
        "_id": agent.get("_id", "agent"),
        "name": agent.get("name", "agent"),
    }

    # 6. sandbox:用 backend 配置构造 harness DockerSandbox
    sandbox_config = DockerSandboxConfig(
        image=settings.SANDBOX_IMAGE,
        enabled=settings.SANDBOX_ENABLED,
        mem_limit=settings.SANDBOX_MEM_LIMIT,
        cpu_quota=settings.SANDBOX_CPU_QUOTA,
        timeout=settings.SANDBOX_TIMEOUT,
        max_output_bytes=settings.SANDBOX_MAX_OUTPUT_BYTES,
        network_mode=settings.SANDBOX_NETWORK_MODE,
        container_workspace_dir=settings.SANDBOX_CONTAINER_WORKSPACE_DIR,
        container_skills_dir=settings.SANDBOX_CONTAINER_SKILLS_DIR,
    )

    # 7. workspace(backend 的,用于 backend 工具的 contextvar + sandbox work_dir)
    #    workspace 优先级:显式传入(task workspace)> 从 state 自动建(session workspace)
    if workspace is not None:
        ws_token = set_workspace_context(workspace)
        work_dir = workspace.tmp_dir
        work_dir.mkdir(parents=True, exist_ok=True)
        sandbox_mounts = {
            "tmp": workspace.tmp_dir,
            "input": workspace.input_dir,
            "output": workspace.output_dir,
        }
        sandbox_id = f"{state.get('session_id') or workspace.root.name}"
    else:
        ws_token = _setup_workspace_context(state)
        session_id = state.get("session_id", "")
        user_id = state.get("user_id", "")
        work_dir = Path(settings.WORKSPACES_CONTAINER_DIR) / user_id / session_id / "tmp"
        work_dir.mkdir(parents=True, exist_ok=True)
        sandbox_mounts = {
            "tmp": work_dir,
            "input": Path(settings.WORKSPACES_CONTAINER_DIR) / user_id / session_id / "input",
            "output": Path(settings.WORKSPACES_CONTAINER_DIR) / user_id / session_id / "output",
        }
        sandbox_id = f"{session_id}"

    sandbox = DockerSandbox(
        sandbox_id=sandbox_id,
        work_dir=work_dir,
        mounts=sandbox_mounts,
        config=sandbox_config,
        timeout=settings.SANDBOX_TIMEOUT,
    )

    # 8. 注入 sandbox context(harness 的工具通过它委托 sandbox)
    sb_token = set_sandbox_context(SandboxContext(sandbox=sandbox))

    return {
        "agent_doc": agent_doc,
        "llm": ctx.llm,
        "tools": all_tools,
        "sb_token": sb_token,
        "ws_token": ws_token,
        "middlewares": [UsageMiddleware()],
        "context_window": ctx.context_window,
    }


def release_harness_context(hctx: dict) -> None:
    """释放 resolve_harness_context 持有的 contextvar token(在 finally 调用)。"""
    from agent_flow_harness.sandbox import reset_sandbox_context

    from app.engine.agent.builtin_tools import reset_workspace_context

    reset_sandbox_context(hctx["sb_token"])
    if hctx.get("ws_token") is not None:
        reset_workspace_context(hctx["ws_token"])


async def run_chat(
    agent: dict,
    state: dict,
    on_event,
    *,
    enable_thinking: bool = False,
) -> dict:
    """装配 + 执行 harness graph,通过 on_event 推送 AppEvent dict。

    替换 agents.py stream 端点的执行段。on_event 接收 **dict** 格式的 AppEvent
    (与老引擎一致,ErrorEvent 的 message 已重映射为 content)。

    Returns:
        含 step_count 的 dict(端点仅用于日志)。
    """
    from agent_flow_harness import build_agent_graph, build_config
    from agent_flow_harness.adapters import stream_events_to_app_events
    from agent_flow_harness.sandbox import reset_sandbox_context  # noqa: F401

    from app.engine.agent.builtin_tools import reset_workspace_context  # noqa: F401

    hctx = await resolve_harness_context(agent, state, enable_thinking=enable_thinking)
    try:
        session_id = state.get("session_id", "")
        # 端点每次请求已全量重建历史 messages 喂入 state(经 MessageService +
        # _history_to_langchain_messages),因此 graph 跑无状态模式(checkpointer=None)。
        # 若用进程级 checkpointer,它会按 thread_id=session_id 累积历史请求的
        # messages,与端点重建的历史叠加,产生重复/非连续 SystemMessage,触发
        # "Received multiple non-consecutive system messages" 错误。
        graph = build_agent_graph(hctx["agent_doc"], checkpointer=None)
        config = build_config(
            hctx["agent_doc"],
            hctx["llm"],
            tools=hctx["tools"],
            context_window=hctx["context_window"],
            middlewares=hctx["middlewares"],
            thread_id=session_id,
        )

        async def _on_event_dict(app_event: AppEvent) -> None:
            data = app_event.model_dump()
            # ErrorEvent 字段是 {message, source},前端契约用 {content},
            # 这里重映射使 harness 路径与老引擎一致(前端零改动)。
            if data.get("type") == "error":
                data["content"] = data.pop("message", "")
            await on_event(data)

        event_stream = graph.astream_events(state, config=config, version="v2")
        await stream_events_to_app_events(
            event_stream,
            _on_event_dict,
            enable_thinking=enable_thinking,
        )
    finally:
        release_harness_context(hctx)

    return {"step_count": 0}


async def run_once(
    agent: dict,
    state: dict,
    *,
    enable_thinking: bool = False,
    workspace: Any | None = None,
) -> dict:
    """非流式执行 harness graph(供 invoke 端点 / workflow agent 节点使用)。

    替换 ``build_agent_graph`` + ``graph.ainvoke`` 路径。

    Args:
        workspace: 可选,workflow agent 节点传入 task workspace。

    Returns:
        harness graph 执行后的最终 state(含 messages / step_count 等)。
    """
    from agent_flow_harness import build_agent_graph, build_config

    hctx = await resolve_harness_context(
        agent, state, enable_thinking=enable_thinking, workspace=workspace,
    )
    try:
        session_id = state.get("session_id", "")
        # 同 run_chat:端点全量喂历史,checkpointer=None 避免 thread 累积导致
        # 重复/非连续 SystemMessage。
        graph = build_agent_graph(hctx["agent_doc"], checkpointer=None)
        config = build_config(
            hctx["agent_doc"],
            hctx["llm"],
            tools=hctx["tools"],
            context_window=hctx["context_window"],
            middlewares=hctx["middlewares"],
            thread_id=session_id,
        )
        return await graph.ainvoke(state, config=config)
    finally:
        release_harness_context(hctx)


async def get_history(session_id: str) -> list[AppEvent]:
    """从 thread 读取历史 messages,转成 AppEvent 列表。

    [DEFERRED] 当前应用层历史仍由 MessageService + timeline_entries 重建,
    不依赖 harness thread。此函数保留供未来 checkpointer 收敛后启用。
    """
    raise NotImplementedError("get_history 暂缓实现(当前用 MessageService 重建历史)")


# ===========================================================================
# ③ 输出转换(harness → 应用层/前端)
# ===========================================================================


def app_event_to_timeline_entry(event: AppEvent) -> dict:
    """AppEvent → 前端 timeline_entries 形状(前端零改动的默认实现)。

    与现有 ``timeline_entries`` dict 兼容(前端 historyEntryToTimeline 直接消费)。
    tool_call_start / *_delta / error 在历史路径不出现(messages_to_app_events
    不产出这些瞬态事件)。
    """
    data = event.model_dump() if hasattr(event, "model_dump") else dict(event)
    t = data.get("type")
    if t == "tool_call":
        return {"type": "tool_call", "tool_name": data.get("tool_name"),
                "args": data.get("args", {}), "id": data.get("id", "")}
    if t == "tool_result":
        return {"type": "tool_result", "tool_name": data.get("tool_name"),
                "content": data.get("content", "")}
    if t == "final_answer":
        return {"type": "final_answer", "content": data.get("content", "")}
    if t == "thinking":
        return {"type": "thinking", "content": data.get("content", "")}
    # 兜底:原样返回
    return data


def app_events_to_message(
    events: list[AppEvent],
    *,
    role: str = "agent",
) -> dict:
    """AppEvent 列表 → MessageRecord 形状(兼容前端 historyToMessages)。

    把 events 经 app_event_to_timeline_entry 转成 timeline_entries,
    并提取最后一个 final_answer 的 content 作为消息正文。
    """
    timeline = [app_event_to_timeline_entry(e) for e in events]
    content = ""
    for e in reversed(events):
        data = e.model_dump() if hasattr(e, "model_dump") else dict(e)
        if data.get("type") == "final_answer":
            content = data.get("content", "")
            break
    return {"role": role, "content": content, "timeline_entries": timeline}



__all__ = [
    "app_event_to_timeline_entry",
    "app_events_to_message",
    "build_agent_doc",
    "get_checkpointer",
    "get_history",
    "release_harness_context",
    "resolve_guards",
    "resolve_harness_context",
    "resolve_llm",
    "resolve_middleware",
    "resolve_tools",
    "run_chat",
    "run_once",
]

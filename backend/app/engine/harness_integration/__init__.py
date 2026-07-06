"""应用层 ↔ harness Integration Adapter。

本模块是 session→thread 迁移的接线层,确立"应用层如何调用 harness"的模式。

三层架构:
    ① API 层 (FastAPI)         app/api/v1/*          只懂 HTTP + 业务语义
    ② Integration Adapter 层   app/engine/harness_*  本模块:应用层世界 ↔ harness
    ③ harness                  agent_flow_harness    纯净,不认 app.*

核心函数:
    - get_checkpointer:        返回 harness checkpointer 单例
    - resolve_harness_context: 装配 LLM/工具/sandbox/workspace 为 harness 注入物
    - release_harness_context: 释放 contextvar token
    - run_chat / run_once:     流式/非流式执行 harness graph
    - run_chat_resume:         恢复被 interrupt 挂起的 graph
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


def get_checkpointer() -> Any:
    """返回 harness 的 checkpointer 单例。

    harness 默认用 MemorySaver,应用层在 lifespan 启动时通过
    ``configure_checkpointer`` 覆盖为 MongoDBSaver。
    """
    from agent_flow_harness import get_checkpointer as _harness_get_checkpointer

    return _harness_get_checkpointer()


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
    # ask_clarification: agent 中途追问用户(interrupt),需要 checkpointer 支持
    if "ask_clarification" in BUILTIN_TOOLS:
        harness_file_tools.append(BUILTIN_TOOLS["ask_clarification"])
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


async def _maybe_migrate_legacy(graph, config, legacy_records: list[dict] | None) -> None:
    """灌入老session历史到 thread(仅当 MIGRATE_LEGACY_SESSIONS 且 thread 空)。

    老session的 MessageRecord 历史被重建为 LangChain messages 并写入 thread
    checkpoint。之后 thread 非空,后续请求走新路径(只喂增量)。
    """
    if not legacy_records:
        return
    from app.core.config import settings

    if not settings.MIGRATE_LEGACY_SESSIONS:
        return
    # 检查 thread 是否已有 checkpoint
    state = await graph.aget_state(config)
    if state.values:  # thread 非空,已迁移过
        return
    from app.engine.harness_integration.history import rebuild_messages_from_records

    rebuilt = await rebuild_messages_from_records(legacy_records)
    if rebuilt:
        await graph.aupdate_state(config, {"messages": rebuilt})


async def run_chat(
    agent: dict,
    state: dict,
    on_event,
    *,
    enable_thinking: bool = False,
    legacy_records: list[dict] | None = None,
) -> dict:
    """装配 + 执行 harness graph,通过 on_event 推送 AppEvent dict。

    替换 agents.py stream 端点的执行段。on_event 接收 **dict** 格式的 AppEvent
    (与老引擎一致,ErrorEvent 的 message 已重映射为 content)。

    Args:
        legacy_records: 老session的 MessageRecord 列表(可选)。当
            ``MIGRATE_LEGACY_SESSIONS=True`` 且 thread 为空时,首次灌入历史。

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
        graph = build_agent_graph(
            hctx["agent_doc"], checkpointer=get_checkpointer(),
            middleware=hctx["middlewares"], tools=hctx["tools"],
        )
        config = build_config(
            hctx["agent_doc"],
            hctx["llm"],
            tools=hctx["tools"],
            context_window=hctx["context_window"],
            middlewares=hctx["middlewares"],
            thread_id=session_id,
        )

        # 老session兼容:首次访问时灌入历史(thread 空才灌)
        await _maybe_migrate_legacy(graph, config, legacy_records)

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
    legacy_records: list[dict] | None = None,
) -> dict:
    """非流式执行 harness graph(供 invoke 端点 / workflow agent 节点使用)。

    替换 ``build_agent_graph`` + ``graph.ainvoke`` 路径。

    Args:
        workspace: 可选,workflow agent 节点传入 task workspace。
        legacy_records: 可选,老session历史(灌入 thread)。

    Returns:
        harness graph 执行后的最终 state(含 messages / step_count 等)。
    """
    from agent_flow_harness import build_agent_graph, build_config

    hctx = await resolve_harness_context(
        agent, state, enable_thinking=enable_thinking, workspace=workspace,
    )
    try:
        session_id = state.get("session_id", "")
        graph = build_agent_graph(
            hctx["agent_doc"], checkpointer=get_checkpointer(),
            middleware=hctx["middlewares"], tools=hctx["tools"],
        )
        config = build_config(
            hctx["agent_doc"],
            hctx["llm"],
            tools=hctx["tools"],
            context_window=hctx["context_window"],
            middlewares=hctx["middlewares"],
            thread_id=session_id,
        )
        await _maybe_migrate_legacy(graph, config, legacy_records)
        return await graph.ainvoke(state, config=config)
    finally:
        release_harness_context(hctx)


async def run_chat_resume(
    agent: dict,
    state: dict,
    on_event,
    answer: str,
    *,
    enable_thinking: bool = False,
) -> dict:
    """恢复被 interrupt 挂起的 graph,用 Command(resume=answer) 继续。

    与 run_chat 共享装配逻辑,但 astream_events 的输入是
    ``Command(resume=answer)`` 而非 state。
    """
    from langgraph.types import Command

    from agent_flow_harness import build_agent_graph, build_config
    from agent_flow_harness.adapters import stream_events_to_app_events

    hctx = await resolve_harness_context(agent, state, enable_thinking=enable_thinking)
    try:
        session_id = state.get("session_id", "")
        graph = build_agent_graph(
            hctx["agent_doc"], checkpointer=get_checkpointer(),
            middleware=hctx["middlewares"], tools=hctx["tools"],
        )
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
            if data.get("type") == "error":
                data["content"] = data.pop("message", "")
            await on_event(data)

        event_stream = graph.astream_events(
            Command(resume=answer), config=config, version="v2",
        )
        await stream_events_to_app_events(
            event_stream,
            _on_event_dict,
            enable_thinking=enable_thinking,
        )
    finally:
        release_harness_context(hctx)

    return {"step_count": 0}


__all__ = [
    "get_checkpointer",
    "release_harness_context",
    "resolve_harness_context",
    "run_chat",
    "run_chat_resume",
    "run_once",
]

"""harness 版 stream 执行 — 用 harness graph 替换老 react_executor。

特性开关 ``USE_HARNESS_ENGINE=True`` 时由 ``stream_agent`` 端点调用。

工具策略（三层模型落地）：
- bash/read/write/glob/grep：用 harness 的（委托 Sandbox），替换 backend 的 builtin
- Skill/MCP/Task 工具：继续用 backend 的（harness 暂无这些能力）
- sandbox：用 backend 的 DockerSandbox 配置（SANDBOX_ENABLED 等）构造 harness DockerSandbox

事件格式与老引擎完全一致（8 种 AppEvent），前端零改动。
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Awaitable, Callable

from loguru import logger

if TYPE_CHECKING:
    from agent_flow_harness.adapters.app_event import AppEvent

StreamCallback = Callable[[dict[str, Any]], Awaitable[None]]

# backend 工具名 → 需要过滤的（harness 有等价的）
_BACKEND_BUILTIN_TOOLS_TO_REPLACE = {
    "bash", "read", "write", "write_to_output", "load_skill",
}


async def run_agent_streaming_harness(
    agent: dict[str, Any],
    state: dict[str, Any],
    on_event: StreamCallback,
    enable_thinking: bool = False,
) -> dict[str, Any]:
    """用 harness graph 执行 REACT 循环，通过 on_event 推送 AppEvent dict。

    Args:
        agent: Agent 文档（from MongoDB）。
        state: 初始 AgentState（含 messages / session_id / user_id）。
        on_event: 异步回调，接收 **dict** 格式的 AppEvent（与老引擎一致）。
        enable_thinking: 是否启用 LLM 推理模式。

    Returns:
        含 step_count 的 dict（端点仅用于日志，不依赖返回值拿最终文本）。
    """
    from agent_flow_harness import (
        UsageMiddleware,
        build_agent_graph,
        build_config,
    )
    from agent_flow_harness.adapters import stream_events_to_app_events
    from agent_flow_harness.sandbox import (
        DockerSandbox,
        DockerSandboxConfig,
        SandboxContext,
        set_sandbox_context,
        reset_sandbox_context,
    )
    from agent_flow_harness.tools.builtin import BUILTIN_TOOLS

    from app.core.config import settings
    from app.engine.agent.builder import _resolve_execution_context
    from app.engine.agent.react_executor import _setup_workspace_context
    from app.engine.agent.builtin_tools import reset_workspace_context
    from app.engine.checkpointer import get_checkpointer

    # 1. 复用 backend 现有的 LLM + tools + context_window
    ctx = await _resolve_execution_context(agent, enable_thinking=enable_thinking)

    # 2. 工具替换：过滤 backend 的 bash/read/write/load_skill/mcp，加入 harness 的
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

    # 2b. Skill：用 harness SkillManager 替换 backend 的 load_skill
    from agent_flow_harness import SkillManager

    skills_dir = Path(settings.SKILLS_CONTAINER_DIR).expanduser()
    skill_mgr = SkillManager(
        skills_dir=skills_dir,
        base_path_prefix=settings.SANDBOX_CONTAINER_SKILLS_DIR if settings.SANDBOX_ENABLED else None,
    )
    # 白名单：从 agent 文档解析 skill 名称
    from app.models.compat import resolve_skill_ids
    skill_ids = resolve_skill_ids(agent)
    if skill_ids:
        from app.services.tool_service import ToolService
        skill_docs = await ToolService.get_tools_by_ids(skill_ids)
        allowed_names = {d.get("name") for d in skill_docs if d.get("name")}
        if allowed_names:
            skill_mgr.set_allowed(allowed_names)
            all_tools.append(skill_mgr.make_load_tool())

    # 2c. MCP：用 harness McpToolLoader 替换 backend 的 MCP 工具
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

    # 3. 构造最小 agent_doc
    agent_doc = {
        "_id": agent.get("_id", "agent"),
        "name": agent.get("name", "agent"),
    }

    # 4. sandbox：用 backend 配置构造 harness DockerSandbox
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

    # 5. workspace（backend 的，用于 backend 工具的 contextvar + sandbox work_dir）
    ws_token = _setup_workspace_context(state)

    # 从 state 拿 work_dir（sandbox 用 tmp_dir 作为工作目录）
    session_id = state.get("session_id", "")
    user_id = state.get("user_id", "")
    work_dir = Path(settings.WORKSPACES_CONTAINER_DIR) / user_id / session_id / "tmp"
    work_dir.mkdir(parents=True, exist_ok=True)

    sandbox = DockerSandbox(
        sandbox_id=f"{session_id}",
        work_dir=work_dir,
        mounts={
            "tmp": work_dir,
            "input": Path(settings.WORKSPACES_CONTAINER_DIR) / user_id / session_id / "input",
            "output": Path(settings.WORKSPACES_CONTAINER_DIR) / user_id / session_id / "output",
        },
        config=sandbox_config,
        timeout=settings.SANDBOX_TIMEOUT,
    )

    # 6. middleware + checkpointer
    middlewares = [UsageMiddleware()]
    try:
        checkpointer = get_checkpointer()
    except Exception:
        checkpointer = None

    # 7. harness graph + config
    graph = build_agent_graph(agent_doc, checkpointer=checkpointer)
    config = build_config(
        agent_doc,
        ctx.llm,
        tools=all_tools,
        context_window=ctx.context_window,
        middlewares=middlewares,
        thread_id=session_id,
    )

    # 8. 注入 sandbox context（harness 的工具通过它委托 sandbox）
    sb_token = set_sandbox_context(SandboxContext(sandbox=sandbox))
    try:
        # 9. adapter: AppEvent(pydantic) → dict
        async def _on_event_dict(app_event: "AppEvent") -> None:
            await on_event(app_event.model_dump())

        # 10. astream_events → AppEvent → on_event
        event_stream = graph.astream_events(state, config=config, version="v2")
        await stream_events_to_app_events(
            event_stream,
            _on_event_dict,
            enable_thinking=enable_thinking,
        )
    finally:
        reset_sandbox_context(sb_token)
        if ws_token is not None:
            reset_workspace_context(ws_token)

    logger.info(
        "harness_stream_completed",
        agent_id=agent.get("_id"),
        request_id=state.get("request_id"),
    )
    return {"step_count": 0}

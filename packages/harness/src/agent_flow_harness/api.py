"""create_agent 高层 API — 收敛 harness 调用入口。

把碎片化的 build/resolve/set 函数收敛成 create_agent(config, model) → agent.run()
线性体验。内部隐藏 build_graph/build_config/resolve_tools/set ContextVar 等全部
LangGraph 接线。底层 build_agent_graph/build_config 保留为 escape hatch。

设计见 docs/implementation-artifacts/create-agent-api.md。
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel
    from langgraph.checkpoint.base import BaseCheckpointSaver



class AgentConfig(BaseModel):
    """创建 Agent 的声明性配置（用户唯一配置入口）。

    model 不在此处（外部传入 create_agent）；checkpointer 是进程单例（另配）。
    sandbox/subagents 接收已构建实例（与 model 同性质，不可序列化）。
    """

    # —— 身份与提示 ——
    name: str = Field(default="agent", description="Agent 名字")
    system_prompt: str | None = Field(
        default=None, description="完整 system prompt（直接用作 SystemMessage）"
    )
    prompt_slots: dict[str, Any] | None = Field(
        default=None, description="6 段式 Slot 配置（优先于 system_prompt）"
    )

    # —— 工具（统一 dict 格式，三层来源）——
    tools: list[dict[str, Any]] = Field(
        default_factory=list,
        description="显式声明的工具 [{name, use?, enabled?, config?}]",
    )
    builtin_tools: list[str] | str | None = Field(
        default="all",
        description=(
            "内建工具便捷开关：'all' 全开(默认) / 工具名子集列表 / None 全关。"
            "用 exclude_tools 减去不需要的。"
        ),
    )
    exclude_tools: list[str] = Field(
        default_factory=list,
        description="要从 builtin_tools 中排除的工具名列表（配合 builtin_tools 用）",
    )

    # —— Guard / Middleware ——
    guards: list[dict[str, Any]] = Field(default_factory=list)
    middleware: list[dict[str, Any]] = Field(default_factory=list)

    # —— 运行参数 ——
    max_iterations: int = Field(default=25, ge=1, description="REACT 最大迭代数")
    context_window: int | None = Field(default=None, description="模型 context window")

    # —— 运行时依赖（实例，外部构建，类型宽松接收任意实例）——
    sandbox: Any = Field(default=None, description="第二层环境实例（Sandbox）")
    subagents: Any = Field(
        default=None, description="第一层委派 registry（SubAgentRegistry）"
    )

    model_config = ConfigDict(arbitrary_types_allowed=True)


def _config_to_doc(config: AgentConfig) -> dict[str, Any]:
    """把 AgentConfig 转成内部 agent_doc（build_agent_graph/build_config 用）。

    用户不接触 agent_doc——这是内部桥接。
    """
    doc: dict[str, Any] = {
        "_id": config.name,
        "name": config.name,
        "tools": config.tools,
    }
    if config.prompt_slots:
        doc["prompt_slots"] = config.prompt_slots
    if config.guards:
        doc["guards"] = config.guards
    if config.middleware:
        doc["middleware"] = config.middleware
    return doc


# ---------------------------------------------------------------------------
# create_agent + Agent（线性执行入口）
# ---------------------------------------------------------------------------


from langchain_core.messages import HumanMessage, SystemMessage  # noqa: E402

from agent_flow_harness.graph import build_agent_graph, build_config  # noqa: E402
from agent_flow_harness.middleware import resolve_middleware  # noqa: E402
from agent_flow_harness.tools.registry import TOOL_REGISTRY  # noqa: E402


def _resolve_tools(config: AgentConfig, agent_doc: dict[str, Any]) -> list[Any]:
    """解析工具：用户显式声明（经 registry）+ 内建工具（opt-out 展开）。

    内建工具直接从 BUILTIN_TOOLS 取实例（不经 registry，因为 registry 默认空），
    按 builtin_tools/exclude_tools 展开。用户显式 tools 经 TOOL_REGISTRY.resolve。
    """
    # 1. 用户显式声明的工具（含 use 字符串）
    user_tools = TOOL_REGISTRY.resolve(agent_doc)

    # 2. 内建工具（opt-out 展开）
    builtin = _expand_builtin(config)
    return user_tools + builtin


def _expand_builtin(config: AgentConfig) -> list[Any]:
    """按 builtin_tools/exclude_tools 展开内建工具实例列表。"""
    from agent_flow_harness.tools.builtin import BUILTIN_TOOLS

    if config.builtin_tools is None:
        return []

    # 确定要启用的内建工具名集合
    if config.builtin_tools == "all":
        names = set(BUILTIN_TOOLS.keys())
    else:
        names = set(config.builtin_tools) & set(BUILTIN_TOOLS.keys())

    # 减去 exclude
    names -= set(config.exclude_tools)

    # 按稳定顺序返回（BUILTIN_TOOLS 定义顺序）
    return [BUILTIN_TOOLS[n] for n in BUILTIN_TOOLS if n in names]


def create_agent(
    config: AgentConfig,
    model: "BaseChatModel",
    *,
    checkpointer: "BaseCheckpointSaver[Any] | None" = None,
    middlewares: list[Any] | None = None,
) -> "Agent":
    """从结构化配置创建可运行的 Agent。

    隐藏所有内部接线：构建 graph、resolve tools、配置 middleware、
    准备 ContextVar 注入。返回的 Agent 只需 run/stream。

    Args:
        config: Agent 声明性配置（含 middleware 声明式配置）。
        model: 已构建的 LLM（外部传入，harness 不碰密钥/连接）。
        checkpointer: 可选持久化（进程级，传 None 则 stateless）。
        middlewares: 可选，直接传入已实例化的 middleware 列表。
            用于需要持有实例引用的场景（如 UsageMiddleware.summary、
            TraceMiddleware(emit=callback)）。与 config.middleware 合并，
            实例追加在声明式之后。
    """
    agent_doc = _config_to_doc(config)
    graph = build_agent_graph(agent_doc, checkpointer=checkpointer)
    tools = _resolve_tools(config, agent_doc)
    resolved_mw = resolve_middleware(agent_doc.get("middleware"))
    if middlewares:
        resolved_mw = resolved_mw + list(middlewares)
    return Agent(
        config=config, model=model, graph=graph,
        tools=tools, middlewares=resolved_mw, agent_doc=agent_doc,
    )


class Agent:
    """create_agent 的产物，暴露线性 run/stream/get_history 接口。

    内部自动处理 build_config + set/reset ContextVar(sandbox/subagent) +
    system prompt 注入，用户无需手动调底层函数。
    """

    def __init__(
        self,
        *,
        config: AgentConfig,
        model: "BaseChatModel",
        graph: Any,
        tools: list[Any],
        middlewares: list[Any],
        agent_doc: dict[str, Any],
    ) -> None:
        self._config = config
        self._model = model
        self._graph = graph
        self._tools = tools
        self._middlewares = middlewares
        self._agent_doc = agent_doc

    @property
    def tool_names(self) -> list[str]:
        """已装配的工具名（调试用）。"""
        return [getattr(t, "name", "?") for t in self._tools]

    def _build_messages(self, input: str | list[Any], system_msg: SystemMessage | None) -> list[Any]:
        """构建 input messages：system prompt（若有）+ user input。"""
        if isinstance(input, str):
            messages: list[Any] = [HumanMessage(content=input)]
        else:
            messages = list(input)
        if system_msg is not None:
            messages.insert(0, system_msg)
        return messages

    async def _render_system_message(self) -> SystemMessage | None:
        """渲染 system prompt（prompt_slots 优先，否则 system_prompt）。"""
        if self._config.prompt_slots:
            from agent_flow_harness.slots import render_system_prompt_simple

            text = await render_system_prompt_simple(self._agent_doc)
            return SystemMessage(content=text) if text else None
        if self._config.system_prompt:
            return SystemMessage(content=self._config.system_prompt)
        return None

    def _set_contexts(self) -> list[tuple[Any, Any]]:
        """注入 sandbox/subagent ContextVar，返回 (reset_fn, token) 对。"""
        pairs: list[tuple[Any, Any]] = []
        if self._config.sandbox is not None:
            from agent_flow_harness.sandbox.context import (
                SandboxContext,
                reset_sandbox_context,
                set_sandbox_context,
            )
            token: Any = set_sandbox_context(SandboxContext(sandbox=self._config.sandbox))
            pairs.append((reset_sandbox_context, token))
        if self._config.subagents is not None:
            from agent_flow_harness.subagents.context import (
                SubAgentContext,
                reset_subagent_context,
                set_subagent_context,
            )
            token = set_subagent_context(SubAgentContext(
                registry=self._config.subagents,
                tool_registry=TOOL_REGISTRY,
                build_llm=lambda cfg: self._model,
                parent_llm=self._model,
            ))
            pairs.append((reset_subagent_context, token))
        return pairs

    def _reset_contexts(self, pairs: list[tuple[Any, Any]]) -> None:
        """逆序 reset ContextVar（用配对的 reset 函数，避免归属混淆）。"""
        for reset_fn, token in reversed(pairs):
            reset_fn(token)

    async def run(
        self,
        input: str | list[Any],
        *,
        thread_id: str | None = None,
        workspace: Any | None = None,
    ) -> str:
        """非流式执行，返回最终文本。"""
        from agent_flow_harness.subagents.delegate import extract_final_text

        sys_msg = await self._render_system_message()
        messages = self._build_messages(input, sys_msg)
        state: dict[str, Any] = {"messages": messages}
        config = build_config(
            self._agent_doc, self._model,
            tools=self._tools, middlewares=self._middlewares,
            thread_id=thread_id, context_window=self._config.context_window,
            workspace=workspace,
        )
        pairs = self._set_contexts()
        try:
            result = await self._graph.ainvoke(state, config=config)
            return extract_final_text(result.get("messages", []))
        finally:
            self._reset_contexts(pairs)

    async def stream(
        self,
        input: str | list[Any],
        *,
        thread_id: str | None = None,
        workspace: Any | None = None,
        on_event: Any | None = None,
    ) -> None:
        """流式执行，通过 on_event 回调推送 AppEvent。

        on_event 是 async 回调：``async def on_event(event: AppEvent) -> None``。
        """
        from agent_flow_harness.adapters import stream_events_to_app_events

        sys_msg = await self._render_system_message()
        messages = self._build_messages(input, sys_msg)
        state: dict[str, Any] = {"messages": messages}
        config = build_config(
            self._agent_doc, self._model,
            tools=self._tools, middlewares=self._middlewares,
            thread_id=thread_id, context_window=self._config.context_window,
            workspace=workspace,
        )
        if on_event is None:
            on_event = _noop_event

        pairs = self._set_contexts()
        try:
            event_stream = self._graph.astream_events(state, config=config, version="v2")
            # AppEvent(pydantic) → dict，保持 on_event 回调与 backend 一致
            async def _on_event_dict(app_event: Any) -> None:
                await on_event(app_event.model_dump())
            await stream_events_to_app_events(event_stream, _on_event_dict)
        finally:
            self._reset_contexts(pairs)

    async def get_history(self, thread_id: str) -> list[Any]:
        """读取 thread 历史消息，返回 AppEvent 列表。"""
        from agent_flow_harness.adapters import messages_to_app_events
        from agent_flow_harness.graph import get_thread_messages

        messages = await get_thread_messages(self._graph, thread_id)
        return messages_to_app_events(messages)


async def _noop_event(_event: Any) -> None:
    """默认空回调（stream 未传 on_event 时用）。"""
    return None


__all__ = ["AgentConfig", "Agent", "create_agent"]

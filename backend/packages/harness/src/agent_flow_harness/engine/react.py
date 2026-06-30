"""REACT reasoning node — the single LangGraph entry point.

Story v0.1-2 collapses the legacy ``react_executor.run`` +
``_run_react_inner`` into one node, :func:`react_node`, driven by the
LangGraph ``StateGraph``. Behaviour is preserved verbatim (depth guard,
context compression, 25-iteration cap, tool execution, step counting) so
the application layer observes the same input/output contract.

Key v0.1-2 decisions (see Story Dev Notes):

* The node reads ``llm`` / ``tools`` / ``context_window`` / ``workspace``
  from ``config["configurable"]`` — never from global state — so the LLM
  object (non-serialisable) stays out of the checkpointer.
* The node does **not** stream or push SSE events. Token-level streaming is
  delivered by the v0.1-3 ``astream_events`` adapter; this node only calls
  ``ainvoke`` and returns a state patch.
* Workspace setup uses the harness context-var (``set_workspace_context``),
  reading a host-supplied workspace object from ``configurable``. The harness
  never imports the concrete backend ``WorkspaceManager``.
"""

from __future__ import annotations

import contextvars
from typing import TYPE_CHECKING, Any, cast

import structlog
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import StructuredTool
from langgraph.errors import GraphInterrupt

from agent_flow_harness.engine.context import (
    compress_messages,
    extract_model_name,
    should_compress,
)
from agent_flow_harness.engine.depth_guard import check_depth
from agent_flow_harness.middleware.chain import MiddlewareChain
from agent_flow_harness.state import AgentState
from agent_flow_harness.tools.workspace_context import (
    WorkspaceProtocol,
    reset_workspace_context,
    set_workspace_context,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from langchain_core.language_models.chat_models import BaseChatModel
    from langchain_core.runnables import RunnableConfig

logger = structlog.get_logger(__name__)

_MAX_ITERATIONS = 25
"""Hard cap on REACT iterations, matching the legacy executor."""


async def react_node(state: AgentState, config: RunnableConfig) -> dict[str, Any]:
    """Single REACT entry point (v0.1-2).

    Args:
        state: Current :class:`AgentState`.
        config: LangGraph runnable config. ``config["configurable"]`` must
            provide ``llm`` and ``tools`` (a list / dict of StructuredTool);
            ``context_window`` and ``workspace`` are optional.

    Returns:
        A state patch with accumulated ``messages`` and incremented
        ``step_count``. On a depth / cycle guard trip, ``error`` is set and the
        loop short-circuits.
    """
    configurable = _configurable(config)
    llm = configurable["llm"]
    tools = configurable.get("tools") or []
    context_window = configurable.get("context_window")
    workspace = configurable.get("workspace")
    context_strategy = configurable.get("context_strategy")
    chain = MiddlewareChain(configurable.get("middlewares") or [])

    ws_token = _setup_workspace_context(workspace, state)
    try:
        return await _run_react_inner(
            state, llm, tools, context_window, chain, context_strategy
        )
    finally:
        if ws_token is not None:
            reset_workspace_context(ws_token)


async def _run_react_inner(
    state: AgentState,
    llm: BaseChatModel,
    tools: Sequence[Any],
    context_window: int | None,
    chain: MiddlewareChain,
    context_strategy: Any = None,
) -> dict[str, Any]:
    """Inner REACT loop — workspace context is already set by the caller."""
    current_messages: list[Any] = list(state.get("messages", []))
    step_count: int = state.get("step_count", 0) or 0
    request_id = state.get("request_id")

    tool_map = _build_tool_map(tools)
    llm_with_tools = llm.bind_tools(list(tool_map.values())) if tool_map else llm
    model_name = extract_model_name(llm)

    for iteration in range(_MAX_ITERATIONS):
        # 1. Depth & cycle guard — terminate early when limits are exceeded.
        depth_result = check_depth(state)
        if not depth_result.allowed:
            log_event = (
                "circular_call_detected"
                if depth_result.cycle is not None
                else "depth_limit_exceeded"
            )
            logger.warning(
                log_event,
                agent_id=state.get("agent_id"),
                request_id=request_id,
                current_depth=depth_result.current_depth,
                max_depth=depth_result.max_depth,
                call_chain=state.get("call_chain", []),
                reason=depth_result.reason,
                cycle=depth_result.cycle,
            )
            return {
                "messages": current_messages,
                "step_count": step_count,
                "error": depth_result.reason,
            }

        # 2. Compress if approaching the model's context window limit.
        if context_strategy is not None:
            # v0.2-5: 可插拔 ContextStrategy（优先于 v0.1 compress_messages）
            before = len(current_messages)
            current_messages = await context_strategy.select(
                current_messages, max_tokens=context_window or 128000
            )
            if len(current_messages) < before:
                logger.info(
                    "react_context_compressed",
                    strategy=context_strategy.name,
                    agent_id=state.get("agent_id"),
                    request_id=request_id,
                    iteration=iteration,
                    before=before,
                    after=len(current_messages),
                )
        elif should_compress(current_messages, model_name, context_window=context_window):
            before = len(current_messages)
            current_messages = compress_messages(
                current_messages, model_name, context_window=context_window
            )
            logger.info(
                "react_context_compressed",
                agent_id=state.get("agent_id"),
                request_id=request_id,
                iteration=iteration,
                before=before,
                after=len(current_messages),
            )

        # 3. LLM call (middleware may rewrite the outgoing messages).
        call_state: AgentState = cast(
            "AgentState", {**state, "messages": current_messages}
        )
        call_state = await chain.run_before_llm(call_state)
        response: AIMessage = await llm_with_tools.ainvoke(call_state["messages"])
        step_count += 1
        await chain.run_after_llm(
            cast("AgentState", {**call_state, "step_count": step_count}), response
        )

        # 4. No tool calls → final answer.
        if not _has_tool_calls(response):
            logger.info(
                "react_node_completed",
                agent_id=state.get("agent_id"),
                request_id=request_id,
                iteration=iteration,
            )
            current_messages.append(response)
            return _build_result(current_messages, step_count)

        # 5. Tool-call round — persist the AIMessage, then run every tool.
        current_messages.append(response)
        for tc_raw in response.tool_calls:
            tc: dict[str, Any] = cast("dict[str, Any]", tc_raw)
            tc = await chain.run_before_tool(state, tc)
            tool_name = tc.get("name", "")
            tool_args = tc.get("args", {})
            tool_call_id = tc.get("id", f"call_{iteration}_{tool_name}")

            tool_fn = tool_map.get(tool_name)
            if tool_fn is None:
                logger.warning(
                    "react_node_tool_not_found",
                    tool_name=tool_name,
                    request_id=request_id,
                )
                result_content = f"Error: tool '{tool_name}' not found."
            else:
                try:
                    result_content = await _execute_tool(tool_fn, tool_args)
                except GraphInterrupt:
                    # HITL: let GraphInterrupt propagate so the graph suspends.
                    # It is an Exception subclass, so it must be re-raised
                    # before the broad ``except Exception`` below, otherwise it
                    # would be swallowed as a tool error (v0.2-x prerequisite).
                    raise
                except Exception as exc:
                    logger.error(
                        "react_node_tool_error",
                        tool_name=tool_name,
                        error=str(exc),
                        request_id=request_id,
                    )
                    result_content = f"Error executing tool '{tool_name}': {exc}"

            current_messages.append(
                ToolMessage(content=str(result_content), tool_call_id=tool_call_id)
            )
            await chain.run_after_tool(state, tc, str(result_content))
        # Loop continues so the LLM can observe the tool results.

    # 6. Max iterations reached without a final text response.
    logger.warning(
        "react_node_max_iterations",
        max_iterations=_MAX_ITERATIONS,
        request_id=request_id,
    )
    return _build_result(current_messages, step_count)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _configurable(config: RunnableConfig | None) -> dict[str, Any]:
    """Return ``config["configurable"]`` as a dict, raising a clear error."""
    if config is None:
        msg = "react_node requires a RunnableConfig with a 'configurable' mapping."
        raise ValueError(msg)
    configurable = config.get("configurable") if isinstance(config, dict) else None
    if not isinstance(configurable, dict):
        msg = "react_node requires config['configurable'] to be a mapping."
        raise ValueError(msg)
    if "llm" not in configurable:
        msg = "react_node requires config['configurable']['llm']."
        raise ValueError(msg)
    return configurable


def _setup_workspace_context(
    workspace: WorkspaceProtocol | None,
    state: AgentState,
) -> contextvars.Token[Any] | None:
    """Bind ``workspace`` to the current async task, returning a reset token.

    Returns ``None`` when no workspace is available (non-isolated tools).
    The harness never constructs the workspace; the host injects it.
    """
    if workspace is None:
        return None
    try:
        return set_workspace_context(workspace)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("workspace_context_setup_failed", error=str(exc))
        return None


def _build_tool_map(tools: Sequence[Any]) -> dict[str, StructuredTool]:
    """Convert a sequence of tools into a ``name -> StructuredTool`` map.

    Accepts both a list of tools and a pre-built mapping (the application
    layer may hand in either shape).
    """
    if isinstance(tools, dict):
        return dict(tools)
    return {fn.name: fn for fn in tools if isinstance(fn, StructuredTool)}


def _has_tool_calls(response: AIMessage) -> bool:
    """Return True when the AIMessage carries at least one tool call."""
    return bool(getattr(response, "tool_calls", None))


async def _execute_tool(tool_fn: StructuredTool, args: dict[str, Any]) -> str:
    """Invoke *tool_fn* with *args*; supports sync and async tools.

    Handles ``response_format="content_and_artifact"`` tools (used by
    ``langchain_mcp_adapters``) which return ``(content_list, artifact)``
    tuples instead of plain strings.
    """
    if hasattr(tool_fn, "ainvoke"):
        result = await tool_fn.ainvoke(args)
    else:
        result = tool_fn.invoke(args)

    if getattr(tool_fn, "response_format", "") == "content_and_artifact":
        return _extract_content_artifact_text(result)

    return str(result)


def _extract_content_artifact_text(result: Any) -> str:
    """Extract text from a ``(content_list, artifact)`` tuple."""
    content, _ = result
    if not isinstance(content, list):
        return str(content)

    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            parts.append(block.get("text", ""))
        else:
            parts.append(str(block))
    return "\n".join(parts)


def _build_result(messages: list[Any], step_count: int) -> dict[str, Any]:
    """Build the LangGraph state patch returned by the node.

    Only the keys the node owns are returned so LangGraph merges them onto the
    incoming state (``messages`` uses the ``add_messages`` reducer).
    """
    return {"messages": messages, "step_count": step_count}


# Public symbol kept for back-compat with the A.1 stub import path.
__all__ = ["react_node"]

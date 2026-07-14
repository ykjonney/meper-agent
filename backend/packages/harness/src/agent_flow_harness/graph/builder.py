"""StateGraph construction — node-based agent graph.

Topology (v0.3 — node-based, replacing the monolithic react_node for-loop)::

    [guard_in*] → compress → llm ──┐
                       ↑            │ tools_condition
                       │            ├─ has tool_calls → tools (native ToolNode)
                       └────────────┘                    │
                                                         │ (fixed edge)
                                                         └─→ compress (next loop)
                                ├─ no tool_calls → [guard_out*] → END
                                └─ error / depth-limit → END

Each step of the former ``react_node`` inner loop is now an independent node
wired by LangGraph edges:

* ``compress`` — context-window compression (runs before every LLM call).
* ``llm`` — single LLM invocation (binds tools, runs middleware hooks).
* ``tools`` — native ``langgraph.prebuilt.ToolNode`` (concurrent execution,
  error handling, middleware via ``awrap_tool_call``).

Routing uses the native ``tools_condition`` conditional edge. Iteration cap is
enforced by the graph's ``recursion_limit`` (default in ``build_config``).

Guards are resolved from ``agent_doc["guards"]`` unless an explicit
``guards=`` list is passed. A ``Block`` from any guard sets ``state["error"]``
and LangGraph terminates the branch naturally; a ``Warn`` appends to
``state["warnings"]`` without blocking.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.errors import GraphBubbleUp
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode, tools_condition

from agent_flow_harness.graph.nodes import compress_node, llm_node, make_tool_wrapper
from agent_flow_harness.guards import resolve_guards
from agent_flow_harness.guards.nodes import make_guard_in_node
from agent_flow_harness.middleware.chain import MiddlewareChain
from agent_flow_harness.state import AgentState
from agent_flow_harness.tools.registry import TOOL_REGISTRY, ToolRegistry

if TYPE_CHECKING:
    from collections.abc import Sequence

    from agent_flow_harness.guards.base import Guard
    from agent_flow_harness.middleware.base import Middleware


def build_agent_graph(
    agent_doc: dict[str, Any],
    *,
    checkpointer: BaseCheckpointSaver[Any] | None = None,
    guards: Sequence[Guard] | None = None,
    middleware: Sequence[Middleware] | None = None,
    tools: Any | None = None,
    registry: ToolRegistry | None = None,
) -> CompiledStateGraph[Any, Any, Any, Any]:
    """Build and compile the node-based agent :class:`StateGraph`.

    Args:
        agent_doc: Agent configuration document. ``agent_doc["guards"]`` /
            ``agent_doc["middleware"]`` are resolved unless the matching
            keyword is given.
        checkpointer: Optional checkpoint saver. Node-based graphs rely on
            graph-level state passing between nodes; a checkpointer is
            recommended for interrupt support and thread persistence.
        guards: Explicit Guard instances; takes priority over
            ``agent_doc["guards"]``. ``None``/empty → no guard nodes.
        middleware: Explicit Middleware instances; takes priority over
            ``agent_doc["middleware"]``. Passed to the LLM node and wrapped
            into the ToolNode.
        tools: Pre-resolved tool list/dict. When ``None`` the registry
            resolves them from ``agent_doc``.
        registry: Registry to resolve tools from (defaults to global).

    Returns:
        A compiled graph.
    """
    # Resolve guards.
    resolved_guards = list(guards) if guards is not None else resolve_guards(
        agent_doc.get("guards"),
    )

    # Resolve middleware into a chain (for the ToolNode wrapper).
    mw_list = list(middleware) if middleware is not None else []
    chain = MiddlewareChain(mw_list)

    # Resolve tools.
    if tools is None:
        reg = registry if registry is not None else TOOL_REGISTRY
        tool_seq = reg.resolve(agent_doc)
    else:
        tool_seq = list(tools.values()) if isinstance(tools, dict) else list(tools)

    builder: StateGraph[Any, Any, Any, Any] = StateGraph(AgentState)

    # ── Core nodes ──────────────────────────────────────────────────────
    builder.add_node("compress", compress_node)
    builder.add_node("llm", llm_node)

    # Native ToolNode with middleware wrapper.
    # Custom error handler: re-raise GraphBubbleUp (from interrupt()) so it
    # propagates to the graph executor instead of becoming an error ToolMessage.
    def _tool_error_handler(exc: Exception) -> str:
        if isinstance(exc, GraphBubbleUp):
            raise exc
        return f"Error: {exc!r}\n Please fix your mistakes."

    tool_node = ToolNode(
        tool_seq,
        name="tools",
        awrap_tool_call=make_tool_wrapper(chain),
        handle_tool_errors=_tool_error_handler,
    )
    builder.add_node("tools", tool_node)

    # ── Edges: compress → llm → (tools_condition) ───────────────────────
    builder.add_edge("compress", "llm")
    # tools_condition returns "tools" or END; route accordingly.
    builder.add_conditional_edges(
        "llm",
        tools_condition,
        {"tools": "tools", END: END},
    )
    # After tools, loop back to compress for the next iteration.
    builder.add_edge("tools", "compress")

    # ── Guards (optional, splice before the core) ───────────────────────
    if not resolved_guards:
        # No guards: entry → compress.
        builder.add_edge(START, "compress")
    else:
        in_names: list[str] = []
        for guard in resolved_guards:
            in_name = f"guard_in_{guard.name}"
            builder.add_node(in_name, make_guard_in_node(guard))
            in_names.append(in_name)

        # entry → guard_in[0] → ... → guard_in[-1] → compress
        builder.add_edge(START, in_names[0])
        for a, b in zip(in_names, in_names[1:], strict=False):
            builder.add_edge(a, b)
        builder.add_edge(in_names[-1], "compress")

        # NOTE: guard_out (post-execution checks) are not wired in v0.3.
        # The native tools_condition routes "no tool calls" straight to END,
        # leaving no intermediate node for guard_out. Supporting post-guard
        # requires a custom conditional-edge function that routes to a
        # guard_out chain instead of END. Will be added when a post-guard
        # use case arises.

    return builder.compile(checkpointer=checkpointer)


__all__ = ["build_agent_graph"]

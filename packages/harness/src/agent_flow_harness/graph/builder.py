"""StateGraph construction.

Topology:

* v0.1-1/2 (no guards): ``react -> END``.
* v0.1-4 (with guards): ``[g1_in, g2_in, ...] -> react -> [g1_out, g2_out, ...] -> END``.

Guards are resolved from ``agent_doc["guards"]`` config specs unless an explicit
``guards=`` list of :class:`~agent_flow_harness.guards.base.Guard` instances is
passed. A ``Block`` from any guard sets ``state["error"]`` and LangGraph
terminates the branch naturally; a ``Warn`` appends to ``state["warnings"]``
without blocking.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from agent_flow_harness.engine.react import react_node
from agent_flow_harness.guards import resolve_guards
from agent_flow_harness.guards.nodes import make_guard_in_node, make_guard_out_node
from agent_flow_harness.state import AgentState

if TYPE_CHECKING:
    from collections.abc import Sequence

    from agent_flow_harness.guards.base import Guard
    from agent_flow_harness.middleware.base import Middleware


def build_agent_graph(
    agent_doc: dict[str, Any],
    *,
    checkpointer: BaseCheckpointSaver | None = None,
    guards: Sequence[Guard] | None = None,
    middleware: Sequence[Middleware] | None = None,
) -> CompiledStateGraph:
    """Build and compile the agent :class:`StateGraph`.

    Args:
        agent_doc: Agent configuration document. ``agent_doc["guards"]`` /
            ``agent_doc["middleware"]`` are resolved unless the matching
            keyword is given.
        checkpointer: Optional checkpoint saver (``None`` → stateless).
        guards: Explicit Guard instances; takes priority over
            ``agent_doc["guards"]``. ``None``/empty → plain ``react -> END``.
        middleware: Explicit Middleware instances; takes priority over
            ``agent_doc["middleware"]``. Middlewares are *not* graph nodes —
            the host injects them via ``config["configurable"]["middlewares"]``
            (see :func:`agent_flow_harness.graph.build_config`).

    Returns:
        A compiled graph.
    """
    _ = middleware  # middlewares flow via configurable, not the graph topology

    resolved = list(guards) if guards is not None else resolve_guards(agent_doc.get("guards"))

    builder: StateGraph = StateGraph(AgentState)
    builder.add_node("react", react_node)

    if not resolved:
        builder.set_entry_point("react")
        builder.add_edge("react", END)
        return builder.compile(checkpointer=checkpointer)

    # Register guard nodes.
    in_names: list[str] = []
    out_names: list[str] = []
    for guard in resolved:
        in_name = f"guard_in_{guard.name}"
        out_name = f"guard_out_{guard.name}"
        builder.add_node(in_name, make_guard_in_node(guard))
        builder.add_node(out_name, make_guard_out_node(guard))
        in_names.append(in_name)
        out_names.append(out_name)

    # Chain: entry -> in[0] -> ... -> in[-1] -> react
    builder.set_entry_point(in_names[0])
    for a, b in zip(in_names, in_names[1:], strict=False):
        builder.add_edge(a, b)
    builder.add_edge(in_names[-1], "react")

    # Chain: react -> out[0] -> ... -> out[-1] -> END
    builder.add_edge("react", out_names[0])
    for a, b in zip(out_names, out_names[1:], strict=False):
        builder.add_edge(a, b)
    builder.add_edge(out_names[-1], END)

    return builder.compile(checkpointer=checkpointer)

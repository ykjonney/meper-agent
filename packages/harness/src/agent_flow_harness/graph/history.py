"""Thread history reading — checkpoint state inspection.

Thin wrappers around LangGraph's ``CompiledStateGraph`` state-read API. These
are the **read** counterpart to :func:`~agent_flow_harness.graph.runner.run_agent`:
they let the application recover a thread's persisted messages (e.g. to
rebuild a chat history) without re-executing the graph.

The harness never constructs the checkpointer; it only requires that the graph
was compiled with one. The ``thread_id`` is an opaque string the application
chooses (typically ``session_id``).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.messages import BaseMessage
    from langgraph.graph.state import CompiledStateGraph


async def get_thread_messages(
    graph: CompiledStateGraph,
    thread_id: str,
) -> list[BaseMessage]:
    """Return the ``messages`` from a thread's latest checkpoint state.

    Args:
        graph: A compiled graph. When it was built without a checkpointer the
            function returns ``[]`` (there is no persisted state to read).
        thread_id: The thread identifier (opaque; applications typically use
            ``session_id``).

    Returns:
        The persisted messages list, or ``[]`` if the thread has no state or
        the graph has no checkpointer.
    """
    try:
        state = await graph.aget_state({"configurable": {"thread_id": thread_id}})
    except (ValueError, LookupError):
        # No checkpointer wired into the graph — nothing to read.
        return []
    if state is None or not state.values:
        return []
    messages = state.values.get("messages", [])
    return list(messages) if messages else []


__all__ = ["get_thread_messages"]

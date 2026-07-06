"""Middleware bridge for the native ``langgraph.prebuilt.ToolNode``.

``ToolNode`` accepts an ``awrap_tool_call`` interceptor that receives every
tool call before execution. This module builds such an interceptor from a
harness :class:`~agent_flow_harness.middleware.chain.MiddlewareChain`, wiring
the ``run_before_tool`` / ``run_after_tool`` hooks without giving up the
native node's error handling, concurrency, and command support.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog
from langchain_core.messages import ToolMessage

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from langgraph.prebuilt.tool_node import ToolCallRequest
    from langgraph.types import Command

    from agent_flow_harness.middleware.chain import MiddlewareChain

# Command is generic in langgraph 1.x; use a type alias without parameters
# for the wrapper's return type annotations (mypy compatible).
_Command = "Command[Any]"

logger = structlog.get_logger(__name__)


def make_tool_wrapper(
    chain: MiddlewareChain,
) -> Callable[
    [ToolCallRequest, Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]]],  # noqa: UP006
    Awaitable[ToolMessage | Command],  # noqa: UP006
]:
    """Create an ``awrap_tool_call`` that runs middleware around tool execution.

    Args:
        chain: The middleware chain whose ``run_before_tool`` /
            ``run_after_tool`` hooks should fire on each tool call.

    Returns:
        An async wrapper compatible with ``ToolNode(awrap_tool_call=...)``.
    """

    async def awrap(
        request: ToolCallRequest,
        execute: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],  # noqa: UP006
    ) -> ToolMessage | Command:
        state: Any = request.state
        tc: dict[str, Any] = dict(request.tool_call)

        # before_tool — middleware may observe / modify the call args.
        tc = await chain.run_before_tool(state, tc)

        # Re-inject any middleware modifications into the request.
        modified = request.override(tool_call=tc)  # type: ignore[arg-type]

        # Execute via the native ToolNode (handles errors, concurrency).
        result = await execute(modified)

        # after_tool — middleware observes the result content.
        result_content = result.content if isinstance(result, ToolMessage) else ""
        await chain.run_after_tool(state, tc, str(result_content))

        return result

    return awrap


__all__ = ["make_tool_wrapper"]

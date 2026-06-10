"""Planner executor — plan → execute → verify loop for complex tasks.

The planner executor implements three phases:

1. **Plan**: The LLM creates a structured execution plan outlining the
   steps needed to fulfil the user's request.
2. **Execute**: Each plan step is carried out via a REACT-style loop
   (Reasoning + Acting with tool calling).
3. **Verify**: The LLM reviews the collected results against the
   original request and produces a verified final answer.
"""
from __future__ import annotations

from collections.abc import Callable

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.tools import StructuredTool
from loguru import logger

from app.engine.state import AgentState

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_PLAN_SYSTEM_PROMPT = """\
You are a meticulous planning agent.  Given the user's request, produce a
concise structured plan with numbered steps.  Each step should state what
action to take and which tool (if any) to use.

Format:
## Plan
1. Step one — description [tool: tool_name_if_needed]
2. Step two — description [tool: tool_name_if_needed]
..."""

_VERIFY_SYSTEM_PROMPT = """\
You are a thorough verification agent.  Review the execution results
against the original request and determine whether the task is complete
and correct.

- If satisfactory → summarise the final answer for the user.
- If incomplete → explain what is missing and what additional steps are
  required.
"""

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_EXECUTION_STEPS = 25


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def run(
    state: AgentState,
    llm: BaseChatModel,
    tools: list[Callable],
) -> dict:
    """Execute the Agent in planner mode (plan → execute → verify).

    Args:
        state: Current AgentState with messages to process.
        llm: Configured LangChain chat model instance.
        tools: List of callables available for execution.

    Returns:
        Updated state with plan, execution results, and verified answer.
    """
    messages = state.get("messages", [])
    step_count = state.get("step_count", 0)
    tool_map = _build_tool_map(tools)
    request_id = state.get("request_id")

    current_messages = list(messages)

    # ── Phase 1: Plan ────────────────────────────────────────────────
    plan_response = await llm.ainvoke(
        [SystemMessage(content=_PLAN_SYSTEM_PROMPT), *current_messages],
    )
    step_count += 1
    current_messages.append(plan_response)

    logger.bind(
        agent_id=state.get("agent_id"),
        request_id=request_id,
    ).info("planner_plan_completed")

    # ── Phase 2: Execute (REACT loop) ────────────────────────────────
    for iteration in range(_MAX_EXECUTION_STEPS):
        response = await llm.ainvoke(current_messages)
        step_count += 1

        if not _has_tool_calls(response):
            current_messages.append(response)
            break

        current_messages.append(response)
        _execute_tool_calls(response, tool_map, current_messages, iteration)

    logger.bind(
        agent_id=state.get("agent_id"),
        request_id=request_id,
    ).info("planner_execution_completed")

    # ── Phase 3: Verify ──────────────────────────────────────────────
    verify_response = await llm.ainvoke(
        [SystemMessage(content=_VERIFY_SYSTEM_PROMPT), *current_messages],
    )
    step_count += 1
    current_messages.append(verify_response)

    logger.bind(
        agent_id=state.get("agent_id"),
        request_id=request_id,
    ).info("planner_verify_completed")

    return _build_result(state, current_messages, step_count)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_tool_map(tools: list[Callable]) -> dict[str, StructuredTool]:
    """Convert a list of callables into a name -> StructuredTool map."""
    tool_map: dict[str, StructuredTool] = {}
    for fn in tools:
        if isinstance(fn, StructuredTool):
            tool_map[fn.name] = fn
        else:
            desc = getattr(fn, "__doc__", None) or f"Tool: {fn.__name__}"
            t = StructuredTool.from_function(fn, description=desc)
            tool_map[t.name] = t
    return tool_map


def _has_tool_calls(response: AIMessage) -> bool:
    """Return True when the AIMessage carries at least one tool call."""
    return bool(hasattr(response, "tool_calls") and response.tool_calls)


def _execute_tool_calls(
    response: AIMessage,
    tool_map: dict[str, StructuredTool],
    messages: list,
    iteration: int,
) -> None:
    """Execute all tool calls in *response* and append ToolMessages."""
    for tc in response.tool_calls:
        tool_name = tc.get("name", "")
        tool_args = tc.get("args", {})
        tool_call_id = tc.get("id", f"call_{iteration}_{tool_name}")

        tool_fn = tool_map.get(tool_name)
        if tool_fn is None:
            logger.warning("planner_tool_not_found", tool_name=tool_name)
            result_content = f"Error: tool '{tool_name}' not found."
        else:
            try:
                result_content = _invoke_tool(tool_fn, tool_args)
            except Exception as exc:
                logger.error(
                    "planner_tool_error",
                    tool_name=tool_name,
                    error=str(exc),
                )
                result_content = f"Error executing tool '{tool_name}': {exc}"

        messages.append(
            ToolMessage(content=str(result_content), tool_call_id=tool_call_id),
        )


def _invoke_tool(tool_fn: StructuredTool, args: dict) -> str:
    """Synchronously invoke *tool_fn* with *args*."""
    return str(tool_fn.invoke(args))


def _build_result(
    state: AgentState,
    messages: list,
    step_count: int,
) -> dict:
    """Build the output dict with accumulated messages."""
    return {
        **state,
        "messages": messages,
        "step_count": step_count,
    }

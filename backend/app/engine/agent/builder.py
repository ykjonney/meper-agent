"""StateGraph builder — constructs the Agent execution graph.

The graph has a single execution path — the REACT loop.  The LLM
inside the loop autonomously decides whether to answer directly,
call tools, or create a Task via workflow tools.

All tools (Agent-configured ``load_skill`` / ``load_skill_file``
tools + built-in tools + workflow tools) are injected into the
REACT loop at graph-build time.

Skill injection follows the Claude Code pattern:
- System prompt lists available Skills (name + description).
- LLM calls ``load_skill`` on demand to load SKILL.md content.
- ``load_skill_file`` loads individual auxiliary files.
- Both tools fetch Skill data from MongoDB at call time.

Graph topology::

    [evaluate] ──→ [react] ──→ END
"""
from __future__ import annotations

import uuid
from collections.abc import Callable, Awaitable

from langchain_core.tools import tool as lc_tool
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from loguru import logger

from app.engine.agent.context import get_context_window_async
from app.engine.agent.evaluator import evaluate_input
from app.engine.agent.react_executor import run as react_run
from app.engine.agent.react_executor import (
    run_streaming as react_run_streaming,
    StreamCallback,
)
from app.engine.agent.builtin_tools import _BUILTIN_TOOLS, _BUILTIN_TOOL_REGISTRY
from app.engine.agent.workflow_executor import _WORKFLOW_TOOLS
from app.engine.checkpointer import get_checkpointer
from app.engine.llm_factory import get_llm_client
from app.engine.state import AgentState


# ---------------------------------------------------------------------------
# Skill declaration builder (called from agents.py to build SystemMessage)
# ---------------------------------------------------------------------------

async def build_skill_declaration(tool_ids: list[str]) -> str:
    """Build the Skill declaration text for the system prompt.

    Queries MongoDB for each tool ID and formats a markdown list
    of available Skills (name + description).  Returns an empty
    string if no Skills are configured.

    Args:
        tool_ids: The Agent's ``tool_ids`` list.

    Returns:
        Declaration paragraph to append to the system prompt,
        or ``""`` if no Skills.
    """
    if not tool_ids:
        return ""

    from app.services.tool_service import ToolService

    skill_docs = await ToolService.get_tools_by_ids(tool_ids)
    if not skill_docs:
        return ""

    lines = [
        "",
        "## Available Skills",
        "",
        "You have access to the following skills. When you need to use one, call the `load_skill` tool with the skill name.",
        "",
        "After loading a skill, you can load individual auxiliary files with `load_skill_file(skill_name, file_path)`.",
        "",
    ]
    for doc in skill_docs:
        name = doc.get("name", "unknown")
        desc = doc.get("description", "")
        lines.append(f"- **{name}**: {desc}")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------


async def build_agent_graph(
    agent: dict,
    enable_thinking: bool = False,
) -> CompiledStateGraph:
    """Build and compile a ``StateGraph`` for the given Agent.

    The graph topology::

        [evaluate] ──→ [react] ──→ END

    Args:
        agent: The Agent document (from MongoDB).  Must contain at
            least ``_id``, ``llm_config``, ``system_prompt``.
        enable_thinking: Enable LLM native reasoning for supported models.

    Returns:
        A compiled ``StateGraph`` ready for ``.invoke()`` / ``.astream()``.
    """
    # Validate the LLM client eagerly (await since get_llm_client is async)
    await get_llm_client(agent.get("llm_config"), enable_thinking=enable_thinking)
    checkpointer = get_checkpointer()

    builder = StateGraph(AgentState)

    # ── Nodes ──────────────────────────────────────────────────────
    builder.add_node("evaluate", _make_evaluate_node(agent))
    builder.add_node("react", await _make_react_node(agent, enable_thinking=enable_thinking))

    # ── Edges ──────────────────────────────────────────────────────
    builder.set_entry_point("evaluate")
    builder.add_edge("evaluate", "react")
    builder.add_edge("react", END)

    graph = builder.compile(checkpointer=checkpointer)
    logger.info("agent_graph_built", agent_id=agent.get("_id"))
    return graph


# ---------------------------------------------------------------------------
# Node factories
# ---------------------------------------------------------------------------


def _make_evaluate_node(agent: dict) -> Callable:  # type: ignore[type-arg]
    """Return the evaluate node closure (captures agent document)."""

    async def _evaluate(state: AgentState) -> dict:
        user_msg = state["messages"][-1].content if state["messages"] else ""
        request_id = state.get("request_id") or str(uuid.uuid4())
        evaluated = evaluate_input(agent, user_msg, request_id)

        return {
            "agent_id": evaluated["agent_id"],
            "execution_path": evaluated["execution_path"],
            "request_id": evaluated["request_id"],
            "tool_results": evaluated["tool_results"],
            "step_count": 0,
        }

    return _evaluate


async def _make_react_node(
    agent: dict,
    enable_thinking: bool = False,
) -> Callable:  # type: ignore[type-arg]
    """Return the REACT node closure (captures agent, LLM, and all tools).

    Injects Agent-configured Skill tools (``load_skill`` /
    ``load_skill_file``), built-in tools (``bash``, ``read``,
    ``write``), and workflow tools so the LLM can autonomously
    decide which to call.
    """
    llm = await get_llm_client(agent.get("llm_config"), enable_thinking=enable_thinking)
    agent_tools = await _resolve_tools(agent)
    all_tools = [*agent_tools, *_resolve_builtin_tools(agent), *_WORKFLOW_TOOLS]

    # Pre-resolve context window for the model
    model_ref = (agent.get("llm_config") or {}).get("default_model", "")
    context_window = await get_context_window_async(model_ref)

    async def _react(state: AgentState) -> dict:
        return await react_run(
            state, llm, all_tools, context_window=context_window
        )

    return _react


# ---------------------------------------------------------------------------
# Tool resolution — returns [skill_tool] for on-demand Skill loading
# ---------------------------------------------------------------------------


async def _resolve_tools(agent: dict) -> list:
    """Resolve the Agent's tool configuration into callables (async).

    Returns a list with ``load_skill`` (loads SKILL.md) and
    ``load_skill_file`` (loads auxiliary files).  If the Agent has
    no Skill tool IDs, returns an empty list.

    Reads from ``skill_ids`` with fallback to ``tool_ids`` for
    backward compatibility with old Agent documents.
    """
    # Backward compat: read from skill_ids, fall back to tool_ids
    tool_ids = agent.get("skill_ids") or agent.get("tool_ids") or []
    if not tool_ids:
        return []

    from app.services.tool_service import ToolService

    skill_docs = await ToolService.get_tools_by_ids(tool_ids)
    if not skill_docs:
        return []  # No valid tools found — don't inject useless tools

    allowed_names = {doc.get("name") for doc in skill_docs if doc.get("name")}
    return [
        _make_skill_loader(allowed_names),
        _make_skill_file_loader(allowed_names),
    ]


_MAX_SKILL_CONTENT = 50_000


def _resolve_builtin_tools(agent: dict) -> list:
    """Resolve built-in tools based on Agent's ``builtin_config`` whitelist.

    When ``builtin_config`` is non-empty, returns only the tools whose
    names are in the whitelist.  When empty, returns no built-in tools
    (Agent must explicitly enable them).
    """
    builtin_config = agent.get("builtin_config") or []
    if not builtin_config:
        return []
    return [
        _BUILTIN_TOOL_REGISTRY[name]
        for name in builtin_config
        if name in _BUILTIN_TOOL_REGISTRY
    ]


def _make_skill_loader(allowed_names: set[str] | None = None) -> Callable:
    """Create ``load_skill`` — loads SKILL.md instructions by name."""

    async def load_skill(skill_name: str) -> str:
        """Load the SKILL.md content of a named skill.

        Returns the main instructions (SKILL.md) for the skill.
        After loading, use ``load_skill_file`` to access individual
        auxiliary files if available.

        Args:
            skill_name: The exact name of the skill to load.
        """
        if allowed_names is not None and skill_name not in allowed_names:
            avail = ", ".join(sorted(allowed_names))
            return f"Skill '{skill_name}' is not available. Available: {avail}."

        from app.services.tool_service import ToolService

        doc = await ToolService.find_by_name(skill_name)
        if doc is None:
            return f"Skill '{skill_name}' not found."

        instructions = doc.get("instructions", "")
        if not instructions:
            return f"Skill '{skill_name}' has no content."

        if len(instructions) > _MAX_SKILL_CONTENT:
            instructions = instructions[:_MAX_SKILL_CONTENT] + (
                f"\n\n... [truncated: exceeds {_MAX_SKILL_CONTENT:,} chars]"
            )
        return instructions

    return lc_tool(load_skill)


def _make_skill_file_loader(allowed_names: set[str] | None = None) -> Callable:
    """Create ``load_skill_file`` — loads a specific file from a skill."""

    async def load_skill_file(skill_name: str, file_path: str) -> str:
        """Load a specific auxiliary file from a named skill.

        Use this after loading the main skill instructions with
        ``load_skill``.  The file path is relative within the skill
        directory (e.g. ``steps/step-01.md``).

        Args:
            skill_name: The exact name of the skill.
            file_path: Relative path of the file within the skill.
        """
        if allowed_names is not None and skill_name not in allowed_names:
            avail = ", ".join(sorted(allowed_names))
            return f"Skill '{skill_name}' is not available. Available: {avail}."

        from app.services.tool_service import ToolService

        doc = await ToolService.find_by_name(skill_name)
        if doc is None:
            return f"Skill '{skill_name}' not found."

        files = doc.get("files", [])
        for f in files:
            if f.get("path") == file_path:
                content = f.get("content", "")
                if not content:
                    return f"File '{file_path}' in skill '{skill_name}' is empty."
                if len(content) > _MAX_SKILL_CONTENT:
                    content = content[:_MAX_SKILL_CONTENT] + (
                        f"\n\n... [truncated: exceeds {_MAX_SKILL_CONTENT:,} chars]"
                    )
                return content

        return f"File '{file_path}' not found in skill '{skill_name}'."

    return lc_tool(load_skill_file)


# ---------------------------------------------------------------------------
# Streaming entry point (bypasses StateGraph for SSE)
# ---------------------------------------------------------------------------


async def run_agent_streaming(
    agent: dict,
    state: AgentState,
    on_event: StreamCallback,
    enable_thinking: bool = False,
) -> dict:
    """Execute the Agent REACT loop with token-level streaming.

    This bypasses the StateGraph and directly calls the streaming
    REACT executor so events can be pushed to SSE token-by-token.

    Args:
        agent: The Agent document (from MongoDB).
        state: Initial AgentState (with messages, etc.).
        on_event: Async callback receiving SSE event dicts.
        enable_thinking: Enable LLM native reasoning.

    Returns:
        Final AgentState after execution completes.
    """
    llm = await get_llm_client(agent.get("llm_config"), enable_thinking=enable_thinking)
    agent_tools = await _resolve_tools(agent)
    all_tools = [*agent_tools, *_resolve_builtin_tools(agent), *_WORKFLOW_TOOLS]

    model_ref = (agent.get("llm_config") or {}).get("default_model", "")
    context_window = await get_context_window_async(model_ref)

    return await react_run_streaming(
        state, llm, all_tools,
        on_event=on_event,
        enable_thinking=enable_thinking,
        context_window=context_window,
    )

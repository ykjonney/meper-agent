"""StateGraph builder — constructs the Agent execution graph.

The graph has a single execution path — the REACT loop.  The LLM
inside the loop autonomously decides whether to answer directly,
call tools, or dispatch a workflow Task via ``dispatch_workflow``.

All tools are injected into the REACT loop at graph-build time:
- **Skill tools** — on-demand loading via ``load_skill``
- **MCP tools** — directly callable, from bound MCP connections
- **Built-in tools** — bash, read, write (whitelisted via builtin_config)
- **Task tools** — ``task_query``, ``task_list``, ``dispatch_workflow``,
  etc. (always available)

Skill injection follows the Claude Code pattern:
- System prompt lists available Skills (name + description).
- LLM calls ``load_skill`` on demand to load SKILL.md content.
- The returned content includes an absolute base path hint so the
  LLM can access auxiliary files via ``read`` / ``bash`` tools.
- Files are stored on disk, MongoDB only keeps registration metadata.

Graph topology::

    [evaluate] ──→ [react] ──→ END
"""
from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.tools import tool as lc_tool
from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph
from loguru import logger

from app.engine.agent.builtin_tools import _BUILTIN_TOOL_REGISTRY
from app.engine.agent.context import get_context_window_async
from app.engine.agent.evaluator import evaluate_input
from app.engine.agent.react_executor import (
    StreamCallback,
)
from app.engine.agent.react_executor import run as react_run
from app.engine.agent.react_executor import (
    run_streaming as react_run_streaming,
)
from app.engine.checkpointer import get_checkpointer
from app.engine.llm_factory import get_llm_client
from app.engine.state import AgentState
from app.models.compat import resolve_skill_ids

# ---------------------------------------------------------------------------
# Shared execution context — eliminates duplication between graph & streaming
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _ExecutionContext:
    """Resolved LLM client, tools, and context window for Agent execution."""

    llm: BaseChatModel
    tools: list
    context_window: int | None


async def _resolve_execution_context(
    agent: dict,
    enable_thinking: bool = False,
) -> _ExecutionContext:
    """Build the shared execution context for both graph and streaming paths.

    Resolves the LLM client, agent tools, built-in tools (including
    ``preview_workflow`` / ``confirm_workflow`` for workflow triggering),
    and the model's context window in a single pass.
    """
    llm = await get_llm_client(agent, enable_thinking=enable_thinking)
    agent_tools = await _resolve_tools(agent)
    builtin_tools = _resolve_builtin_tools(agent)
    all_tools = [*agent_tools, *builtin_tools]

    model_ref = agent.get("default_model") or (agent.get("llm_config") or {}).get("default_model", "")
    context_window = await get_context_window_async(model_ref)

    return _ExecutionContext(
        llm=llm,
        tools=all_tools,
        context_window=context_window,
    )


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
        "After loading a skill, you can access auxiliary files (scripts, templates, etc.) via the skill base path shown in the instructions, using your `read` or `bash` tools.",
        "",
    ]
    for doc in skill_docs:
        name = doc.get("name", "unknown")
        desc = doc.get("description", "")
        lines.append(f"- **{name}**: {desc}")

    return "\n".join(lines)


async def build_tool_declaration(agent: dict) -> str:
    """Build the complete tool declaration text for the system prompt.

    Generates declaration sections for all tool categories:
    - Skills (on-demand via load_skill)
    - MCP tools (directly callable)
    - Workflow list (listed for reference, triggered via preview_workflow)
    - Built-in tools (directly callable)
    - Task tools (always available, includes preview_workflow / confirm_workflow)

    Args:
        agent: The Agent document (from MongoDB).

    Returns:
        Declaration paragraph to append to the system prompt,
        or ``""`` if no tools are configured.
    """
    sections: list[str] = []

    # --- Skill declaration ---
    skill_ids = resolve_skill_ids(agent)
    if skill_ids:
        skill_decl = await build_skill_declaration(skill_ids)
        if skill_decl:
            sections.append(skill_decl)

    # --- MCP tool declaration ---
    mcp_connection_ids = agent.get("mcp_connection_ids") or []
    if mcp_connection_ids:
        mcp_decl = await _build_mcp_tool_declaration(mcp_connection_ids)
        if mcp_decl:
            sections.append(mcp_decl)

    # --- Workflow tool declaration ---
    workflow_ids = agent.get("workflow_ids") or []
    if workflow_ids:
        workflow_decl = await _build_workflow_tool_declaration(workflow_ids)
        if workflow_decl:
            sections.append(workflow_decl)

    # --- Built-in tool declaration ---
    builtin_config = agent.get("builtin_config") or []
    if builtin_config:
        builtin_decl = _build_builtin_tool_declaration(builtin_config)
        if builtin_decl:
            sections.append(builtin_decl)

    # --- Task tool declaration (always shown) ---
    task_decl = _build_task_tool_declaration()
    sections.append(task_decl)

    return "\n".join(sections) if sections else ""


async def build_system_prompt(agent_doc: dict) -> str:
    """Build the fully assembled system prompt for an Agent.

    Delegates to the slot renderer which handles PromptTemplate-based
    prompt composition. Falls back to tool declaration only when no
    template is configured.
    """
    from app.engine.agent.slot_renderer import render_system_prompt_full

    return await render_system_prompt_full(agent_doc)


async def _build_mcp_tool_declaration(mcp_connection_ids: list[str]) -> str:
    """Build MCP tool declaration section for the system prompt."""
    from app.db.mongodb import get_database
    from app.services.mcp_connection_service import McpConnectionService

    lines = [
        "",
        "## MCP Tools",
        "",
        "You have access to the following MCP tools. Call them directly by name with the required arguments.",
        "",
    ]

    total_tools = 0
    for conn_id in mcp_connection_ids:
        conn_doc = await McpConnectionService.get_connection(conn_id)
        if conn_doc is None:
            continue

        conn_name = conn_doc.get("name", "Unknown")
        col = get_database()["tools"]
        cursor = col.find({
            "mcp_connection_id": conn_id,
            "source": "mcp",
        })
        tool_docs = await cursor.to_list(length=100)

        if not tool_docs:
            continue

        lines.append(f"### {conn_name}")
        lines.append("")
        for doc in tool_docs:
            name = doc.get("name", "unknown")
            desc = doc.get("description", "")
            lines.append(f"- **{name}**: {desc}")
            total_tools += 1
        lines.append("")

    return "\n".join(lines) if total_tools > 0 else ""


async def _build_workflow_tool_declaration(workflow_ids: list[str]) -> str:
    """Build workflow declaration section for the system prompt.

    Reads the **actual Workflow definition** (``workflows`` collection)
    to extract the Start node's ``output_variables`` and show the
    exact parameter names the LLM should pass to ``dispatch_workflow``.
    """
    from app.services.workflow_registry_service import WorkflowRegistryService
    from app.services.workflow_service import WorkflowService

    lines = [
        "",
        "## Available Workflows",
        "",
        "When a workflow matches the user's request:",
        "",
        "1. Call ``propose_workflow(workflow_name, params)`` — this shows a",
        "   confirmation card to the user with workflow info and input params.",
        "   After calling, just tell the user you found a suitable workflow.",
        "   **Do NOT ask the user questions** — the card handles confirmation.",
        "",
        "2. When the user confirms (e.g. says '确认', '好的'), call",
        "   ``dispatch_workflow(workflow_name, params)`` to create the Task.",
        "",
    ]

    for wf_id in workflow_ids:
        # Try by workflow_id first, then by registry _id
        entry = await WorkflowRegistryService.get_by_workflow_id(wf_id)
        if entry is None:
            entry = await WorkflowRegistryService.get_by_id(wf_id)
        if entry is None:
            continue

        wf_name = entry.get("name", "unknown")
        wf_desc = entry.get("description", "") or wf_name
        has_human = entry.get("has_human_node", False)
        wf_ref = entry.get("workflow_id", "")

        lines.append(f"- **{wf_name}**: {wf_desc}")
        if has_human:
            lines.append("  - ⚠️ Contains human approval nodes")

        # Read the actual Workflow definition to extract the Start
        # node's output_variables — these define the input params
        # the LLM must pass to dispatch_workflow.
        param_vars: list[dict] = []
        if wf_ref:
            wf_doc = await WorkflowService.get(wf_ref)
            if wf_doc:
                nodes = wf_doc.get("nodes", [])
                start_node = next((n for n in nodes if n.get("type") == "start"), None)
                if start_node:
                    output_vars = start_node.get("config", {}).get("output_variables", [])
                    if isinstance(output_vars, list):
                        param_vars = []
                        for v in output_vars:
                            if not isinstance(v, dict) or not v.get("name"):
                                continue
                            # Frontend (VariableListEditor) stores `required` and `default_value`
                            # inside `constraints`. Fall back to top-level keys for legacy data
                            # (some tests / older docs used top-level `required` / `default`).
                            constraints = v.get("constraints") if isinstance(v.get("constraints"), dict) else {}
                            required = constraints.get("required", v.get("required"))
                            # Required 默认 false（与前端 variable-types.ts 的 defaultValue: false 对齐）
                            required = bool(required) if required is not None else False

                            default_val = constraints.get("default_value", v.get("default"))

                            param_vars.append({
                                "name": v.get("name", ""),
                                "type": v.get("type", "string"),
                                "label": v.get("label", ""),
                                "description": v.get("description", ""),
                                "required": required,
                                "default": default_val,
                            })

        if param_vars:
            parts_list = []
            for p in param_vars:
                # Build type+required+default annotation, e.g. "(string, required)" or "(text, optional, default='')".
                attr_parts = [p["type"]]
                if p["required"]:
                    attr_parts.append("required")
                else:
                    attr_parts.append("optional")
                    default_val = p.get("default")
                    if default_val not in (None, ""):
                        attr_parts.append(f"default={default_val!r}")
                attr_str = ", ".join(attr_parts)

                # Build the full param line: name (type, required): description
                desc = p.get("description") or p.get("label") or ""
                if desc:
                    parts_list.append(f"{p['name']} ({attr_str}): {desc}")
                else:
                    parts_list.append(f"{p['name']} ({attr_str})")

            param_desc = ", ".join(parts_list)
            lines.append(f"  - Input params: {param_desc}")
            lines.append(
                "  - Map the user's request to the exact param name above. "
                "For example, if the param is ``request``, call "
                "``dispatch_workflow(workflow_name, {'request': '<user request>'})``. "
                "Use the EXACT param name from the list — do NOT invent new keys."
            )
        else:
            lines.append(
                "  - Input params: ``input`` (string). "
                "Pass the user's request as ``{'input': '<user request>'}``."
            )

        lines.append("")

    return "\n".join(lines)


def _build_builtin_tool_declaration(builtin_config: list[str]) -> str:
    """Build built-in tool declaration section for the system prompt."""
    lines = [
        "",
        "## Built-in Tools",
        "",
        "You have access to the following built-in tools. Call them directly by name.",
        "",
    ]

    tool_desc_map = {
        "bash": "Execute shell commands (command: str)",
        "read": "Read file contents (path: str)",
        "write": "Write content to tmp/ — for intermediate/scratch files only. These files are NOT visible or downloadable by the user. NEVER use this for files the user needs to keep.",
        "write_to_output": "Write content to output/ — these files ARE visible and downloadable by the user. ALWAYS use this tool when the user asks you to generate, create, save, or export any file (code, document, image list, report, etc.).",
    }

    for name in builtin_config:
        desc = tool_desc_map.get(name, name)
        lines.append(f"- **{name}**: {desc}")

    return "\n".join(lines)


def _build_task_tool_declaration() -> str:
    """Build task management tool declaration section for the system prompt."""
    lines = [
        "",
        "## Task Management Tools",
        "",
        "You have access to the following task management tools. Use them to query or manage workflow Tasks.",
        "",
        "- **propose_workflow(workflow_name, params)**: Propose a workflow to the user. Returns structured info that shows a confirmation card. Does NOT create a Task — just tell the user you found a workflow after calling.",
        "- **dispatch_workflow(workflow_name, params)**: Create and dispatch a workflow Task. Only call this AFTER the user explicitly confirms. Pass the user's original request as params using the exact variable names from the Workflow declaration above.",
        "- **task_query(task_id)**: Query task status and result. Returns status + output (completed) or error (failed). Only call this when the user asks about progress — do NOT poll or loop.",
        "- **task_list**: List Tasks with optional filters (status, workflow_id)",
        "- **task_intervene**: Intervene in a Task (approve, reject, cancel, resume, retry)",
        "- **cancel_task**: Shortcut to cancel a Task",
        "- **update_task_variables**: Update the variable pool of a running Task",
        "",
    ]
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
            least ``_id``, ``default_model``, ``system_prompt``.
        enable_thinking: Enable LLM native reasoning for supported models.

    Returns:
        A compiled ``StateGraph`` ready for ``.invoke()`` / ``.astream()``.
    """
    # Validate the LLM client eagerly (await since get_llm_client is async)
    await get_llm_client(agent, enable_thinking=enable_thinking)
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

    Injects Agent-configured tools (Skill, MCP, Workflow), built-in
    tools (bash, read, write), and task management tools so the LLM
    can autonomously decide which to call.
    """
    ctx = await _resolve_execution_context(agent, enable_thinking=enable_thinking)

    async def _react(state: AgentState) -> dict:
        return await react_run(
            state, ctx.llm, ctx.tools, context_window=ctx.context_window
        )

    return _react


# ---------------------------------------------------------------------------
# Tool resolution — returns [skill_tool] for on-demand Skill loading
# ---------------------------------------------------------------------------


async def _resolve_tools(agent: dict) -> list:
    """Resolve the Agent's tool configuration into callables (async).

    Returns:
        - ``load_skill`` + ``load_skill_file`` for Skill-based tools
        - MCP tool callables for each bound MCP connection
    """
    tools: list = []

    # --- Skill tools ---
    skill_tool_ids = resolve_skill_ids(agent)
    logger.info(
        "resolve_tools_skill_ids",
        agent_id=agent.get("_id"),
        skill_ids=skill_tool_ids,
    )
    if skill_tool_ids:
        from app.services.tool_service import ToolService

        skill_docs = await ToolService.get_tools_by_ids(skill_tool_ids)
        logger.info(
            "resolve_tools_skill_docs",
            agent_id=agent.get("_id"),
            found_docs=len(skill_docs),
            doc_names=[d.get("name") for d in skill_docs],
        )
        if skill_docs:
            allowed_names = {doc.get("name") for doc in skill_docs if doc.get("name")}
            tools.append(_make_skill_loader(allowed_names))

    # --- MCP tools ---
    mcp_tools = await _resolve_mcp_tools(agent)
    tools.extend(mcp_tools)

    logger.info(
        "resolve_tools_result",
        agent_id=agent.get("_id"),
        total_tools=len(tools),
        tool_names=[getattr(t, "name", getattr(t, "__name__", "?")) for t in tools],
    )

    return tools


async def _resolve_mcp_tools(agent: dict) -> list:
    """Resolve MCP tools for Agent-bound MCP connections.

    Uses ``get_mcp_tools_cached`` to avoid creating new connections on
    every execution.  Tools are cached by connection IDs with a 5-minute TTL.
    """
    from app.engine.tool.mcp_tool_cache import get_mcp_tools_cached

    mcp_connection_ids = agent.get("mcp_connection_ids") or []
    if not mcp_connection_ids:
        return []

    return await get_mcp_tools_cached(mcp_connection_ids)


_MAX_SKILL_CONTENT = 50_000


def _resolve_builtin_tools(agent: dict) -> list:
    """Resolve built-in tools based on Agent's ``builtin_config`` whitelist.

    When ``builtin_config`` is non-empty, returns only the base tools (bash,
    read, write) whose names are in the whitelist.  Task management tools are
    always included regardless of ``builtin_config``.

    When ``builtin_config`` is empty, returns only the task management tools.
    """
    from app.engine.agent.workflow_executor import _TASK_TOOLS

    builtin_config = agent.get("builtin_config") or []

    # Base tools (bash, read, write, write_to_output) — filtered by whitelist
    base_tools = [
        _BUILTIN_TOOL_REGISTRY[name]
        for name in builtin_config
        if name in _BUILTIN_TOOL_REGISTRY and name in {"bash", "read", "write", "write_to_output"}
    ]

    # Task management tools — always available
    return [*base_tools, *_TASK_TOOLS]


async def _resolve_workflow_tools(agent: dict) -> list:
    """Resolve workflow trigger tools — now returns empty list.

    Workflow triggering is handled via ``preview_workflow`` /
    ``confirm_workflow`` (injected as built-in task tools).  This
    function is retained for backward compat but returns empty.
    """
    return []


def _make_skill_loader(allowed_names: set[str] | None = None) -> Callable:
    """Create ``load_skill`` — loads SKILL.md instructions by name."""

    async def load_skill(skill_name: str) -> str:
        """Load the SKILL.md content of a named skill.

        Returns the main instructions (SKILL.md) for the skill.
        The returned content includes an absolute base path — use it
        to access auxiliary files via your ``read`` or ``bash`` tools.

        Args:
            skill_name: The exact name of the skill to load.
        """
        if allowed_names is not None and skill_name not in allowed_names:
            avail = ", ".join(sorted(allowed_names))
            logger.warning("load_skill_not_allowed", skill_name=skill_name, available=avail)
            return f"Skill '{skill_name}' is not available. Available: {avail}."

        from app.engine.tool.skill_fs import get_skill_base_path, read_skill_file

        instructions = read_skill_file(skill_name, "SKILL.md")
        if instructions is None:
            logger.warning("load_skill_not_found_on_disk", skill_name=skill_name)
            return f"Skill '{skill_name}' not found."

        if not instructions:
            logger.warning("load_skill_empty_on_disk", skill_name=skill_name)
            return f"Skill '{skill_name}' has no content."

        # Inject path hint so the LLM knows where to find auxiliary files
        base_path = get_skill_base_path(skill_name)
        path_hint = (
            f"\n\n[Skill base path: {base_path}/ "
            f"— use this absolute path for all file references in this skill]"
        )

        content = instructions + path_hint

        logger.info(
            "load_skill_success",
            skill_name=skill_name,
            content_len=len(content),
        )
        if len(content) > _MAX_SKILL_CONTENT:
            content = content[:_MAX_SKILL_CONTENT] + (
                f"\n\n... [truncated: exceeds {_MAX_SKILL_CONTENT:,} chars]"
            )
        return content

    return lc_tool(load_skill)


# ---------------------------------------------------------------------------
# Preview / Dry-run — inspect assembled prompt & tools without invoking LLM
# ---------------------------------------------------------------------------


async def preview_agent(
    agent: dict,
    user_input: str = "Hello",
    enable_thinking: bool = False,
) -> dict:
    """Assemble the Agent's prompt and tools without invoking the LLM.

    Returns a dict with the fully composed system prompt, messages,
    and a structured tool list suitable for debugging and inspection.

    Args:
        agent: The Agent document (from MongoDB).
        user_input: Simulated user message for message list assembly.
        enable_thinking: Whether thinking mode would be enabled.

    Returns:
        Dict with keys: system_prompt, messages, tools, tool_summary.
    """
    from langchain_core.tools import StructuredTool

    # --- Resolve system prompt via slot renderer ---
    from app.engine.agent.slot_renderer import render_system_prompt_full

    system_text = await render_system_prompt_full(agent, strict=False)

    # --- Assemble messages ---
    messages: list[dict] = []
    if system_text:
        messages.append({"role": "system", "content": system_text})
    messages.append({"role": "user", "content": user_input})

    # --- Resolve all tools ---
    agent_tools = await _resolve_tools(agent)
    builtin_tools = _resolve_builtin_tools(agent)
    all_tools = [*agent_tools, *builtin_tools]

    # --- Classify tools for preview ---
    tool_previews: list[dict] = []
    summary: dict[str, int] = {"total": len(all_tools), "skill": 0, "mcp": 0, "builtin": 0, "task": 0}

    # Build lookup sets for classification
    builtin_names_set = set(agent.get("builtin_config") or [])
    task_tool_names = {
        "task_query", "task_list", "task_intervene",
        "cancel_task", "get_task_timeline", "update_task_variables",
        "dispatch_workflow",
    }

    for t in all_tools:
        if isinstance(t, StructuredTool):
            t_name = t.name
            t_desc = t.description or ""
            t_schema = {}
            if t.args_schema:
                if isinstance(t.args_schema, dict):
                    t_schema = t.args_schema
                elif hasattr(t.args_schema, "model_json_schema"):
                    t_schema = t.args_schema.model_json_schema()
                else:
                    t_schema = {}

            # Classify by origin
            if t_name == "load_skill":
                t_type = "skill"
                t_source = "skill_loader"
            elif t_name in task_tool_names:
                t_type = "task"
                t_source = t_name
            elif t_name in builtin_names_set:
                t_type = "builtin"
                t_source = t_name
            else:
                t_type = "mcp"
                t_source = t_name

            summary[t_type] = summary.get(t_type, 0) + 1
            tool_previews.append({
                "name": t_name,
                "type": t_type,
                "description": t_desc[:500],
                "source": t_source,
                "input_schema": t_schema,
            })
        else:
            # Plain callable
            fn_name = getattr(t, "__name__", str(t))
            summary["builtin"] += 1
            tool_previews.append({
                "name": fn_name,
                "type": "builtin",
                "description": getattr(t, "__doc__", "") or "",
                "source": fn_name,
                "input_schema": {},
            })

    # --- LLM config preview ---
    model_ref = agent.get("default_model") or (agent.get("llm_config") or {}).get("default_model", "")

    return {
        "system_prompt": system_text,
        "messages": messages,
        "tools": tool_previews,
        "tool_summary": summary,
        "model": model_ref,
    }


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
    ctx = await _resolve_execution_context(agent, enable_thinking=enable_thinking)

    return await react_run_streaming(
        state, ctx.llm, ctx.tools,
        on_event=on_event,
        enable_thinking=enable_thinking,
        context_window=ctx.context_window,
    )

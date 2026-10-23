"""agent-flow-harness package.

Reusable LangGraph agent runtime. The harness intentionally knows nothing
about HTTP, persistence, auth, or workspace storage: callers inject every
external dependency (LLM, tools, checkpointer, workspace) so the same
runtime can be embedded in different backends.
"""

from __future__ import annotations

from agent_flow_harness.checkpointer import (
    build_mongo_saver,
    configure_checkpointer,
    get_checkpointer,
    reset_checkpointer,
)
from agent_flow_harness.context_engineering import (
    compact_circuit,
    compress_tool_outputs,
)
from agent_flow_harness.graph import build_agent_graph, build_config
from agent_flow_harness.guards import (
    Guard,
    GuardResult,
    TokenBudgetGuard,
    resolve_guards,
)
from agent_flow_harness.llm import (
    apply_thinking_mode,
    build_client_from_doc,
    build_client_from_env,
    build_thinking_kwargs,
    supports_thinking,
)
from agent_flow_harness.middleware import (
    Middleware,
    MiddlewareChain,
    MIDDLEWARE_REGISTRY,
    UsageMiddleware,
    resolve_middleware,
)
from agent_flow_harness.mcp import (
    McpConnectionConfig,
    McpToolLoader,
    get_external_required_context,
    get_user_token_context,
    reset_external_required_context,
    reset_user_token_context,
    set_external_required_context,
    set_user_token_context,
)
from agent_flow_harness.state import AgentState
from agent_flow_harness.subagents import (
    SubAgentContext,
    SubAgentRegistry,
    SubAgentSpec,
    delegate_to_subagent,
    get_subagent_context,
    reset_subagent_context,
    set_subagent_context,
)
from agent_flow_harness.sandbox import (
    DockerSandbox,
    DockerSandboxConfig,
    GrepMatch,
    LocalSandbox,
    Sandbox,
    SandboxContext,
    SandboxResult,
    bash,
    get_sandbox_context,
    glob,
    grep,
    read,
    reset_sandbox_context,
    set_sandbox_context,
    write,
)
from agent_flow_harness.interaction import ask_clarification
from agent_flow_harness.tools import (
    BUILTIN_TOOL_NAMES,
    BUILTIN_TOOLS,
    TOOL_REGISTRY,
    ToolRegistry,
    resolve_variable,
)
from agent_flow_harness.tools.run_code import (
    DESCRIPTION as RUN_CODE_DESCRIPTION,
    EXAMPLE_CODE as RUN_CODE_EXAMPLE_CODE,
    run_code,
)
from agent_flow_harness.tools.tool_bridge_context import (
    ToolBridgeContext,
    get_tool_bridge_context,
    reset_tool_bridge_context,
    set_tool_bridge_context,
)
from agent_flow_harness.slots import (
    SLOT_NAMES,
    SLOT_SCHEMA,
    SlotDef,
    TOOL_DECLARATION_SLOT,
)
from agent_flow_harness.skills import SkillManager, SkillSpec

__version__ = "0.1.0"

# Default checkpointer: an in-memory saver so that interrupt / aget_state /
# thread persistence work out of the box. Applications embedding the harness
# should call ``configure_checkpointer(MongoDBSaver(...), overwrite=True)`` at
# startup to switch to a durable backend.
try:
    from langgraph.checkpoint.memory import MemorySaver as _MemorySaver

    configure_checkpointer(_MemorySaver(), overwrite=True)
except ImportError:  # pragma: no cover - langgraph always provides MemorySaver
    pass

__all__ = [
    "AgentState",
    "BUILTIN_TOOL_NAMES",
    "BUILTIN_TOOLS",
    "DockerSandbox",
    "DockerSandboxConfig",
    "Guard",
    "GuardResult",
    "GrepMatch",
    "MIDDLEWARE_REGISTRY",
    "Middleware",
    "MiddlewareChain",
    "McpConnectionConfig",
    "McpToolLoader",
    "LocalSandbox",
    "SLOT_NAMES",
    "SLOT_SCHEMA",
    "SlotDef",
    "TOOL_DECLARATION_SLOT",
    "SubAgentContext",
    "SubAgentRegistry",
    "SubAgentSpec",
    "Sandbox",
    "SandboxContext",
    "SandboxResult",
    "SkillManager",
    "SkillSpec",
    "TOOL_REGISTRY",
    "TokenBudgetGuard",
    "ToolBridgeContext",
    "ToolRegistry",
    "UsageMiddleware",
    "RUN_CODE_DESCRIPTION",
    "RUN_CODE_EXAMPLE_CODE",
    "apply_thinking_mode",
    "ask_clarification",
    "compact_circuit",
    "compress_tool_outputs",
    "bash",
    "build_agent_graph",
    "build_client_from_doc",
    "build_client_from_env",
    "build_thinking_kwargs",
    "build_config",
    "build_mongo_saver",
    "configure_checkpointer",
    "delegate_to_subagent",
    "get_checkpointer",
    "get_external_required_context",
    "get_sandbox_context",
    "get_subagent_context",
    "get_tool_bridge_context",
    "get_user_token_context",
    "glob",
    "grep",
    "read",
    "reset_checkpointer",
    "reset_external_required_context",
    "reset_sandbox_context",
    "reset_subagent_context",
    "reset_tool_bridge_context",
    "reset_user_token_context",
    "resolve_guards",
    "resolve_middleware",
    "resolve_variable",
    "run_code",
    "set_external_required_context",
    "set_sandbox_context",
    "set_subagent_context",
    "set_tool_bridge_context",
    "set_user_token_context",
    "supports_thinking",
    "write",
    "__version__",
]

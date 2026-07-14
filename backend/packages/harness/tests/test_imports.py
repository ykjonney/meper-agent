"""AC10 cover: public API import paths are stable from v0.1-1."""

from __future__ import annotations

import agent_flow_harness as harness


def test_top_level_exports_present() -> None:
    """The documented public names exist on the package object."""
    expected = {
        "AgentState",
        "build_agent_graph",
        "run_agent",
        "run_agent_streaming",
        "get_checkpointer",
        "configure_checkpointer",
        "reset_checkpointer",
        "__version__",
    }
    missing = expected - set(dir(harness))
    assert not missing, f"missing public exports: {missing}"


def test_version_is_pep440_string() -> None:
    assert isinstance(harness.__version__, str)
    assert harness.__version__.count(".") >= 1


def test_submodule_imports_resolve() -> None:
    """Each of the core module packages imports without error."""
    import importlib

    for mod in (
        "agent_flow_harness.engine",
        "agent_flow_harness.graph",
        "agent_flow_harness.adapters",
        "agent_flow_harness.guards",
        "agent_flow_harness.tools",
        "agent_flow_harness.slots",
        "agent_flow_harness.llm",
        "agent_flow_harness.middleware",
    ):
        assert importlib.import_module(mod) is not None


def test_no_app_layer_imports_leak() -> None:
    """AC3 guard: the package must not drag in fastapi/motor/celery/redis."""
    import sys

    forbidden = {"fastapi", "motor", "pymongo", "celery", "redis", "mongoengine"}
    leaked = forbidden & {m.split(".")[0] for m in sys.modules}
    # numpy / etc. may pull unrelated libs; only assert our banned set.
    assert not leaked, f"harness pulled in forbidden app-layer deps: {leaked}"


def test_subagents_public_api_importable() -> None:
    """AC1 (v0.2-1): subagents 包公开 API 可从顶层导入。"""
    from agent_flow_harness import (
        SubAgentContext,
        SubAgentRegistry,
        SubAgentSpec,
        delegate_to_subagent,
    )
    assert SubAgentSpec is not None
    assert SubAgentRegistry is not None
    assert SubAgentContext is not None
    assert delegate_to_subagent.name == "delegate_to_subagent"


def test_sandbox_public_api_importable() -> None:
    """AC1 (v0.2-2): sandbox 包公开 API 可从顶层导入。"""
    from agent_flow_harness import (
        GrepMatch,
        LocalSandbox,
        Sandbox,
        SandboxProvider,
        SandboxResult,
        bash,
        glob,
        grep,
        read,
        write,
    )
    assert Sandbox is not None
    assert LocalSandbox is not None
    assert SandboxResult is not None
    assert SandboxProvider is not None
    assert GrepMatch is not None
    assert bash.name == "bash"
    assert read.name == "read"
    assert write.name == "write"
    assert glob.name == "glob"
    assert grep.name == "grep"


def test_interaction_public_api_importable() -> None:
    """AC7 (v0.2-x): 第一层能力型工具 + resolver 可从顶层导入。"""
    from agent_flow_harness import (
        ask_clarification,
        resolve_variable,
        tool_search,
    )
    assert ask_clarification.name == "ask_clarification"
    assert tool_search.name == "tool_search"
    assert callable(resolve_variable)


def test_create_agent_api_importable() -> None:
    """create_agent 高层 API 可从顶层导入。"""
    from agent_flow_harness import Agent, AgentConfig, create_agent
    assert AgentConfig is not None
    assert callable(create_agent)
    assert Agent is not None


def test_context_engineering_importable() -> None:
    """v0.2-5 context_engineering 策略可从顶层导入。"""
    from agent_flow_harness import (
        ContextStrategy,
        HybridStrategy,
        SlidingWindowStrategy,
        SummarizationStrategy,
    )
    assert ContextStrategy is not None
    assert HybridStrategy is not None
    assert SlidingWindowStrategy is not None
    assert SummarizationStrategy is not None

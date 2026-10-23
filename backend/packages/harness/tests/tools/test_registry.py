"""AC1/AC2/AC7/AC8/AC9/AC10 cover: ToolRegistry register/resolve/list."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.tools import StructuredTool

from agent_flow_harness.tools.registry import TOOL_REGISTRY, ToolRegistry


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


def _builtin_tool(name: str, ret: str = "ok") -> StructuredTool:
    def _fn(**_kwargs: Any) -> str:  # noqa: ANN202
        return ret

    _fn.__name__ = name
    return StructuredTool.from_function(_fn, name=name, description=f"{name} tool")




# ---------------------------------------------------------------------------
# Fresh registry fixture (isolates tests from the global singleton)
# ---------------------------------------------------------------------------


@pytest.fixture
def registry() -> ToolRegistry:
    return ToolRegistry()


# ---------------------------------------------------------------------------
# register()
# ---------------------------------------------------------------------------


def test_register_builtin_tool(registry: ToolRegistry) -> None:
    tool = _builtin_tool("bash")
    registry.register(tool)
    assert registry.get("bash") is tool
    assert tool in registry.list_builtin_tools()


def test_register_builtin_without_name_raises(registry: ToolRegistry) -> None:
    """An object without a string .name cannot be registered."""

    class _Anon:
        pass

    with pytest.raises(TypeError):
        registry.register(_Anon())  # type: ignore[arg-type]


def test_unregister_removes_tool(registry: ToolRegistry) -> None:
    registry.register(_builtin_tool("bash"))
    registry.unregister("bash")
    assert registry.get("bash") is None


# ---------------------------------------------------------------------------
# resolve()
# ---------------------------------------------------------------------------


def test_resolve_enabled_tools(registry: ToolRegistry) -> None:
    registry.register(_builtin_tool("bash"))
    registry.register(_builtin_tool("read"))
    doc = {"tools": [{"name": "bash", "enabled": True}, {"name": "read", "enabled": True}]}

    resolved = registry.resolve(doc)

    assert [t.name for t in resolved] == ["bash", "read"]


def test_resolve_skip_disabled_tools(registry: ToolRegistry) -> None:
    registry.register(_builtin_tool("bash"))
    doc = {"tools": [{"name": "bash", "enabled": False}]}

    assert registry.resolve(doc) == []


def test_resolve_default_enabled_when_flag_absent(registry: ToolRegistry) -> None:
    """Entries omitting 'enabled' default to enabled."""
    registry.register(_builtin_tool("bash"))
    doc = {"tools": [{"name": "bash"}]}

    assert len(registry.resolve(doc)) == 1


def test_resolve_empty_tools_config(registry: ToolRegistry) -> None:
    assert registry.resolve({}) == []
    assert registry.resolve({"tools": []}) == []


def test_resolve_tool_not_found_skipped(registry: ToolRegistry) -> None:
    """Unknown names log a warning and are skipped (never raise)."""
    doc = {"tools": [{"name": "ghost", "enabled": True}]}
    assert registry.resolve(doc) == []





def test_resolve_skips_reserved_v02_prefixes(registry: ToolRegistry) -> None:
    """skill: / mcp: entries are silently skipped (v0.2 territory)."""
    registry.register(_builtin_tool("bash"))
    doc = {
        "tools": [
            {"name": "bash", "enabled": True},
            {"name": "skill:code-review", "enabled": True},
            {"name": "mcp:github", "enabled": True},
        ]
    }

    resolved = registry.resolve(doc)
    assert [t.name for t in resolved] == ["bash"]


def test_resolve_skips_invalid_entries(registry: ToolRegistry) -> None:
    """Non-dict / missing-name entries are skipped, not raised."""
    registry.register(_builtin_tool("bash"))
    doc = {"tools": ["not-a-dict", {"enabled": True}, {"name": "bash", "enabled": True}]}

    resolved = registry.resolve(doc)
    assert [t.name for t in resolved] == ["bash"]


# ---------------------------------------------------------------------------
# list_builtin_tools()
# ---------------------------------------------------------------------------



def test_list_builtin_tools(registry: ToolRegistry) -> None:
    t1, t2 = _builtin_tool("bash"), _builtin_tool("read")
    registry.register(t1)
    registry.register(t2)
    listed = registry.list_builtin_tools()
    assert len(listed) == 2
    assert t1 in listed
    assert t2 in listed


# ---------------------------------------------------------------------------
# Global singleton
# ---------------------------------------------------------------------------


def test_global_singleton_is_tool_registry() -> None:
    assert isinstance(TOOL_REGISTRY, ToolRegistry)


def test_two_registrations_same_name_overwrite(registry: ToolRegistry) -> None:
    """Registering the same name twice keeps the latest registration."""
    first, second = _builtin_tool("bash", "v1"), _builtin_tool("bash", "v2")
    registry.register(first)
    registry.register(second)
    assert registry.get("bash") is second

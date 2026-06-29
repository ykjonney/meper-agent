"""AC1/AC2/AC7/AC8/AC9/AC10 cover: ToolRegistry register/resolve/list."""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from agent_flow_harness.tools.registry import TOOL_REGISTRY, ToolRegistry


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


def _builtin_tool(name: str, ret: str = "ok") -> StructuredTool:
    def _fn(**_kwargs: Any) -> str:  # noqa: ANN202
        return ret

    _fn.__name__ = name
    return StructuredTool.from_function(_fn, name=name, description=f"{name} tool")


class _EchoConfig(BaseModel):
    suffix: str = ""


class _EchoCommunityTool:
    """Minimal CommunityTool implementation for tests."""

    name = "echo"
    description = "echo community tool"
    config_schema = _EchoConfig
    enabled_by_default = False

    def __init__(self) -> None:
        self.build_calls: list[_EchoConfig] = []

    def build(self, config: _EchoConfig) -> StructuredTool:  # noqa: ANN101
        self.build_calls.append(config)

        def _fn(query: str = "") -> str:  # noqa: ANN202
            return f"echo:{query}{config.suffix}"

        return StructuredTool.from_function(_fn, name="echo", description="echo")


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
    """A non-BaseTool object without config_schema/build must expose .name."""

    class _Anon:
        pass

    with pytest.raises(TypeError):
        registry.register(_Anon())  # type: ignore[arg-type]


def test_register_community_tool(registry: ToolRegistry) -> None:
    ct = _EchoCommunityTool()
    registry.register(ct)
    assert registry.get("echo") is ct
    assert ct in registry.list_community_tools()


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


def test_resolve_builds_community_tool(registry: ToolRegistry) -> None:
    ct = _EchoCommunityTool()
    registry.register(ct)
    doc = {"tools": [{"name": "echo", "enabled": True, "config": {"suffix": "!"}}]}

    resolved = registry.resolve(doc)

    assert len(resolved) == 1
    assert resolved[0].name == "echo"
    assert len(ct.build_calls) == 1
    assert ct.build_calls[0].suffix == "!"
    # The built tool reflects the validated config.
    assert resolved[0].invoke({"query": "hi"}) == "echo:hi!"


def test_resolve_invalid_community_config_skipped(registry: ToolRegistry) -> None:
    """A config failing config_schema validation is skipped, not raised."""

    class _StrictConfig(BaseModel):
        api_key: str  # required, no default

    class _StrictCommunity:
        name = "strict"
        description = "d"
        config_schema = _StrictConfig
        enabled_by_default = False

        def build(self, config):  # noqa: ANN001, ANN202
            return _builtin_tool("strict")

    registry.register(_StrictCommunity())
    doc = {"tools": [{"name": "strict", "enabled": True, "config": {}}]}

    assert registry.resolve(doc) == []


def test_resolve_build_failure_skipped(registry: ToolRegistry) -> None:
    """A build() that raises is logged and skipped."""

    class _BoomConfig(BaseModel):
        pass

    class _BoomCommunity:
        name = "boom"
        description = "d"
        config_schema = _BoomConfig
        enabled_by_default = False

        def build(self, config):  # noqa: ANN001, ANN202
            raise RuntimeError("kaboom")

    registry.register(_BoomCommunity())
    doc = {"tools": [{"name": "boom", "enabled": True, "config": {}}]}

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
# list_community_tools() / list_builtin_tools()
# ---------------------------------------------------------------------------


def test_list_community_tools(registry: ToolRegistry) -> None:
    ct = _EchoCommunityTool()
    registry.register(ct)
    assert registry.list_community_tools() == [ct]


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

"""AC5/AC6 cover: resolve_variable use 字符串 + ToolRegistry.resolve use 分支。"""
from __future__ import annotations

import pytest

from agent_flow_harness.tools.resolver import resolve_variable
from agent_flow_harness.tools.registry import ToolRegistry


def test_resolve_variable_loads_tool():
    """'模块:符号' → 动态 import + 返回对象。"""
    from langchain_core.tools import BaseTool

    ts = resolve_variable("agent_flow_harness.interaction:tool_search", BaseTool)
    assert ts.name == "tool_search"


def test_resolve_variable_wrong_type_raises():
    """类型不匹配 → TypeError。"""
    # tool_search 是 BaseTool，期望 dict 类型 → 应报错
    with pytest.raises(TypeError):
        resolve_variable("agent_flow_harness.interaction:tool_search", dict)


def test_resolve_variable_missing_symbol_raises():
    """符号不存在 → AttributeError。"""
    from langchain_core.tools import BaseTool

    with pytest.raises(AttributeError):
        resolve_variable("agent_flow_harness.interaction:nonexistent_xyz", BaseTool)


def test_resolve_variable_missing_module_raises():
    """模块不存在 → ModuleNotFoundError。"""
    from langchain_core.tools import BaseTool

    with pytest.raises(ModuleNotFoundError):
        resolve_variable("agent_flow_harness.nonexistent_pkg:thing", BaseTool)


def test_resolve_variable_bad_format_raises():
    """格式错误（无冒号）→ ValueError。"""
    from langchain_core.tools import BaseTool

    with pytest.raises(ValueError):
        resolve_variable("no_colon_here", BaseTool)


# ---------------------------------------------------------------------------
# ToolRegistry.resolve use 分支 (AC6 向后兼容)
# ---------------------------------------------------------------------------


def test_registry_resolve_with_use_field():
    """AC6: agent_doc tool entry 带 use → 动态加载（不经 _lookup）。"""
    reg = ToolRegistry()  # 空注册表，没有预注册任何工具
    agent_doc = {
        "tools": [
            {
                "name": "search",
                "use": "agent_flow_harness.interaction:tool_search",
                "enabled": True,
            }
        ]
    }
    resolved = reg.resolve(agent_doc)
    assert len(resolved) == 1
    assert resolved[0].name == "tool_search"


def test_registry_resolve_without_use_uses_lookup():
    """无 use 字段 → 走原 _lookup 实例查找（向后兼容）。"""
    from langchain_core.tools import tool as lc_tool

    @lc_tool
    def my_tool(x: str) -> str:
        """A test tool."""
        return x

    reg = ToolRegistry()
    reg.register(my_tool)
    agent_doc = {"tools": [{"name": "my_tool", "enabled": True}]}
    resolved = reg.resolve(agent_doc)
    assert len(resolved) == 1
    assert resolved[0].name == "my_tool"


def test_registry_resolve_use_and_lookup_mix():
    """use 和非 use 混用：use 走动态加载，普通走 lookup。"""
    from langchain_core.tools import tool as lc_tool

    @lc_tool
    def local_tool(x: str) -> str:
        """Local tool."""
        return x

    reg = ToolRegistry()
    reg.register(local_tool)
    agent_doc = {
        "tools": [
            {"name": "local_tool", "enabled": True},
            {"name": "ts", "use": "agent_flow_harness.interaction:tool_search", "enabled": True},
        ]
    }
    resolved = reg.resolve(agent_doc)
    names = sorted(t.name for t in resolved)
    assert names == ["local_tool", "tool_search"]


def test_registry_resolve_bad_use_skipped():
    """use 加载失败 → 跳过（不 raise，与未知 name 行为一致）。"""
    reg = ToolRegistry()
    agent_doc = {
        "tools": [
            {"name": "bad", "use": "nonexistent.module:symbol", "enabled": True},
        ]
    }
    resolved = reg.resolve(agent_doc)
    assert resolved == []

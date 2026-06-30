"""tool_search 工具 — 按关键词检索可用工具。

三层工具模型第一层。读 TOOL_REGISTRY 进程单例（零注入），模糊匹配 query
与工具 name/description，返回匹配列表。工具太多时帮助 LLM 发现可用工具。
"""
from __future__ import annotations

from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field


class _ToolSearchArgs(BaseModel):
    """tool_search 的 LLM 可见参数。"""

    query: str = Field(..., description="搜索关键词，匹配工具名或描述")


async def _tool_search(query: str) -> str:
    """按关键词检索可用工具，返回匹配的工具列表。"""
    from agent_flow_harness.tools import TOOL_REGISTRY

    query_lower = query.lower()
    query_terms = query_lower.split()

    def _matches(haystack: str) -> bool:
        haystack = haystack.lower()
        return any(term in haystack for term in query_terms) or query_lower in haystack

    matches: list[tuple[str, str]] = []

    def _collect(tools: list[Any]) -> None:
        for t in tools:
            name = getattr(t, "name", "") or ""
            desc = getattr(t, "description", "") or ""
            if _matches(f"{name} {desc}"):
                matches.append((name, desc))

    # builtin 工具
    _collect(TOOL_REGISTRY.list_builtin_tools())

    # community 工具
    _collect(TOOL_REGISTRY.list_community_tools())

    # 去重
    seen: set[str] = set()
    unique: list[tuple[str, str]] = []
    for name, desc in matches:
        if name not in seen:
            seen.add(name)
            unique.append((name, desc))

    if not unique:
        return "(no matching tools found)"

    lines = [f"Found {len(unique)} tool(s):"]
    for name, desc in unique:
        short_desc = desc[:120] + "..." if len(desc) > 120 else desc
        lines.append(f"- {name}: {short_desc}")
    return "\n".join(lines)


tool_search = StructuredTool.from_function(
    _tool_search,
    name="tool_search",
    description="按关键词检索可用工具。当不确定有哪些工具可用时，用关键词搜索工具名和描述。",
    args_schema=_ToolSearchArgs,
    coroutine=_tool_search,
)


__all__ = ["tool_search"]

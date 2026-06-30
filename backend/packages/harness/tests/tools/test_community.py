"""AC4/AC9 cover: CommunityTool protocol is structurally satisfiable."""

from __future__ import annotations

from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from agent_flow_harness.tools.community import CommunityTool


class _SearchConfig(BaseModel):
    api_key_env: str = "SEARCH_API_KEY"
    max_results: int = 5


class _SearchCommunityTool:
    """A complete CommunityTool implementation (duck-typed, no inheritance)."""

    name = "web_search"
    description = "Search the web"
    config_schema = _SearchConfig
    enabled_by_default = False

    def build(self, config: _SearchConfig) -> StructuredTool:
        def _search(query: str) -> str:  # noqa: ANN202
            return f"[{config.api_key_env}] {query} ({config.max_results})"

        return StructuredTool.from_function(_search, name="web_search", description="search")


def test_community_tool_satisfies_protocol() -> None:
    """The duck-typed implementation is recognised by the runtime-checkable protocol."""
    assert isinstance(_SearchCommunityTool(), CommunityTool)


def test_community_tool_build_uses_validated_config() -> None:
    """build() receives a config validated by config_schema and returns a BaseTool."""
    tool = _SearchCommunityTool().build(_SearchConfig(api_key_env="MY_KEY", max_results=2))

    assert isinstance(tool, StructuredTool)
    assert tool.name == "web_search"
    assert tool.invoke({"query": "hi"}) == "[MY_KEY] hi (2)"

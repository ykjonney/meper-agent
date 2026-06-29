"""CommunityTool protocol — third-party pluggable tools.

A :class:`CommunityTool` is a factory that, given a Pydantic config, produces a
LangChain :class:`~langchain_core.tools.BaseTool`. Any package can implement
this protocol and register an instance with the harness
:class:`~agent_flow_harness.tools.registry.ToolRegistry`; ``resolve()`` will
then build it on demand per Agent document.

The protocol intentionally stays free of any backend dependency so it can be
satisfied by external PyPI packages without pulling in the harness runtime.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from pydantic import BaseModel

    from langchain_core.tools import BaseTool


@runtime_checkable
class CommunityTool(Protocol):
    """Third-party pluggable tool factory.

    Implementations are registered with the :class:`ToolRegistry` and built
    lazily by :meth:`ToolRegistry.resolve` using the per-Agent ``config``.

    Attributes:
        name: Stable identifier referenced from ``agent_doc["tools"]`` entries.
        description: Human-readable summary surfaced to the registry caller.
        config_schema: Pydantic model validating the ``config`` block of a
            tool entry before :meth:`build` runs.
        enabled_by_default: When ``True`` the registry may opt the tool in even
            if it is not explicitly listed (reserved for future use).
    """

    name: str
    description: str
    config_schema: type[BaseModel]
    enabled_by_default: bool

    def build(self, config: BaseModel) -> BaseTool:
        """Construct the concrete :class:`BaseTool` from a validated config.

        Args:
            config: An instance of ``self.config_schema`` already validated
                against the Agent's ``config`` block.

        Returns:
            A ready-to-use LangChain tool.
        """
        ...

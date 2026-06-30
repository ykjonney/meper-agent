"""ToolRegistry — the single protocol for wiring tools into Agents.

The registry holds two populations:

* **Built-in tools** — concrete :class:`~langchain_core.tools.BaseTool`
  instances (registered once at host-application startup).
* **Community tools** — :class:`~agent_flow_harness.tools.community.CommunityTool`
  factories, built lazily per Agent via their ``config_schema`` / ``build``.

Agent execution calls :meth:`ToolRegistry.resolve` with the Agent document;
the registry filters by the ``enabled`` flag and returns the resolved
:class:`BaseTool` list. The host decides *which* tools to register; the
registry never imports backend infrastructure.

A module-level :data:`TOOL_REGISTRY` singleton mirrors the legacy application
behaviour (process-global, set up once at startup).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeGuard

import structlog

from agent_flow_harness.tools.community import CommunityTool

if TYPE_CHECKING:
    from collections.abc import Sequence

    from langchain_core.tools import BaseTool

logger = structlog.get_logger(__name__)

# Tool-name prefixes reserved for v0.2 providers (skill / mcp). The registry
# silently skips them in v0.1 so an Agent document can already carry these
# entries without breaking resolve().
_RESERVED_PREFIXES: tuple[str, ...] = ("skill:", "mcp:")


class ToolRegistry:
    """Global registry of built-in and community tools.

    The registry is a plain in-memory store; it performs no I/O and carries no
    backend dependency. Callers own the lifecycle (register at startup, resolve
    per execution).
    """

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}
        self._community_tools: dict[str, CommunityTool] = {}

    # -- registration ------------------------------------------------------

    def register(self, tool: BaseTool | CommunityTool) -> None:
        """Register a built-in or community tool.

        A :class:`CommunityTool` (structurally — anything exposing
        ``config_schema`` + ``build``) is stored as a factory; anything else is
        treated as a concrete :class:`BaseTool` and keyed by its ``name``.

        Args:
            tool: A :class:`BaseTool` instance or a :class:`CommunityTool`.
        """
        if self._is_community_tool(tool):
            self._community_tools[tool.name] = tool
            logger.info("tool_registry_community_registered", name=tool.name)
        else:
            name = getattr(tool, "name", None)
            if not isinstance(name, str):
                msg = (
                    "Cannot register a built-in tool without a string .name "
                    f"(got {type(tool).__name__})."
                )
                raise TypeError(msg)
            self._tools[name] = tool  # type: ignore[assignment]
            logger.info("tool_registry_builtin_registered", name=name)

    def unregister(self, name: str) -> None:
        """Remove a previously-registered tool by name (built-in or community)."""
        self._tools.pop(name, None)
        self._community_tools.pop(name, None)

    # -- resolution --------------------------------------------------------

    def resolve(self, agent_doc: dict[str, Any]) -> list[BaseTool]:
        """Return the concrete tool list for an Agent document.

        Iterates ``agent_doc["tools"]`` (a list of ``{"name", "enabled",
        "config"?}`` dicts), skipping disabled entries and reserved v0.2
        prefixes. Built-in tools are returned as-is; community tools are built
        via their ``config_schema`` / ``build``. Unknown names log a warning
        and are skipped (never raise).

        Args:
            agent_doc: The Agent configuration document.

        Returns:
            A list of resolved :class:`BaseTool` instances.
        """
        tool_configs: Sequence[dict[str, Any]] = agent_doc.get("tools", []) or []
        resolved: list[BaseTool] = []

        for entry in tool_configs:
            if not isinstance(entry, dict):
                logger.warning("tool_registry_invalid_entry", entry=entry)
                continue
            if not entry.get("enabled", True):
                continue

            name = entry.get("name")
            if not isinstance(name, str):
                logger.warning("tool_registry_entry_missing_name", entry=entry)
                continue

            if name.startswith(_RESERVED_PREFIXES):
                # skill: / mcp: land in v0.2 (skills_fs / mcp adapter).
                logger.debug("tool_registry_reserved_prefix_skipped", name=name)
                continue

            # v0.2-x: use 字符串动态加载（有 use 走 resolve_variable，
            # 无 use 走原 _lookup 实例查找 —— 向后兼容）。
            use = entry.get("use")
            if isinstance(use, str) and use:
                try:
                    from langchain_core.tools import BaseTool

                    from agent_flow_harness.tools.resolver import resolve_variable

                    tool = resolve_variable(use, BaseTool)
                    resolved.append(tool)
                    logger.info("tool_registry_use_loaded", name=name, use=use)
                    continue
                except Exception as exc:  # noqa: BLE001 — skip, never raise
                    logger.warning(
                        "tool_registry_use_failed", name=name, use=use, error=str(exc)
                    )
                    continue

            tool = self._lookup(name, entry.get("config", {}))
            if tool is not None:
                resolved.append(tool)

        return resolved

    # -- introspection -----------------------------------------------------

    def list_community_tools(self) -> list[CommunityTool]:
        """Return all registered community tool factories (un-built)."""
        return list(self._community_tools.values())

    def list_builtin_tools(self) -> list[BaseTool]:
        """Return all registered built-in tools."""
        return list(self._tools.values())

    def get(self, name: str) -> BaseTool | CommunityTool | None:
        """Return a registered tool by name, or ``None`` if absent."""
        if name in self._tools:
            return self._tools[name]
        return self._community_tools.get(name)

    # -- internals ---------------------------------------------------------

    def _lookup(self, name: str, config: Any) -> BaseTool | None:
        if name in self._tools:
            return self._tools[name]
        community = self._community_tools.get(name)
        if community is None:
            logger.warning("tool_registry_tool_not_found", name=name)
            return None
        return self._build_community_tool(name, community, config)

    def _build_community_tool(
        self,
        name: str,
        community: CommunityTool,
        config: Any,
    ) -> BaseTool | None:
        config_data: dict[str, Any] = config if isinstance(config, dict) else {}
        try:
            validated = community.config_schema(**config_data)
        except Exception as exc:  # pydantic ValidationError or others
            logger.error(
                "tool_registry_config_invalid",
                name=name,
                error=str(exc),
            )
            return None
        try:
            return community.build(validated)
        except Exception as exc:  # noqa: BLE001 - surface build failures, skip
            logger.error(
                "tool_registry_build_failed",
                name=name,
                error=str(exc),
            )
            return None

    @staticmethod
    def _is_community_tool(tool: BaseTool | CommunityTool) -> TypeGuard[CommunityTool]:
        """Duck-type a CommunityTool without requiring it to inherit a base.

        Distinguishes a community *factory* (has ``config_schema`` + ``build``)
        from a concrete :class:`BaseTool`.
        """
        return (
            hasattr(tool, "config_schema")
            and hasattr(tool, "build")
            and callable(getattr(tool, "build", None))
        )


# Process-global singleton, mirroring the legacy application behaviour.
TOOL_REGISTRY = ToolRegistry()

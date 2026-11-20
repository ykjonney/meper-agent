"""Workspace 路径策略包 — CloudLayout/LocalLayout 双后端（见 layout.py 模块文档）。"""
from agent_flow_harness.workspace.cloud import CloudLayout
from agent_flow_harness.workspace.layout import (
    ResolvedPath,
    SetupSpec,
    WorkspaceLayout,
    is_within,
)
from agent_flow_harness.workspace.local import LocalLayout

__all__ = [
    "CloudLayout",
    "LocalLayout",
    "ResolvedPath",
    "SetupSpec",
    "WorkspaceLayout",
    "is_within",
]

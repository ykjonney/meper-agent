"""SubAgentRegistry — 子 Agent 配置的进程内存储。

与 v0.1 ToolRegistry 同构：plain in-memory store，无 I/O，宿主启动时注册。
子 Agent 必须预先注册（防 prompt injection 动态 spawn）。registry 只存
SubAgentSpec 纯数据；graph 的构建延迟到 delegate 工具被调用时。
"""
from __future__ import annotations

from agent_flow_harness.subagents.spec import SubAgentSpec


class SubAgentRegistry:
    """进程内子 Agent 配置注册中心。"""

    def __init__(self) -> None:
        self._specs: dict[str, SubAgentSpec] = {}

    def register(self, spec: SubAgentSpec) -> None:
        """注册一个子 Agent 配置。重名 raise ValueError。"""
        if spec.name in self._specs:
            msg = f"SubAgent '{spec.name}' already registered."
            raise ValueError(msg)
        self._specs[spec.name] = spec

    def get(self, name: str) -> SubAgentSpec:
        """按名查找；不存在 raise KeyError。"""
        if name not in self._specs:
            msg = f"SubAgent '{name}' not found."
            raise KeyError(msg)
        return self._specs[name]

    def list_names(self) -> list[str]:
        """返回所有已注册子 Agent 的名字。"""
        return list(self._specs.keys())


__all__ = ["SubAgentRegistry"]

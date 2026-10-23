"""Context Engineering 模块 — 上下文压缩与工具输出治理。

生产压缩路径为 llm_nodes._compress_by_turns（turns.py 分级压缩）。
"""
from agent_flow_harness.context_engineering.compact_circuit import compact_circuit
from agent_flow_harness.context_engineering.split import split_system_history
from agent_flow_harness.context_engineering.tool_output import compress_tool_outputs
from agent_flow_harness.context_engineering.turns import (
    DEFAULT_PROTECTED_TURNS,
    split_by_turns,
    split_for_compression,
)

__all__ = [
    "DEFAULT_PROTECTED_TURNS",
    "compact_circuit",
    "compress_tool_outputs",
    "split_by_turns",
    "split_for_compression",
    "split_system_history",
]

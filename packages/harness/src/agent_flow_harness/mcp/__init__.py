"""MCP 模块 — MCP 工具连接与加载（v0.2 增强）。

harness 提供 McpToolLoader，从连接配置加载 MCP 工具（langchain-mcp-adapters）。
应用层从 DB 读出连接配置传给 harness，harness 负责连接/缓存/工具名前缀。

langchain-mcp-adapters 为可选依赖（未安装时 load_tools 报 ImportError）。
"""
from agent_flow_harness.mcp.loader import McpConnectionConfig, McpToolLoader

__all__ = ["McpConnectionConfig", "McpToolLoader"]

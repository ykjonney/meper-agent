"""harness 版 stream 执行 — 委托给 harness_integration Adapter 层。

特性开关 ``USE_HARNESS_ENGINE=True`` 时由 ``stream_agent`` 端点调用。

本文件是薄包装,真正的装配逻辑(三层工具策略 / sandbox / workspace /
LLM / middleware)收敛在 ``harness_integration.resolve_harness_context`` 与
``harness_integration.run_chat`` 中,供 stream / invoke / workflow agent 节点
三条路径复用。

事件格式与老引擎完全一致(8 种 AppEvent),前端零改动。
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

StreamCallback = Callable[[dict[str, Any]], Awaitable[None]]


async def run_agent_streaming_harness(
    agent: dict[str, Any],
    state: dict[str, Any],
    on_event: StreamCallback,
    enable_thinking: bool = False,
    legacy_records: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """用 harness graph 执行 REACT 循环，通过 on_event 推送 AppEvent dict。

    薄包装,委托给 ``harness_integration.run_chat``。保留此函数是为了:
      - 兼容 ``agents.py:stream_agent`` 已有的 import 路径
      - 作为"流式执行"的语义入口(与 invoke 的非流式 run_once 区分)

    Args:
        agent: Agent 文档（from MongoDB）。
        state: 初始 AgentState（含 messages / session_id / user_id）。
        on_event: 异步回调，接收 **dict** 格式的 AppEvent（与老引擎一致）。
        enable_thinking: 是否启用 LLM 推理模式。
        legacy_records: 老session历史(可选,灌入 thread)。

    Returns:
        含 step_count 的 dict（端点仅用于日志，不依赖返回值拿最终文本）。
    """
    from app.engine.harness_integration import run_chat

    result = await run_chat(
        agent, state, on_event,
        enable_thinking=enable_thinking,
        legacy_records=legacy_records,
    )
    logger.info(
        "harness_stream_completed",
        agent_id=agent.get("_id"),
        request_id=state.get("request_id"),
    )
    return result

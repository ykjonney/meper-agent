"""SSE 流式响应辅助（api 层公共，无业务依赖）。"""
import asyncio

# 静默期心跳间隔：首事件前的准备段（查 agent/建会话/解析工具集/编译图）
# 与工具执行期间网络上完全静默，逐秒发注释心跳帧——客户端/中间代理保活，
# 也让"还没出字"与"连接挂了"可区分。
SSE_HEARTBEAT_INTERVAL = 1.0


async def sse_event_stream(event_queue: asyncio.Queue[str | None]):
    """转发事件队列中的 SSE 帧，静默期每秒发注释心跳帧。

    队列项已是完整 SSE 帧（``data: {...}\\n\\n``），``None`` 为结束哨兵。
    心跳 ``: ping\\n\\n`` 是 SSE 规范的注释行——标准解析器与本项目两个
    前端解析器（均只认 ``data:`` 前缀行）都会忽略，不参与事件语义。
    """
    while True:
        try:
            item = await asyncio.wait_for(
                event_queue.get(), timeout=SSE_HEARTBEAT_INTERVAL
            )
        except TimeoutError:
            yield ": ping\n\n"
            continue
        if item is None:
            break
        yield item

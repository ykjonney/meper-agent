"""Tests for app.api.sse.sse_event_stream（SSE 心跳转发）。

覆盖三条路径：事件透传、静默超时发注释心跳帧、None 哨兵结束。
心跳帧是 SSE 注释行（": ping"），前端解析器只认 data: 前缀行会忽略。
"""
import asyncio

from app.api.sse import SSE_HEARTBEAT_INTERVAL, sse_event_stream


async def test_forwards_events_and_stops_on_sentinel():
    queue: asyncio.Queue[str | None] = asyncio.Queue()
    queue.put_nowait('data: {"type":"text_delta"}\n\n')
    queue.put_nowait(None)

    frames = [frame async for frame in sse_event_stream(queue)]

    assert frames == ['data: {"type":"text_delta"}\n\n']


async def test_yields_heartbeat_on_idle():
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    # 空队列静默：应每 SSE_HEARTBEAT_INTERVAL 秒发一帧注释心跳
    gen = sse_event_stream(queue)
    try:
        first = await asyncio.wait_for(
            gen.__anext__(), timeout=SSE_HEARTBEAT_INTERVAL * 4
        )
        second = await asyncio.wait_for(
            gen.__anext__(), timeout=SSE_HEARTBEAT_INTERVAL * 4
        )
        assert first == ": ping\n\n"
        assert second == ": ping\n\n"
    finally:
        await gen.aclose()


async def test_heartbeat_then_event():
    queue: asyncio.Queue[str | None] = asyncio.Queue()

    async def delayed_event() -> None:
        # 首个事件晚于一个心跳周期到达（模拟首字前准备段）
        await asyncio.sleep(SSE_HEARTBEAT_INTERVAL * 1.5)
        queue.put_nowait('data: {"type":"start"}\n\n')
        queue.put_nowait(None)

    producer = asyncio.create_task(delayed_event())
    frames = [frame async for frame in sse_event_stream(queue)]
    await producer

    assert frames[0] == ": ping\n\n"
    assert frames[-1] == 'data: {"type":"start"}\n\n'

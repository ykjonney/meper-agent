from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from app.voice.config import ASRRuntime, TTSRuntime
from app.voice.providers.volcano import (
    ASR_CHUNK_BYTES,
    VolcanoASRClient,
    VolcanoTTSClient,
)
from app.voice.providers.volcano_protocol import EventType, MsgType, TTSMessage


@pytest.mark.asyncio
async def test_asr_dispatches_partial_once_and_each_definite_utterance_once() -> None:
    client = VolcanoASRClient(
        ASRRuntime(
            api_key="key",
            resource_id="volc.seedasr.sauc.duration",
            url="wss://example.test/asr",
        )
    )
    partial = AsyncMock()
    final = AsyncMock()
    ended = AsyncMock()
    client.bind(on_partial=partial, on_final=final, on_utterance_end=ended)

    await client._dispatch_result({"result": {"text": "你"}})
    await client._dispatch_result({"result": {"text": "你"}})
    response = {
        "result": {
            "text": "你好。",
            "utterances": [
                {
                    "text": "你好。",
                    "start_time": 0,
                    "end_time": 500,
                    "definite": True,
                }
            ],
        }
    }
    await client._dispatch_result(response)
    await client._dispatch_result(response)

    partial.assert_awaited_once_with("你")
    final.assert_awaited_once_with("你好。")
    ended.assert_awaited_once()


@pytest.mark.asyncio
async def test_asr_aggregates_browser_frames_into_200ms_chunks() -> None:
    client = VolcanoASRClient(
        ASRRuntime(
            api_key="key",
            resource_id="volc.seedasr.sauc.duration",
            url="wss://example.test/asr",
        )
    )
    client._ws = AsyncMock()

    browser_frame = bytes(640)  # PCM16 mono @16kHz, 20 ms
    for _ in range(9):
        await client.feed(browser_frame)
    client._ws.send.assert_not_awaited()

    await client.feed(browser_frame)

    client._ws.send.assert_awaited_once()
    assert len(client._audio_buffer) == 0
    assert ASR_CHUNK_BYTES == 6400


@pytest.mark.asyncio
async def test_tts_stop_discards_interrupted_connection() -> None:
    client = VolcanoTTSClient(
        TTSRuntime(
            api_key="key",
            resource_id="seed-tts-2.0",
            url="wss://example.test/tts",
            voice_type="test-speaker",
        )
    )
    ws = AsyncMock()
    client._ws = ws
    client._session_id = "interrupted-session"

    await client.stop()

    ws.send.assert_awaited_once()
    cancel = TTSMessage.from_bytes(ws.send.await_args.args[0])
    assert cancel.event == EventType.CANCEL_SESSION
    assert cancel.session_id == "interrupted-session"
    ws.close.assert_awaited_once()
    assert client._ws is None
    assert client._session_id == ""


async def test_tts_chunks_use_independent_protocol_sessions(monkeypatch):
    client = VolcanoTTSClient(
        TTSRuntime(api_key="key", resource_id="tts", url="wss://tts", voice_type="v")
    )
    client._ws = AsyncMock()
    monkeypatch.setattr(client, "_ensure_open", AsyncMock())
    replies = []
    for _ in range(2):
        replies.extend([
            SimpleNamespace(type=MsgType.FULL_SERVER_RESPONSE, event=EventType.SESSION_STARTED),
            SimpleNamespace(type=MsgType.AUDIO_ONLY_SERVER, event=None, payload=b"pcm"),
            SimpleNamespace(type=MsgType.FULL_SERVER_RESPONSE, event=EventType.SESSION_FINISHED),
        ])
    monkeypatch.setattr(client, "_receive", AsyncMock(side_effect=replies))
    assert [chunk async for chunk in client.synth_stream("文" * 331)] == [b"pcm", b"pcm"]
    sent = [TTSMessage.from_bytes(call.args[0]) for call in client._ws.send.await_args_list]
    requests = [msg for msg in sent if msg.event == EventType.TASK_REQUEST]
    assert len(requests) == 2
    assert requests[0].session_id != requests[1].session_id
    assert client._session_id == ""


async def test_tts_stop_while_opening_does_not_start_session(monkeypatch):
    client = VolcanoTTSClient(
        TTSRuntime(api_key="key", resource_id="tts", url="wss://tts", voice_type="v")
    )
    monkeypatch.setattr(client, "_ensure_open", client.stop)
    assert [chunk async for chunk in client.synth_stream("你好")] == []

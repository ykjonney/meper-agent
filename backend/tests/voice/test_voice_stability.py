from unittest.mock import AsyncMock, Mock, patch

import pytest
from app.voice import api
from app.voice.session import _VOICE_MODE_PROMPT
from app.voice.turn import TurnContext

from tests.voice.helpers import FakeWebSocket, make_session, runtime_config


@pytest.mark.parametrize("enabled", [True, False])
async def test_voice_prompt_follows_playback_switch(enabled):
    session = make_session(FakeWebSocket())
    session.agent_id = "agent-1"
    session.cfg.tts_enabled = enabled
    assemble = Mock(return_value=[])
    with (
        patch(
            "app.services.agent_service.AgentService.get_agent",
            new=AsyncMock(return_value={"_id": "agent-1"}),
        ),
        patch(
            "app.services.agent_execution_service._resolve_session",
            new=AsyncMock(return_value="session-1"),
        ),
        patch(
            "app.services.agent_execution_service._build_system_prompt_checked",
            new=AsyncMock(return_value="原有指令"),
        ),
        patch("app.services.agent_execution_service._assemble_messages", new=assemble),
        patch(
            "app.services.agent_execution_service._build_initial_state",
            new=Mock(return_value={}),
        ),
        patch(
            "app.services.agent_execution_service._record_execution_log",
            new=AsyncMock(),
        ),
        patch(
            "app.engine.harness_integration.stream",
            new=AsyncMock(return_value={"usage": {}}),
        ),
    ):
        await session._exec_brain(TurnContext(transcript="你好"))
    system_text, transcript = assemble.call_args.args
    assert transcript == "你好"
    assert system_text == (
        f"原有指令\n\n{_VOICE_MODE_PROMPT}" if enabled else "原有指令"
    )
    await session.close()


async def test_disconnect_event_exits_receive_loop_and_closes_session(monkeypatch):
    ws = Mock()
    ws.accept = AsyncMock()
    ws.receive = AsyncMock(
        side_effect=[
            {"type": "websocket.disconnect"},
            AssertionError("must not receive again"),
        ]
    )
    session = Mock()
    session.close = AsyncMock()
    session.on_audio = AsyncMock()
    session.on_control = AsyncMock()
    logger = Mock()
    monkeypatch.setattr(api, "verify_ws_token", lambda _: "user-1")
    monkeypatch.setattr(
        api, "get_runtime_config", AsyncMock(return_value=runtime_config())
    )
    monkeypatch.setattr(api, "VoiceSession", lambda *args, **kwargs: session)
    monkeypatch.setattr(api, "logger", logger)

    await api.voice_realtime(ws, token="test-token")

    ws.receive.assert_awaited_once()
    session.close.assert_awaited_once()
    session.on_audio.assert_not_awaited()
    session.on_control.assert_not_awaited()
    logger.warning.assert_not_called()

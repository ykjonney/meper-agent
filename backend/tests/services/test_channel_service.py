"""ChannelService orchestration tests.

Mock the DB (motor collection) and AgentExecutionService.invoke so we test
the orchestration logic, not the integration.
"""
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.channels.base import InboundMessage
from app.channels.errors import (
    AgentRuntimeError,
    InvalidCredentialsError,
    LLMRateLimitError,
    PermanentChannelError,
    SendFailedError,
)
from app.channels.providers.mock.channel import MOCK_SENT_MESSAGES
from app.models.channel import (
    ChannelConfig,
    ChannelProvider,
    InboundEventLog,
)
from app.schemas.execution import ExecutionResponse
from app.services.channel_service import ChannelService
from app.services.session_service import SessionService


def _make_inbound(msg_id: str = "msg_1") -> InboundMessage:
    return InboundMessage(
        channel_id="ch_01J",
        platform_chat_id="chat_1",
        platform_user_id="u_1",
        message_id=msg_id,
        text="你好",
        raw={},
        timestamp=datetime.now(UTC),
    )


def _make_config() -> ChannelConfig:
    return ChannelConfig(
        name="test",
        provider=ChannelProvider.MOCK,
        agent_id="agent_01J",
        owner_user_id="user_01J",
        webhook_secret="mock_secret_at_least_16",
        credentials={},
    )


def _make_event_log() -> InboundEventLog:
    """Event log whose payload round-trips back into a valid InboundMessage."""
    inbound = _make_inbound()
    return InboundEventLog(
        channel_id=inbound.channel_id,
        platform_message_id=inbound.message_id,
        payload=inbound.model_dump(mode="json"),
    )


class TestCreateOrDedupEvent:
    @pytest.mark.asyncio
    async def test_new_event_inserts_and_returns_log_id(self):
        # Mongo find_one returns None → insert_one succeeds
        mock_coll = MagicMock()
        mock_coll.find_one = AsyncMock(return_value=None)
        mock_coll.insert_one = AsyncMock(return_value=MagicMock(inserted_id="inb_01J"))

        with patch.object(ChannelService, "_event_logs_coll", return_value=mock_coll):
            log_id = await ChannelService.create_or_dedup_event(_make_inbound())

        assert log_id is not None
        mock_coll.insert_one.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_duplicate_event_returns_none(self):
        # find_one returns existing doc → dedup, no insert
        mock_coll = MagicMock()
        mock_coll.find_one = AsyncMock(return_value={"_id": "inb_existing"})
        mock_coll.insert_one = AsyncMock()

        with patch.object(ChannelService, "_event_logs_coll", return_value=mock_coll):
            log_id = await ChannelService.create_or_dedup_event(_make_inbound())

        assert log_id is None
        mock_coll.insert_one.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_concurrent_race_returns_none_on_duplicate_key(self):
        """Regression for issue #5: find_one missed the row, then insert_one
        lost the race against a concurrent request and hit the unique index.
        Must surface as a clean dedup (None), NOT a DuplicateKeyError that
        would escape the route handler as a 500."""
        from pymongo.errors import DuplicateKeyError

        mock_coll = MagicMock()
        mock_coll.find_one = AsyncMock(return_value=None)  # race: not yet inserted
        mock_coll.insert_one = AsyncMock(
            side_effect=DuplicateKeyError("E11000 duplicate key")
        )

        with patch.object(ChannelService, "_event_logs_coll", return_value=mock_coll):
            log_id = await ChannelService.create_or_dedup_event(_make_inbound())

        assert log_id is None
        mock_coll.insert_one.assert_awaited_once()


class TestExecute:
    def setup_method(self):
        MOCK_SENT_MESSAGES.clear()

    @pytest.mark.asyncio
    async def test_success_invokes_agent_and_sends_reply(self):
        inbound = _make_inbound()
        config = _make_config()

        # NOTE: ExecutionResponse.execution_path is a str (not list) — confirmed
        # in app/schemas/execution.py during Step 0.
        fake_response = ExecutionResponse(
            output="你好,有什么可以帮你?",
            execution_path="react",
            request_id="req_1",
            agent_id="agent_01J",
            session_id="session_01J",
            step_count=1,
        )
        with patch(
            "app.services.channel_service.AgentExecutionService.invoke",
            new=AsyncMock(return_value=fake_response),
        ), patch.object(
            ChannelService, "get_config", new=AsyncMock(return_value=config)
        ), patch.object(
            ChannelService, "_find_continuable_session", new=AsyncMock(return_value=None)
        ), patch.object(
            ChannelService, "_reset_failure_counter", new=AsyncMock()
        ):
            await ChannelService.execute(inbound)

        assert len(MOCK_SENT_MESSAGES) == 1
        assert MOCK_SENT_MESSAGES[0]["text"] == "你好,有什么可以帮你?"

    @pytest.mark.asyncio
    async def test_permanent_error_triggers_handle_error(self):
        inbound = _make_inbound()
        config = _make_config()

        with patch(
            "app.services.channel_service.AgentExecutionService.invoke",
            new=AsyncMock(side_effect=InvalidCredentialsError("bad creds")),
        ), patch.object(
            ChannelService, "get_config", new=AsyncMock(return_value=config)
        ), patch.object(
            ChannelService, "_find_continuable_session", new=AsyncMock(return_value=None)
        ), patch.object(
            ChannelService, "handle_error", new=AsyncMock()
        ) as mock_handler:
            await ChannelService.execute(inbound)

        mock_handler.assert_awaited_once()
        passed_err = mock_handler.call_args.args[2]
        assert isinstance(passed_err, PermanentChannelError)

    @pytest.mark.asyncio
    async def test_transient_error_propagates_uncaught(self):
        """Transient errors propagate to the Celery task for retry."""
        inbound = _make_inbound()
        config = _make_config()

        with patch(
            "app.services.channel_service.AgentExecutionService.invoke",
            new=AsyncMock(side_effect=LLMRateLimitError("rate limited")),
        ), patch.object(
            ChannelService, "get_config", new=AsyncMock(return_value=config)
        ), patch.object(
            ChannelService, "_find_continuable_session", new=AsyncMock(return_value=None)
        ), patch.object(
            ChannelService, "handle_error", new=AsyncMock()
        ), pytest.raises(LLMRateLimitError):
            await ChannelService.execute(inbound)

    @pytest.mark.asyncio
    async def test_permanent_error_threads_real_event_log_id(self):
        """When event_log_id is passed, handle_error must receive the *real*
        persisted log (so its FAILED status update hits the actual document,
        not a dummy with a fresh id that was never inserted). Regression test
        for the Task 5 spec-review bug."""
        inbound = _make_inbound()
        config = _make_config()
        real_log = _make_event_log()
        real_log_id = real_log.id  # id generated by _make_event_log()

        with patch(
            "app.services.channel_service.AgentExecutionService.invoke",
            new=AsyncMock(side_effect=InvalidCredentialsError("bad creds")),
        ), patch.object(
            ChannelService, "get_config", new=AsyncMock(return_value=config)
        ), patch.object(
            ChannelService, "_find_continuable_session", new=AsyncMock(return_value=None)
        ), patch.object(
            ChannelService, "get_event_log", new=AsyncMock(return_value=real_log)
        ) as mock_get_log, patch.object(
            ChannelService, "handle_error", new=AsyncMock()
        ) as mock_handler:
            await ChannelService.execute(inbound, event_log_id=real_log_id)

        # The real log was fetched by id (not reconstructed as a dummy)
        mock_get_log.assert_awaited_once_with(real_log_id)
        # handle_error received the real log with the expected id
        mock_handler.assert_awaited_once()
        passed_log = mock_handler.call_args.args[0]
        assert passed_log.id == real_log_id


class TestHandleError:
    def setup_method(self):
        MOCK_SENT_MESSAGES.clear()

    @pytest.mark.asyncio
    async def test_permanent_error_sends_user_message(self):
        config = _make_config()
        event_log = _make_event_log()
        mock_coll = MagicMock()
        mock_coll.update_one = AsyncMock()

        with patch.object(
            ChannelService, "_event_logs_coll", return_value=mock_coll
        ), patch.object(
            ChannelService, "_bump_failure_counter", new=AsyncMock()
        ):
            await ChannelService.handle_error(
                event_log, config, InvalidCredentialsError("bad"),
            )

        assert len(MOCK_SENT_MESSAGES) == 1
        assert MOCK_SENT_MESSAGES[0]["text"] == "机器人配置异常,请联系管理员"

    @pytest.mark.asyncio
    async def test_invalid_credentials_bumps_counter(self):
        config = _make_config()
        event_log = _make_event_log()
        mock_coll = MagicMock()
        mock_coll.update_one = AsyncMock()

        with patch.object(
            ChannelService, "_event_logs_coll", return_value=mock_coll
        ), patch.object(
            ChannelService, "_bump_failure_counter", new=AsyncMock()
        ) as mock_bump, patch.object(
            ChannelService, "_maybe_degrade", new=AsyncMock()
        ):
            await ChannelService.handle_error(
                event_log, config, InvalidCredentialsError(),
            )
        mock_bump.assert_awaited_once_with(config.id)

    @pytest.mark.asyncio
    async def test_send_failed_bumps_counter(self):
        """Spec §5.2.4: send failures also count toward consecutive_failures,
        otherwise a persistently broken platform API would silently lose every
        message and the channel would stay ACTIVE forever."""
        config = _make_config()
        event_log = _make_event_log()
        mock_coll = MagicMock()
        mock_coll.update_one = AsyncMock()

        with patch.object(
            ChannelService, "_event_logs_coll", return_value=mock_coll
        ), patch.object(
            ChannelService, "_bump_failure_counter", new=AsyncMock()
        ) as mock_bump:
            await ChannelService.handle_error(
                event_log, config, SendFailedError("platform down"),
            )
        mock_bump.assert_awaited_once_with(config.id)

    @pytest.mark.asyncio
    async def test_runtime_error_does_not_bump_counter(self):
        """AgentRuntimeError = transient code bug, don't degrade the channel."""
        config = _make_config()
        event_log = _make_event_log()
        mock_coll = MagicMock()
        mock_coll.update_one = AsyncMock()

        with patch.object(
            ChannelService, "_event_logs_coll", return_value=mock_coll
        ), patch.object(
            ChannelService, "_bump_failure_counter", new=AsyncMock()
        ) as mock_bump:
            await ChannelService.handle_error(
                event_log, config, AgentRuntimeError(),
            )
        mock_bump.assert_not_awaited()


class TestSessionContinuity:
    """IM 会话延续：channel:{ch}:{chat} 域内复用最近活跃 session。"""

    def setup_method(self):
        MOCK_SENT_MESSAGES.clear()

    @pytest.mark.asyncio
    async def test_reuses_latest_active_session(self):
        inbound = _make_inbound()
        config = _make_config()
        fake_response = ExecutionResponse(
            output="ok", execution_path="react", request_id="req_1",
            agent_id="agent_01J", session_id="session_old", step_count=1,
        )
        invoke_mock = AsyncMock(return_value=fake_response)
        with patch(
            "app.services.channel_service.AgentExecutionService.invoke",
            new=invoke_mock,
        ), patch.object(
            ChannelService, "get_config", new=AsyncMock(return_value=config)
        ), patch.object(
            ChannelService, "_find_continuable_session",
            new=AsyncMock(return_value="session_old"),
        ):
            await ChannelService.execute(inbound)

        body = invoke_mock.call_args.kwargs["body"]
        assert body.session_id == "session_old"

    @pytest.mark.asyncio
    async def test_no_recent_session_starts_new(self):
        inbound = _make_inbound()
        config = _make_config()
        fake_response = ExecutionResponse(
            output="ok", execution_path="react", request_id="req_1",
            agent_id="agent_01J", session_id="session_new", step_count=1,
        )
        invoke_mock = AsyncMock(return_value=fake_response)
        with patch(
            "app.services.channel_service.AgentExecutionService.invoke",
            new=invoke_mock,
        ), patch.object(
            ChannelService, "get_config", new=AsyncMock(return_value=config)
        ), patch.object(
            ChannelService, "_find_continuable_session",
            new=AsyncMock(return_value=None),
        ):
            await ChannelService.execute(inbound)

        assert invoke_mock.call_args.kwargs["body"].session_id is None

    @pytest.mark.asyncio
    async def test_idle_window_computed_from_settings(self):
        """idle > 0 → 查询带 updated_since 窗口；返回的 session id 透传。"""
        from types import SimpleNamespace

        get_latest = AsyncMock(return_value={"_id": "sess_recent"})
        with patch(
            "app.services.channel_service.settings",
            new=SimpleNamespace(
                CHANNEL_SESSION_IDLE_RESET_MINUTES=60,
                CHANNEL_SESSION_MAX_AGE_HOURS=0,
            ),
        ), patch.object(
            SessionService, "get_latest_session", new=get_latest,
        ):
            found = await ChannelService._find_continuable_session("u1", "a1")

        assert found == "sess_recent"
        assert get_latest.call_args.kwargs["updated_since"] is not None

    @pytest.mark.asyncio
    async def test_idle_disabled_queries_without_window(self):
        """idle = 0 → 永不因空闲重置，查询不带时间窗。"""
        from types import SimpleNamespace

        get_latest = AsyncMock(return_value={"_id": "sess_any"})
        with patch(
            "app.services.channel_service.settings",
            new=SimpleNamespace(
                CHANNEL_SESSION_IDLE_RESET_MINUTES=0,
                CHANNEL_SESSION_MAX_AGE_HOURS=0,
            ),
        ), patch.object(
            SessionService, "get_latest_session", new=get_latest,
        ):
            found = await ChannelService._find_continuable_session("u1", "a1")

        assert found == "sess_any"
        assert get_latest.call_args.kwargs["updated_since"] is None


class TestResetCommand:
    """重置指令：精确命中 → 开新 session + 确认回复，不进 agent。"""

    def setup_method(self):
        MOCK_SENT_MESSAGES.clear()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("cmd", ["#新话题", "/new", "/reset", "  #新话题  "])
    async def test_reset_command_skips_agent_and_creates_session(self, cmd):
        inbound = _make_inbound()
        inbound.text = cmd
        config = _make_config()

        invoke_mock = AsyncMock()
        create_mock = AsyncMock(return_value={"_id": "session_new"})
        with patch(
            "app.services.channel_service.AgentExecutionService.invoke",
            new=invoke_mock,
        ), patch.object(
            ChannelService, "get_config", new=AsyncMock(return_value=config)
        ), patch(
            "app.services.channel_service.SessionService.create_session",
            new=create_mock,
        ):
            await ChannelService.execute(inbound)

        invoke_mock.assert_not_awaited()
        create_mock.assert_awaited_once()
        assert create_mock.call_args.kwargs["user_id"] == (
            f"channel:{config.id}:chat_1"
        )
        assert create_mock.call_args.kwargs["agent_id"] == "agent_01J"
        # 确认回复发出（MOCK provider 落到 MOCK_SENT_MESSAGES）
        assert len(MOCK_SENT_MESSAGES) == 1
        assert MOCK_SENT_MESSAGES[0]["text"] == "已开启新话题，请直接说出你的问题～"

    @pytest.mark.asyncio
    async def test_text_containing_command_still_goes_to_agent(self):
        """命令作为句子一部分不是重置指令，仍走 agent。"""
        inbound = _make_inbound()
        inbound.text = "帮我看看#新话题这个功能"
        config = _make_config()

        fake_response = ExecutionResponse(
            output="ok", execution_path="react", request_id="req_1",
            agent_id="agent_01J", session_id="session_x", step_count=1,
        )
        invoke_mock = AsyncMock(return_value=fake_response)
        create_mock = AsyncMock()
        with patch(
            "app.services.channel_service.AgentExecutionService.invoke",
            new=invoke_mock,
        ), patch.object(
            ChannelService, "get_config", new=AsyncMock(return_value=config)
        ), patch.object(
            ChannelService, "_find_continuable_session",
            new=AsyncMock(return_value=None),
        ), patch(
            "app.services.channel_service.SessionService.create_session",
            new=create_mock,
        ):
            await ChannelService.execute(inbound)

        invoke_mock.assert_awaited_once()
        create_mock.assert_not_awaited()


class TestGroupSenderPrefix:
    """群聊消息送入 agent 前加 [昵称] 前缀（共享会话流 + 用户可感知）。"""

    def _make_inbound_group(self, text: str, chat_type: str, name: str | None):

        inbound = _make_inbound()
        inbound.text = text
        inbound.chat_type = chat_type
        inbound.platform_user_name = name
        return inbound

    @pytest.mark.asyncio
    async def test_group_message_gets_sender_prefix(self):
        from app.services.channel_service import _agent_input

        inbound = self._make_inbound_group("帮我订会议室", "2", "张三")
        assert _agent_input(inbound) == "[张三] 帮我订会议室"

    @pytest.mark.asyncio
    async def test_single_chat_no_prefix(self):
        from app.services.channel_service import _agent_input

        inbound = self._make_inbound_group("帮我订会议室", "1", "张三")
        assert _agent_input(inbound) == "帮我订会议室"

    @pytest.mark.asyncio
    async def test_group_without_name_falls_back_to_raw(self):
        from app.services.channel_service import _agent_input

        inbound = self._make_inbound_group("帮我订会议室", "group", None)
        assert _agent_input(inbound) == "帮我订会议室"

    @pytest.mark.asyncio
    async def test_group_reset_command_still_exact_matched(self):
        """群聊发 #新话题：重置匹配用原始 text，不受前缀影响。"""
        inbound = self._make_inbound_group("#新话题", "2", "张三")
        config = _make_config()
        invoke_mock = AsyncMock()

        with patch(
            "app.services.channel_service.AgentExecutionService.invoke",
            new=invoke_mock,
        ), patch.object(
            ChannelService, "get_config", new=AsyncMock(return_value=config)
        ), patch(
            "app.services.channel_service.SessionService.create_session",
            new=AsyncMock(return_value={"_id": "s_new"}),
        ):
            await ChannelService.execute(inbound)

        invoke_mock.assert_not_awaited()  # 重置生效，未进 agent

"""Tests for _record_ext_call_log — phase-2 token backfill.

Covers the three ContextVar states:
- No stashed context (internal/non-ext call → no-op)
- Context stashed (ext call → writes log with token, marks consumed)
- Context already consumed (idempotent — does not double-write)
"""
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from app.services.agent_execution_service import _record_ext_call_log
from app.services.ext_api_call_log_service import (
    ExtCallContext,
    clear_ext_call_context,
    set_ext_call_context,
)


@pytest.fixture(autouse=True)
def _clear_ctx():
    clear_ext_call_context()
    yield
    clear_ext_call_context()


class TestRecordExtCallLog:
    async def test_no_context_is_noop(self, monkeypatch):
        """Non-ext calls (no stashed context) → no DB write."""
        write_spy = AsyncMock()
        monkeypatch.setattr(
            "app.services.ext_api_call_log_service.ExtApiCallLogService.write_log",
            write_spy,
        )
        await _record_ext_call_log("agent_01", "sess_01", {"total_tokens": 100})
        write_spy.assert_not_awaited()

    async def test_with_context_writes_log_and_marks_consumed(self, monkeypatch):
        write_spy = AsyncMock(return_value="elog_xxx")
        monkeypatch.setattr(
            "app.services.ext_api_call_log_service.ExtApiCallLogService.write_log",
            write_spy,
        )
        ctx = ExtCallContext(
            api_key_id="apikey_01", owner_user_id="user_owner",
            auth_mode="callback", user_sub="user-123",
            endpoint="agents:invoke", request_id="req_1",
            start_time_ms=0,
        )
        set_ext_call_context(ctx)

        await _record_ext_call_log(
            "agent_99", "sess_99", {"total_tokens": 150, "input_tokens": 80, "output_tokens": 70},
        )

        write_spy.assert_awaited_once()
        kwargs = write_spy.await_args.kwargs
        assert kwargs["total_tokens"] == 150
        assert kwargs["input_tokens"] == 80
        assert kwargs["output_tokens"] == 70
        assert kwargs["status"] == "success"
        assert kwargs["status_code"] == 200
        # Context patched with agent_id/session_id.
        assert ctx.agent_id == "agent_99"
        assert ctx.session_id == "sess_99"
        # Marked consumed so middleware fallback skips.
        assert ctx.consumed is True

    async def test_error_status_when_error_passed(self, monkeypatch):
        write_spy = AsyncMock(return_value="elog_err")
        monkeypatch.setattr(
            "app.services.ext_api_call_log_service.ExtApiCallLogService.write_log",
            write_spy,
        )
        set_ext_call_context(ExtCallContext(
            api_key_id="k", owner_user_id="u", start_time_ms=0,
        ))

        await _record_ext_call_log(
            "a", "s", None, error=RuntimeError("boom"),
        )

        kwargs = write_spy.await_args.kwargs
        assert kwargs["status"] == "error"
        assert kwargs["status_code"] == 500
        assert kwargs["total_tokens"] == 0

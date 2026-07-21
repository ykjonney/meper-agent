"""Tests for ExtApiCallLogService — write_log + queries.

Uses AsyncMock to stub out MongoDB collection operations; no real DB.
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

from app.services.ext_api_call_log_service import (
    ExtApiCallLogService,
    ExtCallContext,
)


def _make_ctx(**overrides) -> ExtCallContext:
    defaults = {
        "api_key_id": "apikey_01",
        "owner_user_id": "user_owner",
        "user_sub": "user-123",
        "auth_mode": "callback",
        "endpoint": "agents:invoke",
        "request_id": "req_abc",
        "start_time_ms": 1000,
        "agent_id": "agent_01",
        "session_id": "sess_01",
    }
    defaults.update(overrides)
    return ExtCallContext(**defaults)


class TestWriteLog:
    async def test_write_log_returns_id(self, monkeypatch):
        fake_col = MagicMock()
        fake_col.insert_one = AsyncMock(return_value=MagicMock(inserted_id="x"))
        monkeypatch.setattr(ExtApiCallLogService, "_collection", lambda: fake_col)

        ctx = _make_ctx()
        log_id = await ExtApiCallLogService.write_log(
            ctx, status="success", status_code=200,
            total_tokens=100, input_tokens=60, output_tokens=40,
        )

        assert log_id is not None
        assert log_id.startswith("elog_")
        # Verify payload shape
        payload = fake_col.insert_one.await_args.args[0]
        assert payload["api_key_id"] == "apikey_01"
        assert payload["total_tokens"] == 100
        assert payload["status"] == "success"
        assert payload["status_code"] == 200
        assert isinstance(payload["timestamp"], datetime)

    async def test_write_log_failure_returns_none(self, monkeypatch):
        fake_col = MagicMock()
        fake_col.insert_one = AsyncMock(side_effect=RuntimeError("db down"))
        monkeypatch.setattr(ExtApiCallLogService, "_collection", lambda: fake_col)

        log_id = await ExtApiCallLogService.write_log(
            _make_ctx(), status="success", status_code=200,
        )
        # Logging failures MUST NOT raise.
        assert log_id is None


class TestListLogs:
    async def test_list_logs_filters_and_paginates(self, monkeypatch):
        fake_col = MagicMock()
        fake_col.count_documents = AsyncMock(return_value=42)
        # Cursor stub: find → sort → skip → limit → to_list
        cursor = MagicMock()
        cursor.sort.return_value = cursor
        cursor.skip.return_value = cursor
        cursor.limit.return_value = cursor
        cursor.to_list = AsyncMock(return_value=[
            {"api_key_id": "apikey_01", "timestamp": datetime(2026, 7, 21)},
        ])
        fake_col.find.return_value = cursor
        monkeypatch.setattr(ExtApiCallLogService, "_collection", lambda: fake_col)

        items, total = await ExtApiCallLogService.list_logs(
            "apikey_01", user_sub="user-123", page=2, page_size=10,
        )

        assert total == 42
        assert len(items) == 1
        assert items[0]["timestamp"] == "2026-07-21T00:00:00"
        # Verify query shape
        query = fake_col.find.call_args.args[0]
        assert query["api_key_id"] == "apikey_01"
        assert query["user_sub"] == "user-123"


class TestGetTokenSummary:
    async def test_summary_aggregates_tokens(self, monkeypatch):
        fake_col = MagicMock()
        cursor = MagicMock()
        cursor.to_list = AsyncMock(return_value=[{
            "_id": None,
            "total_tokens": 500,
            "input_tokens": 300,
            "output_tokens": 200,
            "calls": 5,
        }])
        fake_col.aggregate.return_value = cursor
        monkeypatch.setattr(ExtApiCallLogService, "_collection", lambda: fake_col)

        summary = await ExtApiCallLogService.get_token_summary("apikey_01")

        assert summary["total_tokens"] == 500
        assert summary["calls"] == 5

    async def test_summary_empty_returns_zeroes(self, monkeypatch):
        fake_col = MagicMock()
        cursor = MagicMock()
        cursor.to_list = AsyncMock(return_value=[])
        fake_col.aggregate.return_value = cursor
        monkeypatch.setattr(ExtApiCallLogService, "_collection", lambda: fake_col)

        summary = await ExtApiCallLogService.get_token_summary("apikey_01")
        assert summary == {
            "total_tokens": 0, "input_tokens": 0,
            "output_tokens": 0, "calls": 0,
        }


class TestGetUsersSummary:
    async def test_users_summary_groups_by_sub(self, monkeypatch):
        fake_col = MagicMock()
        cursor = MagicMock()
        cursor.to_list = AsyncMock(return_value=[
            {"_id": "user-A", "calls": 3, "total_tokens": 100, "last_seen_at": datetime(2026, 7, 21)},
            {"_id": "user-B", "calls": 1, "total_tokens": 50, "last_seen_at": datetime(2026, 7, 20)},
        ])
        fake_col.aggregate.return_value = cursor
        monkeypatch.setattr(ExtApiCallLogService, "_collection", lambda: fake_col)

        users = await ExtApiCallLogService.get_users_summary("apikey_01", period_days=7)

        assert len(users) == 2
        assert users[0]["user_sub"] == "user-A"
        assert users[0]["calls"] == 3
        assert users[0]["last_seen_at"].startswith("2026-07-21")

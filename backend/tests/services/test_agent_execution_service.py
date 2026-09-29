"""Tests for AgentExecutionService — execution orchestration.

Covers the pure helper logic (error-source classification) that the stream/
resume top-level except blocks rely on to populate ErrorEvent.source, plus
the call-timing helpers (duration split / TTFT) used to locate slow calls.
"""
import asyncio

import pytest
from app.core import perf
from app.services.agent_execution_service import (
    _TTFT_EVENT_TYPES,
    _classify_error_source,
    _compose_phase_timing,
    _duration_metrics,
    _emit_stream_done,
    _now_ms,
    _request_usage,
)

# ── _classify_error_source ──────────────────────────────────────────────────


def test_classify_llm_error_by_type():
    """LLM 限流类异常（类型名含 ratelimit）归 llm。"""
    class RateLimitError(Exception):
        pass
    assert _classify_error_source(RateLimitError("too many")) == "llm"


def test_classify_llm_error_by_message():
    """错误消息含 LLM 关键词（如 quota）归 llm。"""
    assert _classify_error_source(Exception("insufficient_quota for model")) == "llm"


def test_classify_generic_error_as_graph():
    """未识别的异常归 graph。"""
    assert _classify_error_source(RuntimeError("unexpected")) == "graph"


def test_classify_empty_message_returns_graph():
    """无异常信息时归 graph。"""
    assert _classify_error_source(Exception("")) == "graph"


# ── _duration_metrics — usage 秒 → 毫秒耗时拆分 ─────────────────────────────


def test_duration_metrics_converts_seconds_and_derives_other():
    """usage 中浮点秒 duration 换算毫秒，other = latency - llm - tool。"""
    start = _now_ms() - 10_000  # 10s ago
    m = _duration_metrics(
        {"llm_duration": 7.0, "tool_duration": 2.0, "input_tokens": 80, "output_tokens": 20},
        start_time_ms=start,
        ttft_ms=1_200,
    )
    assert m["total_latency_ms"] >= 10_000
    assert m["llm_duration_ms"] == 7_000
    assert m["tool_duration_ms"] == 2_000
    assert m["ttft_ms"] == 1_200
    # other = latency - 7000 - 2000（latency ≥ 10000，可能略大）
    assert m["other_duration_ms"] == m["total_latency_ms"] - 9_000


def test_duration_metrics_clamps_negative_other():
    """monotonic 与墙钟做差可能轻微为负 —— other clamp ≥ 0。"""
    start = _now_ms() - 100  # 100ms 前开始
    m = _duration_metrics(
        {"llm_duration": 0.5, "tool_duration": 0.0},  # 500ms > latency
        start_time_ms=start,
    )
    assert m["other_duration_ms"] == 0


def test_duration_metrics_without_usage_or_start():
    """无 usage / 无 start_time_ms 时全 0（invoke 兜底、ext 兜底路径）。"""
    m = _duration_metrics(None, start_time_ms=None)
    assert m == {
        "total_latency_ms": 0,
        "llm_duration_ms": 0,
        "tool_duration_ms": 0,
        "other_duration_ms": 0,
        "ttft_ms": 0,
    }


def test_ttft_event_types_cover_token_events():
    """TTFT 事件类型覆盖文本/思考的 delta 与完成事件。"""
    assert set(_TTFT_EVENT_TYPES) == {"text_delta", "thinking_delta", "text", "thinking"}


# ── _emit_stream_done — done 事件 usage 补毫秒拆分 ──────────────────────────


@pytest.mark.asyncio
async def test_emit_stream_done_injects_timing_fields():
    """start_time_ms 提供时，done 事件的 usage 带毫秒级耗时拆分。"""
    import json

    queue: asyncio.Queue = asyncio.Queue()
    usage = {"llm_duration": 2.5, "tool_duration": 0.5, "total_tokens": 100}
    await _emit_stream_done(
        queue, request_id="req_1", session_id="sess_1",
        usage=usage, start_time_ms=_now_ms() - 4_000, ttft_ms=800,
    )
    raw = queue.get_nowait()
    payload = json.loads(raw.removeprefix("data: ").strip())
    u = payload["usage"]
    assert payload["done"] is True
    assert u["total_latency_ms"] >= 4_000
    assert u["llm_duration_ms"] == 2_500
    assert u["tool_duration_ms"] == 500
    assert u["ttft_ms"] == 800
    assert u["other_duration_ms"] == u["total_latency_ms"] - 3_000
    # 原始秒字段保留（兼容既有消费方），且原 dict 未被修改
    assert u["llm_duration"] == 2.5
    assert usage.get("total_latency_ms") is None
    # 收尾哨兵
    assert queue.get_nowait() is None


@pytest.mark.asyncio
async def test_emit_stream_done_without_start_keeps_usage_as_is():
    """未提供 start_time_ms 时不注入 timing 字段（保持原 usage）。"""
    import json

    queue: asyncio.Queue = asyncio.Queue()
    await _emit_stream_done(
        queue, request_id="req_1", session_id="sess_1", usage={"total_tokens": 5},
    )
    raw = queue.get_nowait()
    u = json.loads(raw.removeprefix("data: ").strip())["usage"]
    assert u == {"total_tokens": 5}


# ── 同 session 并发写 checkpointer 防护（#10）───────────────────────────────


@pytest.mark.asyncio
async def test_find_runs_by_session_filters_active_and_session():
    """find_runs_by_session 只返回指定 session 上未完成（活跃）的 run。"""
    from unittest.mock import patch

    from app.services import run_registry
    from app.services.run_registry import ActiveRun, find_runs_by_session

    running = asyncio.Future()
    done = asyncio.Future()
    done.set_result(None)

    runs = {
        "r1": ActiveRun(task=running, request_id="r1", agent_id="a", user_id="u", session_id="s1"),
        "r2": ActiveRun(task=done, request_id="r2", agent_id="a", user_id="u", session_id="s1"),
        "r3": ActiveRun(task=running, request_id="r3", agent_id="a", user_id="u", session_id="s2"),
    }
    with patch.object(run_registry, "_ACTIVE_RUNS", runs):
        assert [r.request_id for r in find_runs_by_session("s1")] == ["r1"]


@pytest.mark.asyncio
async def test_cancel_runs_by_session_cancels_and_sets_flag():
    """cancel_runs_by_session 取消同 session 残留 run 并打取消标志。"""
    from unittest.mock import AsyncMock, patch

    from app.services import run_registry
    from app.services.run_registry import ActiveRun, cancel_runs_by_session

    stale_task = asyncio.Future()
    stale = ActiveRun(
        task=stale_task, request_id="stale-1", agent_id="a",
        user_id="u", session_id="s1",
    )

    with (
        patch.object(run_registry, "_ACTIVE_RUNS", {"stale-1": stale}),
        patch.object(run_registry, "set_cancel_flag", new=AsyncMock()) as mock_flag,
    ):
        await cancel_runs_by_session("s1")

    assert stale_task.cancelled()
    mock_flag.assert_awaited_once_with("stale-1")


@pytest.mark.asyncio
async def test_stream_cancels_stale_runs_same_session():
    """同 session 残留活跃 run 时，新 stream 启动前调用并发防护。"""
    from unittest.mock import AsyncMock, MagicMock, patch

    from app.services import agent_execution_service as svc

    async def fake_harness_stream(*_args, **_kwargs):
        return {"step_count": 1, "usage": None}

    with (
        patch.object(svc, "_resolve_session", new=AsyncMock(return_value="s1")),
        patch.object(svc, "AgentService") as mock_agent,
        patch.object(svc, "_build_system_prompt_checked", new=AsyncMock(return_value="sys")),
        patch.object(svc, "cancel_runs_by_session", new=AsyncMock()) as mock_cancel,
        patch.object(svc, "register_run"),
        patch.object(svc, "make_cancel_checker", return_value=AsyncMock()),
        patch.object(svc, "_build_user_content", new=AsyncMock(return_value="uc")),
        patch.object(svc, "_assemble_messages", return_value=[]),
        patch.object(svc, "_load_legacy_records", new=AsyncMock(return_value=[])),
        patch.object(svc, "SessionService") as mock_session,
        patch.object(svc, "_build_initial_state", return_value={}),
        patch.object(svc, "_persist_agent_message", new=AsyncMock()),
        patch.object(svc, "_record_execution_log", new=AsyncMock()),
        patch("app.engine.harness_integration.stream", new=fake_harness_stream),
    ):
        mock_agent.get_agent = AsyncMock(return_value={"_id": "a"})
        mock_session.get_session = AsyncMock(return_value={})

        queue, request_id, session_id = await svc.AgentExecutionService.stream(
            "a", MagicMock(input="hi"), "u",
        )

        # 并发防护在 stream 返回前已执行（create_task 之前）
        mock_cancel.assert_awaited_once_with("s1")

        # 消费 done + sentinel，等后台 _run 收尾，避免 pending task 泄漏
        await queue.get()
        await queue.get()
        await asyncio.sleep(0)


# ── perf.timed_phase — DEBUG 门控分段计时 ───────────────────────────────────


def test_phases_if_debug_gated_by_settings(monkeypatch):
    """DEBUG=true 返回空 dict（调用方收集）；false 返回 None（关闭信号）。"""
    monkeypatch.setattr(perf.settings, "DEBUG", True)
    assert perf.phases_if_debug() == {}
    monkeypatch.setattr(perf.settings, "DEBUG", False)
    assert perf.phases_if_debug() is None


def test_timed_phase_accumulates_milliseconds():
    """同名阶段多次计时应累加（毫秒整数）。"""
    phases: dict[str, int] = {}
    with perf.timed_phase(phases, "build_tools_mcp"):
        pass
    with perf.timed_phase(phases, "build_tools_mcp"):
        pass
    assert phases["build_tools_mcp"] >= 0  # 计时两次，值非负
    assert len(phases) == 1


def test_timed_phase_none_is_passthrough():
    """phases=None（DEBUG 关闭）时直通，不建 dict 不抛错。"""
    with perf.timed_phase(None, "anything"):
        pass  # 零开销直通


def test_timed_phase_records_on_exception():
    """块内抛异常也照常记录已耗时间（finally 语义）。"""
    phases: dict[str, int] = {}
    with pytest.raises(RuntimeError), perf.timed_phase(phases, "boom"):
        raise RuntimeError("x")
    assert "boom" in phases


# ── _compose_phase_timing — 阶段日志字段合成 ────────────────────────────────


def test_compose_phase_timing_full_split():
    """完整链路：prep/build/exec/llm/tool/graph_overhead/persist + build 子阶段平铺。"""
    result_timing = {
        "build_ms": 780,
        "exec_ms": 11650,
        "phases": {"build_llm_client_ms": 80, "build_tools_mcp_ms": 620},
    }
    usage = {"llm_duration": 10.1, "tool_duration": 1.4}
    f = _compose_phase_timing(result_timing, usage, prep_ms=350, persist_ms=120)
    assert f["prep_ms"] == 350
    assert f["build_ms"] == 780
    assert f["exec_ms"] == 11650
    assert f["llm_ms"] == 10100
    assert f["tool_ms"] == 1400
    assert f["graph_overhead_ms"] == 11650 - 10100 - 1400
    assert f["persist_ms"] == 120
    # build 子阶段平铺并入同一 dict
    assert f["build_llm_client_ms"] == 80
    assert f["build_tools_mcp_ms"] == 620


def test_compose_phase_timing_none_when_debug_off():
    """result_timing 为 None（DEBUG=false 时 execution.py 不注入）→ 不输出。"""
    assert _compose_phase_timing(None, {"llm_duration": 1.0}) is None


def test_compose_phase_timing_clamps_negative_overhead():
    """llm+tool 超过 exec（monotonic 与墙钟做差）→ graph_overhead clamp ≥ 0。"""
    f = _compose_phase_timing(
        {"build_ms": 1, "exec_ms": 100, "phases": {}},
        {"llm_duration": 0.2, "tool_duration": 0.0},  # 200ms > exec 100ms
    )
    assert f["graph_overhead_ms"] == 0


def test_compose_phase_timing_missing_values_default_zero():
    """缺 prep/persist/usage（如 invoke 无 persist、异常路径）→ 字段兜底 0。"""
    f = _compose_phase_timing({"build_ms": 5, "exec_ms": 50}, None)
    assert f["prep_ms"] == 0
    assert f["persist_ms"] == 0
    assert f["llm_ms"] == 0
    assert f["tool_ms"] == 0
    assert f["graph_overhead_ms"] == 50


class TestChannelMessagePersistence:
    """IM 渠道会话默认不落 messages 明细（上下文由 checkpointer 承载），
    但 updated_at 必须照常推进——它是会话延续空闲窗口的时钟。"""

    async def test_channel_user_skips_messages_but_bumps_updated_at(self):
        from unittest.mock import AsyncMock, patch

        from app.schemas.execution import ExecutionRequest
        from app.services import agent_execution_service as aes

        body = ExecutionRequest(input="你好")
        created = {"_id": "session_ch1"}

        with patch.object(
            aes.SessionService, "create_session",
            new=AsyncMock(return_value=created),
        ) as mock_create, patch.object(
            aes.SessionService, "update_session", new=AsyncMock(),
        ) as mock_update, patch.object(
            aes.MessageService, "add_message", new=AsyncMock(),
        ) as mock_add:
            session_id = await aes._resolve_session("agent_1", body, "channel:ch_1:cid_1")

        assert session_id == "session_ch1"
        mock_create.assert_awaited_once()
        mock_add.assert_not_awaited()          # 不落明细
        mock_update.assert_awaited_once()      # 但推进 updated_at
        assert mock_update.call_args.args[1] == {}

    async def test_web_user_persists_messages_as_before(self):
        from unittest.mock import AsyncMock, patch

        from app.schemas.execution import ExecutionRequest
        from app.services import agent_execution_service as aes

        body = ExecutionRequest(input="你好", session_id="session_web1")

        with patch.object(
            aes.SessionService, "update_session", new=AsyncMock(),
        ) as mock_update, patch.object(
            aes.MessageService, "add_message", new=AsyncMock(),
        ) as mock_add:
            session_id = await aes._resolve_session("agent_1", body, "user_01J")

        assert session_id == "session_web1"
        mock_add.assert_awaited_once()         # Web 用户照常落明细
        mock_update.assert_not_awaited()

    async def test_channel_user_persists_when_flag_enabled(self):
        from types import SimpleNamespace
        from unittest.mock import AsyncMock, patch

        from app.schemas.execution import ExecutionRequest
        from app.services import agent_execution_service as aes

        body = ExecutionRequest(input="你好", session_id="session_ch2")

        with patch(
            "app.core.config.settings",
            new=SimpleNamespace(CHANNEL_PERSIST_MESSAGES=True),
        ), patch.object(
            aes.SessionService, "update_session", new=AsyncMock(),
        ) as mock_update, patch.object(
            aes.MessageService, "add_message", new=AsyncMock(),
        ) as mock_add:
            await aes._resolve_session("agent_1", body, "channel:ch_1:cid_1")

        mock_add.assert_awaited_once()         # 开关打开 → 审计模式落明细
        mock_update.assert_not_awaited()


class TestChannelSessionCleanup:
    """渠道旧会话按保留期级联清理（只碰 channel: 前缀，Web 会话不动）。"""

    async def test_cleanup_deletes_only_expired_channel_sessions(self):
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.services import session_service as ss

        class _AsyncIter:
            def __init__(self, items): self._it = iter(items)
            def __aiter__(self):
                return self

            async def __anext__(self):
                try:
                    return next(self._it)
                except StopIteration:
                    raise StopAsyncIteration from None

        mock_coll = MagicMock()
        mock_coll.find.return_value.limit.return_value = _AsyncIter([
            {"_id": "session_old_1"}, {"_id": "session_old_2"},
        ])

        with patch.object(ss.SessionService, "_collection", return_value=mock_coll), \
             patch.object(
                 ss.SessionService, "delete_session", new=AsyncMock(),
             ) as mock_del:
            n = await ss.SessionService.cleanup_channel_sessions(7)

        assert n == 2
        assert mock_del.await_count == 2
        query = mock_coll.find.call_args.args[0]
        assert query["user_id"] == {"$regex": "^channel:"}  # 只碰渠道会话
        assert "$lt" in query["updated_at"]



# ── _request_usage — mw.summary 运行累计 → 本轮真实增量 ──────────────────────


def test_request_usage_strips_seed_from_total():
    """seed 过的累计 total 扣除 session 历史累计，换算后 total = input + output。"""
    u = _request_usage(
        {"total_tokens": 2_050, "input_tokens": 800, "output_tokens": 250, "llm_calls": 2},
        seed_tokens=1_000,
    )
    assert u["total_tokens"] == 1_050
    assert u["total_tokens"] == u["input_tokens"] + u["output_tokens"]
    assert u["llm_calls"] == 2  # 其余字段原样保留


def test_request_usage_clamps_negative_delta():
    """total < seed（异常数据）时 clamp ≥ 0，不出现负数被 $inc。"""
    assert _request_usage({"total_tokens": 30}, seed_tokens=100)["total_tokens"] == 0


def test_request_usage_passthrough_on_empty():
    """None / 空 usage 原样返回（cancelled、guard 静默路径兜底）。"""
    assert _request_usage(None, seed_tokens=500) is None
    assert _request_usage({}, seed_tokens=500) == {}
    # seed=0（新 session / 工作流节点）时即本轮值，不变
    assert _request_usage({"total_tokens": 7}, seed_tokens=0)["total_tokens"] == 7


# ── token 累计回归：session total 按本轮增量线性增长（防指数膨胀）────────────


class TestSessionTokenAccumulation:
    """mw.summary 的 total_tokens 被 seed 过（session 历史累计 + 本轮）。
    落库必须只加本轮增量——否则 S_N = 2·S_{N-1} + T_N，每轮近翻倍。"""

    async def test_stream_session_total_grows_linearly_across_rounds(self):
        """连续两轮各耗 100 tokens → session 累计 200（bug 下第二轮会 $inc 200 得 300）。"""
        import json
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.services import agent_execution_service as svc

        session_store = {"s1": {"_id": "s1", "total_tokens": 0}}
        round_delta = 100

        async def fake_harness_stream(_doc, initial_state, on_event=None, **_kw):
            # 模拟 UsageMiddleware 的 seeding：summary.total = seed + 本轮
            seed = int(initial_state.get("total_tokens", 0) or 0)
            await on_event({"type": "text", "content": "hi"})
            return {
                "step_count": 1,
                "usage": {
                    "total_tokens": seed + round_delta,
                    "input_tokens": 80, "output_tokens": 20, "llm_calls": 1,
                },
            }

        async def fake_add_tokens(session_id: str, tokens: int):
            session_store[session_id]["total_tokens"] += tokens

        async def consume_done(queue: asyncio.Queue) -> dict:
            """消费至哨兵，返回 done 事件。"""
            events: list[dict] = []
            while True:
                item = await queue.get()
                if item is None:
                    return events[-1]
                events.append(json.loads(item.removeprefix("data: ").strip()))

        with (
            patch.object(svc, "_resolve_session", new=AsyncMock(return_value="s1")),
            patch.object(svc, "AgentService") as mock_agent,
            patch.object(svc, "_build_system_prompt_checked", new=AsyncMock(return_value="sys")),
            patch.object(svc, "_build_user_content", new=AsyncMock(return_value="uc")),
            patch.object(svc, "_assemble_messages", return_value=[]),
            patch.object(svc, "_load_legacy_records", new=AsyncMock(return_value=[])),
            patch.object(svc.SessionService, "get_session", new=AsyncMock(return_value=session_store["s1"])),
            patch.object(svc.SessionService, "add_tokens", new=fake_add_tokens),
            patch.object(svc.MessageService, "add_message", new=AsyncMock()) as mock_add_message,
            patch.object(svc, "_record_execution_log", new=AsyncMock()),
            patch.object(svc, "cancel_runs_by_session", new=AsyncMock()),
            patch.object(svc, "register_run"),
            patch.object(svc, "make_cancel_checker", return_value=AsyncMock()),
            patch("app.engine.harness_integration.stream", new=fake_harness_stream),
        ):
            mock_agent.get_agent = AsyncMock(return_value={"_id": "a"})

            done_1 = await consume_done((await svc.AgentExecutionService.stream(
                "a", MagicMock(input="hi"), "u",
            ))[0])
            done_2 = await consume_done((await svc.AgentExecutionService.stream(
                "a", MagicMock(input="hi"), "u",
            ))[0])

        # session 累计 = 两轮真实增量之和，线性不翻倍
        assert session_store["s1"]["total_tokens"] == 2 * round_delta
        # 每轮 done 事件的 usage 都是本轮值，且 total = in + out
        for done in (done_1, done_2):
            u = done["usage"]
            assert u["total_tokens"] == round_delta
            assert u["total_tokens"] == u["input_tokens"] + u["output_tokens"]
        # 消息 token_usage 同为本轮增量
        add_calls = mock_add_message.await_args_list
        assert [c.kwargs["token_usage"]["total_tokens"] for c in add_calls] == [
            round_delta, round_delta,
        ]

    async def test_invoke_persists_usage_and_adds_delta(self):
        """invoke（非流式）也落 token_usage 并按增量累计（原路径完全不计数）。"""
        from unittest.mock import AsyncMock, MagicMock, patch

        from app.services import agent_execution_service as svc

        async def fake_harness_invoke(*_args, **_kw):
            # session total=500 为 seed，本轮真实消耗 200
            return {
                "messages": [],
                "execution_path": "react",
                "usage": {"total_tokens": 700, "input_tokens": 150, "output_tokens": 50, "llm_calls": 1},
            }

        with (
            patch.object(svc, "_resolve_session", new=AsyncMock(return_value="s1")),
            patch.object(svc, "AgentService") as mock_agent,
            patch.object(svc, "_build_system_prompt_checked", new=AsyncMock(return_value="sys")),
            patch.object(svc, "_build_user_content", new=AsyncMock(return_value="uc")),
            patch.object(svc, "_assemble_messages", return_value=[]),
            patch.object(svc, "_load_legacy_records", new=AsyncMock(return_value=[])),
            patch.object(svc, "SessionService") as mock_session,
            patch.object(svc, "MessageService") as mock_message,
            patch.object(svc, "_record_execution_log", new=AsyncMock()) as mock_log,
            patch.object(svc, "_should_persist_messages", return_value=True),
            patch.object(svc, "extract_final_answer", return_value="ok"),
            patch.object(svc, "messages_to_timeline_entries", return_value=[]),
            patch("app.engine.harness_integration.invoke", new=fake_harness_invoke),
        ):
            mock_agent.get_agent = AsyncMock(return_value={"_id": "a"})
            mock_session.get_session = AsyncMock(return_value={"total_tokens": 500})
            mock_session.add_tokens = AsyncMock()
            mock_message.add_message = AsyncMock()

            resp = await svc.AgentExecutionService.invoke(
                "a", MagicMock(input="hi", enable_thinking=False), "u",
            )

        assert resp.output == "ok"
        # 消息 token_usage = 本轮增量（700 − seed 500）
        persisted = mock_message.add_message.call_args.kwargs["token_usage"]
        assert persisted["total_tokens"] == 200
        # session 只加增量 200，不是 seed 过的 700
        mock_session.add_tokens.assert_awaited_once_with("s1", 200)
        # execution_log 同口径
        assert mock_log.call_args.kwargs["token_usage"]["total_tokens"] == 200

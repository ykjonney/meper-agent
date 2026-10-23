"""按轮次/段分区测试 — split_by_turns / split_for_compression 的边界与切分。"""
from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent_flow_harness.context_engineering.turns import (
    DEFAULT_PROTECTED_TURNS,
    count_turns,
    split_by_turns,
    split_for_compression,
)


def _history(n_turns: int) -> list:
    """构造 n_turns 轮历史(每轮 Human + AI),不含 system。"""
    msgs = []
    for i in range(n_turns):
        msgs.append(HumanMessage(content=f"q{i}", id=f"h{i}"))
        msgs.append(AIMessage(content=f"a{i}", id=f"a{i}"))
    return msgs


def test_count_turns_counts_human_messages() -> None:
    assert count_turns(_history(3)) == 3
    assert count_turns([]) == 0


def test_split_enough_turns() -> None:
    """7轮:倒数第5个 HumanMessage(含)之后是 recent(5轮),之前是 outer(2轮)。"""
    history = _history(7)
    outer, recent = split_by_turns(history, n_turns=5)
    # recent 应含最近5轮 = 10条;outer 含最早2轮 = 4条。
    assert len(recent) == 10
    assert len(outer) == 4
    # recent 第一个应是倒数第5个 HumanMessage(h2)。
    assert isinstance(recent[0], HumanMessage)
    assert recent[0].content == "q2"
    # outer 最后一个应是 a1(第2轮的AI)。
    assert outer[-1].content == "a1"


def test_split_insufficient_turns_all_recent() -> None:
    """不足5轮:全部归入 recent,outer 为空。"""
    history = _history(3)
    outer, recent = split_by_turns(history, n_turns=5)
    assert outer == []
    assert len(recent) == 6


def test_split_exactly_n_turns_all_recent() -> None:
    """正好5轮:全部是 recent(没有5轮之外)。"""
    history = _history(5)
    outer, recent = split_by_turns(history, n_turns=5)
    assert outer == []
    assert len(recent) == 10


def test_default_protected_turns_is_5() -> None:
    assert DEFAULT_PROTECTED_TURNS == 5


def test_split_with_tool_messages_in_turns() -> None:
    """工具消息跟在 AI 后,按 HumanMessage 切分时落在正确的段。"""
    history = [
        HumanMessage(content="q0", id="h0"),
        AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "c0"}]),
        ToolMessage(content="r0", tool_call_id="c0"),
        AIMessage(content="a0"),
        HumanMessage(content="q1", id="h1"),
        AIMessage(content="a1"),
    ]
    # n_turns=1: 只有最后一轮(q1,a1)是 recent,q0 那轮(含工具)在 outer。
    outer, recent = split_by_turns(history, n_turns=1)
    assert recent[0].content == "q1"
    assert any(isinstance(m, ToolMessage) for m in outer)


# ---------------------------------------------------------------------------
# split_for_compression — agent 长任务切分(token 预算 + 段边界 + 锚定)
# ---------------------------------------------------------------------------


def _task_history(n_batches: int, *, tool_chars: int = 200) -> list:
    """单任务指令 + n_batches 个工具批次的 agent 长任务历史(不含 system)。

    每批 = AIMessage(tool_calls) + ToolMessage —— 复刻 workflow agent 节点
    的典型形态(1 条 user message + 几十次工具往返,旧轮语义的盲区场景)。
    """
    msgs = [HumanMessage(content="执行长任务", id="task")]
    for i in range(n_batches):
        msgs.append(
            AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": f"c{i}"}])
        )
        msgs.append(ToolMessage(content="r" * tool_chars, tool_call_id=f"c{i}"))
    return msgs


def test_long_task_outer_nonempty_and_anchored() -> None:
    """长任务核心修复:outer 非空(可压缩)+ 任务指令锚定在 recent[0]。

    旧 split_by_turns 在此场景 outer 恒空 → LLM 摘要永不触发。
    """
    history = _task_history(50)
    # 窗口 10k → 预算 1500 tok,每批 ~54 tok → 保护 ~27 批,outer ~23 批。
    outer, recent = split_for_compression(history, context_window=10_000)
    assert outer, "长任务的 outer 必须非空(否则摘要永不触发——旧盲区)"
    # 任务指令锚定:永不进 outer。
    assert recent[0].content == "执行长任务"
    assert not any(
        isinstance(m, HumanMessage) and m.content == "执行长任务" for m in outer
    )
    # outer 开头是完整批次边界(带 tool_calls 的 AIMessage)。
    assert getattr(outer[0], "tool_calls", None)


def test_long_task_recent_within_budget_plus_one_batch() -> None:
    """保护窗 token ≤ 预算 + 单批溢出(预算是软目标,切点 snap 到段边界)。"""
    # 每批 ~54 tok(200字符ASCII/4+4+4+...);预算 15000 → 保护 ~270 批?
    # 用小预算更直观:窗口 20000 → 预算 3000 → 保护 ~55 批内。
    history = _task_history(100, tool_chars=200)
    outer, recent = split_for_compression(history, context_window=20_000)
    # recent token 应在预算(3000)附近,允许最后一个纳入段的溢出。
    from agent_flow_harness.engine.context import estimate_messages_tokens

    recent_tokens = estimate_messages_tokens(recent)
    assert recent_tokens <= 3000 + 60  # 预算 + 单批(~54)溢出
    assert recent_tokens > 3000 - 500  # 且接近预算(不至于过保护)


def test_min_batches_floor_when_batches_huge() -> None:
    """大批次场景:单批 token 超预算时仍保护最近 min_batches 批(下限硬)。"""
    # 每批 100k 字符 ≈ 25k tok,预算 15k —— 最近 3 批无条件保护。
    history = _task_history(10, tool_chars=100_000)
    outer, recent = split_for_compression(history, context_window=100_000)
    # recent = 任务指令 + 最近 3 批(每批2条) = 7 条。
    assert len(recent) == 7
    assert len(outer) == 14


def test_few_batches_all_protected() -> None:
    """段总量不足(≤ min_batches)→ 全保护,等价旧行为(早期历史不多)。"""
    history = _task_history(3)
    outer, recent = split_for_compression(history, context_window=100_000)
    assert outer == []
    assert len(recent) == 7


def test_chat_multi_turn_cut_matches_legacy_plus_anchor() -> None:
    """chat 多轮(human ≥ 5):切点与旧 split_by_turns 一致 + 首条用户消息锚定。"""
    history = _history(7)
    outer, recent = split_for_compression(
        history, protected_turns=5, context_window=1_000_000,
    )
    old_outer, old_recent = split_by_turns(history, n_turns=5)
    # 锚定:首条 h0 从 outer 剥到 recent 头部。
    assert recent[0].content == "q0"
    assert [m.content for m in recent[1:]] == [m.content for m in old_recent]
    assert [m.content for m in outer] == [m.content for m in old_outer[1:]]


def test_split_never_tears_tool_pairing() -> None:
    """配对完整性:outer/recent 两侧各自 tool_call 与 tool_result 完整配对。"""
    history = _task_history(30, tool_chars=1_000)
    outer, recent = split_for_compression(history, context_window=10_000)

    for part in (outer, recent):
        call_ids = {
            tc["id"]
            for m in part
            if isinstance(m, AIMessage)
            for tc in (getattr(m, "tool_calls", None) or [])
        }
        result_ids = {
            m.tool_call_id for m in part if isinstance(m, ToolMessage)
        }
        assert call_ids == result_ids, "切点撕裂了 tool_call/tool_result 配对"


def test_anchor_takes_precedence_over_budget() -> None:
    """预算极小(甚至0)时锚定消息仍在 recent——锚定优先级高于预算。"""
    history = _task_history(10)
    outer, recent = split_for_compression(
        history, context_window=1,  # 预算 max(1, 0) = 1 tok
    )
    assert recent[0].content == "执行长任务"

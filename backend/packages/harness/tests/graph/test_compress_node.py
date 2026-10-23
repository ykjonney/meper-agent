"""compress_node / llm_node 测试 — system 连续性与历史替换语义。

回归 ``Received multiple non-consecutive system messages``：压缩后历史必须
整体替换（而非追加），且所有 SystemMessage 连续在最前。
"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, RemoveMessage, SystemMessage, ToolMessage

from agent_flow_harness.graph.nodes.llm_nodes import (
    _system_messages_first,
    compress_node,
)


def _config(llm=None, *, context_window=None) -> dict:
    configurable: dict = {}
    if llm is not None:
        configurable["llm"] = llm
    if context_window is not None:
        configurable["context_window"] = context_window
    return {"configurable": configurable}


class _RecordingLLM:
    """记录每次 ainvoke 收到的 messages，返回固定 AIMessage。"""

    def __init__(self, reply: str = "done") -> None:
        self._reply = reply
        self.calls: list[list] = []

    @property
    def model_name(self) -> str:
        return "gpt-4o-mini"

    def bind_tools(self, _tools):  # noqa: ANN001, ANN202
        return self

    async def ainvoke(self, messages, _config=None):  # noqa: ANN001
        self.calls.append(list(messages))
        return AIMessage(content=self._reply)


# ---------------------------------------------------------------------------
# compress_node — 替换语义 + system 连续
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_compress_node_replaces_not_appends(base_state) -> None:
    """压缩分支返回的 patch 以 RemoveMessage(REMOVE_ALL) 开头 → 整体替换。"""
    llm = _RecordingLLM()
    # 构造超阈值的长历史（小 context_window 强制压缩）。
    base_state["messages"] = [SystemMessage(content="sys", id="sys")] + [
        HumanMessage(content="h" * 200) if i % 2 == 0
        else AIMessage(content="a" * 200)
        for i in range(40)
    ]
    patch = await compress_node(
        base_state, _config(llm, context_window=64),
    )
    messages_patch = patch["messages"]
    # patch 第一条必须是清空指令。
    assert isinstance(messages_patch[0], RemoveMessage)
    # 后面接压缩结果（条数远小于原 41 条）。
    rebuilt = messages_patch[1:]
    assert len(rebuilt) < len(base_state["messages"])


@pytest.mark.asyncio
async def test_compress_node_keeps_system_continuous(base_state) -> None:
    """compress_node 输出的消息序列里，所有 system 连续在最前。"""
    llm = _RecordingLLM()
    base_state["messages"] = [SystemMessage(content="AGENT_PROMPT", id="sys")] + [
        HumanMessage(content="h" * 200) if i % 2 == 0
        else AIMessage(content="a" * 200)
        for i in range(40)
    ]
    patch = await compress_node(base_state, _config(llm, context_window=64))
    msgs = patch["messages"][1:]  # 去掉 RemoveMessage

    # 原始 system 在最前，且所有 system 连续（触底压缩可能只剩原始 system）。
    assert msgs[0].content == "AGENT_PROMPT"
    system_count = sum(1 for m in msgs if isinstance(m, SystemMessage))
    assert all(isinstance(m, SystemMessage) for m in msgs[:system_count])
    assert not any(isinstance(m, SystemMessage) for m in msgs[system_count:])


@pytest.mark.asyncio
async def test_compress_node_noop_when_under_threshold(base_state) -> None:
    """未超阈值时返回空 patch（不改动 state）。"""
    llm = _RecordingLLM()
    base_state["messages"] = [
        SystemMessage(content="sys", id="sys"),
        HumanMessage(content="hi"),
    ]
    patch = await compress_node(
        base_state, _config(llm, context_window=1_000_000),
    )
    assert patch == {}


# ---------------------------------------------------------------------------
# _system_messages_first — llm_node 防御层
# ---------------------------------------------------------------------------


def test_system_messages_first_already_leading_is_noop() -> None:
    """system 已在最前时原样返回，不分配新列表。"""
    msgs = [
        SystemMessage(content="sys", id="sys"),
        HumanMessage(content="hi", id="h"),
        AIMessage(content="yo", id="a"),
    ]
    assert _system_messages_first(msgs) is msgs


def test_system_messages_first_moves_scattered_to_front() -> None:
    """散落的 system 被移到最前，相对顺序不变，history 顺序不变。"""
    msgs = [
        HumanMessage(content="h1", id="h1"),
        SystemMessage(content="sys-mid", id="sm"),
        AIMessage(content="a1", id="a1"),
        SystemMessage(content="sys-tail", id="st"),
        HumanMessage(content="h2", id="h2"),
    ]
    result = _system_messages_first(msgs)
    # 前两条是 system，按原相对顺序。
    assert [m.content for m in result[:2]] == ["sys-mid", "sys-tail"]
    # history 顺序保持。
    assert [m.content for m in result[2:]] == ["h1", "a1", "h2"]


# ---------------------------------------------------------------------------
# 按轮分区:四种情况
# ---------------------------------------------------------------------------

import json as _json  # noqa: E402


def _big_tool_result(tcid: str) -> ToolMessage:
    """构造一个超限(>1500字)的已消费工具结果。"""
    content = _json.dumps(
        [{"text": "片段" * 300, "source": "doc.md"} for _ in range(6)],
        ensure_ascii=False,
    )
    return ToolMessage(content=content, tool_call_id=tcid)


def _seven_turns_with_outer_tool() -> list:
    """7轮历史,第1轮有个已消费的大工具结果(5轮之外)。"""
    msgs = [
        SystemMessage(content="sys", id="sys"),
        AIMessage(content="", tool_calls=[{"name": "kb", "args": {}, "id": "old_tc"}]),
        _big_tool_result("old_tc"),
    ]
    for i in range(7):
        msgs.append(HumanMessage(content=f"q{i}", id=f"h{i}"))
        msgs.append(AIMessage(content=f"a{i}", id=f"a{i}"))
    return msgs


def _patch_msgs(patch: dict | None) -> list:
    """从 compress_node 的 patch 里取出实际消息(去掉 RemoveMessage)。"""
    if not patch:
        return []
    return [m for m in patch["messages"] if getattr(m, "id", "") != "__remove_all__"]


@pytest.mark.asyncio
async def test_case1_insufficient_turns_nothing_done() -> None:
    """情况1:不足5轮 + 未达阈值 → 什么都不做。"""
    msgs = [SystemMessage(content="sys", id="sys")] + [
        HumanMessage(content="q" * 100, id=f"h{i}") if i % 2 == 0
        else AIMessage(content="a" * 100, id=f"a{i}")
        for i in range(6)
    ]
    config = _config(context_window=1_000_000)  # 大窗口,不达阈值
    patch = await compress_node({"messages": msgs, "agent_id": "a", "request_id": "r"}, config)
    assert patch == {}


@pytest.mark.asyncio
async def test_case2_under_threshold_does_nothing() -> None:
    """新规则:未达阈值 → 什么都不做(即使有5轮外大工具也不压)。"""
    msgs = _seven_turns_with_outer_tool()
    config = {
        "configurable": {
            "llm": None,
            "context_window": 1_000_000,  # 大窗口,不达阈值
            "tool_output_reference_formatter": lambda t, orig: f"[REF:{t}]",
        }
    }
    patch = await compress_node({"messages": msgs, "agent_id": "a", "request_id": "r"}, config)
    # 未达阈值 → compress_skipped,什么都不做。
    assert patch == {}


@pytest.mark.asyncio
async def test_level1_outer_tools_compressed() -> None:
    """达阈值 + 5轮外大工具:第1级工具压缩够 → "5轮外工具压缩"。"""
    msgs = _seven_turns_with_outer_tool()
    config = {
        "configurable": {
            "llm": None,
            "context_window": 1200,  # 阈值≈840,工具结果951tok > 阈值 → 触发压缩
            "tool_output_reference_formatter": lambda t, orig: f"[REF:{t}]",
        }
    }
    patch = await compress_node({"messages": msgs, "agent_id": "a", "request_id": "r"}, config)
    result = _patch_msgs(patch)
    # 5轮外的 old_tc 工具被压缩(带 formatter 标记)。
    tool = [m for m in result if isinstance(m, ToolMessage) and m.tool_call_id == "old_tc"]
    assert tool, "5轮外工具应被压缩保留(不是删除)"
    assert "[REF:old_tc]" in tool[0].content
    # 没有走摘要(第1级就够)。
    summaries = [m for m in result if isinstance(m, SystemMessage) and m.id == "summary"]
    assert not summaries, "第1级够,不应触发摘要"


@pytest.mark.asyncio
async def test_oversize_triggers_background_or_discard() -> None:
    """达阈值 + 工具压缩不够 → 触发后台LLM压缩 + 可能丢弃(不再同步机械摘要)。"""
    msgs = [SystemMessage(content="sys", id="sys")]
    for i in range(7):
        msgs.append(HumanMessage(content=f"问题{i}" + "x" * 500, id=f"h{i}"))
        msgs.append(AIMessage(content=f"回答{i}" + "y" * 500, id=f"a{i}"))
    config = _config(context_window=800)  # 阈值≈560,普通历史超了
    patch = await compress_node({"messages": msgs, "agent_id": "a", "request_id": "r"}, config)
    # 新逻辑:不生成同步机械摘要(id="summary"),而是触发后台压缩/丢弃兜底。
    result = _patch_msgs(patch)
    # 不应有同步 summary(机械摘要已移除)。
    summaries = [m for m in result if isinstance(m, SystemMessage) and m.id == "summary"]
    assert not summaries, "不应生成同步机械摘要"
    # 但应该有处理(patch 非空)。
    assert patch != {}


@pytest.mark.asyncio
async def test_recent_turns_protected_when_under_threshold() -> None:
    """5轮内的内容(含大工具)在未达阈值时不被压缩。"""
    # 3轮(不足5),最后一轮有未消费大工具。
    big = _big_tool_result("recent_tc")
    msgs = [
        SystemMessage(content="sys", id="sys"),
        HumanMessage(content="q0", id="h0"),
        AIMessage(content="a0"),
        HumanMessage(content="q1", id="h1"),
        AIMessage(content="a1"),
        HumanMessage(content="q2", id="h2"),
        AIMessage(content="", tool_calls=[{"name": "kb", "args": {}, "id": "recent_tc"}]),
        big,
    ]
    config = _config(context_window=1_000_000)
    patch = await compress_node({"messages": msgs, "agent_id": "a", "request_id": "r"}, config)
    # 不足5轮 → 全保护,不处理。
    assert patch == {}


@pytest.mark.asyncio
async def test_unconsumed_oversized_tool_raises() -> None:
    """未消费的单个工具结果超出剩余预算 → 报错(无法压缩,留着必超窗口)。

    窗口需 > RESERVED_RESPONSE(4000) 才能构造出正预算:工具 ~5000 tokens,
    预算 = 8000 - 少量其它 - 4000 ≈ 3900 < 5000 → 走"返回结果过大"分支。
    """
    big = ToolMessage(content="z" * 20000, tool_call_id="big_tc")  # ~5000 tokens
    msgs = [
        SystemMessage(content="sys", id="sys"),
        HumanMessage(content="q", id="h0"),
        AIMessage(content="", tool_calls=[{"name": "kb", "args": {}, "id": "big_tc"}]),
        big,  # 未消费(后面无 AIMessage)
    ]
    config = _config(context_window=8000)
    with pytest.raises(ValueError, match="返回结果过大"):
        await compress_node({"messages": msgs, "agent_id": "a", "request_id": "r"}, config)


@pytest.mark.asyncio
async def test_history_over_window_error_not_blames_tool() -> None:
    """历史本身超窗(budget<0) → 报错归因"上下文已超出模型窗口",
    不再误导性地指责工具返回过大(实测事故:59 tokens 的结果背了 331k 历史的锅)。"""
    msgs = [
        SystemMessage(content="sys", id="sys"),
        HumanMessage(content="q", id="h0"),
        AIMessage(content="", tool_calls=[{"name": "kb", "args": {}, "id": "tc_small"}]),
        ToolMessage(content="ok", tool_call_id="tc_small"),  # 很小的未消费结果
    ]
    config = _config(context_window=200)  # budget = 200 - few - 4000 < 0
    with pytest.raises(ValueError, match="已超出模型窗口"):
        await compress_node({"messages": msgs, "agent_id": "a", "request_id": "r"}, config)


@pytest.mark.asyncio
async def test_compressible_history_rescues_oversized_check() -> None:
    """回归:可压缩历史 + 小的未消费工具结果 → 压缩先行救回,不再误报。

    旧时序(检查在压缩前)会直接抛错;新时序先压已消费工具输出,
    budget 转正即放行——正是线上"59 tokens 结果 + 331k 历史"误报的形态。
    """
    msgs = [SystemMessage(content="sys", id="sys")]
    # 8 轮含大已消费工具输出(>1500 字,可被截断压缩),总计超阈值。
    for i in range(8):
        msgs.append(HumanMessage(content=f"q{i}", id=f"h{i}"))
        msgs.append(
            AIMessage(content="", tool_calls=[{"name": "kb", "args": {}, "id": f"tc{i}"}])
        )
        msgs.append(ToolMessage(content="x" * 4000, tool_call_id=f"tc{i}"))
        msgs.append(AIMessage(content=f"done{i}", id=f"a{i}"))  # 消费
    # 末尾:小的未消费工具结果。
    msgs.append(
        AIMessage(content="", tool_calls=[{"name": "kb", "args": {}, "id": "tc_new"}])
    )
    msgs.append(ToolMessage(content="small", tool_call_id="tc_new"))

    config = _config(context_window=10_000)  # 阈值 7000;压缩前 ~8100 超
    patch = await compress_node({"messages": msgs, "agent_id": "a", "request_id": "r"}, config)
    # 不抛错;返回压缩 patch;未消费的小结果原样保留。
    result = _patch_msgs(patch)
    kept = [m for m in result if getattr(m, "tool_call_id", "") == "tc_new"]
    assert kept and kept[0].content == "small"


@pytest.mark.asyncio
async def test_consumed_oversized_tool_not_raises() -> None:
    """已消费的单个工具结果超阈值 → 不报错(会被正常压缩截断)。"""
    big = _big_tool_result("consumed_tc")
    msgs = [
        SystemMessage(content="sys", id="sys"),
        AIMessage(content="", tool_calls=[{"name": "kb", "args": {}, "id": "consumed_tc"}]),
        big,
        AIMessage(content="基于结果回答"),  # 消费了 → 可压缩,不报错
    ]
    config = _config(context_window=200)  # 阈值 140,工具 950 > 140,但已消费
    # 不应抛异常(已消费的工具会被压缩,不是报错)。
    patch = await compress_node({"messages": msgs, "agent_id": "a", "request_id": "r"}, config)
    assert patch != {}  # 正常返回压缩 patch


# ---------------------------------------------------------------------------
# B.3-3：存量 SystemMessage 摘要 → 迁移为 HumanMessage（替代旧"回卷"）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_system_summary_migrated_to_history() -> None:
    """B.3-3：存量 SystemMessage(id=llm_summary) 压缩时迁移为 HumanMessage 并留在历史区。"""
    from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

    class _MockLLM:
        async def ainvoke(self, messages, _config=None):
            return AIMessage(content="新结构化摘要")

    # sys + 旧 SystemMessage 摘要 + 8 轮长历史。
    # 尺寸设计：CJK 估算校正(0.75 token/字)后 ~9.7k tokens，窗口 12000 →
    # 超阈值(8400)但未达硬上限(10800)，不触发兜底丢弃（丢弃会从 outer
    # 头部扔消息，干扰迁移断言）。
    msgs: list = [SystemMessage(content="AGENT PROMPT", id="sys")]
    msgs.append(SystemMessage(content="用户此前要求整理 Q3 报销", id="llm_summary"))
    for i in range(8):
        msgs.append(HumanMessage(content=f"问题{i}" + "长" * 800, id=f"h{i}"))
        msgs.append(HumanMessage(content=f"答{i}" + "长" * 800, id=f"a{i}"))

    config = {
        "configurable": {
            "llm": _MockLLM(),
            "context_window": 12_000,
            "protected_turns": 5,
        },
    }
    patch = await compress_node(
        {"messages": msgs, "agent_id": "a", "request_id": "r", "session_id": "mig_test_unique"},
        config,
    )
    assert patch != {}
    result = _patch_msgs(patch)

    # system 区只剩主 prompt——旧摘要已迁出
    system_msgs = [m for m in result if isinstance(m, SystemMessage)]
    assert [getattr(m, "id", "") for m in system_msgs] == ["sys"]

    # 迁移后的 HumanMessage 摘要留在历史区（内容保留，参与下次再压缩）
    migrated = [m for m in result if getattr(m, "id", "") == "llm_summary"]
    assert migrated and isinstance(migrated[0], HumanMessage)
    assert "Q3 报销" in migrated[0].content


# ---------------------------------------------------------------------------
# 中断标注（mid-stream 取消/崩溃保护）：三种形态 + 两个不触发场景
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_annotate_orphan_tool_call_cancelled(base_state) -> None:
    """形态① 工具执行中被中断：孤儿 tool_call → 合成"被中断"ToolMessage，
    而非剥离——模型知情，且结构变为完整配对（防 OpenAI 400）。"""
    llm = _RecordingLLM()
    base_state["messages"] = [
        SystemMessage(content="sys", id="sys"),
        HumanMessage(content="查一下天气", id="u1"),
        AIMessage(
            content="",
            tool_calls=[{"name": "bash", "args": {"command": "date"}, "id": "call_1"}],
            id="a1",
        ),
        # 取消发生在工具执行中：没有 call_1 的 ToolMessage
        HumanMessage(content="算了，换个问题", id="u2"),
    ]
    patch = await compress_node(
        base_state, _config(llm, context_window=1_000_000),
    )

    # 标注触发 → 整体替换 patch（RemoveMessage 开头）
    assert patch != {}
    messages = patch["messages"]
    assert isinstance(messages[0], RemoveMessage)
    names = [type(m).__name__ for m in messages[1:]]
    assert names == ["SystemMessage", "HumanMessage", "AIMessage", "ToolMessage", "HumanMessage"]
    # 原始 tool_call 保留 + 合成的"被中断"结果配对
    synthetic = messages[-2]
    assert synthetic.tool_call_id == "call_1"
    assert "中断" in synthetic.content


@pytest.mark.asyncio
async def test_annotate_tools_done_reply_interrupted(base_state) -> None:
    """形态② 工具已完成、总结回复被中断：注入标记 AIMessage，
    防模型把工具结果当作"已汇报过"。"""
    llm = _RecordingLLM()
    base_state["messages"] = [
        SystemMessage(content="sys", id="sys"),
        HumanMessage(content="查一下天气", id="u1"),
        AIMessage(
            content="",
            tool_calls=[{"name": "bash", "args": {"command": "date"}, "id": "call_1"}],
            id="a1",
        ),
        ToolMessage(content="Mon Aug 24", tool_call_id="call_1", id="t1"),
        HumanMessage(content="不用了，换个问题", id="u2"),
    ]
    patch = await compress_node(
        base_state, _config(llm, context_window=1_000_000),
    )
    assert patch != {}
    messages = patch["messages"]
    marker = messages[-2]  # Tool 与新 Human 之间
    assert isinstance(marker, AIMessage)
    assert "中断" in marker.content
    assert "尚未汇报" in marker.content


@pytest.mark.asyncio
async def test_annotate_no_output_interrupted(base_state) -> None:
    """形态③ 未产生任何输出即被中断（连续两条 user）：注入标记。"""
    llm = _RecordingLLM()
    base_state["messages"] = [
        SystemMessage(content="sys", id="sys"),
        HumanMessage(content="第一句被取消了", id="u1"),
        HumanMessage(content="重新问", id="u2"),
    ]
    patch = await compress_node(
        base_state, _config(llm, context_window=1_000_000),
    )
    assert patch != {}
    messages = patch["messages"]
    marker = messages[-2]
    assert isinstance(marker, AIMessage)
    assert "未产生输出" in marker.content


@pytest.mark.asyncio
async def test_no_annotation_for_completed_turn(base_state) -> None:
    """正常完成的轮次（尾部带文本 AIMessage）：不标注，未达阈值空 patch。"""
    llm = _RecordingLLM()
    base_state["messages"] = [
        SystemMessage(content="sys", id="sys"),
        HumanMessage(content="hi", id="u1"),
        AIMessage(content="你好！", id="a1"),
        HumanMessage(content="下一轮", id="u2"),
    ]
    patch = await compress_node(
        base_state, _config(llm, context_window=1_000_000),
    )
    assert patch == {}


@pytest.mark.asyncio
async def test_no_annotation_without_new_human(base_state) -> None:
    """孤儿存在但尾部不是新 Human（非新轮开始）：不注入"中断"标注；
    配对安全网仍剥孤儿防 400，但内容里绝不能出现中断标记。"""
    llm = _RecordingLLM()
    base_state["messages"] = [
        SystemMessage(content="sys", id="sys"),
        HumanMessage(content="查一下", id="u1"),
        AIMessage(
            content="",
            tool_calls=[{"name": "bash", "args": {"command": "date"}, "id": "call_1"}],
            id="a1",
        ),
    ]
    patch = await compress_node(
        base_state, _config(llm, context_window=1_000_000),
    )
    # 安全网剥孤儿 → 有替换补丁；但没有任何"中断"标记（annotation 未触发）
    assert patch != {}
    assert "中断" not in str(patch["messages"])


@pytest.mark.asyncio
async def test_compress_node_keeps_paired_tool_calls_under_threshold(base_state) -> None:
    """配对完整的 tool_call/result：未达阈值时不做任何改动（回归保护）。"""
    llm = _RecordingLLM()
    base_state["messages"] = [
        SystemMessage(content="sys", id="sys"),
        HumanMessage(content="查天气", id="u1"),
        AIMessage(
            content="",
            tool_calls=[{"name": "bash", "args": {"command": "date"}, "id": "call_1"}],
            id="a1",
        ),
        ToolMessage(content="Mon Aug 24 10:00:00 UTC 2026", tool_call_id="call_1", id="t1"),
    ]
    patch = await compress_node(
        base_state, _config(llm, context_window=1_000_000),
    )
    assert patch == {}


# ---------------------------------------------------------------------------
# 长任务盲区修复：单任务指令 + 几十次工具往返（split_for_compression 路径）
# ---------------------------------------------------------------------------

import uuid  # noqa: E402

from agent_flow_harness.context_engineering.compact_circuit import (  # noqa: E402
    compact_circuit,
)


@pytest.fixture
def unique_session() -> str:
    """唯一 session_id + 用后清熔断状态(模块级单例防测试间污染)。"""
    sid = f"test_{uuid.uuid4().hex[:8]}"
    yield sid
    compact_circuit.reset(sid)


def _long_task_messages(n_batches: int, *, ai_chars: int = 900) -> list:
    """sys + 任务指令 + n 个批次(AI(tool_calls) + 小Tool + 长AI文本)。

    工具结果很小(截断无收益)、AI 文本长——只有 LLM 摘要能压缩 outer,
    复刻「工具已截断、推理文本膨胀」的长任务中后期形态。
    """
    msgs = [SystemMessage(content="sys", id="sys")]
    msgs.append(HumanMessage(content="长任务指令:处理并汇总全部数据", id="task"))
    for i in range(n_batches):
        msgs.append(
            AIMessage(content="", tool_calls=[{"name": "bash", "args": {"cmd": f"ls {i}"}, "id": f"c{i}"}])
        )
        msgs.append(ToolMessage(content=f"ok{i}", tool_call_id=f"c{i}"))
        msgs.append(AIMessage(content=f"step {i} " + "y" * ai_chars, id=f"a{i}"))
    return msgs


class _SummaryLLM:
    """摘要 LLM:记录调用,返回固定摘要文本。"""

    def __init__(self, reply: str = "1. 意图:汇总数据 2. 已完成 30 步") -> None:
        self.reply = reply
        self.calls = 0

    async def ainvoke(self, messages, config=None):  # noqa: ANN001
        self.calls += 1
        return AIMessage(content=self.reply)


@pytest.mark.asyncio
async def test_long_task_sync_summary_replaces_outer(unique_session) -> None:
    """长任务超阈值 → 同步摘要当轮回填:outer 替换为一条摘要 + 任务指令锚定保留。"""
    llm = _SummaryLLM()
    msgs = _long_task_messages(30)
    state = {"messages": msgs, "agent_id": "a", "request_id": "r", "session_id": unique_session}
    patch = await compress_node(state, _config(llm, context_window=8_000))
    assert patch != {}
    result = _patch_msgs(patch)

    # 同步摘要当轮生效:摘要 LLM 被调用,outer 替换为一条 HumanMessage(id=llm_summary)。
    assert llm.calls == 1
    summaries = [m for m in result if getattr(m, "id", "") == "llm_summary"]
    assert len(summaries) == 1 and isinstance(summaries[0], HumanMessage)
    assert "汇总数据" in summaries[0].content

    # 任务指令锚定保留(旧实现会在硬限时第一个丢掉它)。
    assert any(
        isinstance(m, HumanMessage) and m.content.startswith("长任务指令") for m in result
    )
    # 早期批次的 AI 文本被摘要覆盖(step 0/1 不在),近期批次保留(末尾存在)。
    assert not any("step 0 " in str(m.content) for m in result)
    assert any("step 29 " in str(m.content) for m in result)
    # 熔断器计入一次成功(compact_count 可观测)。
    assert compact_circuit.success_count(unique_session) == 1


@pytest.mark.asyncio
async def test_summary_three_outcomes_progress_semantics(unique_session) -> None:
    """摘要三态落点:有进展成功回落;无进展计数(不熔断直到连续3次)。"""
    # 有进展:30 批长任务,摘要替换大 outer → token 大降。
    llm = _SummaryLLM()
    msgs = _long_task_messages(30)
    state = {"messages": msgs, "agent_id": "a", "request_id": "r", "session_id": unique_session}
    patch = await compress_node(state, _config(llm, context_window=8_000))
    assert llm.calls == 1
    result = _patch_msgs(patch)
    # 降回阈值(8k×0.7=5.6k)以下:带病运行的告警场景之外,正常回落。
    from agent_flow_harness.engine.context import estimate_context_tokens
    assert estimate_context_tokens(result, prefer_usage=False) <= 5_600


@pytest.mark.asyncio
async def test_summary_failure_retries_then_circuit_opens(unique_session) -> None:
    """摘要连续失败 3 次 → 熔断;熔断后不再调用摘要 LLM(降级运行)。"""

    class _FailingLLM:
        def __init__(self) -> None:
            self.calls = 0

        async def ainvoke(self, messages, config=None):  # noqa: ANN001
            self.calls += 1
            raise RuntimeError("provider down")

    llm = _FailingLLM()
    msgs = _long_task_messages(30)
    state = {"messages": msgs, "agent_id": "a", "request_id": "r", "session_id": unique_session}
    cfg = _config(llm, context_window=8_000)

    for _ in range(3):
        patch = await compress_node(state, cfg)
        assert patch != {}  # 失败当轮仍返回截断/丢弃结果,不抛错
    assert llm.calls == 3

    # 第 4 次:熔断冷却期内 → 跳过摘要,LLM 零调用。
    patch = await compress_node(state, cfg)
    assert llm.calls == 3
    assert patch != {}
    # 冷却期后(注入假时钟快进)恢复试探 —— 半开由 compact_circuit 单测覆盖。


# ---------------------------------------------------------------------------
# 分级截断:outer 狠截(~500) / recent 宽松(1500) / 未消费不动
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tiered_tool_output_truncation() -> None:
    """outer 内 600 字符工具被压缩(~500 上限);recent 内 600 字符保留(1500 上限)。"""
    # 7 轮 chat(产生 outer):第 1 轮(outer)与第 6 轮(recent)各放一个 600 字符已消费工具。
    def _turn_with_tool(i: int, tcid: str) -> list:
        return [
            AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": tcid}]),
            ToolMessage(content="d" * 600, tool_call_id=tcid),
        ]

    msgs = [SystemMessage(content="sys", id="sys")]
    msgs.extend(_turn_with_tool(0, "old_tc"))  # 第 1 轮 → outer
    for i in range(7):
        msgs.append(HumanMessage(content=f"q{i}", id=f"h{i}"))
        msgs.append(AIMessage(content=f"a{i}", id=f"ai{i}"))
        if i == 5:
            msgs.extend(_turn_with_tool(i, "recent_tc"))  # recent 内
    # 让总量超阈值:recent 的 q 加长(7 条 × ~300 tok ≈ 2100+ > 阈值)。
    msgs = [
        m if not isinstance(m, HumanMessage) else HumanMessage(content=m.content + "x" * 1200, id=m.id)
        for m in msgs
    ]

    config = {
        "configurable": {
            "llm": None,
            "context_window": 3_000,  # 阈值 2100
            "tool_output_reference_formatter": lambda t, orig: f"[REF:{t}]",
        }
    }
    patch = await compress_node({"messages": msgs, "agent_id": "a", "request_id": "r"}, config)
    result = _patch_msgs(patch)

    old_tool = [m for m in result if getattr(m, "tool_call_id", "") == "old_tc"]
    recent_tool = [m for m in result if getattr(m, "tool_call_id", "") == "recent_tc"]
    assert old_tool, "outer 工具应被压缩保留(不是删除)"
    assert "[REF:old_tc]" in old_tool[0].content
    assert "d" * 600 not in old_tool[0].content  # outer 级狠截(500 上限 → 600 字符被压)
    # recent 级 1500 上限 → 600 字符原样保留。
    assert recent_tool and "d" * 600 in recent_tool[0].content


# ---------------------------------------------------------------------------
# ⑤ 紧急丢弃安全网:锚定保留 + HumanMessage 占位 + 保底最后 2 条
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emergency_discard_keeps_anchor_and_notes_humans(unique_session) -> None:
    """超硬限丢弃(llm=None,④ 不可用):任务指令锚定保留;被丢 Human 合成占位。"""
    msgs = [SystemMessage(content="sys", id="sys")]
    msgs.append(HumanMessage(content="任" * 400, id="task"))  # ~300 tok 任务指令
    msgs.append(HumanMessage(content="反馈", id="fb"))  # 非锚定 Human(schema 反馈轮)
    for i in range(6):
        msgs.append(
            AIMessage(content="", tool_calls=[{"name": "bash", "args": {}, "id": f"c{i}"}])
        )
        msgs.append(ToolMessage(content=f"ok{i}", tool_call_id=f"c{i}"))
        msgs.append(AIMessage(content="z" * 7000, id=f"a{i}"))  # ~1750 tok AI 文本

    state = {"messages": msgs, "agent_id": "a", "request_id": "r", "session_id": unique_session}
    # llm=None → ④ 跳过;窗口 5000 → 阈值 3500,硬限 4500,丢弃目标 4250。
    patch = await compress_node(state, _config(None, context_window=5_000))
    result = _patch_msgs(patch)

    # 锚定任务指令保留(原实现会从 recent 头部第一个丢掉它)。
    anchor = [m for m in result if getattr(m, "id", "") == "task"]
    assert anchor and "任" * 400 in anchor[0].content
    # 被丢的 HumanMessage 有占位提示,不是纯丢失。
    assert any(getattr(m, "id", "") == "llm_discarded_note" for m in result)
    # 保底:尾部最后 2 条未被丢弃。
    assert getattr(result[-1], "id", "") == "a5"
    # 配对完整(丢弃不制造孤儿)。
    call_ids = {
        tc["id"]
        for m in result
        if isinstance(m, AIMessage)
        for tc in (getattr(m, "tool_calls", None) or [])
    }
    result_ids = {m.tool_call_id for m in result if isinstance(m, ToolMessage)}
    assert call_ids == result_ids


# ---------------------------------------------------------------------------
# 固定占用前置检查(_check_oversized_prompt)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_oversized_prompt_raises_clear_error() -> None:
    """system + 任务指令固定占用超窗 → ValueError 明确归因(取代 provider 400)。"""
    msgs = [
        SystemMessage(content="s" * 30_000),  # ~7500 tok
        HumanMessage(content="q", id="h0"),
        AIMessage(content="hi"),
    ]
    config = _config(None, context_window=8_000)  # 预算 8000-4000=4000 < 7500
    with pytest.raises(ValueError, match="固定占用"):
        await compress_node({"messages": msgs, "agent_id": "a", "request_id": "r"}, config)


@pytest.mark.asyncio
async def test_tiny_window_skips_prompt_check() -> None:
    """窗口 ≤ 预留(极端小窗)时跳过固定占用检查(由 oversized_tool 兜底)。"""
    msgs = [
        SystemMessage(content="sys", id="sys"),
        AIMessage(content="", tool_calls=[{"name": "t", "args": {}, "id": "tc"}]),
        ToolMessage(content="x" * 2600, tool_call_id="tc"),  # ~650 tok > 阈值 140
        AIMessage(content="done"),
    ]
    # window=200 ≤ 4000 → 不走固定占用报错;已消费工具正常压缩。
    patch = await compress_node(
        {"messages": msgs, "agent_id": "a", "request_id": "r"},
        _config(None, context_window=200),
    )
    assert patch != {}


# ---------------------------------------------------------------------------
# system 收敛：跨 invoke（chat 多轮 / loop continue）累积的重复 system 去重
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_system_messages_deduped_keeps_latest() -> None:
    """thread 内多条 SystemMessage → 只保留最后一条（最新 invoke 传入）。"""
    msgs = [
        SystemMessage(content="sys v1", id="sys-1"),
        HumanMessage(content="q1", id="h1"),
        AIMessage(content="a1", id="a1"),
        SystemMessage(content="sys v2", id="sys-2"),
        HumanMessage(content="q2", id="h2"),
        SystemMessage(content="sys v3", id="sys-3"),
    ]
    patch = await compress_node(
        {"messages": msgs, "agent_id": "a", "request_id": "r"},
        _config(context_window=1_000_000),
    )
    assert patch != {}
    result = _patch_msgs(patch)
    systems = [m for m in result if isinstance(m, SystemMessage)]
    assert len(systems) == 1
    assert systems[0].content == "sys v3"
    # 非系统消息原样保留。
    contents = [m.content for m in result if isinstance(m, HumanMessage)]
    assert contents == ["q1", "q2"]


@pytest.mark.asyncio
async def test_single_system_message_untouched() -> None:
    """单条 system → 零操作（未达阈值时返回空 patch）。"""
    msgs = [
        SystemMessage(content="sys", id="sys"),
        HumanMessage(content="q1", id="h1"),
        AIMessage(content="a1", id="a1"),
    ]
    patch = await compress_node(
        {"messages": msgs, "agent_id": "a", "request_id": "r"},
        _config(context_window=1_000_000),
    )
    assert patch == {}

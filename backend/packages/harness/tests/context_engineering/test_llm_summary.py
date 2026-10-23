"""LLM 摘要模块测试:历史渲染 + 同步核心 run_summary + 摘要消息装配。"""
from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from agent_flow_harness.context_engineering.llm_summary import (
    build_summary_message,
    render_history_for_summary,
    run_summary,
)


# ---------------------------------------------------------------------------
# render_history_for_summary
# ---------------------------------------------------------------------------


def test_render_keeps_user_text_original() -> None:
    """用户消息原文保留(不截断)。"""
    msgs = [HumanMessage(content="帮我查所有工艺路线的详细信息", id="h1")]
    result = render_history_for_summary(msgs)
    assert "帮我查所有工艺路线的详细信息" in result
    assert "[用户]" in result


def test_render_tool_result_only_reference() -> None:
    """工具结果不喂原始内容,只留引用(formatter 注入时带工具名)。"""
    big_content = '{"data": {"rows": [...]}}' * 100
    msgs = [
        AIMessage(content="", tool_calls=[{"name": "kb_search", "args": {"q": "x"}, "id": "c1"}]),
        ToolMessage(content=big_content, tool_call_id="c1"),
    ]
    # 传 formatter:工具结果带 recall 引用(签名 (tcid, 原文))。
    seen: list[tuple[str, str]] = []
    result = render_history_for_summary(
        msgs,
        reference_formatter=lambda t, orig: (seen.append((t, orig)), f"(recall:{t})")[1],
    )
    assert big_content not in result  # 大结果内容不进摘要
    assert "(recall:c1)" in result   # formatter 标记
    # formatter 收到原文(应用层可据此归档)。
    assert seen == [("c1", big_content)]

    # 不传 formatter:只留"已返回",不硬编码工具名。
    result2 = render_history_for_summary(msgs)
    assert "已返回" in result2
    assert "recall_tool_result" not in result2  # harness 不硬编码工具名


def test_render_tool_calls_as_summary() -> None:
    """工具调用渲染成「已调用 X(参数概要)」。"""
    msgs = [
        AIMessage(content="", tool_calls=[{"name": "process_route_list", "args": {"page": 1}, "id": "c1"}]),
    ]
    result = render_history_for_summary(msgs)
    assert "已调用 process_route_list" in result
    assert "page" in result  # 参数概要


def test_render_ai_text_original() -> None:
    """AI 文本回复原文保留(短文本不截断)。"""
    msgs = [AIMessage(content="根据查询,共有13条工艺路线", id="a1")]
    result = render_history_for_summary(msgs)
    assert "根据查询,共有13条工艺路线" in result


def test_render_ai_text_truncated_when_huge() -> None:
    """超长 AI 文本截断(防几十条长推理累计撑爆摘要请求自身)。"""
    long_text = "分析" * 5000  # 1 万字
    msgs = [AIMessage(content=long_text, id="a1")]
    result = render_history_for_summary(msgs)
    assert len(result) < len(long_text)
    assert result.endswith("...")


def test_render_ai_text_no_truncation_when_disabled() -> None:
    """max_ai_text_chars=None → AI 文本不截断(向后兼容开关)。"""
    long_text = "分析" * 5000
    msgs = [AIMessage(content=long_text, id="a1")]
    result = render_history_for_summary(msgs, max_ai_text_chars=None)
    assert long_text in result


# ---------------------------------------------------------------------------
# run_summary(同步核心)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_run_summary_returns_text_on_success() -> None:
    """摘要 LLM 成功 → 返回摘要文本。"""

    class _MockLLM:
        async def ainvoke(self, messages, config=None):
            return AIMessage(content="这是LLM生成的语义摘要")

    outer = [HumanMessage(content="问题1", id="m1"), AIMessage(content="回答1", id="m2")]
    text = await run_summary(_MockLLM(), outer)
    assert text == "这是LLM生成的语义摘要"


@pytest.mark.asyncio
async def test_run_summary_none_on_failure() -> None:
    """摘要 LLM 抛异常 → 返回 None(调用方按失败处理,当轮继续)。"""

    class _FailingLLM:
        async def ainvoke(self, messages, config=None):
            raise RuntimeError("provider down")

    text = await run_summary(_FailingLLM(), [HumanMessage(content="q", id="m1")])
    assert text is None


@pytest.mark.asyncio
async def test_run_summary_none_on_empty() -> None:
    """摘要 LLM 返回空内容 → None。"""

    class _EmptyLLM:
        async def ainvoke(self, messages, config=None):
            return AIMessage(content="   ")

    text = await run_summary(_EmptyLLM(), [HumanMessage(content="q", id="m1")])
    assert text is None


@pytest.mark.asyncio
async def test_run_summary_isolates_callbacks() -> None:
    """摘要 ainvoke 必须显式传 callbacks=[] + llm_summary tag。

    空 callbacks 覆盖 contextvar 隐式继承的主图 astream_events 回调,
    摘要 LLM 的 on_chat_model_* 事件就不会冒泡进聊天 SSE 流;tag 供
    适配器 stream_events_to_app_events 二次过滤。
    """
    captured: dict = {}

    class _MockLLM:
        async def ainvoke(self, messages, config=None):
            captured["config"] = config
            return AIMessage(content="摘要")

    await run_summary(_MockLLM(), [HumanMessage(content="问题1", id="m1")])

    config = captured.get("config") or {}
    assert config.get("callbacks") == []  # 阻断 contextvar 回调继承
    assert "llm_summary" in (config.get("tags") or [])  # 适配器过滤标记


# ---------------------------------------------------------------------------
# build_summary_message
# ---------------------------------------------------------------------------


def test_build_summary_message_shape() -> None:
    """摘要消息:HumanMessage + id=llm_summary + 框架声明(防归因混淆)。"""
    msg = build_summary_message("1. 意图:整理报销单")
    assert isinstance(msg, HumanMessage)
    assert msg.id == "llm_summary"
    assert "非用户发言" in msg.content
    assert "整理报销单" in msg.content


# ---------------------------------------------------------------------------
# B.3 修复：render 摘要分支（硬丢失 bug）+ 结构化模板
# ---------------------------------------------------------------------------


def test_render_legacy_system_summary_not_lost() -> None:
    """B.3-2 修复：SystemMessage 形态的旧摘要不再被静默跳过（硬丢失 bug）。"""
    msgs = [
        SystemMessage(content="用户此前要求整理 Q3 报销单", id="llm_summary"),
        HumanMessage(content="继续处理第 3 张", id="h1"),
    ]
    result = render_history_for_summary(msgs)
    assert "[此前摘要]" in result
    assert "Q3 报销单" in result  # 旧摘要内容参与再摘要，不再蒸发


def test_render_human_summary_not_misattributed() -> None:
    """B.3-3：HumanMessage 形态的新摘要（id=llm_summary）渲染为 [此前摘要] 而非 [用户]。"""
    msgs = [
        HumanMessage(content="[系统生成的此前对话摘要，非用户发言]\n1. 意图：xxx", id="llm_summary"),
        HumanMessage(content="真正的用户消息", id="h1"),
    ]
    result = render_history_for_summary(msgs)
    assert result.count("[此前摘要]") == 1
    assert "[用户] 真正的用户消息" in result
    # 摘要不能被当成 [用户] 发言
    assert "[用户] [系统生成的此前对话摘要" not in result


def test_render_other_system_message_also_included() -> None:
    """其他 SystemMessage（无摘要 id）同样进 [此前摘要] 分支，不再丢失。"""
    msgs = [SystemMessage(content="某中间件注入的系统级说明", id="x")]
    result = render_history_for_summary(msgs)
    assert "[此前摘要]" in result and "系统级说明" in result


def test_summary_prompt_structured_six_sections() -> None:
    """B.3-1：模板为 Claude 式六段结构化，且不再限制 500 字。"""
    from agent_flow_harness.context_engineering.llm_summary import _SUMMARY_PROMPT

    for section in (
        "核心意图与需求",
        "关键决策与结论",
        "重要错误与修复",
        "进行中的任务与未完成项",
        "当前工作状态与建议的下一步",
        "关键文件/数据引用",
        "[此前摘要]",  # 明确要求旧摘要信息合并保留
    ):
        assert section in _SUMMARY_PROMPT, section
    assert "500" not in _SUMMARY_PROMPT  # 硬上限已移除

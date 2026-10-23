"""AC10 cover: migrated context helpers behave correctly inside the harness."""

from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from agent_flow_harness.engine.context import (
    estimate_context_tokens,
    estimate_message_tokens,
    estimate_tokens,
    extract_model_name,
)


class _NamedLLM:
    """Tiny stand-in exposing ``model_name`` like a LangChain chat model."""

    def __init__(self, name: str) -> None:
        self.model_name = name


def test_estimate_tokens_positive_for_text() -> None:
    assert estimate_tokens("") >= 0
    assert estimate_tokens("hello world") > 0
    assert estimate_tokens("a" * 1000) > estimate_tokens("a")


def test_estimate_message_tokens_handles_message_and_dict() -> None:
    msg = HumanMessage(content="hello")
    assert estimate_message_tokens(msg) > 0
    assert estimate_message_tokens({"role": "user", "content": "hello"}) > 0


def test_estimate_message_tokens_multimodal_not_counting_base64() -> None:
    """image 块按固定估值计,base64 载荷绝不进 len//4。"""
    huge_b64 = "x" * 400_000  # 若误按 str() 估算会是 ~10 万 token
    blocks = [
        {"type": "text", "text": "hello world"},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{huge_b64}"}},
    ]
    msg = HumanMessage(content=blocks)
    tokens = estimate_message_tokens(msg)
    # 文本 ~3 + image 固定估值(1200) + 元数据 4 —— 远小于 10 万。
    assert tokens < 2_000
    assert tokens > 1_200
    # dict 形态同样处理。
    assert estimate_message_tokens({"role": "user", "content": blocks}) == tokens


def test_extract_model_name_reads_attribute() -> None:
    assert extract_model_name(_NamedLLM("gpt-4o-mini")) == "gpt-4o-mini"


# ---------------------------------------------------------------------------
# estimate_context_tokens — 用 input_tokens 优先,fallback len//4
# ---------------------------------------------------------------------------


def test_estimate_context_tokens_uses_input_tokens() -> None:
    """有 AIMessage(带 usage_metadata)时,用 input_tokens + 新增消息估算。"""
    ai = AIMessage(
        content="回答",
        usage_metadata={"input_tokens": 1000, "output_tokens": 50, "total_tokens": 1050},
    )
    # AIMessage 之后新增了一条 HumanMessage("新问题"*2 = 6字符)
    new_content = "新问题" * 2
    msgs = [SystemMessage(content="sys"), HumanMessage(content="hi"), ai,
            HumanMessage(content=new_content)]
    result = estimate_context_tokens(msgs)
    # 1000(input_tokens) + 新增消息估算(6字符//4 + 4元数据 = 5)
    assert result == 1000 + estimate_message_tokens(HumanMessage(content=new_content))


def test_estimate_context_tokens_no_ai_fallback() -> None:
    """无 AIMessage(首轮) → fallback 全量 len//4。"""
    msgs = [SystemMessage(content="sys"), HumanMessage(content="hello world")]
    result = estimate_context_tokens(msgs)
    assert result == estimate_message_tokens(msgs[0]) + estimate_message_tokens(msgs[1])


def test_estimate_context_tokens_ai_no_usage_fallback() -> None:
    """AIMessage 无 usage_metadata → fallback 全量估算。"""
    ai = AIMessage(content="回答")  # 无 usage_metadata
    msgs = [SystemMessage(content="sys"), ai]
    result = estimate_context_tokens(msgs)
    assert result == estimate_message_tokens(msgs[0]) + estimate_message_tokens(ai)


def test_estimate_context_tokens_uses_last_ai() -> None:
    """多条 AIMessage 时,用最后一条的 input_tokens。"""
    ai1 = AIMessage(content="r1", usage_metadata={"input_tokens": 500, "output_tokens": 10, "total_tokens": 510})
    ai2 = AIMessage(content="r2", usage_metadata={"input_tokens": 2000, "output_tokens": 20, "total_tokens": 2020})
    msgs = [SystemMessage(content="sys"), ai1, HumanMessage(content="q"), ai2]
    result = estimate_context_tokens(msgs)
    # 用 ai2 的 2000,ai2 之后无新增消息
    assert result == 2000


# ---------------------------------------------------------------------------
# CJK 估算校正 + 压缩后 usage 基准失效（回归：中文会话压缩系统性偏晚）
# ---------------------------------------------------------------------------


def test_estimate_tokens_cjk_not_underestimated() -> None:
    """中文按 ~0.75 token/字估算——旧的 len//4 (0.25/字) 低估 3 倍，
    导致压缩阈值判断偏晚、真实 prompt 早已逼近窗口。"""
    text = "查" * 100  # 纯 CJK 100 字
    assert estimate_tokens(text) >= 60  # ~75,不再是 25


def test_estimate_tokens_ascii_unchanged() -> None:
    """ASCII 内容维持 4 字符/token 的旧口径,行为不变。"""
    assert estimate_tokens("z" * 400) == 100
    assert estimate_tokens("hello world!") == 3  # 12//4


def test_estimate_tokens_mixed() -> None:
    """中英混合:各按各的系数相加。"""
    text = "查" * 40 + "z" * 400  # ~30 + 100
    assert 120 <= estimate_tokens(text) <= 140


def test_estimate_context_tokens_prefer_usage_false_ignores_stale_base() -> None:
    """prefer_usage=False → 忽略旧 input_tokens 基准,全量重算。

    压缩改写历史后,旧基准(描述的是压缩前那次调用的 prompt)会持续
    虚高预算判断——直到下一次真实调用才校准。"""
    ai = AIMessage(
        content="done",
        usage_metadata={"input_tokens": 100_000, "output_tokens": 10, "total_tokens": 100_010},
    )
    msgs = [SystemMessage(content="sys"), ai]
    # 默认:用 usage 基准(100000 + 后续无新增)。
    assert estimate_context_tokens(msgs) == 100_000
    # prefer_usage=False:全量估算(真实内容很小)。
    assert estimate_context_tokens(msgs, prefer_usage=False) < 100

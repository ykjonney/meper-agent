"""LLM 错误转译测试 — 图片不支持错误的识别与友好提示 + 稳定错误码分类。"""
from __future__ import annotations

from app.utils.llm_errors import (
    LLMErrorCode,
    classify_llm_error,
    is_retryable_code,
    looks_like_image_error,
    translate_llm_error,
)


def test_recognizes_common_provider_image_errors() -> None:
    assert looks_like_image_error(
        "Invalid content type: image_url is not supported by this model"
    )
    assert looks_like_image_error("Error code: 400 - image input is not supported")
    assert looks_like_image_error("该模型不支持图片输入")


def test_ignores_unrelated_errors() -> None:
    assert not looks_like_image_error("rate limit exceeded")
    assert not looks_like_image_error("connection timeout")
    # "image" 出现但无拒绝信号 → 不误报。
    assert not looks_like_image_error("image generation finished")


def test_translate_prefixes_hint_and_keeps_original() -> None:
    raw = "Invalid content type: image_url not supported"
    out = translate_llm_error(raw)
    assert out.startswith("当前模型可能不支持图片输入")
    assert raw in out


def test_translate_passthrough_for_normal_errors() -> None:
    assert translate_llm_error("rate limit exceeded") == "rate limit exceeded"
    assert translate_llm_error("") == ""


# ---------------------------------------------------------------------------
# LLMErrorCode 稳定错误码 — 分类 + 可重试判定（P0-3）
# ---------------------------------------------------------------------------


class _RateLimitError(Exception):
    pass


class _APIConnectionError(Exception):
    pass


def test_classify_by_message_keywords() -> None:
    assert classify_llm_error("Request timed out") is LLMErrorCode.TIMEOUT
    assert classify_llm_error("Error code: 429 - rate limit exceeded") is LLMErrorCode.RATE_LIMIT
    assert classify_llm_error("Incorrect API key provided") is LLMErrorCode.AUTH
    assert classify_llm_error("You exceeded your current quota") is LLMErrorCode.QUOTA
    assert classify_llm_error("账户欠费，请充值") is LLMErrorCode.QUOTA
    assert classify_llm_error("Connection error while requesting") is LLMErrorCode.NETWORK
    assert (
        classify_llm_error("This model's maximum context length is 128000 tokens")
        is LLMErrorCode.INVALID_INPUT
    )


def test_classify_by_exception_type_name() -> None:
    """消息无信号时按异常类名兜底识别。"""
    assert classify_llm_error(_RateLimitError("boom")) is LLMErrorCode.RATE_LIMIT
    assert classify_llm_error(_APIConnectionError("")) is LLMErrorCode.NETWORK


def test_classify_image_unsupported_first() -> None:
    """图片不支持单独优先识别（双信号防误报,复用 looks_like_image_error）。"""
    code = classify_llm_error("Invalid content type: image_url is not supported")
    assert code is LLMErrorCode.UNSUPPORTED


def test_classify_unknown() -> None:
    assert classify_llm_error("some totally unexpected failure") is LLMErrorCode.UNKNOWN


def test_auth_beats_quota_when_both_present() -> None:
    """鉴权信号优先于配额（更致命,重试无意义）。"""
    assert classify_llm_error("invalid_api_key and quota exceeded") is LLMErrorCode.AUTH


def test_is_retryable_code() -> None:
    for code in (LLMErrorCode.TIMEOUT, LLMErrorCode.NETWORK, LLMErrorCode.RATE_LIMIT):
        assert is_retryable_code(code)
        assert is_retryable_code(code.value)  # 字符串形态同样可判
    for code in (LLMErrorCode.AUTH, LLMErrorCode.QUOTA, LLMErrorCode.UNSUPPORTED):
        assert not is_retryable_code(code)
    assert not is_retryable_code("NOT_A_CODE")  # 未知字符串 → False

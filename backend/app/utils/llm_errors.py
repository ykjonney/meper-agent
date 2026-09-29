"""LLM 错误消息转译 — 供 SSE 事件与异常两条路径共用。

多模态图片消息发到不支持 vision 的模型时，provider 返回的错误各式各样
（"Invalid content type"、"image input is not supported"、"does not support
image"…）。这里按关键词识别并前缀友好提示（原文附后），让终端用户能直接
理解"换个模型或去掉图片"，而不是面对一段 provider 原始报错。

设计取舍：平台是 BYO-model（自定义 base_url + model），无法可靠预知模型
是否支持 vision —— 因此不做能力声明，靠报错兜底转译。
"""
from __future__ import annotations

from enum import StrEnum

# "不支持图片输入"类错误的关键词（小写匹配，覆盖 OpenAI/Anthropic/GLM 兼容
# 网关的常见报错文案）。
_IMAGE_ERROR_KEYWORDS = (
    "image", "multimodal", "multi-modal", "modality", "vision",
    "visual", "不支持图片", "图片输入",
)

_IMAGE_HINT = (
    "当前模型可能不支持图片输入，请切换到视觉模型（如 GLM-4V/GPT-4o/Claude）"
    "或移除图片后重试。"
)


def looks_like_image_error(message: str) -> bool:
    """判断错误消息是否疑似"模型不支持图片输入"。

    需要"图片类关键词"与"拒绝/不支持类信号"同时命中，避免
    "image generation tool failed" 这类误报。
    """
    msg = (message or "").lower()
    if not any(kw in msg for kw in _IMAGE_ERROR_KEYWORDS):
        return False
    reject_signals = (
        "not support", "unsupported", "invalid content", "invalid type",
        "invalid_request", "does not", "cannot", "无法", "不支持", "失败",
        "error", "unexpected",
    )
    return any(sig in msg for sig in reject_signals)


def translate_llm_error(message: str) -> str:
    """疑似图片不支持错误 → 前缀友好提示（原文附后）；其余原样返回。"""
    if message and looks_like_image_error(message):
        return f"{_IMAGE_HINT}\n原始错误：{message}"
    return message or ""


# ---------------------------------------------------------------------------
# 稳定错误码（P0-3）：错误分类的唯一事实源
#
# 语义对齐 penguin-harness 的 stop_reason 纪律——"错误码只回答一个问题：
# 要不要重试"。SSE ErrorEvent / execution_log events / 渠道熔断按同一份
# code 决策，前端可据 code 本地化文案。
# ---------------------------------------------------------------------------


class LLMErrorCode(StrEnum):
    """LLM 调用失败的稳定机器码（跨 provider，不随文案漂移）。"""

    TIMEOUT = "LLM_TIMEOUT"                # 请求超时（可重试）
    NETWORK = "LLM_NETWORK"                # 连接失败/网络抖动（可重试）
    RATE_LIMIT = "LLM_RATE_LIMIT"          # 限流（可重试，SDK 已退避后仍失败）
    QUOTA = "LLM_QUOTA"                    # 欠费/配额耗尽（不可重试）
    AUTH = "LLM_AUTH"                      # 鉴权失败/无效 Key（不可重试）
    UNSUPPORTED = "LLM_UNSUPPORTED"        # 模型能力不支持（如图片输入）
    INVALID_INPUT = "LLM_INVALID_INPUT"    # 请求非法：上下文超限/参数错误
    UNKNOWN = "LLM_UNKNOWN"                # 未识别（默认）


# 可重试码：SDK 层已按 max_retries 原生退避过一轮，仍失败说明瞬时问题
# 持续存在——上层（渠道/用户重发）再试一次仍有意义。
_RETRYABLE_CODES = frozenset({
    LLMErrorCode.TIMEOUT,
    LLMErrorCode.NETWORK,
    LLMErrorCode.RATE_LIMIT,
})

# 分类信号：异常类型名关键词（langchain/openai/anthropic SDK 的异常类名）。
_CODE_TYPE_KEYWORDS: list[tuple[str, LLMErrorCode]] = [
    ("authentication", LLMErrorCode.AUTH),
    ("permissiondenied", LLMErrorCode.AUTH),
    ("ratelimit", LLMErrorCode.RATE_LIMIT),
    ("rate_limit", LLMErrorCode.RATE_LIMIT),
    ("apitimeout", LLMErrorCode.TIMEOUT),
    ("timeout", LLMErrorCode.TIMEOUT),
    ("connection", LLMErrorCode.NETWORK),
    ("apiconnection", LLMErrorCode.NETWORK),
    ("quota", LLMErrorCode.QUOTA),
]

# 分类信号：错误消息关键词（小写子串匹配，覆盖中英 provider 文案）。
_CODE_MSG_KEYWORDS: list[tuple[str, LLMErrorCode]] = [
    # 鉴权类优先识别（"api key" 与 "quota" 可能同现，鉴权语义更致命）
    ("invalid_api_key", LLMErrorCode.AUTH),
    ("api key", LLMErrorCode.AUTH),
    ("authentication", LLMErrorCode.AUTH),
    ("unauthorized", LLMErrorCode.AUTH),
    ("permission denied", LLMErrorCode.AUTH),
    # 配额/欠费
    ("insufficient_quota", LLMErrorCode.QUOTA),
    ("quota", LLMErrorCode.QUOTA),
    ("余额不足", LLMErrorCode.QUOTA),
    ("欠费", LLMErrorCode.QUOTA),
    ("billing", LLMErrorCode.QUOTA),
    # 限流
    ("rate limit", LLMErrorCode.RATE_LIMIT),
    ("ratelimit", LLMErrorCode.RATE_LIMIT),
    ("429", LLMErrorCode.RATE_LIMIT),
    ("请求过于频繁", LLMErrorCode.RATE_LIMIT),
    # 超时/网络
    ("timeout", LLMErrorCode.TIMEOUT),
    ("timed out", LLMErrorCode.TIMEOUT),
    ("connection", LLMErrorCode.NETWORK),
    ("network", LLMErrorCode.NETWORK),
    ("econnrefused", LLMErrorCode.NETWORK),
    ("eof occurred", LLMErrorCode.NETWORK),
    # 请求非法（模型不存在/上下文超限等）
    ("model_not_found", LLMErrorCode.INVALID_INPUT),
    ("context_length_exceeded", LLMErrorCode.INVALID_INPUT),
    ("maximum context", LLMErrorCode.INVALID_INPUT),
    ("invalid_request", LLMErrorCode.INVALID_INPUT),
]


def classify_llm_error(exc_or_msg: BaseException | str) -> LLMErrorCode:
    """把异常/消息分类为稳定错误码。

    识别顺序：鉴权 → 配额 → 图片不支持 → 消息关键词 → 类型名关键词。
    UNSUPPORTED 单独先判（复用 looks_like_image_error 的双信号防误报）。
    未识别返回 UNKNOWN。
    """
    msg = str(exc_or_msg)
    type_name = type(exc_or_msg).__name__.lower() if isinstance(exc_or_msg, BaseException) else ""

    if looks_like_image_error(msg):
        return LLMErrorCode.UNSUPPORTED
    for kw, code in _CODE_MSG_KEYWORDS:
        if kw in msg.lower():
            return code
    for kw, code in _CODE_TYPE_KEYWORDS:
        if kw in type_name:
            return code
    return LLMErrorCode.UNKNOWN


def is_retryable_code(code: LLMErrorCode | str) -> bool:
    """该错误码是否值得再试（TIMEOUT / NETWORK / RATE_LIMIT）。"""
    if isinstance(code, str):
        try:
            code = LLMErrorCode(code)
        except ValueError:
            return False
    return code in _RETRYABLE_CODES

"""ToolGeneratorService 用例 — AI 多轮对话生成工具定义草稿（mock LLM）。

覆盖：
1. 首轮生成：回复文本 + ```json 围栏草稿（_validate_code 通过，一轮出结果）
2. 修订轮：携带历史（user → assistant带草稿 → user 修改意见）→ 新草稿
3. 澄清轮：纯文本回复无围栏 → draft=None
4. 依赖白名单违规 → 带反馈修复一轮（反馈消息含校验错误）
5. 两轮均失败 → UserToolError
6. openapi 草稿归一化（code 清空 / endpoint 保留）
7. source_hint 强制覆盖；模型侧异常转可读错误；末条非 user 拒绝
"""
from __future__ import annotations

import json

import pytest
from app.services.tool_generator import ToolGeneratorService
from app.services.user_tool_service import UserToolError
from langchain_core.messages import AIMessage, HumanMessage


class _FakeLLM:
    """按序吐预设回复，记录收到的消息（验证反馈轮/历史内容）。"""

    def __init__(self, replies: list[str]):
        self.replies = list(replies)
        self.calls = 0
        self.received: list[list] = []

    async def ainvoke(self, messages):
        self.received.append(list(messages))
        self.calls += 1
        content = self.replies.pop(0) if self.replies else "{}"
        return AIMessage(content=content)


class _FailingLLM:
    """模拟模型侧错误（403 无权限 / 429 限额）——ainvoke 直接抛异常。"""

    def __init__(self, exc: Exception):
        self.exc = exc

    async def ainvoke(self, messages):
        raise self.exc


def _patch_llm(monkeypatch, replies: list[str]) -> _FakeLLM:
    fake = _FakeLLM(replies)

    async def _build(model_id: str = ""):
        return fake

    monkeypatch.setattr(ToolGeneratorService, "_build_llm", _build)
    return fake


def _msg(role: str, content: str) -> dict[str, str]:
    return {"role": role, "content": content}


def _draft_payload() -> dict:
    return {
        "name": "send-notice",
        "description": "给指定邮箱发送通知邮件",
        "source": "code",
        "llm_args_schema": {
            "type": "object",
            "properties": {"to": {"type": "string", "description": "收件人邮箱"}},
            "required": ["to"],
        },
        "user_args_schema": {
            "type": "object",
            "properties": {"password": {"type": "string", "sensitive": True}},
        },
        "code": "import os\n\n\ndef run(to: str) -> str:\n    return 'sent:' + to\n",
        "output_schema": {},
        "tags": ["email"],
    }


def _reply_with_draft(text: str, payload: dict) -> str:
    return f"{text}\n```json\n{json.dumps(payload, ensure_ascii=False)}\n```"


# ── 1. 首轮生成 ──────────────────────────────────────────────────────


async def test_first_turn_generates_draft(monkeypatch):
    fake = _patch_llm(monkeypatch, [_reply_with_draft("已生成通知邮件工具草稿。", _draft_payload())])

    result = await ToolGeneratorService.generate([_msg("user", "做一个发通知邮件的工具")])

    assert fake.calls == 1
    assert result["reply"] == "已生成通知邮件工具草稿。"
    assert result["draft"]["name"] == "send-notice"
    assert result["draft"]["source"] == "code"
    assert "def run(to: str)" in result["draft"]["code"]
    assert result["draft"]["user_args_schema"]["properties"]["password"]["sensitive"] is True


# ── 2. 修订轮：携带历史 ─────────────────────────────────────────────


async def test_revision_turn_carries_history(monkeypatch):
    prev_payload = _draft_payload()
    revised = {**prev_payload, "name": "send-notice-v2",
               "description": "给指定邮箱发送通知邮件（支持抄送）"}
    fake = _patch_llm(monkeypatch, [_reply_with_draft("已加抄送参数。", revised)])

    history = [
        _msg("user", "做一个发通知邮件的工具"),
        _msg("assistant", _reply_with_draft("已生成草稿。", prev_payload)),
        _msg("user", "加一个抄送参数 cc"),
    ]
    result = await ToolGeneratorService.generate(history)

    assert result["draft"]["name"] == "send-notice-v2"
    # 历史完整传给模型（AI 能看到上一版草稿做修订）
    sent = fake.received[0]
    assert sent[-3].content == history[0]["content"]  # user 首轮
    assert isinstance(sent[-2], AIMessage) and "send-notice" in sent[-2].content
    assert sent[-1].content == "加一个抄送参数 cc"


# ── 3. 澄清轮：纯文本无草稿 ─────────────────────────────────────────


async def test_clarify_turn_without_draft(monkeypatch):
    _patch_llm(monkeypatch, ["这个工具需要配置 SMTP 凭证吗？请提供发件服务器信息。"])

    result = await ToolGeneratorService.generate([_msg("user", "做个发邮件工具")])

    assert result["draft"] is None
    assert "SMTP" in result["reply"]


# ── 4. 依赖白名单违规 → 带反馈修复一轮 ────────────────────────────────


async def test_invalid_import_repaired(monkeypatch):
    bad = _draft_payload()
    bad["code"] = "import flask\n\n\ndef run(to: str) -> str:\n    return to\n"
    fake = _patch_llm(monkeypatch, [
        _reply_with_draft("已生成。", bad),
        _reply_with_draft("已修复依赖。", _draft_payload()),
    ])

    result = await ToolGeneratorService.generate([_msg("user", "发通知邮件的工具")])

    assert fake.calls == 2
    assert "def run(to: str)" in result["draft"]["code"]
    feedback = fake.received[1][-1]
    assert isinstance(feedback, HumanMessage)
    assert "依赖不可用" in feedback.content and "flask" in feedback.content


# ── 5. 两轮均失败 → UserToolError ────────────────────────────────────


async def test_two_failures_raise(monkeypatch):
    bad = _draft_payload()
    bad["name"] = "非法名字!"
    fake = _patch_llm(monkeypatch, [
        _reply_with_draft("已生成。", bad),
        _reply_with_draft("再试。", bad),
    ])

    with pytest.raises(UserToolError, match="未通过校验"):
        await ToolGeneratorService.generate([_msg("user", "随便什么工具")])
    assert fake.calls == 2


# ── 6. openapi 草稿归一化 ────────────────────────────────────────────


async def test_openapi_draft_normalized(monkeypatch):
    payload = {
        "name": "query-currency",
        "description": "查询汇率",
        "source": "openapi",
        "llm_args_schema": {},
        "user_args_schema": {},
        "endpoint": {
            "method": "GET",
            "url": "https://api.example.com/rate",
            "params": [
                {"name": "base", "in": "query", "description": "基准币",
                 "required": True, "credential": False},
                {"name": "Authorization", "in": "header", "description": "认证",
                 "required": True, "credential": True},
            ],
        },
        "output_schema": {"type": "object", "fields": [
            {"name": "rate", "type": "number", "is_list": False, "description": "汇率"},
        ]},
        "tags": ["finance"],
    }
    _patch_llm(monkeypatch, [_reply_with_draft("已生成汇率查询工具。", payload)])

    result = await ToolGeneratorService.generate([_msg("user", "查汇率的工具")])

    draft = result["draft"]
    assert draft["source"] == "openapi"
    assert draft["code"] == ""
    assert draft["endpoint"]["params"][1]["credential"] is True
    assert draft["output_schema"]["fields"][0]["name"] == "rate"


# ── 7. source_hint / 模型异常 / 入参 ─────────────────────────────────


async def test_source_hint_overrides(monkeypatch):
    payload = _draft_payload()  # AI 输出 source=code
    payload["endpoint"] = {"method": "GET", "url": "https://api.example.com/x", "params": []}
    _patch_llm(monkeypatch, [_reply_with_draft("已生成。", payload)])

    result = await ToolGeneratorService.generate(
        [_msg("user", "工具")], source_hint="openapi"
    )
    assert result["draft"]["source"] == "openapi"
    assert result["draft"]["code"] == ""


async def test_llm_error_becomes_friendly_error(monkeypatch):
    failing = _FailingLLM(RuntimeError("Error code: 429 - 已达到 5 小时的使用上限"))

    async def _build(model_id: str = ""):
        return failing

    monkeypatch.setattr(ToolGeneratorService, "_build_llm", _build)

    with pytest.raises(UserToolError, match="生成模型调用失败.*使用上限"):
        await ToolGeneratorService.generate([_msg("user", "随便什么工具")])


async def test_rejects_non_user_last_message():
    with pytest.raises(UserToolError, match="末条不是用户消息"):
        await ToolGeneratorService.generate([_msg("assistant", "你好")])


# ── 8. 无围栏裸 JSON 兜底提取 ────────────────────────────────────────


async def test_bare_json_extracted_as_draft(monkeypatch):
    """模型无视围栏要求、末尾裸输出 JSON → 兜底提取为草稿，
    回复只留说明文本（不再把原始结构当文本显示）。"""
    payload = _draft_payload()
    reply = "已生成工具草稿，说明如下：\n- 入口 run\n- 凭证走环境变量\n" + json.dumps(payload, ensure_ascii=False)
    _patch_llm(monkeypatch, [reply])

    result = await ToolGeneratorService.generate([_msg("user", "发通知邮件的工具")])

    assert result["draft"] is not None
    assert result["draft"]["name"] == "send-notice"
    assert "已生成工具草稿" in result["reply"]
    assert '"name"' not in result["reply"]  # 原始 JSON 不再出现在回复文本里


async def test_pure_text_reply_still_no_draft(monkeypatch):
    """纯澄清文本（无 JSON）→ 兜底不误伤，draft=None。"""
    _patch_llm(monkeypatch, ["请问要用 SMTP 还是邮件 API？"])
    result = await ToolGeneratorService.generate([_msg("user", "做个发邮件工具")])
    assert result["draft"] is None
    assert "SMTP" in result["reply"]


# ── 9. 结构化 content 块（thinking/text）——dict 原文不得泄漏 ─────────


async def test_structured_content_blocks_extract_text_only(monkeypatch):
    """模型返回 thinking + text 块（GLM/Anthropic 思考模式）→ 只取 text，
    绝不 str(块) 裸拼（否则用户看到 {'signature': ...} 原文）。"""
    from langchain_core.messages import AIMessage

    class _BlockLLM:
        def __init__(self, blocks):
            self.blocks = blocks

        async def ainvoke(self, messages):
            return AIMessage(content=self.blocks)

    payload = _draft_payload()
    blocks = [
        {"type": "thinking", "thinking": "User wants email tool...", "signature": "df7ccdf2f2b8"},
        {"type": "text", "text": "已生成草稿。\n```json\n"
         + json.dumps(payload, ensure_ascii=False) + "\n```"},
    ]

    async def _resolve(model_id: str = "", *, temperature: float = 0.2):
        return _BlockLLM(blocks)

    from app.services.tool_generator import ToolGeneratorService
    monkeypatch.setattr(ToolGeneratorService, "_build_llm", _resolve)

    result = await ToolGeneratorService.generate([_msg("user", "发通知邮件的工具")])

    assert result["draft"]["name"] == "send-notice"
    assert result["reply"] == "已生成草稿。"
    assert "signature" not in result["reply"]      # thinking 块不泄漏
    assert "thinking" not in result["reply"]
    assert "User wants email tool" not in result["reply"]

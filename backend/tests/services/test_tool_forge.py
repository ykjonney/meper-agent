"""ToolForgeService — 工具工坊 agent 测试（FakeLLM 驱动最小 harness 图）。

覆盖：create 全循环（提交草稿→用例→试跑→保存落库）、凭证 interrupt→resume
（known_user_args 记录与透传）、edit 模式走 update、凭证预检不空跑沙箱。
DB 用 fake motor（复用 test_user_tool_service 的 fake）；tool_tester 打桩。
"""
from __future__ import annotations

import json
from typing import Any

from app.services.tool_forge_service import ToolForgeService
from app.services.user_tool_service import UserToolService
from langchain_core.messages import AIMessage

from tests.services.test_user_tool_service import _published_tool, db  # noqa: F401

# ---------------------------------------------------------------------------
# FakeLLM（仿 harness conftest 鸭子类型：model_name / bind_tools / ainvoke）
# ---------------------------------------------------------------------------


class FakeLLM:
    def __init__(self, responses: list[AIMessage]):
        self._responses = list(responses)

    @property
    def model_name(self) -> str:
        return "fake-forge"

    def bind_tools(self, _tools):  # noqa: ANN001, ANN202 —— LangChain API 形态
        return self

    async def ainvoke(self, messages, _config=None):  # noqa: ANN001, ANN202
        if not self._responses:
            raise RuntimeError("FakeLLM exhausted")
        return self._responses.pop(0)


def _tool_msg(name: str, args: dict, idx: int) -> AIMessage:
    return AIMessage(content="", tool_calls=[
        {"name": name, "args": args, "id": f"call_{idx}", "type": "tool_call"},
    ])


DRAFT = {
    "name": "forge-echo",
    "description": "回显输入",
    "source": "code",
    "code": "def run(text: str) -> str:\n    return text",
    "llm_args_schema": {
        "type": "object",
        "properties": {"text": {"type": "string", "description": "输入文本"}},
        "required": ["text"],
    },
    "user_args_schema": {},
    "endpoint": {},
    "output_schema": {},
    "tags": [],
}


async def _drain(queue) -> list[dict]:
    """收完 SSE 帧（到 None 哨兵），返回解析后的 JSON 列表。"""
    frames: list[dict] = []
    while True:
        item = await queue.get()
        if item is None:
            return frames
        assert item.startswith("data: ")
        frames.append(json.loads(item[len("data: "):]))


def _patch_llm(monkeypatch, responses: list[AIMessage]) -> FakeLLM:
    llm = FakeLLM(responses)
    from app.services.tool_generator import ToolGeneratorService

    monkeypatch.setattr(ToolGeneratorService, "_build_llm", staticmethod(
        lambda model_id="": _async_return(llm)
    ))
    return llm


async def _async_return(value: Any) -> Any:
    return value


# ---------------------------------------------------------------------------
# create 全循环
# ---------------------------------------------------------------------------


async def test_forge_create_full_loop(monkeypatch, db):  # noqa: F811
    """提交 → 用例 → 试跑（通过）→ 保存：草稿落库 + done 帧附保存态。"""
    run_calls: list[dict] = []

    async def fake_run_once(definition, params, user_args):  # noqa: ANN001
        run_calls.append({"params": params, "user_args": user_args})
        return {"ok": True, "result": params.get("text", "")}

    async def fake_generate_cases(definition, model_id=""):  # noqa: ANN001
        return {"cases": [{"name": "c1", "description": "", "params": {"text": "hi"}}]}

    monkeypatch.setattr("app.services.tool_tester.run_once", fake_run_once)
    monkeypatch.setattr("app.services.tool_tester.generate_cases", fake_generate_cases)
    _patch_llm(monkeypatch, [
        _tool_msg("submit_definition", {"definition": DRAFT}, 1),
        _tool_msg("make_test_cases", {}, 2),
        _tool_msg("run_test", {"params": {"text": "hi"}}, 3),
        _tool_msg("save_tool", {}, 4),
        AIMessage(content="已完成：用例通过并保存。"),
    ])

    queue, forge_id = await ToolForgeService.stream(
        "u1", message="做个回显工具", mode="create",
    )
    frames = await _drain(queue)

    # 落库断言（fake motor）
    doc = await UserToolService.find_by_name("forge-echo")
    assert doc is not None and doc["status"] == "private"  # 非 admin 创建走治理链
    # 试跑凭证透传
    assert run_calls and run_calls[0]["params"] == {"text": "hi"}
    # done 帧附草稿与保存态
    done = frames[-1]
    assert done["done"] is True
    assert done["saved_tool_id"] == doc["_id"]
    assert done["draft"]["name"] == "forge-echo"
    assert forge_id == done["forge_id"]
    # 事件流里有工具结果事件（tool_call 来自模型侧流事件，FakeLLM 不产生）
    types = [f.get("type") for f in frames if "type" in f]
    assert "tool_result" in types


async def test_forge_admin_create_auto_publish(monkeypatch, db):  # noqa: F811
    """admin 的 save_tool 直接 published（免审）。"""
    monkeypatch.setattr("app.services.tool_tester.generate_cases", fake_no_cases)
    _patch_llm(monkeypatch, [
        _tool_msg("submit_definition", {"definition": DRAFT}, 1),
        _tool_msg("save_tool", {}, 2),
        AIMessage(content="已保存。"),
    ])
    queue, _ = await ToolForgeService.stream(
        "admin1", message="做个回显工具", mode="create", is_admin=True,
    )
    frames = await _drain(queue)
    doc = await UserToolService.find_by_name("forge-echo")
    assert doc is not None and doc["status"] == "published"
    assert frames[-1]["saved_tool_id"] == doc["_id"]


async def fake_no_cases(definition, model_id=""):  # noqa: ANN001
    return {"cases": []}


# ---------------------------------------------------------------------------
# 凭证：interrupt → resume
# ---------------------------------------------------------------------------


async def test_forge_credentials_interrupt_and_resume(monkeypatch, db):  # noqa: F811
    """run_test 缺凭证 → 提示引导；LLM 转 ask_clarification → interrupt 暂停
    → resume 答复 → 凭证记录并在后续 run_test 透传。"""
    cred_draft = {
        **DRAFT,
        "name": "forge-mail",
        "user_args_schema": {
            "type": "object",
            "properties": {"token": {"type": "string", "description": "授权码", "sensitive": True}},
        },
    }
    run_calls: list[dict] = []

    async def fake_run_once(definition, params, user_args):  # noqa: ANN001
        run_calls.append({"user_args": user_args})
        return {"ok": True, "result": "sent"}

    monkeypatch.setattr("app.services.tool_tester.run_once", fake_run_once)
    monkeypatch.setattr("app.services.tool_tester.generate_cases", fake_no_cases)
    _patch_llm(monkeypatch, [
        _tool_msg("submit_definition", {"definition": cred_draft}, 1),
        # 先不带凭证试跑 → 工具层预检拦截（返回缺凭证提示，不进沙箱）
        _tool_msg("run_test", {"params": {"text": "hi"}}, 2),
        # LLM 转向用户索取（interrupt 暂停图）
        _tool_msg("ask_clarification", {
            "question": "请提供发件授权码",
            "fields": [{"name": "token", "label": "授权码（敏感）"}],
        }, 3),
        # resume 后：带凭证重试 + 保存
        _tool_msg("run_test", {"params": {"text": "hi"}, "user_args": {"token": "tk-1"}}, 4),
        _tool_msg("save_tool", {}, 5),
        AIMessage(content="凭证已获取，测试通过并保存。"),
    ])

    queue, forge_id = await ToolForgeService.stream(
        "u1", message="做个发邮件工具", mode="create",
    )
    frames = await _drain(queue)
    # 第一轮：interrupt 事件出现、未保存、凭证未记录（沙箱未空跑）
    assert any(f.get("type") == "interrupt" for f in frames)
    assert not run_calls
    assert frames[-1]["saved_tool_id"] == ""

    # resume（前端凭证卡提交 dict）→ 续跑到保存
    queue2 = await ToolForgeService.resume(forge_id, {"token": "tk-1"})
    frames2 = await _drain(queue2)
    assert frames2[-1]["saved_tool_id"] != ""
    # 沙箱收到了凭证
    assert run_calls and run_calls[0]["user_args"] == {"token": "tk-1"}


# ---------------------------------------------------------------------------
# edit 模式与边界
# ---------------------------------------------------------------------------


async def test_forge_edit_mode_updates(monkeypatch, db):  # noqa: F811
    """edit 模式：save_tool 走 update（不新建）。"""
    tool_id = await _published_tool(db, owner="u1", name="forge-edit-t")
    monkeypatch.setattr("app.services.tool_tester.generate_cases", fake_no_cases)
    _patch_llm(monkeypatch, [
        _tool_msg("submit_definition", {"definition": {
            **DRAFT, "name": "forge-edit-t",
            "code": "def run(text: str) -> str:\n    return text + '!'",
            "description": "改：加感叹号",
        }}, 1),
        _tool_msg("save_tool", {}, 2),
        AIMessage(content="已更新。"),
    ])
    queue, _ = await ToolForgeService.stream(
        "u1", message="加个感叹号", mode="edit", tool_id=tool_id,
    )
    frames = await _drain(queue)
    doc = await UserToolService.get_tool(tool_id)
    assert doc is not None
    assert "!" in doc["code"] or doc["description"] == "改：加感叹号"
    assert frames[-1]["saved_tool_id"] == tool_id
    # owner 修改功能性字段 → 回 private 重审（治理不变）
    assert doc["status"] == "private"


async def test_forge_submit_invalid_definition_feedback(monkeypatch, db):  # noqa: F811
    """校验不过的草稿：工具层返回错误 JSON（LLM 可见），不落库不保存。"""
    monkeypatch.setattr("app.services.tool_tester.generate_cases", fake_no_cases)
    _patch_llm(monkeypatch, [
        _tool_msg("submit_definition", {"definition": {**DRAFT, "name": "bad name!"}}, 1),
        _tool_msg("save_tool", {}, 2),  # 无有效草稿 → 保存被拒
        AIMessage(content="名称不合法。"),
    ])
    queue, _ = await ToolForgeService.stream("u1", message="x", mode="create")
    frames = await _drain(queue)
    assert frames[-1]["saved_tool_id"] == ""
    assert frames[-1]["draft"] is None
    assert await UserToolService.find_by_name("bad name!") is None


async def test_forge_run_test_without_draft_rejected(monkeypatch, db):  # noqa: F811
    """未提交草稿直接 run_test → 工具层拒绝（不进沙箱）。"""
    called = {"run": False}

    async def fake_run_once(*_a, **_k):  # noqa: ANN202
        called["run"] = True
        return {"ok": True}

    monkeypatch.setattr("app.services.tool_tester.run_once", fake_run_once)
    _patch_llm(monkeypatch, [
        _tool_msg("run_test", {"params": {}}, 1),
        AIMessage(content="需要先提交草稿。"),
    ])
    queue, _ = await ToolForgeService.stream("u1", message="x", mode="create")
    await _drain(queue)
    assert called["run"] is False


async def test_forge_run_error_emits_error_event(monkeypatch, db):  # noqa: F811
    """graph 执行异常 → error 事件（source=graph，含 content 兼容字段）+ done 收尾，
    不裸奔（回归：source 曾误传 'forge' 触发 ErrorEvent 校验错、掩盖原始异常）。"""
    _patch_llm(monkeypatch, [])  # FakeLLM 耗尽 → RuntimeError 冒泡

    queue, _ = await ToolForgeService.stream("u1", message="x", mode="create")
    frames = await _drain(queue)

    errors = [f for f in frames if f.get("type") == "error"]
    assert errors, f"应有 error 事件，实际帧类型：{[f.get('type') for f in frames]}"
    assert errors[0]["source"] == "graph"
    assert errors[0]["content"]  # 前端 StreamEvent 兼容字段
    assert frames[-1]["done"] is True  # done 收尾不丢


async def test_forge_model_hot_switch_on_continue(monkeypatch, db):  # noqa: F811
    """续接会话时换模型 → 重建 LLM 注入 config（回归：曾「选 A 用 B」——
    会话模型创建时固化，续接的 model_id 被忽略）。"""
    built: list[str] = []
    llms: dict[str, FakeLLM] = {}

    def fake_build(model_id=""):  # noqa: ANN202
        built.append(model_id)
        llm = FakeLLM([AIMessage(content="ok")])
        llms[model_id] = llm
        return _async_return(llm)

    from app.services.tool_generator import ToolGeneratorService

    monkeypatch.setattr(ToolGeneratorService, "_build_llm", staticmethod(fake_build))

    queue1, forge_id = await ToolForgeService.stream("u1", message="hi", model_id="model_a")
    assert built == ["model_a"]
    first_llm = llms["model_a"]
    await _drain(queue1)  # 等第一轮跑完（busy 解除）再续接

    # 续接且换模型 → config 注入新 LLM
    queue2, _ = await ToolForgeService.stream(
        "u1", message="again", forge_id=forge_id, model_id="model_b",
    )
    await _drain(queue2)
    assert built == ["model_a", "model_b"]
    session = ToolForgeService._sessions[forge_id]
    assert session.model_id == "model_b"
    assert session.config["configurable"]["llm"] is llms["model_b"]
    assert session.config["configurable"]["llm"] is not first_llm


async def test_forge_run_test_hint_lists_injected_env(monkeypatch, db):  # noqa: F811
    """凭证已注入但执行报缺凭证类错误 → 结果附真实注入清单（防 AI 误判
    「沙箱限制」——实际是代码读取的 USER_ 名与参数名不一致）。"""
    cred_draft = {
        **DRAFT,
        "name": "forge-hint-t",
        "code": 'import os\n\ndef run(text: str) -> str:\n    return os.environ["USER_smtp_host"] + text',
        "user_args_schema": {
            "type": "object",
            "properties": {"smtp_host": {"type": "string", "sensitive": True}},
        },
    }

    async def fake_run_once(definition, params, user_args):  # noqa: ANN001
        # 断言 hint 前提：凭证确实传到了执行层
        assert user_args == {"smtp_host": "smtp.x"}
        return {"ok": False, "result": None, "error": "KeyError: 'USER_smtp_host'"}

    monkeypatch.setattr("app.services.tool_tester.run_once", fake_run_once)
    ToolForgeService._sessions.clear()  # 类级注册表跨测试累积——隔离本用例
    _patch_llm(monkeypatch, [
        _tool_msg("submit_definition", {"definition": cred_draft}, 1),
        _tool_msg("run_test", {"params": {"text": "hi"}, "user_args": {"smtp_host": "smtp.x"}}, 2),
        AIMessage(content="修订中。"),
    ])
    queue, forge_id = await ToolForgeService.stream("u1", message="x", mode="create")
    frames = await _drain(queue)
    # 凭证已记录进会话（后续 run_test 复用）
    assert ToolForgeService._sessions[forge_id].known_user_args == {"smtp_host": "smtp.x"}
    # run_test 的工具结果里包含注入清单提示
    results = [
        f for f in frames
        if f.get("type") == "tool_result" and f.get("tool_name") == "run_test"
    ]
    assert results and "USER_smtp_host" in (results[-1].get("content") or "")


async def test_forge_edit_session_seeds_current_definition(monkeypatch, db):  # noqa: F811
    """edit 会话注入当前工具定义（AI 修改必须知道改的是哪个工具——
    含名称/代码/参数 schema，用户只描述问题即可）。"""
    tool_id = await _published_tool(db, owner="u1", name="seed-t")
    _patch_llm(monkeypatch, [AIMessage(content="了解当前定义。")])
    queue, _ = await ToolForgeService.stream(
        "u1", message="跑起来很慢，帮我优化", mode="edit", tool_id=tool_id,
    )
    await _drain(queue)
    session = next(
        s for s in ToolForgeService._sessions.values() if s.tool_id == tool_id
    )
    assert "【编辑模式】" in session.system_prompt
    assert "seed-t" in session.system_prompt
    assert "def run(): return 1" in session.system_prompt  # 代码本体在种子 JSON 里

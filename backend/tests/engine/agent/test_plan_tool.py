"""propose_plan 工具测试 — 协程接线（回归：from_function 不识别 async）与 resume 语义。

回归背景：StructuredTool.from_function 不做协程自动识别——async 函数缺省
被当同步 func 调用，工具结果变成 "<coroutine object _propose_plan at ...>"
且 interrupt 不触发。必须显式传 coroutine=（与 ask_clarification 一致）。
"""
from __future__ import annotations

import langgraph.types as lgt
from app.engine.agent.plan_tool import (
    PLAN_APPROVED_MARKER,
    PLAN_TOOL_BY_NAME,
    propose_plan,
)

#: 结构齐全的测试计划（目标/验收标准必备；冒号后缀计入正文）。
_COMPLETE_PLAN = "# 目标：修复测试\n# 步骤\n- [ ] 跑 pytest\n# 验收标准\npytest -q 全绿\n"


def test_coroutine_wired() -> None:
    """协程接线：coroutine 已显式挂载（缺省 = 同步调用返回协程对象）。"""
    assert propose_plan.coroutine is not None
    assert "propose_plan" in PLAN_TOOL_BY_NAME


def test_args_schema_inferred() -> None:
    """参数 schema 从协程签名推断：plan 必填字符串。"""
    props = propose_plan.args_schema.model_json_schema()["properties"]
    assert "plan" in props


async def test_ainvoke_approval_marker(monkeypatch) -> None:
    """resume = 批准标记 → 工具返回批准语义（等待用户指示，不自行开工）。"""
    monkeypatch.setattr(lgt, "interrupt", lambda payload: PLAN_APPROVED_MARKER)
    result = await propose_plan.ainvoke({"plan": _COMPLETE_PLAN})
    assert "已批准" in result
    assert "等待用户指示" in result


async def test_ainvoke_feedback_text(monkeypatch) -> None:
    """resume = 任意文本 → 工具返回反馈语义（修订后重新提交）。"""
    monkeypatch.setattr(lgt, "interrupt", lambda payload: "范围缩小到后端")
    result = await propose_plan.ainvoke({"plan": _COMPLETE_PLAN})
    assert "用户对计划的反馈" in result
    assert "范围缩小到后端" in result


async def test_ainvoke_executes_coroutine_path(monkeypatch) -> None:
    """ainvoke 走 coroutine 路径（回归主断言：func 路径会返回协程 repr）。"""
    monkeypatch.setattr(lgt, "interrupt", lambda payload: PLAN_APPROVED_MARKER)
    result = await propose_plan.ainvoke({"plan": _COMPLETE_PLAN})
    assert "已批准" in result  # 真实字符串 = 协程被正确 await（而非 "<coroutine ...>"）


# ---------------------------------------------------------------------------
# 结构闸门（服务端校验）：缺必需章节不挂起，反馈模型补全
# ---------------------------------------------------------------------------


def test_validate_plan_sections_complete() -> None:
    """五段齐全 → 无缺失。"""
    from app.engine.agent.plan_tool import validate_plan_sections

    complete = (
        "# 目标：修复测试\n"
        "# 背景与约束\n仅后端\n"
        "# 步骤\n- [ ] 跑测试\n"
        "# 验收标准\npytest 全绿\n"
        "# 完成时交付\n摘要\n"
    )
    assert validate_plan_sections(complete) == []


def test_validate_plan_sections_missing_or_empty() -> None:
    """缺验收标准 / 目标空壳 → 报缺失（冒号后缀标题可识别）。"""
    from app.engine.agent.plan_tool import validate_plan_sections

    no_acceptance = "# 目标：修复测试\n# 步骤\n- [ ] x\n"
    assert validate_plan_sections(no_acceptance) == ["验收标准"]

    empty_objective = "# 目标\n# 验收标准\npytest 全绿\n"  # 目标空壳
    assert validate_plan_sections(empty_objective) == ["目标"]


async def test_propose_plan_rejects_incomplete_without_interrupt(monkeypatch) -> None:
    """缺必需章节：直接返回补全指引，不触发 interrupt（用户看不到残缺计划书）。"""
    def must_not_interrupt(payload):
        raise AssertionError("结构不完整的计划不应挂起")

    monkeypatch.setattr(lgt, "interrupt", must_not_interrupt)
    result = await propose_plan.ainvoke({"plan": "# 目标：修测试\n# 步骤\n- [ ] x"})
    assert "缺少必要章节" in result
    assert "验收标准" in result


async def test_propose_plan_complete_passes_gate(monkeypatch) -> None:
    """结构齐全：通过闸门正常挂起（interrupt 被调用）。"""
    from app.engine.agent.plan_tool import PLAN_APPROVED_MARKER

    monkeypatch.setattr(lgt, "interrupt", lambda payload: PLAN_APPROVED_MARKER)
    result = await propose_plan.ainvoke({"plan": _COMPLETE_PLAN})
    assert "已批准" in result

"""Tests for GatewayNodeExecutor and ``_gateway_compare``.

核心回归：前端「期望值」是纯文本 Input（恒存字符串），后端 actual 被
ExpressionEngine 还原为原始类型（bool/int/...）。修复前 ``True == "true"``、
``42 == "42"`` 被判不匹配、``42 > "10"`` 抛 TypeError 被吞——条件明明满足却
静默走默认分支；修复后字符串 expected 按 actual 类型归一化
（``_coerce_expected``）。同时锁定反向 bug：expected 为真 bool、actual 为
字符串 ``"false"`` 时不应误匹配（``bool("false")`` 是 True）。
"""
from __future__ import annotations

from app.engine.workflow.node_executor import GatewayNodeExecutor, _gateway_compare


def _make(
    conditions: list[dict] | None = None,
    default_branch: str = "node_default",
    fallback_on_error: str = "",
) -> GatewayNodeExecutor:
    config: dict = {"conditions": conditions or [], "default_branch": default_branch}
    if fallback_on_error:
        config["fallback_on_error"] = fallback_on_error
    return GatewayNodeExecutor(node_id="gw_1", node_config=config)


# ── GatewayNodeExecutor.execute：类型归一化后条件匹配 ──


async def test_bool_expected_string_matches_true():
    """actual 为布尔 True、expected 为字符串 "true" → 匹配（修复主 bug）。"""
    executor = _make(
        conditions=[{"expression": "{{ node_1.flag }}", "operator": "==", "expected": "true", "target": "node_a"}]
    )
    result = await executor.execute({"node_1": {"flag": True}})

    assert result.success
    assert result.selected_branch == "node_a"
    assert result.output["condition"] == "{{ node_1.flag }}"


async def test_bool_expected_string_matches_false():
    """actual 为布尔 False、expected 为字符串 "false" → 匹配。"""
    executor = _make(
        conditions=[{"expression": "{{ node_1.flag }}", "operator": "==", "expected": "false", "target": "node_a"}]
    )
    result = await executor.execute({"node_1": {"flag": False}})

    assert result.selected_branch == "node_a"


async def test_int_expected_string_matches():
    """actual 为 int 42、expected 为字符串 "42" → 匹配（修复主 bug）。"""
    executor = _make(
        conditions=[{"expression": "{{ node_1.count }}", "operator": "==", "expected": "42", "target": "node_a"}]
    )
    result = await executor.execute({"node_1": {"count": 42}})

    assert result.selected_branch == "node_a"


async def test_ordering_expected_string_matches():
    """actual 为 int 42、expected 为字符串 "10"、op ">" → 匹配（修复 TypeError 被吞）。"""
    executor = _make(
        conditions=[{"expression": "{{ node_1.count }}", "operator": ">", "expected": "10", "target": "node_a"}]
    )
    result = await executor.execute({"node_1": {"count": 42}})

    assert result.selected_branch == "node_a"


async def test_quoted_string_expected_unquoted():
    """actual 为字符串 "ok"、expected 按占位符提示填了 'ok'（带引号）→ 去引号后匹配。"""
    executor = _make(
        conditions=[{"expression": "{{ node_1.status }}", "operator": "==", "expected": "'ok'", "target": "node_a"}]
    )
    result = await executor.execute({"node_1": {"status": "ok"}})

    assert result.selected_branch == "node_a"


async def test_string_case_insensitive():
    """str vs str 大小写不敏感（既有行为保持）。"""
    executor = _make(
        conditions=[{"expression": "{{ node_1.decision }}", "operator": "==", "expected": "approve", "target": "node_a"}]
    )
    result = await executor.execute({"node_1": {"decision": "APPROVE"}})

    assert result.selected_branch == "node_a"


async def test_string_true_no_bool_regression():
    """actual 与 expected 都是字符串 "true" → 按 str/str 匹配（归一化不引入回归）。"""
    executor = _make(
        conditions=[{"expression": "{{ node_1.flag }}", "operator": "==", "expected": "true", "target": "node_a"}]
    )
    result = await executor.execute({"node_1": {"flag": "true"}})

    assert result.selected_branch == "node_a"


async def test_first_match_wins_in_order():
    """多条条件按顺序评估，首个匹配即返回。"""
    executor = _make(
        conditions=[
            {"expression": "{{ node_1.status }}", "operator": "==", "expected": "fail", "target": "node_fail"},
            {"expression": "{{ node_1.status }}", "operator": "==", "expected": "ok", "target": "node_ok"},
            {"expression": "{{ node_1.status }}", "operator": "==", "expected": "ok", "target": "node_ok2"},
        ]
    )
    result = await executor.execute({"node_1": {"status": "ok"}})

    assert result.selected_branch == "node_ok"


# ── GatewayNodeExecutor.execute：fallback 语义 ──


async def test_no_match_falls_back_to_default():
    executor = _make(
        conditions=[{"expression": "{{ node_1.status }}", "operator": "==", "expected": "ok", "target": "node_a"}]
    )
    result = await executor.execute({"node_1": {"status": "error"}})

    assert result.success
    assert result.selected_branch == "node_default"
    assert result.output["condition"] == "default"


async def test_fallback_on_error_precedes_default():
    executor = _make(
        conditions=[{"expression": "{{ node_1.status }}", "operator": "==", "expected": "ok", "target": "node_a"}],
        fallback_on_error="node_fb",
    )
    result = await executor.execute({"node_1": {"status": "error"}})

    assert result.selected_branch == "node_fb"


async def test_undefined_variable_falls_back():
    """变量路径不存在 → ChainableUndefined 渲染为空串 → 不匹配走 default（fail-safe）。"""
    executor = _make(
        conditions=[{"expression": "{{ node_1.missing.field }}", "operator": "==", "expected": "ok", "target": "node_a"}]
    )
    result = await executor.execute({"node_1": {"status": "ok"}})

    assert result.selected_branch == "node_default"


async def test_empty_conditions_fall_back():
    executor = _make(conditions=[])
    result = await executor.execute({})

    assert result.selected_branch == "node_default"


# ── _gateway_compare：类型归一化矩阵 ──


def test_compare_bool_vs_string():
    assert _gateway_compare(True, "true", "==") is True
    assert _gateway_compare(True, "True", "==") is True
    assert _gateway_compare(False, "false", "==") is True
    assert _gateway_compare(True, "false", "==") is False
    assert _gateway_compare(False, "true", "==") is False


def test_compare_number_vs_string():
    assert _gateway_compare(42, "42", "==") is True
    assert _gateway_compare(3.14, "3.14", "==") is True
    assert _gateway_compare(42, "41", "==") is False
    assert _gateway_compare(42, "abc", "==") is False


def test_compare_ordering_with_string_expected():
    assert _gateway_compare(42, "10", ">") is True
    assert _gateway_compare(5, "10", ">=") is False
    # 数字型字符串 actual 也能数值化重试
    assert _gateway_compare("42", "10", ">") is True


def test_compare_ordering_incomparable_is_no_match():
    # dict 与数字不可比，数值化重试也失败 → 不匹配
    assert _gateway_compare({"a": 1}, "5", ">") is False


def test_compare_true_bool_expected_with_string_actual():
    """反向 bug：expected 为真 bool、actual 为字符串 "false" → 不应误匹配。"""
    assert _gateway_compare("false", True, "==") is False
    assert _gateway_compare("false", False, "==") is True
    assert _gateway_compare("true", True, "==") is True


def test_compare_quoted_string_expected():
    assert _gateway_compare("ok", "'ok'", "==") is True
    # actual 是字符串 "42" 时 expected 保持字符串（不做数值化）
    assert _gateway_compare("42", "42", "==") is True


def test_compare_list_literal_expected():
    assert _gateway_compare([1, 2, 3], "[1, 2, 3]", "==") is True
    assert _gateway_compare([1, 2], "[1, 2, 3]", "==") is False


def test_compare_none_vs_string():
    assert _gateway_compare(None, "x", "==") is False
    assert _gateway_compare(None, "x", "!=") is True


def test_compare_contains_string():
    assert _gateway_compare("hello WORLD", "world", "contains") is True
    assert _gateway_compare("hello", "xyz", "contains") is False
    assert _gateway_compare("hello", "xyz", "not_contains") is True


def test_compare_contains_list():
    assert _gateway_compare(["a", "b"], "a", "contains") is True
    assert _gateway_compare(["a", "b"], "c", "contains") is False
    assert _gateway_compare(["a", "b"], "c", "not_contains") is True


def test_compare_contains_type_mismatch():
    # actual 非 str/list 一律不包含
    assert _gateway_compare(None, "x", "contains") is False
    assert _gateway_compare(42, "4", "contains") is False


def test_compare_unknown_operator():
    assert _gateway_compare("a", "a", "=~") is False

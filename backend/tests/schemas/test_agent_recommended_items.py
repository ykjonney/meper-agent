"""推荐项（recommended_items / recommended_groups）数量与字段校验测试。

独立项上限 200 条；分组上限 20 组、每组 50 条、组名 ≤50 字符。
纯 schema/model 校验，不触 DB。
"""
from __future__ import annotations

import pytest
from app.models.agent import Agent
from app.schemas.agent import AgentUpdate
from pydantic import ValidationError


def _items(n: int) -> list[dict[str, str]]:
    return [{"label": f"快捷输入 {i}", "prompt": f"prompt {i}"} for i in range(n)]


def _groups(n: int, items_per_group: int = 1) -> list[dict]:
    return [
        {"title": f"分组 {i}", "items": _items(items_per_group)} for i in range(n)
    ]


def test_agent_update_allows_200_items() -> None:
    update = AgentUpdate(name="a", recommended_items=_items(200))
    assert len(update.recommended_items) == 200


def test_agent_update_rejects_201_items() -> None:
    with pytest.raises(ValidationError):
        AgentUpdate(name="a", recommended_items=_items(201))


def test_agent_model_rejects_201_items() -> None:
    with pytest.raises(ValidationError):
        Agent(name="a", recommended_items=_items(201))


def test_recommended_item_label_too_long_rejected() -> None:
    with pytest.raises(ValidationError):
        AgentUpdate(name="a", recommended_items=[{"label": "x" * 101, "prompt": ""}])


def test_recommended_item_prompt_too_long_rejected() -> None:
    with pytest.raises(ValidationError):
        AgentUpdate(name="a", recommended_items=[{"label": "ok", "prompt": "x" * 501}])


# ── recommended_groups 分组 ──────────────────────────────────────────


def test_agent_update_allows_20_groups() -> None:
    update = AgentUpdate(name="a", recommended_groups=_groups(20))
    assert len(update.recommended_groups) == 20


def test_agent_update_rejects_21_groups() -> None:
    with pytest.raises(ValidationError):
        AgentUpdate(name="a", recommended_groups=_groups(21))


def test_agent_model_rejects_21_groups() -> None:
    with pytest.raises(ValidationError):
        Agent(name="a", recommended_groups=_groups(21))


def test_group_allows_50_items() -> None:
    update = AgentUpdate(
        name="a", recommended_groups=[{"title": "g", "items": _items(50)}]
    )
    assert len(update.recommended_groups[0].items) == 50


def test_group_rejects_51_items() -> None:
    with pytest.raises(ValidationError):
        AgentUpdate(name="a", recommended_groups=[{"title": "g", "items": _items(51)}])


def test_group_title_too_long_rejected() -> None:
    with pytest.raises(ValidationError):
        AgentUpdate(name="a", recommended_groups=[{"title": "x" * 51, "items": []}])


def test_group_title_empty_rejected() -> None:
    with pytest.raises(ValidationError):
        AgentUpdate(name="a", recommended_groups=[{"title": "", "items": _items(1)}])


def test_group_sanitizes_xss_payloads() -> None:
    update = AgentUpdate(
        name="a",
        recommended_groups=[
            {
                "title": '<script>alert("g")</script>销售查询',
                "items": [
                    {
                        "label": '<img src=x onerror=alert(1)>查业绩',
                        "prompt": "javascript:alert(2)",
                    }
                ],
            }
        ],
    )
    group = update.recommended_groups[0]
    assert "<script>" not in group.title
    assert "销售查询" in group.title
    assert "onerror" not in group.items[0].label
    assert "查业绩" in group.items[0].label
    assert "javascript:" not in group.items[0].prompt

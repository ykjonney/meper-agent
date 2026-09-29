"""llm_factory 的 Agent.max_retry 接线测试（P0-3 SDK 级瞬态重试）。

get_llm_client 把 Agent.max_retry（模型默认 3，ge=0 le=10）透传给 harness
的 build_client_from_doc/env —— 此前该字段沉睡未接任何调用方。
"""
from __future__ import annotations

import app.engine.llm_factory as lf


def _patch_env_builder(monkeypatch, calls: dict):
    """替换 harness 的 env 构建器（get_llm_client 函数内延迟 import，patch 包属性）。"""
    import agent_flow_harness

    def fake_env(model_name, agent_config=None, enable_thinking=False, max_retries=None):
        calls["model"] = model_name
        calls["max_retries"] = max_retries
        return object()

    monkeypatch.setattr(agent_flow_harness, "build_client_from_env", fake_env)


async def test_agent_max_retry_wired(monkeypatch) -> None:
    """Agent.max_retry → harness max_retries（显式值原样透传）。"""
    calls: dict = {}
    _patch_env_builder(monkeypatch, calls)

    await lf.get_llm_client({"default_model": "gpt-4o", "max_retry": 5})
    assert calls["max_retries"] == 5


async def test_max_retry_default_for_legacy_docs(monkeypatch) -> None:
    """旧文档缺 max_retry 字段 → 按模型默认 3。"""
    calls: dict = {}
    _patch_env_builder(monkeypatch, calls)

    await lf.get_llm_client({"default_model": "gpt-4o"})
    assert calls["max_retries"] == 3


async def test_max_retry_zero_disables_retries(monkeypatch) -> None:
    """显式 0 = 关闭 SDK 重试（不是回退默认）。"""
    calls: dict = {}
    _patch_env_builder(monkeypatch, calls)

    await lf.get_llm_client({"default_model": "gpt-4o", "max_retry": 0})
    assert calls["max_retries"] == 0


async def test_model_table_path_also_wired(monkeypatch) -> None:
    """模型表路径（model_ 前缀）同样透传 max_retries。"""
    import agent_flow_harness

    calls: dict = {}

    async def fake_resolve(model_ref: str):
        return {
            "model_id": "gpt-4o-mini", "base_url": None, "api_key": "sk-test",
            "compatibility_type": "openai", "auth_type": "bearer",
        }

    def fake_doc(doc, agent_config=None, enable_thinking=False, max_retries=None):
        calls["max_retries"] = max_retries
        return object()

    monkeypatch.setattr(lf, "_resolve_model_doc", fake_resolve)
    monkeypatch.setattr(agent_flow_harness, "build_client_from_doc", fake_doc)

    await lf.get_llm_client({"default_model": "model_01TEST", "max_retry": 8})
    assert calls["max_retries"] == 8

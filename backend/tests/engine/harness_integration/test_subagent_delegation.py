"""Tests for M1 sub-agent delegation wiring (workflow-side).

Covers:
- builder: delegation declaration section (only when subagents wired)
- _build_subagent_environment: spec/prompt/tools/llm assembly + per-subagent
  failure isolation (one broken sub-agent skips, not node-level failure)
- _merge_subagent_usage: numeric merge for the token ledger
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── builder: delegation declaration ──


class TestSubagentDeclaration:
    """build_tool_declaration emits the delegation section iff subagents."""

    @pytest.mark.asyncio
    async def test_declaration_lists_subagents_with_discipline(self) -> None:
        from app.engine.agent.builder import build_tool_declaration

        decl = await build_tool_declaration(
            {"builtin_config": []},
            execution_context="workflow",
            subagents=[
                {"name": "researcher", "description": "查资料并总结"},
                {"name": "fact_checker", "description": "核对事实"},
            ],
        )
        assert "Sub-Agent Delegation" in decl
        assert "delegate_to_subagent" in decl
        assert "researcher" in decl
        assert "fact_checker" in decl
        # 资源预算纪律（Anthropic 式治理进 prompt）
        assert "self-contained" in decl
        assert "synchronous" in decl

    @pytest.mark.asyncio
    async def test_no_section_without_subagents(self) -> None:
        from app.engine.agent.builder import build_tool_declaration

        decl = await build_tool_declaration(
            {"builtin_config": []}, execution_context="workflow",
        )
        assert "Sub-Agent Delegation" not in decl


# ── _build_subagent_environment: assembly ──


def _sub_doc(name: str, description: str = "desc") -> dict:
    return {
        "_id": f"agent_{name}",
        "name": name,
        "description": description,
        "prompt_slots": {"role": "你是助手", "task": "干活"},
        "builtin_config": [],
    }


class TestBuildSubagentEnvironment:
    """_build_subagent_environment assembles registry + providers."""

    @pytest.mark.asyncio
    async def test_assembles_specs_and_providers(self) -> None:
        from app.engine.harness_integration.context import _build_subagent_environment

        fake_tool = MagicMock()
        fake_tool.name = "kb_search"
        fake_llm = object()
        with patch(
            "app.engine.agent.slot_renderer.render_system_prompt_full",
            new=AsyncMock(return_value="SUB SYSTEM PROMPT"),
        ), patch(
            "app.engine.harness_integration.context.resolve_all_tools",
            new=AsyncMock(return_value=([fake_tool], [])),
        ), patch(
            "app.engine.llm_factory.get_llm_client",
            new=AsyncMock(return_value=fake_llm),
        ):
            ctx, decls, errors = await _build_subagent_environment(
                [
                    {"agent_doc": _sub_doc("researcher"), "timeout_ms": 60_000},
                    {"agent_doc": _sub_doc("checker"), "timeout_ms": 90_000},
                ],
                {"user_id": "u1", "session_id": "s1"},
                "workflow",
            )

        assert ctx is not None and not errors
        assert [d["name"] for d in decls] == ["researcher", "checker"]
        assert set(ctx.registry.list_names()) == {"researcher", "checker"}
        spec = ctx.registry.get("researcher")
        assert spec.timeout_ms == 60_000
        assert ctx.registry.get("checker").timeout_ms == 90_000
        # providers 预解析通道：工具与 LLM 都来自宿主注入
        assert ctx.resolve_tools(spec) == [fake_tool]
        assert ctx.resolve_llm(spec) is fake_llm

    @pytest.mark.asyncio
    async def test_broken_subagent_skips_not_fails(self) -> None:
        """单个子 agent 装配失败（如 slot 必填缺失）跳过并记 load_error，
        其余子 agent 正常装配——降级不炸节点。"""
        from app.engine.harness_integration.context import _build_subagent_environment

        async def _render(doc, **kw):
            if doc.get("name") == "broken":
                raise ValueError("missing required slot")
            return "OK PROMPT"

        with patch(
            "app.engine.agent.slot_renderer.render_system_prompt_full",
            new=_render,
        ), patch(
            "app.engine.harness_integration.context.resolve_all_tools",
            new=AsyncMock(return_value=([], [])),
        ), patch(
            "app.engine.llm_factory.get_llm_client",
            new=AsyncMock(return_value=object()),
        ):
            ctx, decls, errors = await _build_subagent_environment(
                [
                    {"agent_doc": _sub_doc("broken"), "timeout_ms": 60_000},
                    {"agent_doc": _sub_doc("fine"), "timeout_ms": 60_000},
                ],
                {},
                "workflow",
            )

        assert ctx is not None
        assert [d["name"] for d in decls] == ["fine"]
        assert len(errors) == 1 and "broken" in errors[0]["tool"]

    @pytest.mark.asyncio
    async def test_all_broken_returns_none_ctx(self) -> None:
        from app.engine.harness_integration.context import _build_subagent_environment

        with patch(
            "app.engine.agent.slot_renderer.render_system_prompt_full",
            new=AsyncMock(side_effect=ValueError("bad slots")),
        ):
            ctx, decls, errors = await _build_subagent_environment(
                [{"agent_doc": _sub_doc("broken"), "timeout_ms": 60_000}],
                {},
                "workflow",
            )

        assert ctx is None and decls == [] and len(errors) == 1

    @pytest.mark.asyncio
    async def test_duplicate_names_reported(self) -> None:
        from app.engine.harness_integration.context import _build_subagent_environment

        with patch(
            "app.engine.agent.slot_renderer.render_system_prompt_full",
            new=AsyncMock(return_value="P"),
        ), patch(
            "app.engine.harness_integration.context.resolve_all_tools",
            new=AsyncMock(return_value=([], [])),
        ), patch(
            "app.engine.llm_factory.get_llm_client",
            new=AsyncMock(return_value=object()),
        ):
            ctx, decls, errors = await _build_subagent_environment(
                [
                    {"agent_doc": _sub_doc("dup"), "timeout_ms": 60_000},
                    {"agent_doc": _sub_doc("dup"), "timeout_ms": 60_000},
                ],
                {},
                "workflow",
            )

        # 第二个重名被拒（记 error），第一个正常装配
        assert ctx is not None
        assert [d["name"] for d in decls] == ["dup"]
        assert len(errors) == 1

    @pytest.mark.asyncio
    async def test_subagent_tools_exclude_hitl_interrupt_tools(self) -> None:
        """子 agent 无人值守语义：HITL interrupt 工具必须剥离。子图无
        checkpointer，interrupt 即异常——chat 上下文强制开启的
        ask_clarification 若不剥离，子 agent 一调委派就报错。"""
        from app.engine.harness_integration.context import _build_subagent_environment

        def _tool(name: str) -> MagicMock:
            t = MagicMock()
            t.name = name
            return t

        sub_tools = [
            _tool("kb_search"),
            _tool("ask_clarification"),
            _tool("request_app_authorization"),
        ]
        with patch(
            "app.engine.agent.slot_renderer.render_system_prompt_full",
            new=AsyncMock(return_value="P"),
        ), patch(
            "app.engine.harness_integration.context.resolve_all_tools",
            new=AsyncMock(return_value=(sub_tools, [])),
        ), patch(
            "app.engine.llm_factory.get_llm_client",
            new=AsyncMock(return_value=object()),
        ):
            ctx, _decls, _errors = await _build_subagent_environment(
                [{"agent_doc": _sub_doc("researcher"), "timeout_ms": 60_000}],
                {},
                "chat",  # chat 上下文才会强制注入 ask_clarification
            )

        assert ctx is not None
        names = [
            t.name for t in ctx.resolve_tools(ctx.registry.get("researcher"))
        ]
        assert "ask_clarification" not in names
        assert "request_app_authorization" not in names
        assert "kb_search" in names

    @pytest.mark.asyncio
    async def test_subagent_tool_load_errors_surface(self) -> None:
        """子 agent 自身工具加载错误（MCP 不可达等）必须进 load_errors——
        静默丢弃会让宿主看不见工具残缺，排查时无从下手。"""
        from app.engine.harness_integration.context import _build_subagent_environment

        fake_tool = MagicMock()
        fake_tool.name = "kb_search"
        tool_err = {"tool": "mcp:conn1", "error": "connection refused"}
        with patch(
            "app.engine.agent.slot_renderer.render_system_prompt_full",
            new=AsyncMock(return_value="P"),
        ), patch(
            "app.engine.harness_integration.context.resolve_all_tools",
            new=AsyncMock(return_value=([fake_tool], [tool_err])),
        ), patch(
            "app.engine.llm_factory.get_llm_client",
            new=AsyncMock(return_value=object()),
        ):
            ctx, _decls, errors = await _build_subagent_environment(
                [{"agent_doc": _sub_doc("researcher"), "timeout_ms": 60_000}],
                {},
                "workflow",
            )

        # 子 agent 装配成功（ctx 非 None），但工具加载错误必须上报
        assert ctx is not None
        assert any(e.get("error") == "connection refused" for e in errors)


# ── usage merge ──


class TestMergeSubagentUsage:
    """_merge_subagent_usage merges numeric metrics into parent usage."""

    def test_merges_numeric_and_skips_non_numeric(self) -> None:
        from app.engine.harness_integration.execution import _merge_subagent_usage

        usage = {"total_tokens": 100, "llm_calls": 2}
        hctx = {"subagent_usage": {"total_tokens": 30, "llm_calls": 1, "flag": True}}
        _merge_subagent_usage(usage, hctx)
        assert usage == {"total_tokens": 130, "llm_calls": 3}

    def test_noop_without_subagent_usage(self) -> None:
        from app.engine.harness_integration.execution import _merge_subagent_usage

        usage = {"total_tokens": 100}
        _merge_subagent_usage(usage, {"subagent_usage": None})
        _merge_subagent_usage(usage, {})
        assert usage == {"total_tokens": 100}


# ── load_subagent_bundles（M1/M2 共用拉取，chat 侧 agent.subagent_ids 形态）──


def _db_with_agents(docs_by_id: dict) -> MagicMock:
    """Mongo mock：agents.find_one 按 _id 返回预置文档（模拟 status 查询条件）。"""
    mock_db = MagicMock()
    mock_col = MagicMock()

    async def _find(q: dict) -> dict | None:
        doc = docs_by_id.get(q.get("_id"))
        if doc is None:
            return None
        if "status" in q and doc.get("status") != q["status"]:
            return None  # 模拟真实查询的 status 过滤（draft 不命中）
        return doc

    mock_col.find_one = AsyncMock(side_effect=_find)
    mock_db.return_value.__getitem__.return_value = mock_col
    return mock_db


class TestLoadSubagentBundles:
    """published-only 拉取 + 两种输入形态兼容。"""

    @pytest.mark.asyncio
    async def test_dict_and_str_forms_both_supported(self) -> None:
        from app.engine.harness_integration.context import load_subagent_bundles

        docs = {
            "a1": {"_id": "a1", "name": "researcher", "description": "查资料", "status": "published"},
            "a2": {"_id": "a2", "name": "checker", "description": "核事实", "status": "published"},
        }
        with patch("app.db.mongodb.get_database", new=_db_with_agents(docs)):
            bundles, decls = await load_subagent_bundles(
                [{"agent_id": "a1", "timeout_ms": 60_000}, "a2"],
            )

        assert [b["agent_doc"]["name"] for b in bundles] == ["researcher", "checker"]
        assert bundles[0]["timeout_ms"] == 60_000
        assert bundles[1]["timeout_ms"] == 120_000  # str 形态默认
        assert [d["name"] for d in decls] == ["researcher", "checker"]

    @pytest.mark.asyncio
    async def test_published_only_and_dedup(self) -> None:
        """draft 跳过、不存在跳过、重复声明去重；空名跳过。"""
        from app.engine.harness_integration.context import load_subagent_bundles

        docs = {
            "pub": {"_id": "pub", "name": "ok", "status": "published"},
            "draft": {"_id": "draft", "name": "nope", "status": "draft"},
            "blank": {"_id": "blank", "name": "", "status": "published"},
        }
        with patch("app.db.mongodb.get_database", new=_db_with_agents(docs)):
            bundles, decls = await load_subagent_bundles(
                ["pub", "draft", "missing", "blank", "pub"],
            )

        assert [b["agent_doc"]["_id"] for b in bundles] == ["pub"]
        assert len(decls) == 1
        # 空 description 兜底（委派声明里没有说明的子 agent 会被 LLM 冷落）
        assert decls[0]["description"]

    @pytest.mark.asyncio
    async def test_empty_description_falls_back(self) -> None:
        from app.engine.harness_integration.context import load_subagent_bundles

        docs = {"a1": {"_id": "a1", "name": "helper", "description": "", "status": "published"}}
        with patch("app.db.mongodb.get_database", new=_db_with_agents(docs)):
            _, decls = await load_subagent_bundles(["a1"])
        assert "helper" in decls[0]["description"]


class TestSelfReferenceGuard:
    """自引用防御：父 agent 自身 id 不进委派池。"""

    @pytest.mark.asyncio
    async def test_exclude_agent_id_filters_self(self) -> None:
        from app.engine.harness_integration.context import load_subagent_bundles

        docs = {
            "me": {"_id": "me", "name": "self", "status": "published"},
            "other": {"_id": "other", "name": "helper", "status": "published"},
        }
        with patch("app.db.mongodb.get_database", new=_db_with_agents(docs)):
            bundles, decls = await load_subagent_bundles(
                ["me", "other"], exclude_agent_id="me",
            )

        assert [b["agent_doc"]["_id"] for b in bundles] == ["other"]
        assert [d["name"] for d in decls] == ["helper"]

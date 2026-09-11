"""Wiki builder tests — REACT loop with a fake LLM + status lifecycle.

The fake LLM scripts a minimal ingest: kb_guide → kb_write(create) →
final answer (no more tool calls). Verifies tool wiring, wiki page
output, and the Celery task's running→completed guard.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.core.config import settings
from app.engine.kb.tree import fs as kb_fs


class _FakeAIMessage:
    def __init__(self, content: str, tool_calls: list[dict] | None = None):
        self.content = content
        self.tool_calls = tool_calls or []


class _FakeLLM:
    """First call emits tool calls; second call returns the final summary."""

    def __init__(self):
        self.calls = 0
        self.bound_tools: list | None = None

    def bind_tools(self, tools):
        self.bound_tools = tools
        return self

    async def ainvoke(self, messages):
        self.calls += 1
        if self.calls == 1:
            return _FakeAIMessage(
                "",
                tool_calls=[
                    {
                        "name": "kb_guide",
                        "args": {},
                        "id": "call_1",
                    }
                ],
            )
        if self.calls == 2:
            return _FakeAIMessage(
                "",
                tool_calls=[
                    {
                        "name": "kb_write",
                        "args": {
                            "command": "create",
                            "path": "concepts/attention.md",
                            "content": "## 定义\n内容[^1]。\n\n[^1]: sources/paper.pdf, p.1\n",
                            "title": "Attention",
                            "tags": ["dl"],
                        },
                        "id": "call_2",
                    }
                ],
            )
        return _FakeAIMessage("已构建 1 页。", None)


@pytest.fixture
def kb_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "KB_CONTAINER_DIR", str(tmp_path))
    kb_id = "kb_b"
    kb_fs.init_wiki_skeleton(kb_id)
    base = kb_fs.get_kb_base_path(kb_id)
    (base / "sources" / "paper.pdf").write_bytes(b"%PDF")
    kb_doc = {
        "_id": kb_id,
        "type": "tree",
        "wiki_enabled": True,
        "builder_model_id": "model_x",
    }
    return kb_id, base, kb_doc


def _mock_db(kb_doc: dict):
    col = MagicMock()
    col.find_one = AsyncMock(return_value=kb_doc)
    col.find_one_and_update = AsyncMock(return_value=kb_doc)
    col.update_one = AsyncMock()
    # registry list_by_kb 的 find().sort().to_list() 链
    cursor = MagicMock()
    cursor.to_list = AsyncMock(return_value=[])
    cursor.sort = MagicMock(return_value=cursor)
    col.find = MagicMock(return_value=cursor)
    db = MagicMock()
    db.__getitem__ = MagicMock(return_value=col)
    return db, col


async def test_run_wiki_build_loop(kb_setup):
    kb_id, base, kb_doc = kb_setup
    fake = _FakeLLM()
    db, _ = _mock_db(kb_doc)
    with (
        patch("app.db.mongodb.get_database", return_value=db),
        patch(
            "app.engine.llm_factory.build_client_from_doc", return_value=fake
        ) as mock_build,
        patch(
            "app.services.model_service.ModelService.get_model_config_by_id",
            new=AsyncMock(return_value={"_id": "model_x", "name": "gpt"}),
        ),
    ):
        from app.services.kb_wiki_builder import run_wiki_build

        result = await run_wiki_build(kb_id)

    assert result["status"] == "completed"
    assert result["summary"].startswith("已构建")
    # bind_tools 拿到的是完整 wiki 工具集
    assert fake.bound_tools is not None
    names = {t.name for t in fake.bound_tools}
    assert {"kb_guide", "kb_write", "kb_delete", "kb_lint"} <= names
    # 工具真的执行了：页面落盘且带 frontmatter
    page = kb_fs.read_kb_file(kb_id, "wiki/concepts/attention.md")
    assert page is not None and page.startswith("---\ntitle: Attention")
    mock_build.assert_called_once()


async def test_run_wiki_build_requires_builder_model(kb_setup):
    kb_id, _base, kb_doc = kb_setup
    kb_doc["builder_model_id"] = ""
    db, _ = _mock_db(kb_doc)
    with patch("app.db.mongodb.get_database", return_value=db):
        from app.services.kb_wiki_builder import run_wiki_build

        result = await run_wiki_build(kb_id)
    assert result["status"] == "failed"
    assert "构建模型" in result["error"]


async def test_build_task_status_lifecycle(kb_setup):
    """Celery 任务侧：claim running → completed 落库；running 时拒绝重入。"""
    kb_id, _base, kb_doc = kb_setup
    db, col = _mock_db(kb_doc)
    # find_one_and_update 第一次返回 kb_doc（claim 成功）；重入场景返回 None
    col.find_one_and_update = AsyncMock(side_effect=[kb_doc, None])

    async def _fake_run(kb_id):
        return {"status": "completed", "steps": 3, "summary": "ok"}

    with (
        patch("app.db.mongodb.get_database", return_value=db),
        patch("app.services.kb_wiki_builder.run_wiki_build", new=_fake_run),
    ):
        from app.workers.tasks.wiki_build import _build_async

        r1 = await _build_async(kb_id)
        r2 = await _build_async(kb_id)  # 已 running → 拒绝

    assert r1["status"] == "completed"
    assert r2["status"] == "already_running"
    # 完成态落库
    sets = [c.args[1]["$set"] for c in col.update_one.call_args_list]
    assert any(s.get("last_build_status") == "completed" for s in sets)


# ---------------------------------------------------------------------------
# 卡死 running 恢复
# ---------------------------------------------------------------------------


def test_is_stale_running() -> None:
    import time
    from datetime import datetime, timedelta

    from app.services.kb_wiki_builder import is_stale_running

    now = time.time()
    fresh = datetime.now().isoformat()
    dead = (datetime.now() - timedelta(seconds=2400)).isoformat()

    assert is_stale_running({"last_build_status": "running", "last_build_at": dead})
    assert not is_stale_running({"last_build_status": "running", "last_build_at": fresh})
    assert not is_stale_running({"last_build_status": "completed", "last_build_at": dead})
    # 异常态：running 但无时间戳 / 坏时间戳 → 视为卡死可重派
    assert is_stale_running({"last_build_status": "running", "last_build_at": ""})
    assert is_stale_running({"last_build_status": "running", "last_build_at": "not-a-date"})
    _ = now


# ---------------------------------------------------------------------------
# 内容变更触发重消化（digest_hash 对账）
# ---------------------------------------------------------------------------


def _registry_rows(rows: list[dict]) -> MagicMock:
    col = MagicMock()
    cursor = MagicMock()
    cursor.to_list = AsyncMock(return_value=rows)
    cursor.sort = MagicMock(return_value=cursor)
    col.find = MagicMock(return_value=cursor)
    col.update_one = AsyncMock()
    return col


async def test_pending_digest_merges_uncited_and_stale(tmp_path, monkeypatch):
    """清单 = 未引用 ∪ 已引用但 hash 变了。"""
    from app.core.config import settings
    from app.engine.kb.tree import fs as kb_fs
    from app.services.kb_wiki_builder import pending_digest_sources

    monkeypatch.setattr(settings, "KB_CONTAINER_DIR", str(tmp_path))
    kb_fs.init_wiki_skeleton("kb_p")
    base = kb_fs.get_kb_base_path("kb_p")
    (base / "sources" / "new.pdf").write_bytes(b"%PDF")          # 未引用
    (base / "sources" / "updated.pdf").write_bytes(b"%PDF-v2")   # 已引用+hash 变了
    (base / "sources" / "stable.pdf").write_bytes(b"%PDF")       # 已引用+hash 一致
    (base / "wiki" / "overview.md").write_text(
        "---\ntitle: t\ntags: [a]\n---\n"
        "论断[^1][^2]。\n\n"
        "[^1]: sources/updated.pdf, p.1\n[^2]: sources/stable.pdf, p.1\n",
        encoding="utf-8",
    )
    rows = [
        {"_id": "r1", "relative_path": "sources/updated.pdf",
         "content_hash": "h2", "digest_hash": "h1"},
        {"_id": "r2", "relative_path": "sources/stable.pdf",
         "content_hash": "h3", "digest_hash": "h3"},
    ]
    reg_col = _registry_rows(rows)
    db = MagicMock()
    db.__getitem__ = MagicMock(return_value=reg_col)
    with patch("app.services.kb_wiki_registry.get_database", return_value=db):
        result = await pending_digest_sources("kb_p")
    assert result["uncited"] == ["sources/new.pdf"]
    assert result["stale"] == ["sources/updated.pdf"]
    assert result["pending"] == ["sources/new.pdf", "sources/updated.pdf"]


async def test_stamp_digested_only_cited_and_changed(tmp_path, monkeypatch):
    from app.core.config import settings
    from app.engine.kb.tree import fs as kb_fs
    from app.services.kb_wiki_builder import stamp_digested

    monkeypatch.setattr(settings, "KB_CONTAINER_DIR", str(tmp_path))
    kb_fs.init_wiki_skeleton("kb_s")
    base = kb_fs.get_kb_base_path("kb_s")
    (base / "sources" / "cited.pdf").write_bytes(b"x")
    (base / "sources" / "uncited.pdf").write_bytes(b"x")
    (base / "wiki" / "overview.md").write_text(
        "---\ntitle: t\ntags: [a]\n---\n论断[^1]。\n\n[^1]: sources/cited.pdf, p.1\n",
        encoding="utf-8",
    )
    rows = [
        {"_id": "r1", "relative_path": "sources/cited.pdf",
         "content_hash": "h_new", "digest_hash": "h_old"},
        # 未引用：不盖
        {"_id": "r2", "relative_path": "sources/uncited.pdf",
         "content_hash": "h_x", "digest_hash": ""},
    ]
    reg_col = _registry_rows(rows)
    db = MagicMock()
    db.__getitem__ = MagicMock(return_value=reg_col)
    with patch("app.services.kb_wiki_registry.get_database", return_value=db):
        stamped = await stamp_digested("kb_s")
    assert stamped == 1
    args = reg_col.update_one.call_args
    assert args.args[0] == {"_id": "r1"}
    assert args.args[1]["$set"]["digest_hash"] == "h_new"

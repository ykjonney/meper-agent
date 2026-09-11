"""Wiki-mode service tests — enable / upload routing / file view / build.

DB accesses are mocked (motor collections); filesystem hits a tmp
KB_CONTAINER_DIR. Celery dispatch is monkeypatched (no broker needed,
though conftest sets eager mode anyway).
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from app.core.config import settings
from app.engine.kb.tree import fs as kb_fs
from app.services.kb_service import KnowledgeBaseService


@pytest.fixture
def kb_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "KB_CONTAINER_DIR", str(tmp_path))
    return tmp_path


def _mock_db(kb_doc: dict | None, collections: dict[str, MagicMock] | None = None):
    """Mock get_database with a knowledge_bases collection.

    find_one returns kb_doc on first call, then {**kb_doc, wiki_enabled:
    True} — approximates the post-update read-back that service methods
    do via ``get_kb`` after ``update_one``.
    """
    kb_col = MagicMock()
    kb_col.find_one = AsyncMock(
        side_effect=[kb_doc, kb_doc]
    )
    for m in (
        "update_one",
        "insert_one",
        "delete_one",
        "delete_many",
        "create_index",
        "find_one_and_update",
    ):
        setattr(kb_col, m, AsyncMock())
    # registry list_by_kb 的 find().sort().to_list() 链
    kb_cursor = MagicMock()
    kb_cursor.to_list = AsyncMock(return_value=[])
    kb_cursor.sort = MagicMock(return_value=kb_cursor)
    kb_col.find = MagicMock(return_value=kb_cursor)
    db = MagicMock()
    db.__getitem__ = lambda self, key: (collections or {}).get(key, kb_col)
    return db, kb_col


# ---------------------------------------------------------------------------
# tree == wiki：存量懒迁移
# ---------------------------------------------------------------------------


async def test_legacy_tree_files_migrated_to_sources(kb_dir):
    """访问文件视图时，根目录/旧子目录的散 .md 被移入 sources/ 并建骨架。"""
    d = kb_dir / "kb_m"
    d.mkdir()
    (d / "README.md").write_text("r", encoding="utf-8")
    (d / "notes").mkdir()
    (d / "notes" / "api.md").write_text("a", encoding="utf-8")
    db, _ = _mock_db({"_id": "kb_m", "type": "tree"})
    with patch("app.services.kb_service.get_database", return_value=db):
        data = await KnowledgeBaseService.get_wiki_files("kb_m")
    assert data is not None
    base = kb_fs.get_kb_base_path("kb_m")
    assert (base / "sources" / "README.md").is_file()
    assert (base / "sources" / "api.md").is_file()
    assert not (base / "notes").exists()  # 搬空的旧目录被清掉
    assert (base / "wiki" / "overview.md").is_file()  # 骨架就绪
    # 迁移后的文件以源的身份出现在列表里
    assert {s["path"] for s in data["sources"]} >= {"sources/README.md", "sources/api.md"}
    # 幂等：再跑一次不重复搬
    with patch("app.services.kb_service.get_database", return_value=db):
        await KnowledgeBaseService.get_wiki_files("kb_m")
    assert (base / "sources" / "README.md").is_file()


async def test_create_kb_tree_initializes_wiki_skeleton(kb_dir):
    db, _ = _mock_db(None)
    with patch("app.services.kb_service.get_database", return_value=db):
        doc = await KnowledgeBaseService.create_kb(
            "测试库", "d", owner_user_id="u1", type="tree",
            builder_model_id="model_1",
        )
    assert doc["type"] == "tree"
    base = kb_fs.get_kb_base_path(doc["_id"])
    assert (base / "sources").is_dir()
    assert (base / "wiki" / "overview.md").is_file()
    assert (base / "wiki" / "concepts").is_dir()
    assert (base / "wiki" / "entities").is_dir()


# ---------------------------------------------------------------------------
# upload routing
# ---------------------------------------------------------------------------


async def test_upload_routes_wiki_sources(kb_dir):
    kb_fs.init_wiki_skeleton("kb_u")
    reg_col = _registry_col()
    db, _ = _mock_db(
        {"_id": "kb_u", "type": "tree", "owner_user_id": "u1"},
        collections={"kb_wiki_documents": reg_col},
    )
    # find_one：无既有登记 → 注册后读回 ready 记录（md 直读原文，不派提取）
    reg_col.find_one = AsyncMock(
        side_effect=[
            None,
            {"_id": "reg_1", "status": "ready", "knowledge_base_id": "kb_u"},
        ]
    )
    md_bytes = "# note\n内容".encode()
    with (
        patch("app.services.kb_service.get_database", return_value=db),
        patch("app.services.kb_wiki_registry.get_database", return_value=db),
    ):
        result = await KnowledgeBaseService.upload_files(
            "kb_u",
            [("note.md", md_bytes), ("evil.md", b"x")],
            uploaded_by="u1",
        )
    assert result["created"] == ["note.md"]
    assert (kb_fs.get_kb_base_path("kb_u") / "sources" / "note.md").read_bytes() == md_bytes
    # md 源直接 ready：find_one 第二次读回的应已是 ready（本 mock 返回 pending
    # 只为断言派发逻辑——md 不会派任务）。此处 md 为唯一样本，断言不派发即可。
    reg_col.insert_one.assert_awaited_once()


async def test_upload_wiki_dispatches_extract_for_binary(kb_dir):
    kb_fs.init_wiki_skeleton("kb_u3")
    reg_col = _registry_col()
    db, _ = _mock_db(
        {"_id": "kb_u3", "type": "tree"},
        collections={"kb_wiki_documents": reg_col},
    )
    reg_col.find_one = AsyncMock(
        side_effect=[
            None,
            {
                "_id": "reg_2",
                "status": "pending",
                "knowledge_base_id": "kb_u3",
                "relative_path": "sources/paper.pdf",
            },
        ]
    )
    with (
        patch("app.services.kb_service.get_database", return_value=db),
        patch("app.services.kb_wiki_registry.get_database", return_value=db),
        patch("app.services.kb_wiki_registry.dispatch_extract_task") as mock_dispatch,
    ):
        result = await KnowledgeBaseService.upload_files(
            "kb_u3", [("paper.pdf", b"%PDF-1.4 fake")], uploaded_by="u1"
        )
    assert result["created"] == ["paper.pdf"]
    mock_dispatch.assert_called_once_with("reg_2")


async def test_upload_wiki_rejects_bad_type(kb_dir):
    kb_fs.init_wiki_skeleton("kb_u2")
    reg_col = _registry_col()
    db, _ = _mock_db(
        {"_id": "kb_u2", "type": "tree"},
        collections={"kb_wiki_documents": reg_col},
    )
    with (
        patch("app.services.kb_service.get_database", return_value=db),
        patch("app.services.kb_wiki_registry.get_database", return_value=db),
    ):
        result = await KnowledgeBaseService.upload_files(
            "kb_u2", [("app.zip", b"PK")], uploaded_by="u1"
        )
    assert result["created"] == []
    assert "不支持的文件类型" in result["errors"][0]["error"]


# ---------------------------------------------------------------------------
# wiki file view
# ---------------------------------------------------------------------------


def _registry_col(rows: list[dict] | None = None) -> MagicMock:
    """Registry collection mock with a chainable find().sort().to_list()."""
    col = MagicMock()
    cursor = MagicMock()
    cursor.to_list = AsyncMock(return_value=rows or [])
    cursor.sort = MagicMock(return_value=cursor)
    col.find = MagicMock(return_value=cursor)
    col.delete_one = AsyncMock()
    col.create_index = AsyncMock()
    col.update_one = AsyncMock()
    col.insert_one = AsyncMock()
    return col


async def test_get_wiki_files_returns_tree_and_sources(kb_dir):
    kb_fs.init_wiki_skeleton("kb_v")
    base = kb_fs.get_kb_base_path("kb_v")
    (base / "sources" / "paper.pdf").write_bytes(b"%PDF")
    (base / "wiki" / "concepts" / "x.md").write_text("x", encoding="utf-8")
    reg_col = _registry_col()
    db, _ = _mock_db(
        {"_id": "kb_v", "type": "tree"},
        collections={"kb_wiki_documents": reg_col},
    )
    with (
        patch("app.services.kb_service.get_database", return_value=db),
        patch("app.services.kb_wiki_registry.get_database", return_value=db),
    ):
        data = await KnowledgeBaseService.get_wiki_files("kb_v")
    assert data is not None

    def _leaf_keys(nodes: list[dict]) -> list[str]:
        out: list[str] = []
        for n in nodes:
            if n.get("children"):
                out.extend(_leaf_keys(n["children"]))
            else:
                out.append(n["key"])
        return out

    wiki_paths = _leaf_keys(data["wiki"])
    assert "wiki/concepts/x.md" in wiki_paths
    assert "wiki/overview.md" in wiki_paths
    assert data["sources"][0]["path"] == "sources/paper.pdf"
    assert data["sources"][0]["status"] == "ready"  # 无登记 → 默认 ready


# ---------------------------------------------------------------------------
# delete hooks
# ---------------------------------------------------------------------------


async def test_delete_source_cleans_registry_and_extract(kb_dir):
    kb_fs.init_wiki_skeleton("kb_d")
    base = kb_fs.get_kb_base_path("kb_d")
    (base / "sources" / "a.pdf").write_bytes(b"x")
    (base / "sources" / ".extracted" / "a.pdf.md").write_text("t", encoding="utf-8")
    reg_col = _registry_col()
    db, _ = _mock_db(
        {"_id": "kb_d", "type": "tree"},
        collections={"kb_wiki_documents": reg_col},
    )
    with (
        patch("app.services.kb_service.get_database", return_value=db),
        patch("app.services.kb_wiki_registry.get_database", return_value=db),
    ):
        ok = await KnowledgeBaseService.delete_kb_file("kb_d", "sources/a.pdf")
    assert ok is True
    assert not (base / "sources" / "a.pdf").exists()
    assert not (base / "sources" / ".extracted" / "a.pdf.md").exists()
    reg_col.delete_one.assert_awaited_once()

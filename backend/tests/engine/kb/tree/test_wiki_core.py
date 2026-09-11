"""Wiki-mode core tests — skeleton / listing / guide stats / lint (pure FS).

All tests run against a tmp KB_CONTAINER_DIR; no DB access needed for the
engine layer (guide/lint/manager scan the filesystem directly).
"""
from pathlib import Path

import pytest
from app.core.config import settings
from app.engine.kb.tree import fs as kb_fs
from app.engine.kb.tree.guide import cited_sources, wiki_links, wiki_stats
from app.engine.kb.tree.lint import run_lint


@pytest.fixture
def kb_root(tmp_path, monkeypatch):
    """Point the KB container at a tmp dir; returns factory making KB dirs."""
    monkeypatch.setattr(settings, "KB_CONTAINER_DIR", str(tmp_path))

    def _make(kb_id: str) -> Path:
        d = tmp_path / kb_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    return _make


# ---------------------------------------------------------------------------
# skeleton + listing
# ---------------------------------------------------------------------------


def test_init_wiki_skeleton_creates_layout(kb_root):
    kb_root("kb_a")
    kb_fs.init_wiki_skeleton("kb_a")

    base = kb_fs.get_kb_base_path("kb_a")
    assert (base / "sources" / ".extracted").is_dir()
    assert (base / "wiki" / "concepts").is_dir()
    assert (base / "wiki" / "entities").is_dir()
    assert (base / "wiki" / "overview.md").is_file()
    assert (base / "wiki" / "log.md").is_file()
    # 幂等：重跑不覆盖已有 overview
    (base / "wiki" / "overview.md").write_text("custom", encoding="utf-8")
    kb_fs.init_wiki_skeleton("kb_a")
    assert (base / "wiki" / "overview.md").read_text(encoding="utf-8") == "custom"


def test_list_kb_files_skips_hidden_dirs(kb_root):
    d = kb_root("kb_b")
    (d / "sources" / ".extracted").mkdir(parents=True)
    (d / "sources" / "paper.pdf").write_bytes(b"%PDF")
    (d / "sources" / ".extracted" / "paper.pdf.md").write_text("p1", encoding="utf-8")
    (d / "wiki").mkdir()
    (d / "wiki" / "overview.md").write_text("ov", encoding="utf-8")
    (d / "README.md").write_text("r", encoding="utf-8")

    paths = [f["path"] for f in kb_fs.list_kb_files("kb_b")]
    assert "wiki/overview.md" in paths
    assert "README.md" in paths
    assert "sources/.extracted/paper.pdf.md" not in paths

    srcs = [f["path"] for f in kb_fs.list_wiki_sources("kb_b")]
    assert srcs == ["sources/paper.pdf"]

    pages = [f["path"] for f in kb_fs.list_wiki_pages("kb_b")]
    assert pages == ["wiki/overview.md"]


def test_iter_md_files_scopes(kb_root):
    d = kb_root("kb_c")
    (d / "sources" / ".extracted").mkdir(parents=True)
    (d / "sources" / "a.pdf").write_bytes(b"x")
    (d / "sources" / ".extracted" / "a.pdf.md").write_text("ext", encoding="utf-8")
    (d / "sources" / "note.md").write_text("n", encoding="utf-8")
    (d / "wiki").mkdir()
    (d / "wiki" / "overview.md").write_text("ov", encoding="utf-8")
    (d / "legacy.md").write_text("l", encoding="utf-8")

    rel = lambda ps: sorted(str(p.relative_to(kb_fs.get_kb_base_path("kb_c"))) for p in ps)  # noqa: E731

    assert rel(kb_fs.iter_md_files("kb_c", "wiki")) == ["wiki/overview.md"]
    assert rel(kb_fs.iter_md_files("kb_c", "sources")) == [
        "sources/.extracted/a.pdf.md",
        "sources/note.md",
    ]
    assert rel(kb_fs.iter_md_files("kb_c", "all")) == [
        "legacy.md",
        "sources/.extracted/a.pdf.md",
        "sources/note.md",
        "wiki/overview.md",
    ]


def test_extracted_path_for_injective(kb_root):
    assert (
        kb_fs.extracted_path_for("kb", "sources/report.pdf")
        == "sources/.extracted/report.pdf.md"
    )
    # 同名不同扩展不冲突
    assert kb_fs.extracted_path_for("kb", "sources/report.docx") != (
        kb_fs.extracted_path_for("kb", "sources/report.pdf")
    )


# ---------------------------------------------------------------------------
# guide stats + link graph
# ---------------------------------------------------------------------------


def _build_sample_wiki(d: Path) -> None:
    kb_fs.init_wiki_skeleton("kb_d")
    base = d
    (base / "sources" / "paper.pdf").write_bytes(b"%PDF")
    (base / "sources" / "extra.docx").write_bytes(b"x")
    (base / "wiki" / "overview.md").write_text(
        "---\ntitle: 总览\ntags: [总览]\n---\n"
        "- [Attention](concepts/attention.md)\n",
        encoding="utf-8",
    )
    (base / "wiki" / "concepts").mkdir(exist_ok=True)
    (base / "wiki" / "concepts" / "attention.md").write_text(
        "---\ntitle: Attention\ntags: [dl]\n---\n"
        "## 定义\nQ/K/V…[^1]\n\n"
        "## 作者\n见 [Vaswani](../entities/vaswani.md)\n\n"
        "[^1]: sources/paper.pdf, p.5\n",
        encoding="utf-8",
    )
    (base / "wiki" / "entities").mkdir(exist_ok=True)
    (base / "wiki" / "entities" / "vaswani.md").write_text(
        "---\ntitle: Vaswani\ntags: [people]\n---\n作者页。\n",
        encoding="utf-8",
    )
    # log 追加一条 ingest 便于 stats 的 log_tail
    (base / "wiki" / "log.md").write_text(
        "---\ntitle: 工作日志\ntags: [日志]\n---\n"
        "## [2026-09-09] ingest | paper\n",
        encoding="utf-8",
    )


def test_guide_stats_and_links(kb_root):
    d = kb_root("kb_d")
    _build_sample_wiki(d)

    pages: dict[str, str] = {}
    for e in kb_fs.list_wiki_pages("kb_d"):
        c = kb_fs.read_kb_file("kb_d", e["path"])
        if c is not None:
            pages[e["path"]] = c
    assert cited_sources(pages) == {"sources/paper.pdf"}

    links = wiki_links(pages)
    assert links["wiki/overview.md"] == {"wiki/concepts/attention.md"}
    assert links["wiki/concepts/attention.md"] == {"wiki/entities/vaswani.md"}

    stats = wiki_stats("kb_d")
    assert stats["source_count"] == 2
    assert stats["page_count"] == 4  # overview+log+attention+vaswani
    assert stats["uncited_sources"] == ["sources/extra.docx"]
    assert "ingest | paper" in stats["log_tail"]


# ---------------------------------------------------------------------------
# lint rules
# ---------------------------------------------------------------------------


def test_lint_all_rules(kb_root):
    d = kb_root("kb_e")
    kb_fs.init_wiki_skeleton("kb_e")
    (d / "sources" / "paper.pdf").write_bytes(b"%PDF")
    (d / "sources" / "unused.txt").write_text("u", encoding="utf-8")
    (d / "wiki" / "overview.md").write_text(
        "---\ntitle: 总览\ntags: [a]\n---\n- [好页](concepts/good.md)\n",
        encoding="utf-8",
    )
    # 好页：引用存在 + 链接存在
    (d / "wiki" / "concepts").mkdir(exist_ok=True)
    (d / "wiki" / "concepts" / "good.md").write_text(
        "---\ntitle: 好\ntags: [a, b]\n---\n论断[^1]。\n\n[^1]: sources/paper.pdf, p.1\n",
        encoding="utf-8",
    )
    # 坏页：缺 frontmatter、未定义脚注、悬空链接、孤儿
    (d / "wiki" / "concepts" / "bad.md").write_text(
        "## 节\n引用[^9]缺失。链接到 [不存在](nope.md)。\n\n[^1]: 已定义但没人用\n",
        encoding="utf-8",
    )

    report = run_lint("kb_e")
    rules = {}
    for i in report["issues"]:
        rules.setdefault(i["rule"], []).append(i)

    assert any("bad.md" in i["path"] for i in rules["frontmatter"])
    fh = rules["footnote-hygiene"]
    assert any("未定义" in i["detail"] for i in fh)
    assert any("未被引用" in i["detail"] for i in fh)
    assert any("悬空" in i["detail"] or "不存在" in i["detail"] for i in rules["dangling-link"])
    assert any("bad.md" in i["path"] for i in rules["orphan-page"])
    assert any("unused.txt" in i["path"] for i in rules["uncited-source"])
    # good.md 不产生 error
    error_paths = [i["path"] for i in report["issues"] if i["severity"] == "error"]
    assert "wiki/concepts/good.md" not in error_paths
    assert report["stats"]["page_count"] == 4
    assert report["stats"]["cited_source_count"] == 1


def test_lint_unresolved_citation(kb_root):
    d = kb_root("kb_f")
    kb_fs.init_wiki_skeleton("kb_f")
    (d / "wiki" / "overview.md").write_text(
        "---\ntitle: t\ntags: [a]\n---\n话[^1]。\n\n[^1]: sources/gone.pdf, p.2\n",
        encoding="utf-8",
    )
    report = run_lint("kb_f")
    assert any(
        i["rule"] == "unresolved-citation" and "gone.pdf" in i["detail"]
        for i in report["issues"]
    )

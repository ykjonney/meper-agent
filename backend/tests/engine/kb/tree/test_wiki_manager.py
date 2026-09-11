"""Wiki-mode KbManager toolset tests — guide/write/delete/lint + scoped read.

Runs against a tmp KB container; wiki tools are pure FS (no DB).
"""

import pytest
from app.core.config import settings
from app.engine.kb.tree import fs as kb_fs
from app.engine.kb.tree.manager import KbManager


@pytest.fixture
def wiki_kb(tmp_path, monkeypatch):
    """A wiki-mode KB with one extracted source; returns (kb_id, manager)."""
    monkeypatch.setattr(settings, "KB_CONTAINER_DIR", str(tmp_path))
    kb_id = "kb_w"
    kb_fs.init_wiki_skeleton(kb_id)
    base = kb_fs.get_kb_base_path(kb_id)
    (base / "sources" / "paper.pdf").write_bytes(b"%PDF")
    (base / "sources" / ".extracted" / "paper.pdf.md").write_text(
        "<!-- source: paper.pdf -->\n<!-- p.1 -->\n\n## Abstract\n\nattention is all you need\n\n"
        "<!-- p.2 -->\n\n## Method\n\ndot product of q and k\n",
        encoding="utf-8",
    )
    (base / "sources" / "note.md").write_text("plain md source\n", encoding="utf-8")
    mgr = KbManager({kb_id: base}, wiki_kb_ids={kb_id})
    return kb_id, mgr


# ---------------------------------------------------------------------------
# kb_guide
# ---------------------------------------------------------------------------


def test_guide_returns_conventions_and_stats(wiki_kb):
    kb_id, mgr = wiki_kb
    out = mgr.guide()
    assert "黄金法则" in out
    assert "sources/ 只读" in out
    assert "源文件数: 2" in out
    assert "paper.pdf" in out  # 未引用源清单
    assert "note.md" in out


def test_guide_requires_wiki_kb(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "KB_CONTAINER_DIR", str(tmp_path))
    (tmp_path / "kb_p").mkdir()
    mgr = KbManager({"kb_p": tmp_path / "kb_p"})
    assert "Error" in mgr.guide()


# ---------------------------------------------------------------------------
# kb_write / kb_delete
# ---------------------------------------------------------------------------


def test_write_create_generates_frontmatter(wiki_kb):
    kb_id, mgr = wiki_kb
    out = mgr.write(
        "create",
        "concepts/attention.md",
        content="## 定义\n内容…[^1]\n\n[^1]: sources/paper.pdf, p.1\n",
        title="Attention",
        tags=["dl", "seq"],
    )
    assert "已创建" in out
    content = kb_fs.read_kb_file(kb_id, "wiki/concepts/attention.md")
    assert content is not None
    assert content.startswith("---\ntitle: Attention")
    assert "tags: [dl, seq]" in content
    assert "## 定义" in content
    assert "# Attention" not in content.split("---")[-1].split("##")[0]  # 无 H1


def test_write_create_strips_h1_and_existing_frontmatter(wiki_kb):
    kb_id, mgr = wiki_kb
    mgr.write(
        "create",
        "concepts/x.md",
        content="---\ntitle: old\n---\n# 大标题\n正文",
    )
    content = kb_fs.read_kb_file(kb_id, "wiki/concepts/x.md")
    assert content is not None
    assert content.count("---") == 2  # 只剩系统 frontmatter
    assert "# 大标题" not in content


def test_write_str_replace_unique(wiki_kb):
    kb_id, mgr = wiki_kb
    mgr.write("create", "concepts/r.md", content="AAA BBB AAA")
    # 多次出现 → 拒绝
    out = mgr.write("str_replace", "concepts/r.md", old_string="AAA", new_string="CCC")
    assert "不唯一" in out
    out = mgr.write("str_replace", "concepts/r.md", old_string="AAA BBB", new_string="CCC BBB")
    assert "已更新" in out
    content = kb_fs.read_kb_file(kb_id, "wiki/concepts/r.md") or ""
    assert content.rstrip("\n").endswith("CCC BBB AAA")


def test_write_append(wiki_kb):
    kb_id, mgr = wiki_kb
    mgr.write("create", "concepts/a.md", content="line1")
    out = mgr.write("append", "concepts/a.md", content="line2")
    assert "已更新" in out
    assert kb_fs.read_kb_file(kb_id, "wiki/concepts/a.md").endswith("line1\nline2")


def test_write_rejects_sources_and_traversal(wiki_kb):
    _kb_id, mgr = wiki_kb
    assert "只读" in mgr.write("create", "sources/evil.md", content="x")
    assert "非法" in mgr.write("create", "../outside.md", content="x")
    assert "非法" in mgr.write("create", "wiki/../../escape.md", content="x")


def test_delete_protections(wiki_kb):
    kb_id, mgr = wiki_kb
    assert "受保护" in mgr.delete("overview.md")
    assert "受保护" in mgr.delete("log.md")
    mgr.write("create", "concepts/tmp.md", content="x")
    out = mgr.delete("concepts/tmp.md")
    assert "已删除" in out
    assert kb_fs.read_kb_file(kb_id, "wiki/concepts/tmp.md") is None


# ---------------------------------------------------------------------------
# kb_read：源提取文本映射 / 分页 / sections / 批量
# ---------------------------------------------------------------------------


def test_read_source_maps_to_extracted(wiki_kb):
    _kb_id, mgr = wiki_kb
    out = mgr.read("sources/paper.pdf")
    assert "提取文本" in out
    assert "attention is all you need" in out


def test_read_pages_filter(wiki_kb):
    _kb_id, mgr = wiki_kb
    out = mgr.read("sources/paper.pdf", pages="2")
    assert "dot product" in out
    assert "all you need" not in out


def test_read_sections_filter(wiki_kb):
    _kb_id, mgr = wiki_kb
    out = mgr.read("sources/paper.pdf", sections=["Method"])
    assert "dot product" in out
    assert "all you need" not in out


def test_read_batch_glob(wiki_kb):
    _kb_id, mgr = wiki_kb
    mgr.write("create", "concepts/a.md", content="甲" * 10)
    mgr.write("create", "concepts/b.md", content="乙" * 10)
    out = mgr.read("wiki/concepts/*.md")
    assert "== " in out
    assert "甲" in out and "乙" in out


# ---------------------------------------------------------------------------
# grep scope
# ---------------------------------------------------------------------------


def test_grep_scope_partition(wiki_kb):
    kb_id, mgr = wiki_kb
    mgr.write(
        "create",
        "concepts/attention.md",
        content="## 定义\nwiki 层的关键词 ALPHA\n",
    )
    wiki_hits = mgr.grep("ALPHA|attention is all", scope="wiki")
    assert f"{kb_id}/wiki/concepts/attention.md" in wiki_hits
    assert "paper.pdf.md" not in wiki_hits

    src_hits = mgr.grep("ALPHA|attention is all", scope="sources")
    assert "paper.pdf.md" in src_hits
    assert "wiki/concepts" not in src_hits


def test_lint_tool_output(wiki_kb):
    _kb_id, mgr = wiki_kb
    out = mgr.lint()
    # 初始骨架：overview/log 均有 frontmatter；sources 未引用 → info
    assert "uncited-source" in out


def test_make_tools_includes_wiki_set_only_for_wiki(wiki_kb, tmp_path):
    _kb_id, mgr = wiki_kb
    names = [t.name for t in mgr.make_tools()]
    assert {"kb_glob", "kb_grep", "kb_read"} <= set(names)
    assert {"kb_guide", "kb_write", "kb_delete", "kb_lint"} <= set(names)

    plain = KbManager({"kb_p": tmp_path / "kb_p"})
    plain_names = [t.name for t in plain.make_tools()]
    assert "kb_write" not in plain_names
    assert plain_names == ["kb_glob", "kb_grep", "kb_read"]

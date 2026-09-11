"""Wiki guide — the conventions the AI follows to build/maintain the wiki.

llmwiki-style "compiled wiki" for wiki-mode tree KBs. ``GUIDE_TEXT`` is the
single source of truth handed to agents (via the ``kb_guide`` tool and the
one-click builder prompt): layout, page skeleton, writing standards,
citation format and the three workflows (ingest / 沉淀 / lint).

``wiki_stats`` is a pure-FS scan (no DB) — sources/pages/uncited counts
feed both the guide tool and the builder's incremental decisions.
"""
from __future__ import annotations

import re
from pathlib import Path

from app.engine.kb.tree import fs as kb_fs

# Footnote definitions at page bottom: ``[^1]: sources/xxx.pdf, p.3``.
_FOOTNOTE_DEF_RE = re.compile(r"^\[\^(\w+)\]:\s*(.+)$", re.MULTILINE)
# Citation target file (before optional ", p.N" page suffix).
_CITE_FILE_RE = re.compile(r"^(sources/[^\s,]+)")
# Wiki-internal markdown links: [text](relative.md) — skip http/anchor-only.
_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)]+)\)")

GUIDE_TEXT = """# LLM Wiki 构建指南

本知识库是「编译型 wiki」：sources/ 存放原始资料（只读），wiki/ 是你（AI）编译、维护的知识层。

## 黄金法则
1. **sources/ 只读**：原始资料一字不改；你只能读写 wiki/ 下的页面。
2. **冲突时原文赢**：wiki 页与源资料矛盾时，以源资料为准（必要时修正 wiki 并在 log 记录）。
3. **每个论断可溯源**：wiki 页中的事实主张必须带脚注引用源文件（含页码）。

## 目录骨架（固定）
- `wiki/overview.md` —— 枢纽页：覆盖范围、源/页计数、主题导览、Key Findings、Recent Updates。**每次 ingest 后必须更新**。
- `wiki/concepts/` —— 概念页（抽象：方法/机制/思想，如 attention.md）。
- `wiki/entities/` —— 实体页（具体：人/组织/产品/项目，如 vaswani.md）。
- `wiki/log.md` —— append-only 日志：`## [YYYY-MM-DD] ingest | 源标题`（或 query / lint）。禁止改写历史条目。
- 可选：`wiki/comparisons/`（对比页）、`wiki/timeline.md`（时间线）。

## 页面写作规范
- YAML frontmatter 必填：title、date、tags（≥2 个）；description 可选。
- **不要 H1**（UI 渲染页面标题）；用 `##` / `###` 分节，标题即主题。
- 每页至少一个**视觉元素**：表格或 Mermaid 图。
  Mermaid 规范：节点标签内**禁止**脚注标记 `[^n]`、ASCII 括号 `()`、反引号——
  引用一律写在图外的正文里，标签尽量用中文书名号/全角括号；
  边必须写完整箭头 `A -->|标签| B`，**禁止**省略箭头的 `A --|标签| B`（mermaid 不认）。
- 每个事实主张**必须脚注引用**：`[^1]: sources/report.pdf, p.3`（PDF 带页码；非分页源可省略页码）。
- 相关主题用相对链接交叉引用：`参见 [稀疏注意力](sparse-attention.md)`。
- 页面是持久资产，要比聊天回答更丰富；目标是「一页讲透一个主题」。

## 查询工作流（wiki 优先，两段式）
1. 首次进入本库：先读 `wiki/overview.md`（地图+全库词汇表），再定位。
2. 定位：① 顺 overview 的链接导航，或 ② kb_grep(scope=wiki) 精确查找。
3. 读取命中页整节；页内交叉链接可继续追。
4. **wiki 不够时才降级**：按脚注 kb_read 源文件对应页，或 kb_grep(scope=sources) 搜原文。
5. 答案若属「wiki 应覆盖却没覆盖」：用 kb_write 沉淀为新页/更新已有页，并在 log.md 追加 `query` 条目。

## Ingest 工作流（消化新源）
1. 读源：kb_read("sources/xxx.pdf", pages="1-10") 采样通读，再精读关键页。
2. 判定涉及的概念/实体：更新已有页（kb_write str_replace）或创建新页（create）。
   一份源通常触碰 5-15 个页面——知识按主题归位，不是一文档一页。
   若源是「内容已更新」（同名重传），重点把变化之处织入，并核对旧论断是否仍成立。
3. 更新 overview.md（计数、导览、Recent Updates）。
4. log.md 追加 `## [日期] ingest | 源标题` 条目，简述写了/改了哪些页。
5. 收尾：kb_lint 检查，修复可修复项。

## Lint 工作流（维护）
kb_lint 报告：frontmatter 缺失、脚注卫生（重复/未定义/未使用）、引用的源不存在、
悬空页间链接、孤儿页（无入链，overview/log 豁免）、未被引用的源。
逐项评估修复（补引用、修链接、合并重复页、给过期页标注），并记 log。
"""


def _read_pages(kb_id: str) -> dict[str, str]:
    """Read all wiki pages → {rel_path: content} (missing files skipped)."""
    out: dict[str, str] = {}
    for entry in kb_fs.list_wiki_pages(kb_id):
        content = kb_fs.read_kb_file(kb_id, entry["path"])
        if content is not None:
            out[entry["path"]] = content
    return out


def read_all_pages(kb_id: str) -> dict[str, str]:
    """Public read of all wiki pages (service layer entry, e.g. build-time
    digest accounting)."""
    return _read_pages(kb_id)


def cited_sources(pages: dict[str, str]) -> set[str]:
    """Collect `sources/…` targets referenced by any footnote definition."""
    cited: set[str] = set()
    for content in pages.values():
        for _label, target in _FOOTNOTE_DEF_RE.findall(content):
            m = _CITE_FILE_RE.match(target.strip())
            if m:
                cited.add(m.group(1))
    return cited


def wiki_links(pages: dict[str, str]) -> dict[str, set[str]]:
    """Collect wiki-internal link targets per page → {page: {targets}}.

    Targets are normalized to wiki-root-relative posix paths (``../`` is
    collapsed via os.path.normpath) so lint/graph checks can compare them
    against ``list_wiki_pages`` keys directly.
    """
    import os

    out: dict[str, set[str]] = {}
    for path, content in pages.items():
        targets: set[str] = set()
        base_dir = str(Path(path).parent)
        for href in _LINK_RE.findall(content):
            if href.startswith(("http://", "https://", "#", "mailto:")):
                continue
            href = href.split("#")[0].strip()
            if not href:
                continue
            resolved = os.path.normpath(os.path.join(base_dir, href))
            out_target = resolved.replace("\\", "/").lstrip("/")
            targets.add(out_target)
        out[path] = targets
    return out


def wiki_stats(kb_id: str) -> dict:
    """Scan-based stats for the guide tool / builder / lint summary.

    Pure filesystem (engine layer — no DB access). Uncited sources are the
    builder's incremental signal: sources present on disk but never cited
    by any wiki footnote.
    """
    sources = kb_fs.list_wiki_sources(kb_id)
    pages = _read_pages(kb_id)
    cited = cited_sources(pages)
    source_paths = {s["path"] for s in sources}
    uncited = sorted(source_paths - cited)
    # 引用了但磁盘上不存在的源（builder 提示用）。
    missing_refs = sorted(
        {c for c in cited if c not in source_paths and not c.endswith(".md")}
    )
    log_tail = ""
    log_content = pages.get("wiki/log.md")
    if log_content:
        entries = re.findall(r"^## \[.*$", log_content, re.MULTILINE)
        log_tail = "\n".join(entries[-5:])
    return {
        "source_count": len(sources),
        "page_count": len(pages),
        "uncited_sources": uncited,
        "missing_source_refs": missing_refs,
        "log_tail": log_tail,
    }

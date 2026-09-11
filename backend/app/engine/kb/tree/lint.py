"""Wiki lint — deterministic hygiene checks over the wiki layer.

Scan-based (no DB, no index): every rule reads the wiki pages / source
listing straight from the filesystem, so results are always fresh. Runs
inside the ``kb_lint`` agent tool and the ``GET /knowledge-bases/{id}/wiki/lint``
API — same implementation, two doors.

Rules (llmwiki-aligned):
- ``frontmatter``          page missing frontmatter / title / tags (warn)
- ``footnote-hygiene``     duplicate / undefined / unused footnotes
- ``unresolved-citation``  footnote cites a sources/ file that doesn't exist (error)
- ``dangling-link``        wiki-internal link target missing (error)
- ``orphan-page``          no inbound links (overview/log exempt) (warn)
- ``uncited-source``       source never cited by any footnote (info)
"""
from __future__ import annotations

import re

from app.engine.kb.tree import fs as kb_fs
from app.engine.kb.tree.guide import (
    _FOOTNOTE_DEF_RE,
    _read_pages,
    cited_sources,
    wiki_links,
)

# Frontmatter block: opening --- … closing --- with title:/tags: inside.
_FM_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_FM_TITLE_RE = re.compile(r"^title:\s*\S+", re.MULTILINE)
_FM_TAGS_RE = re.compile(r"^tags:", re.MULTILINE)
# Footnote usages in body: [^n] not immediately followed by ":" (definition).
_FOOTNOTE_USE_RE = re.compile(r"\[\^(\w+)\](?!:)")
# Footnote definitions lines (to exclude from body-usage scan).
_FOOTNOTE_DEF_LINE_RE = re.compile(r"^\[\^(\w+)\]:.*$", re.MULTILINE)


def _strip_footnote_defs(content: str) -> str:
    return _FOOTNOTE_DEF_LINE_RE.sub("", content)


def _check_frontmatter(path: str, content: str, issues: list[dict]) -> None:
    m = _FM_RE.match(content)
    if m is None:
        issues.append(
            _issue("warn", "frontmatter", path, "缺少 YAML frontmatter（title/date/tags）")
        )
        return
    block = m.group(1)
    if not _FM_TITLE_RE.search(block):
        issues.append(_issue("warn", "frontmatter", path, "frontmatter 缺少非空 title"))
    if not _FM_TAGS_RE.search(block):
        issues.append(_issue("warn", "frontmatter", path, "frontmatter 缺少 tags（至少 2 个）"))


def _check_footnotes(path: str, content: str, issues: list[dict]) -> None:
    defs = _FOOTNOTE_DEF_RE.findall(content)
    labels = [label for label, _target in defs]
    dup = {x for x in labels if labels.count(x) > 1}
    for label in sorted(dup):
        issues.append(_issue("error", "footnote-hygiene", path, f"脚注 [^{label}] 重复定义"))
    defined = set(labels)
    body = _strip_footnote_defs(content)
    used = set(_FOOTNOTE_USE_RE.findall(body))
    for label in sorted(used - defined):
        issues.append(_issue("error", "footnote-hygiene", path, f"脚注 [^{label}] 被引用但未定义"))
    for label in sorted(defined - used):
        issues.append(_issue("warn", "footnote-hygiene", path, f"脚注 [^{label}] 已定义但未被引用"))


def _issue(severity: str, rule: str, path: str, detail: str) -> dict:
    return {"severity": severity, "rule": rule, "path": path, "detail": detail}


_EXEMPT_ORPHANS = {"wiki/overview.md", "wiki/log.md"}


def run_lint(kb_id: str) -> dict:
    """Run all checks; returns ``{"issues": [...], "stats": {...}}``."""
    issues: list[dict] = []
    pages = _read_pages(kb_id)
    source_paths = {s["path"] for s in kb_fs.list_wiki_sources(kb_id)}

    for path, content in pages.items():
        _check_frontmatter(path, content, issues)
        _check_footnotes(path, content, issues)

    # unresolved-citation: footnote targets that don't exist under sources/.
    from app.engine.kb.tree.guide import _CITE_FILE_RE

    for path, content in pages.items():
        for _label, target in _FOOTNOTE_DEF_RE.findall(content):
            m = _CITE_FILE_RE.match(target.strip())
            if not m:
                continue
            cited = m.group(1)
            if cited not in source_paths:
                issues.append(
                    _issue(
                        "error",
                        "unresolved-citation",
                        path,
                        f"引用的源不存在: {cited}",
                    )
                )

    # dangling-link + orphan-page over the link graph.
    links = wiki_links(pages)
    page_keys = set(pages.keys())
    inbound: dict[str, int] = {}
    for path, targets in links.items():
        for target in targets:
            inbound[target] = inbound.get(target, 0) + 1
            if target not in page_keys:
                issues.append(
                    _issue("error", "dangling-link", path, f"链接目标不存在: {target}")
                )
    for path in sorted(page_keys):
        if path in _EXEMPT_ORPHANS:
            continue
        if inbound.get(path, 0) == 0:
            issues.append(_issue("warn", "orphan-page", path, "无任何入链（孤儿页）"))

    # uncited-source: on-disk sources never cited by any footnote.
    cited = cited_sources(pages)
    for src in sorted(source_paths - cited):
        issues.append(
            _issue("info", "uncited-source", src, "源从未被 wiki 引用（未消化或无用）")
        )

    # Order: errors first, then warn, then info; stable within a rule.
    rank = {"error": 0, "warn": 1, "info": 2}
    issues.sort(key=lambda i: (rank[i["severity"]], i["rule"], i["path"]))
    return {
        "issues": issues,
        "stats": {
            "page_count": len(pages),
            "source_count": len(source_paths),
            "cited_source_count": len(cited & source_paths),
            "error_count": sum(1 for i in issues if i["severity"] == "error"),
            "warn_count": sum(1 for i in issues if i["severity"] == "warn"),
        },
    }

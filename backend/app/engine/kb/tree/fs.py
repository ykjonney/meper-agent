"""Knowledge Base filesystem — read / write / delete KB .md files on disk.

Each KB lives under ``{KB_CONTAINER_DIR}/{kb_id}/`` as a tree of ``.md``
files (tree-style KB: no index, no chunking — agents explore it at
runtime via kb_glob/kb_grep/kb_read). MongoDB keeps only metadata; file
content lives here on the filesystem.

Unlike ``skill_fs.py`` there is **no materialize** step — KB files are
mutated in place (upload/edit/delete touch the FS directly), because the
DB never stores file content for KBs.

Layout::

    KB_DIR/
      kb_xxx/                      # plain tree KB (wiki mode off)
        README.md
        notes/api.md
      kb_yyy/                      # wiki mode enabled (llmwiki-style)
        sources/                   # raw materials (read-only)
          report.pdf
          .extracted/report.md     # extraction text, hidden (dot-dir)
        wiki/                      # AI-compiled layer
          overview.md
          log.md
          concepts/attention.md
          entities/vaswani.md
"""
from __future__ import annotations

import shutil
from pathlib import Path

from loguru import logger

from app.core.config import settings
from app.engine.tool.workspace import WorkspaceManager


def _kb_dir() -> Path:
    """Return the configured Knowledge Base root directory.

    Reads ``KB_CONTAINER_DIR`` from settings; defaults to
    ``~/.agent-flow/knowledge_bases/``.
    """
    return Path(settings.KB_CONTAINER_DIR).expanduser()


def get_kb_base_path(kb_id: str) -> Path:
    """Return the absolute path for a KB directory.

    Does **not** validate that the path exists.
    """
    return _kb_dir() / kb_id


def ensure_kb_dir(kb_id: str) -> Path:
    """Create the KB directory if missing and return it."""
    base = get_kb_base_path(kb_id)
    base.mkdir(parents=True, exist_ok=True)
    return base


def _resolve(kb_id: str, rel_path: str) -> Path | None:
    """Resolve a relative path inside a KB, guarding against traversal."""
    return WorkspaceManager.safe_resolve_path(get_kb_base_path(kb_id), rel_path)


def read_kb_file(kb_id: str, rel_path: str) -> str | None:
    """Read a single file from the KB directory (UTF-8 text or None)."""
    full = _resolve(kb_id, rel_path)
    if full is None or not full.is_file():
        return None
    try:
        return full.read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning("kb_file_read_error", kb_id=kb_id, rel_path=rel_path, error=str(exc))
        return None


def write_kb_file(kb_id: str, rel_path: str, content: str) -> Path:
    """Write (create or overwrite) a file inside the KB directory.

    Raises ValueError if rel_path escapes the KB base (traversal).
    """
    full = _resolve(kb_id, rel_path)
    if full is None:
        raise ValueError(f"path escapes kb base: {rel_path}")
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content, encoding="utf-8")
    return full


def delete_kb_file(kb_id: str, rel_path: str) -> bool:
    """Delete a single file from the KB directory."""
    full = _resolve(kb_id, rel_path)
    if full is None or not full.is_file():
        return False
    full.unlink()
    return True


def delete_kb_dir(kb_id: str) -> bool:
    """Remove an entire KB directory from disk."""
    base = get_kb_base_path(kb_id)
    if not base.exists():
        return False
    shutil.rmtree(base)
    logger.info("kb_dir_deleted", kb_id=kb_id, path=str(base))
    return True


def list_kb_files(kb_id: str) -> list[dict]:
    """Scan the KB directory and return ``.md`` file entries for the tree view.

    Returns a list of dicts with ``path`` (relative) and ``size`` keys,
    suitable for ``_build_file_tree`` (same shape as ``list_skill_files``).
    Hidden directories (dot-prefixed, e.g. wiki mode's ``sources/.extracted``)
    are skipped — extraction text is a derived cache, not tree content.
    """
    base = get_kb_base_path(kb_id)
    if not base.is_dir():
        return []
    entries: list[dict] = []
    for p in base.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() != ".md":
            continue
        rel = p.relative_to(base)
        if any(part.startswith(".") for part in rel.parts):
            continue
        entries.append({"path": str(rel), "size": p.stat().st_size})
    return entries


def compute_stats(kb_id: str) -> tuple[int, int]:
    """Return (file_count, total_size) over ``.md`` files in the KB."""
    files = list_kb_files(kb_id)
    total = sum(f["size"] for f in files)
    return len(files), total


# ── Wiki mode (llmwiki-style two-layer layout) ──────────────────────────


def _is_hidden(rel: Path | str) -> bool:
    """True when any path segment is dot-prefixed (hidden cache dir)."""
    parts = rel.parts if isinstance(rel, Path) else Path(rel).parts
    return any(part.startswith(".") for part in parts)


def init_wiki_skeleton(kb_id: str) -> Path:
    """Create the wiki-mode skeleton under the KB directory (idempotent).

    ``sources/``        raw materials (read-only)
    ``wiki/overview.md`` hub page template
    ``wiki/log.md``     append-only ingest log template
    ``wiki/concepts/`` + ``wiki/entities/``

    Existing files are never touched — enabling wiki mode on a legacy tree
    KB keeps its ``.md`` files in place (readable as before, just outside
    the sources/wiki split).
    """
    base = ensure_kb_dir(kb_id)
    (base / "sources" / ".extracted").mkdir(parents=True, exist_ok=True)
    wiki = base / "wiki"
    (wiki / "concepts").mkdir(parents=True, exist_ok=True)
    (wiki / "entities").mkdir(parents=True, exist_ok=True)

    overview = wiki / "overview.md"
    if not overview.exists():
        overview.write_text(
            "---\n"
            "title: 知识库总览\n"
            "description: 本知识库的导航首页（由 AI 维护）\n"
            f"date: {_today()}\n"
            "tags: [总览]\n"
            "---\n\n"
            "（尚未构建——上传源资料到 sources/ 后点击「构建 Wiki」，"
            "AI 会生成主题导览、Key Findings 与 Recent Updates。）\n",
            encoding="utf-8",
        )

    log = wiki / "log.md"
    if not log.exists():
        log.write_text(
            "---\n"
            "title: 工作日志\n"
            "description: append-only 的构建/沉淀记录（增量维护的锚点）\n"
            f"date: {_today()}\n"
            "tags: [日志]\n"
            "---\n\n"
            "## 条目格式\n\n"
            "`## [YYYY-MM-DD] ingest | 源标题`（其余类型：query / lint）\n",
            encoding="utf-8",
        )
    logger.info("kb_wiki_skeleton_ready", kb_id=kb_id)
    return base


def _today() -> str:
    from datetime import date

    return date.today().isoformat()


def migrate_legacy_layout(kb_id: str) -> int:
    """One-time migration for legacy plain-tree KBs (wiki mode is now THE
    tree behaviour): move loose ``.md`` files (root or legacy subdirs,
    outside ``wiki/``/``sources/``/hidden dirs) into ``sources/`` so they
    become digestible source material.

    Idempotent and cheap after the first run — the quick path only scans
    top-level entries; the full walk happens solely when an unexpected
    top-level entry exists. Returns the number of moved files.
    """
    base = get_kb_base_path(kb_id)
    if not base.is_dir():
        return 0
    expected_top = {"wiki", "sources"}

    def _needs_walk() -> bool:
        return any(
            p.name not in expected_top and not p.name.startswith(".")
            for p in base.iterdir()
        )

    if not _needs_walk():
        return 0

    moved = 0
    for p in base.rglob("*"):
        if not p.is_file() or p.suffix.lower() != ".md":
            continue
        rel = p.relative_to(base)
        if rel.parts[0] in expected_top or any(part.startswith(".") for part in rel.parts):
            continue
        target = base / "sources" / p.name
        if target.exists():
            logger.warning("kb_wiki_migration_name_clash", kb_id=kb_id, rel_path=str(rel))
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        p.rename(target)
        moved += 1
    # 清掉搬空的原目录（只删空目录，绝不删非空；wiki/sources 骨架不动）
    import contextlib

    for p in sorted(base.rglob("*"), reverse=True):
        if not p.is_dir():
            continue
        rel = p.relative_to(base)
        if rel.parts[0] in expected_top or p.name.startswith("."):
            continue
        with contextlib.suppress(OSError):
            p.rmdir()
    if moved:
        logger.info("kb_wiki_legacy_migrated", kb_id=kb_id, moved=moved)
    return moved


def ensure_wiki_layout(kb_id: str) -> Path:
    """Ensure the wiki layout exists + legacy files migrated (idempotent).

    Call at the entry of user-facing tree-KB operations (file view /
    upload) — cheap when the layout is already in place.
    """
    base = init_wiki_skeleton(kb_id)
    migrate_legacy_layout(kb_id)
    return base


def list_wiki_pages(kb_id: str) -> list[dict]:
    """List ``.md`` pages under ``wiki/`` (relative paths incl. prefix)."""
    base = get_kb_base_path(kb_id)
    wiki = base / "wiki"
    if not wiki.is_dir():
        return []
    entries: list[dict] = []
    for p in wiki.rglob("*.md"):
        if not p.is_file():
            continue
        entries.append(
            {"path": f"wiki/{p.relative_to(wiki)}", "size": p.stat().st_size}
        )
    return entries


def list_wiki_sources(kb_id: str) -> list[dict]:
    """List source files under ``sources/`` (hidden ``.extracted`` skipped)."""
    base = get_kb_base_path(kb_id)
    sources = base / "sources"
    if not sources.is_dir():
        return []
    entries: list[dict] = []
    for p in sources.rglob("*"):
        if not p.is_file():
            continue
        rel = p.relative_to(base)
        if _is_hidden(rel):
            continue
        entries.append({"path": str(rel), "size": p.stat().st_size})
    return entries


def extracted_path_for(kb_id: str, source_rel: str) -> str:
    """Deterministic extracted-text path for a binary source.

    ``sources/report.pdf`` → ``sources/.extracted/report.pdf.md``. Keeping
    the original extension in the name makes the mapping injective — no
    collisions between same-stem originals (report.pdf vs report.docx).
    """
    name = Path(source_rel).name
    return f"sources/.extracted/{name}.md"


def iter_md_files(kb_id: str, scope: str = "all") -> list[Path]:
    """Yield readable ``.md`` files for scoped grep/read (wiki mode).

    Scopes (ignored for plain tree KBs — caller passes ``all``):
    - ``wiki``:    files under ``wiki/``
    - ``sources``: readable source text — ``sources/**/*.md`` originals
                   plus ``sources/.extracted/*.md`` extraction text
    - ``all``:     everything above (legacy root-level ``.md`` included)

    Hidden dirs are skipped except ``.extracted``. Order is stable
    (sorted) so truncation behaviour is deterministic.
    """
    base = get_kb_base_path(kb_id)
    if not base.is_dir():
        return []
    files: list[Path] = []
    for p in base.rglob("*.md"):
        if not p.is_file():
            continue
        rel = p.relative_to(base)
        hidden = any(
            part.startswith(".") and part != ".extracted" for part in rel.parts
        )
        if hidden:
            continue
        if scope == "wiki" and (not rel.parts or rel.parts[0] != "wiki"):
            continue
        if scope == "sources" and (not rel.parts or rel.parts[0] != "sources"):
            continue
        files.append(p)
    return sorted(files)

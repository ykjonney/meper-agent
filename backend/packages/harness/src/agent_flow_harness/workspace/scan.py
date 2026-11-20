"""工作区文件遍历 — gitignore 感知（B7：grep/glob 共用）。

问题：原实现 ``Path.rglob("*")`` 盲扫，会钻进 .git/、node_modules/、
.venv/ 等目录——repo 规模 workspace 上既慢又把噪音灌进工具输出。

策略（对齐主流 grep 工具的默认行为）：
1. 硬跳过常见噪音目录（无视 .gitignore 是否存在）；
2. 尊重 .gitignore：收集 base 树内各级 .gitignore，构造 pathspec 的
   GitIgnoreSpec；候选文件按其所在 ignore 文件的目录转为相对路径
   匹配（对齐 git 的 per-directory ignore 语义的主干行为）。

注意：.gitignore 语义的完整实现（负模式、目录/文件区分、core.excludes
等）不在本层目标内——按"主干行为"取舍，pathspec 处理模式匹配本身。
"""
from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from agent_flow_harness.sandbox.base import GrepMatch
    from pathspec import GitIgnoreSpec

# 硬跳过的目录名（无论 .gitignore 是否声明）
SKIP_DIRS = frozenset({
    ".git", ".hg", ".svn",
    "node_modules",
    ".venv", "venv",
    "__pycache__",
    ".mypy_cache", ".pytest_cache", ".ruff_cache",
    "dist", "build",
})


def _load_ignore_specs(base: Path) -> list[tuple[Path, GitIgnoreSpec]]:
    """收集 base 树内全部 .gitignore → [(所在目录, spec)]。"""
    import pathspec

    specs: list[tuple[Path, GitIgnoreSpec]] = []
    for ignore_file in base.rglob(".gitignore"):
        if not ignore_file.is_file():
            continue
        # ignore 文件本身可能在被跳过的目录里（如 node_modules 内）——跳过
        if any(part in SKIP_DIRS for part in ignore_file.relative_to(base).parts[:-1]):
            continue
        try:
            text = ignore_file.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        spec = pathspec.GitIgnoreSpec.from_lines(text.splitlines())
        specs.append((ignore_file.parent, spec))
    return specs


def _is_ignored(
    candidate: Path, base: Path, specs: list[tuple[Path, GitIgnoreSpec]],
) -> bool:
    """candidate 相对各级 .gitignore 目录匹配；任一命中即忽略。"""
    for ignore_dir, spec in specs:
        try:
            rel = candidate.relative_to(ignore_dir)
        except ValueError:
            continue
        if spec.match_file(rel.as_posix()):
            return True
    return False


def iter_workspace_files(base: Path, *, respect_gitignore: bool = True) -> Iterator[Path]:
    """遍历 base 树内的普通文件：硬跳过噪音目录 + gitignore 感知。

    base 为单文件时直接产出该文件。目录不存在由调用方处理（grep/glob
    的 resolve 层保证存在）。
    """
    if base.is_file():
        yield base
        return
    specs = _load_ignore_specs(base) if respect_gitignore else []
    for path in base.rglob("*"):
        rel_parts = path.relative_to(base).parts
        # 剪枝：路径上任一级命中噪音目录即跳过（rglob 无真正剪枝，逐项过滤）
        if any(part in SKIP_DIRS for part in rel_parts[:-1]):
            continue
        if not path.is_file():
            continue
        if specs and _is_ignored(path, base, specs):
            continue
        yield path


def glob_workspace_files(base: Path, pattern: str) -> list[Path]:
    """glob 文件匹配（主流行为）：无目录分隔符的 pattern 自动递归。

    递归路径走 iter_workspace_files（gitignore/噪音目录感知），非递归
    保持 ``Path.glob`` 字面行为。结果按 mtime 降序（最新优先，并列按
    路径稳定排序）。
    """
    if "/" not in pattern and "**" not in pattern:
        import fnmatch

        matches = [
            p for p in iter_workspace_files(base)
            if fnmatch.fnmatch(p.relative_to(base).as_posix(), pattern)
        ]
    else:
        matches = [p for p in base.glob(pattern) if p.is_file()]
    def _mtime(p: Path) -> tuple[int, str]:
        try:
            return (p.stat().st_mtime_ns, str(p))
        except OSError:
            return (0, str(p))
    matches.sort(key=_mtime, reverse=True)
    return matches


def grep_workspace(
    base: Path,
    pattern: str,
    *,
    context: int = 0,
    ignore_case: bool = False,
    glob_filter: str | None = None,
) -> list["GrepMatch"]:
    """内容搜索（gitignore/噪音目录感知）：正则逐行匹配 + 上下文行。

    返回按文件、行号排序的 GrepMatch；context>0 时每条命中带前后
    各 context 行（before/after）。Local/Docker 两个 Sandbox 共用。
    """
    import fnmatch
    import re

    from agent_flow_harness.sandbox.base import GrepMatch

    regex = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
    files: list[Path] = [base] if base.is_file() else list(iter_workspace_files(base))
    if glob_filter:
        files = [f for f in files if fnmatch.fnmatch(f.name, glob_filter)]
    matches: list[GrepMatch] = []
    for f in files:
        if not f.is_file():
            continue
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for i, line in enumerate(lines, 1):
            if regex.search(line):
                before = (
                    tuple(lines[max(0, i - 1 - context):i - 1]) if context else ()
                )
                after = tuple(lines[i:i + context]) if context else ()
                matches.append(GrepMatch(
                    path=str(f), line_number=i, line=line,
                    before=before, after=after,
                ))
    return matches


__all__ = ["SKIP_DIRS", "glob_workspace_files", "grep_workspace", "iter_workspace_files"]

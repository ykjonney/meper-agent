"""Knowledge Base tools — read trio + wiki maintenance toolset (closure-injected).

Mirrors the harness ``SkillManager`` pattern: a stateful manager
constructed once per ``resolve_harness_context`` call, closure-capturing
the KB directories the agent is bound to, producing StructuredTools
for the LLM.

Unlike the harness sandbox glob/grep (which operate on the session
workspace via ContextVar), these tools read KB directories directly from
the backend process filesystem — they do NOT depend on the sandbox, so
they work identically in local-dev and container modes.

Toolsets:
- Plain tree KB (wiki mode off): ``kb_glob`` / ``kb_grep`` / ``kb_read``
  — read-only exploration, unchanged behaviour (hidden dirs are skipped).
- Wiki-mode KB (``wiki_kb_ids``): the trio gains scoped grep + paginated
  source reads + glob batch reads, plus the llmwiki-style maintenance
  tools ``kb_guide`` / ``kb_write`` / ``kb_delete`` / ``kb_lint``.

Security:
    - Only the KB directories passed to the constructor are readable.
    - Every path is resolved through ``WorkspaceManager.safe_resolve_path``.
    - Only ``.md`` files are matched / read; writes are confined to the
      ``wiki/`` subtree (sources are read-only — golden rule) and capped
      in size; ``overview.md`` / ``log.md`` cannot be deleted.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.core.config import settings
from app.engine.kb.tree import fs as kb_fs
from app.engine.tool.workspace import WorkspaceManager

# ── args schemas (module-level; descriptions are per-instance) ─────────


class _KbGlobArgs(BaseModel):
    pattern: str = Field("**/*.md", description="glob 模式，默认列出所有 .md")
    kb_id: str | None = Field(None, description="限定单个知识库；省略则跨所有绑定知识库")


class _KbGrepArgs(BaseModel):
    pattern: str = Field(..., description="正则表达式")
    kb_id: str | None = Field(None, description="限定单个知识库；省略则跨所有绑定知识库")
    scope: str = Field(
        "all",
        description="检索范围（仅 Wiki 型知识库生效）: wiki=只搜编译层页面；"
        "sources=只搜源文件文本；all=全部。查询优先用 wiki，不够再降级 sources。",
    )


class _KbReadArgs(BaseModel):
    path: str = Field(
        ...,
        description="知识库内相对路径、glob 模式（批量采样读）、或 kb_glob/kb_grep 返回的"
        " 'kb_id/路径' 形式。sources/ 下的二进制源自动映射到提取文本。",
    )
    kb_id: str | None = Field(None, description="当 path 不含 kb 前缀时显式指定")
    pages: str | None = Field(
        None, description="页码过滤（仅源文件提取文本），如 '3' 或 '3-5'"
    )
    sections: list[str] | None = Field(
        None, description="只抽取标题包含任一关键词的 ## 节（如 ['变体','定义']）"
    )


class _KbGuideArgs(BaseModel):
    kb_id: str | None = Field(None, description="目标 Wiki 知识库；省略则取唯一绑定的 Wiki 库")


class _KbWriteArgs(BaseModel):
    command: str = Field(
        ..., description="create=新建页面 | str_replace=精确替换 | append=文末追加"
    )
    path: str = Field(
        ...,
        description="wiki/ 下相对路径（如 wiki/concepts/attention.md，wiki/ 前缀可省略）。"
        "sources/ 只读，禁止写入。",
    )
    content: str = Field(
        "", description="create/append 的内容（create 不要写 H1 和 frontmatter，系统自动生成）"
    )
    old_string: str = Field("", description="str_replace: 被替换文本（必须在文件中唯一）")
    new_string: str = Field("", description="str_replace: 替换后的文本")
    title: str | None = Field(None, description="create 时的页面标题（默认取文件名）")
    description: str | None = Field(None, description="create 时的 frontmatter 描述")
    tags: list[str] | None = Field(None, description="create 时的标签（至少 2 个）")
    kb_id: str | None = Field(None, description="目标 Wiki 知识库")


class _KbDeleteArgs(BaseModel):
    path: str = Field(..., description="wiki/ 下要删除的页面路径（overview/log 禁删）")
    kb_id: str | None = Field(None, description="目标 Wiki 知识库")


class _KbLintArgs(BaseModel):
    kb_id: str | None = Field(None, description="目标 Wiki 知识库")


# Page markers injected by the extraction pipeline: ``<!-- p.N -->``.
_PAGE_MARKER_RE = re.compile(r"(?m)^<!--\s*p\.(\d+)\s*-->\s*$")
_HEADING_RE = re.compile(r"(?m)^##\s+(.+)$")

_PROTECTED_PAGES = {"wiki/overview.md", "wiki/log.md"}

# Batch-read caps come from settings (see config.py KB_WIKI_*).
_WRITE_MAX_BYTES = settings.KB_WIKI_WRITE_MAX_BYTES


def _is_hidden(rel: Path) -> bool:
    return any(part.startswith(".") for part in rel.parts)


class KbManager:
    """Build KB-bound tools for a single agent resolve.

    Args:
        kb_roots: mapping of ``kb_id -> base path``. Only these KBs are
            readable by the produced tools.
        wiki_kb_ids: subset of ``kb_roots`` keys with wiki mode enabled —
            those get the maintenance toolset + scoped retrieval. Agents
            with none keep the plain read-only trio.
    """

    def __init__(self, kb_roots: dict[str, Path], wiki_kb_ids: set[str] | None = None):
        self._kb_roots = kb_roots
        self._wiki_kb_ids = set(wiki_kb_ids or ())

    # ── path resolution ────────────────────────────────────────────────

    def _resolve(self, kb_id: str, rel_path: str) -> Path | None:
        base = self._kb_roots.get(kb_id)
        if base is None:
            return None
        return WorkspaceManager.safe_resolve_path(base, rel_path)

    def _parse_target(self, path: str, kb_id: str | None) -> tuple[str, str] | None:
        """Resolve ``(kb_id, rel_path)`` from tool args.

        Accepts either an explicit ``kb_id`` + relative path, or a
        compound ``{kb_id}/{rel}`` path (as returned by kb_glob/kb_grep).
        Bare paths resolve against the only KB when exactly one is bound.
        """
        if kb_id:
            return (kb_id, path) if kb_id in self._kb_roots else None
        parts = path.split("/", 1)
        if len(parts) == 2 and parts[0] in self._kb_roots:
            return parts[0], parts[1]
        if len(self._kb_roots) == 1:
            return next(iter(self._kb_roots)), path
        return None

    def _target_kb_ids(self, kb_id: str | None) -> list[str]:
        if kb_id and kb_id in self._kb_roots:
            return [kb_id]
        return list(self._kb_roots)

    def _wiki_target(self, kb_id: str | None) -> tuple[str, Path] | None:
        """Resolve the single wiki KB for maintenance tools (guide/write/…)."""
        candidates = [kid for kid in self._target_kb_ids(kb_id) if kid in self._wiki_kb_ids]
        if len(candidates) == 1:
            kid = candidates[0]
            return kid, self._kb_roots[kid]
        if not candidates:
            return None
        return None  # 多个 Wiki 库时必须显式指定 kb_id

    # ── read trio ──────────────────────────────────────────────────────

    def glob(self, pattern: str, kb_id: str | None = None) -> str:
        max_n = settings.KB_GLOB_MAX_RESULTS
        results: list[str] = []
        done = False
        for kid in self._target_kb_ids(kb_id):
            if done:
                break
            base = self._kb_roots[kid]
            try:
                iterator = base.glob(pattern)
            except Exception:
                continue
            for p in iterator:
                if not p.is_file() or p.suffix.lower() != ".md":
                    continue
                if _is_hidden(p.relative_to(base)):
                    continue
                results.append(f"{kid}/{p.relative_to(base)}")
                if len(results) >= max_n:
                    done = True
                    break
        if not results:
            return "(no matches)"
        out = "\n".join(results)
        if done:
            out += f"\n... [truncated at {max_n} results]"
        return out

    def _grep_files(self, kid: str, scope: str) -> list[Path]:
        base = self._kb_roots[kid]
        if kid in self._wiki_kb_ids and scope in ("wiki", "sources"):
            return kb_fs.iter_md_files(kid, scope)
        # Plain KB (or scope=all): everything .md, hidden dirs skipped.
        files = [
            p
            for p in base.rglob("*.md")
            if p.is_file() and not _is_hidden(p.relative_to(base))
        ]
        if kid in self._wiki_kb_ids:
            # scope=all for wiki KBs: add extracted text of binary sources.
            for p in kb_fs.iter_md_files(kid, "sources"):
                if p not in files:
                    files.append(p)
        return sorted(files)

    def grep(self, pattern: str, kb_id: str | None = None, scope: str = "all") -> str:
        try:
            regex = re.compile(pattern)
        except re.error as exc:
            return f"Error: invalid regex: {exc}"
        max_files = settings.KB_GREP_MAX_FILES
        max_matches = settings.KB_GREP_MAX_MATCHES
        matches: list[str] = []
        scanned = 0
        done = False
        for kid in self._target_kb_ids(kb_id):
            if done:
                break
            base = self._kb_roots[kid]
            for p in self._grep_files(kid, scope):
                scanned += 1
                if scanned > max_files:
                    break
                try:
                    text = p.read_text(encoding="utf-8", errors="replace")
                except Exception:
                    continue
                rel = p.relative_to(base)
                for lineno, line in enumerate(text.splitlines(), 1):
                    if regex.search(line):
                        matches.append(f"{kid}/{rel}:{lineno}: {line}")
                        if len(matches) >= max_matches:
                            done = True
                            break
                if done:
                    break
        if not matches:
            return "(no matches)"
        out = "\n".join(matches)
        if done:
            out += f"\n... [truncated at {max_matches} matches]"
        return out

    # ── read (single / paginated / sections / batch) ───────────────────

    def _map_read_path(self, kid: str, rel: str) -> str:
        """Map a tool-facing path to the readable file (binary→extracted)."""
        if rel.startswith("sources/") and not rel.lower().endswith(".md"):
            extracted = kb_fs.extracted_path_for(kid, rel)
            base = self._kb_roots[kid]
            if (base / extracted).is_file():
                return extracted
        return rel

    @staticmethod
    def _parse_pages_spec(spec: str) -> set[int] | None:
        spec = spec.strip()
        if "-" in spec:
            lo, _, hi = spec.partition("-")
            try:
                return set(range(int(lo), int(hi) + 1))
            except ValueError:
                return None
        try:
            return {int(spec)}
        except ValueError:
            return None

    @staticmethod
    def _filter_pages(content: str, pages: set[int]) -> str:
        parts = _PAGE_MARKER_RE.split(content)
        # re.split with one capture group → [pre, p1, seg1, p2, seg2, …]
        blocks: dict[int, str] = {}
        for i in range(1, len(parts) - 1, 2):
            blocks[int(parts[i])] = parts[i + 1]
        wanted = [blocks[p] for p in sorted(pages) if p in blocks]
        if not wanted:
            return (
                "(指定页码不存在；该文件无分页标记——.md 源直读全文即可，"
                "或改用 sections=['标题词'] 按节抽取)"
            )
        return "\n".join(w.strip("\n") for w in wanted)

    @staticmethod
    def _filter_sections(content: str, keywords: list[str]) -> str:
        lines = content.splitlines(keepends=True)
        out: list[str] = []
        fm_lines: list[str] = []
        # Keep frontmatter block for context.
        if lines and lines[0].strip() == "---":
            fm_lines.append(lines[0])
            for line in lines[1:]:
                fm_lines.append(line)
                if line.strip() == "---":
                    break
        current: list[str] | None = None
        heading = ""
        for line in lines:
            m = re.match(r"^##\s+(.+)$", line)
            if m:
                heading = m.group(1)
                if any(kw.lower() in heading.lower() for kw in keywords):
                    if current:
                        out.extend(current)
                    current = [line]
                else:
                    if current:
                        out.extend(current)
                    current = None
            elif current is not None:
                current.append(line)
        if current:
            out.extend(current)
        if not out:
            return "(没有匹配的 ## 节；检查关键词或直接读全文)"
        return "".join(fm_lines + out)

    def _read_single(
        self,
        kid: str,
        rel: str,
        pages: str | None = None,
        sections: list[str] | None = None,
    ) -> str:
        mapped = self._map_read_path(kid, rel)
        full = self._resolve(kid, mapped)
        if full is None or not full.is_file():
            if mapped != rel:
                return (
                    f"Error: 源 {rel} 的提取文本尚未生成（解析中或失败）。"
                    "可稍后重试或检查文件列表状态。"
                )
            return f"Error: file not found: {rel}"
        try:
            content = full.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            return f"Error reading file: {exc}"
        note = ""
        if mapped != rel:
            note = f"（{rel} 的提取文本）"
        if pages:
            page_set = self._parse_pages_spec(pages)
            if page_set is None:
                return "Error: 无效页码，格式如 '3' 或 '3-5'"
            content = self._filter_pages(content, page_set)
        if sections:
            content = self._filter_sections(content, sections)
        if len(content.encode("utf-8")) > settings.KB_READ_MAX_BYTES:
            return note + content[: settings.KB_READ_MAX_BYTES] + "\n... [truncated]"
        return note + content

    def read(
        self,
        path: str,
        kb_id: str | None = None,
        pages: str | None = None,
        sections: list[str] | None = None,
    ) -> str:
        # Batch mode: glob pattern → sample multiple files within budget.
        if any(ch in path for ch in "*?["):
            return self._read_batch(path, kb_id)
        target = self._parse_target(path, kb_id)
        if target is None:
            return "Error: path not available in bound knowledge bases. Call kb_glob first to list files."
        kid, rel = target
        return self._read_single(kid, rel, pages=pages, sections=sections)

    def _read_batch(self, pattern: str, kb_id: str | None = None) -> str:
        listing = self.glob(pattern, kb_id)
        if listing == "(no matches)":
            return listing
        paths = [line for line in listing.splitlines() if not line.startswith("...")]
        budget = settings.KB_WIKI_READ_BUDGET
        sample_cap = settings.KB_WIKI_READ_SAMPLE
        out: list[str] = []
        used = 0
        skipped: list[str] = []
        for compound in paths:
            if used >= budget:
                skipped.append(compound)
                continue
            kid, rel = compound.split("/", 1)
            text = self._read_single(kid, rel)
            if text.startswith("Error"):
                continue
            sampled = text[:sample_cap]
            used += len(sampled)
            trunc = f" …[采样前 {len(sampled)} 字符]" if len(text) > sample_cap else ""
            out.append(f"== {compound} ==\n{sampled}{trunc}")
        if not out:
            return "(no readable files)"
        result = "\n\n".join(out)
        if skipped:
            result += f"\n\n(预算 {budget} 字符已用完，未采样 {len(skipped)} 个文件)"
        return result

    # ── wiki maintenance operations ────────────────────────────────────

    @staticmethod
    def _normalize_wiki_path(rel: str) -> str | None:
        """Normalize a tool-supplied path to ``wiki/…`` (None if invalid)."""
        rel = rel.replace("\\", "/").strip().lstrip("/")
        if rel.startswith("sources/") or rel.startswith("."):
            return None
        if not rel.startswith("wiki/"):
            rel = f"wiki/{rel}"
        if "../" in rel or not rel.lower().endswith(".md"):
            return None
        return rel

    @staticmethod
    def _make_frontmatter(
        title: str, description: str | None, tags: list[str] | None
    ) -> str:
        tag_list = tags or []
        tags_inline = ", ".join(tag_list)
        lines = [
            "---",
            f"title: {title}",
            f"description: {description or title}",
            f"date: {date.today().isoformat()}",
            f"tags: [{tags_inline}]",
            "---",
            "",
        ]
        return "\n".join(lines)

    def guide(self, kb_id: str | None = None) -> str:
        from app.engine.kb.tree.guide import GUIDE_TEXT, wiki_stats

        target = self._wiki_target(kb_id)
        if target is None:
            return "Error: 未绑定 Wiki 型知识库，或绑定了多个但未指定 kb_id。"
        kid, _base = target
        stats = wiki_stats(kid)
        uncited = "\n".join(f"- {s}" for s in stats["uncited_sources"]) or "-（无）"
        return (
            f"{GUIDE_TEXT}\n\n---\n\n## 本库状态\n"
            f"- 源文件数: {stats['source_count']}\n"
            f"- Wiki 页面数: {stats['page_count']}\n"
            f"- 未被引用的源（待消化）:\n{uncited}\n\n"
            f"### log.md 最近条目\n{stats['log_tail'] or '（空）'}"
        )

    def write(
        self,
        command: str,
        path: str,
        content: str = "",
        old_string: str = "",
        new_string: str = "",
        title: str | None = None,
        description: str | None = None,
        tags: list[str] | None = None,
        kb_id: str | None = None,
    ) -> str:
        target = self._wiki_target(kb_id)
        if target is None:
            return "Error: 未绑定 Wiki 型知识库，或绑定了多个但未指定 kb_id。"
        kid, _base = target
        rel = self._normalize_wiki_path(path)
        if rel is None:
            return f"Error: 非法路径 {path}（只能写 wiki/ 下的 .md；sources/ 只读）"

        base = self._kb_roots[kid]
        full = WorkspaceManager.safe_resolve_path(base, rel)
        if full is None:
            return f"Error: 非法路径 {path}"

        if command == "create":
            if full.exists():
                return f"Error: 页面已存在: {rel}（更新请用 str_replace/append）"
            body = content.lstrip("\n")
            # 剥掉 LLM 可能自带的 H1 与 frontmatter（规范：标题进 frontmatter）。
            body = re.sub(r"\A---\n.*?\n---\n?", "", body, flags=re.DOTALL)
            body = re.sub(r"\A#\s+.+?\n", "", body)
            page_title = (title or Path(rel).stem).strip()
            fm = self._make_frontmatter(page_title, description, tags)
            new_content = fm + body
            if not new_content.endswith("\n"):
                new_content += "\n"
            if len(new_content.encode("utf-8")) > _WRITE_MAX_BYTES:
                return f"Error: 内容超限（>{_WRITE_MAX_BYTES} bytes）"
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(new_content, encoding="utf-8")
            return f"已创建 {kid}/{rel}（title={page_title}）。记得更新 overview.md 并在 log.md 记录。"

        if not full.exists():
            return f"Error: 页面不存在: {rel}（新建请用 create）"
        current = full.read_text(encoding="utf-8", errors="replace")

        if command == "str_replace":
            if not old_string:
                return "Error: str_replace 需要 old_string"
            count = current.count(old_string)
            if count == 0:
                return "Error: old_string 未出现在文件中"
            if count > 1:
                return f"Error: old_string 出现 {count} 次，不唯一——请扩大上下文使其唯一"
            updated = current.replace(old_string, new_string, 1)
        elif command == "append":
            if not content:
                return "Error: append 需要 content"
            sep = "" if current.endswith("\n") else "\n"
            updated = current + sep + content
        else:
            return f"Error: 未知 command: {command}（create | str_replace | append）"

        if len(updated.encode("utf-8")) > _WRITE_MAX_BYTES:
            return f"Error: 写入后超限（>{_WRITE_MAX_BYTES} bytes）"
        full.write_text(updated, encoding="utf-8")
        return f"已更新 {kid}/{rel}。"

    def delete(self, path: str, kb_id: str | None = None) -> str:
        target = self._wiki_target(kb_id)
        if target is None:
            return "Error: 未绑定 Wiki 型知识库，或绑定了多个但未指定 kb_id。"
        kid, _base = target
        rel = self._normalize_wiki_path(path)
        if rel is None:
            return f"Error: 非法路径 {path}"
        if rel in _PROTECTED_PAGES:
            return f"Error: {rel} 是受保护页面，禁止删除"
        base = self._kb_roots[kid]
        full = WorkspaceManager.safe_resolve_path(base, rel)
        if full is None or not full.is_file():
            return f"Error: 页面不存在: {rel}"
        full.unlink()
        return f"已删除 {kid}/{rel}。检查 overview/交叉链接是否需要清理（kb_lint）。"

    def lint(self, kb_id: str | None = None) -> str:
        from app.engine.kb.tree.lint import run_lint

        target = self._wiki_target(kb_id)
        if target is None:
            return "Error: 未绑定 Wiki 型知识库，或绑定了多个但未指定 kb_id。"
        kid, _base = target
        report = run_lint(kid)
        issues = report["issues"]
        if not issues:
            return "✅ 无问题：脚注、引用、链接、页面覆盖全部健康。"
        lines = []
        for i in issues:
            lines.append(f"[{i['severity']}] {i['rule']} · {i['path']} — {i['detail']}")
        s = report["stats"]
        header = (
            f"共 {len(issues)} 项（error {s['error_count']} / warn {s['warn_count']}）："
            f"页面 {s['page_count']}，源 {s['source_count']}（已引用 {s['cited_source_count']}）"
        )
        return header + "\n" + "\n".join(lines)

    # ── tool factory ───────────────────────────────────────────────────

    def make_tools(self) -> list[StructuredTool]:
        kb_hint = ", ".join(self._kb_roots) or "none"
        wiki_hint = ", ".join(sorted(self._wiki_kb_ids)) or "none"

        async def _glob_coro(pattern: str, kb_id: str | None = None) -> str:
            return self.glob(pattern, kb_id)

        async def _grep_coro(
            pattern: str, kb_id: str | None = None, scope: str = "all"
        ) -> str:
            return self.grep(pattern, kb_id, scope)

        async def _read_coro(
            path: str,
            kb_id: str | None = None,
            pages: str | None = None,
            sections: list[str] | None = None,
        ) -> str:
            return self.read(path, kb_id, pages=pages, sections=sections)

        glob_tool = StructuredTool.from_function(
            _glob_coro,
            name="kb_glob",
            description=(
                "列出知识库中匹配 glob 模式的 Markdown 文件，返回 'kb_id/相对路径' 列表。"
                "Wiki 型知识库首次查询建议从 wiki/overview.md（全库地图）开始导航，"
                "不要盲目 glob 全库。"
                f" 可用知识库: {kb_hint}"
            ),
            args_schema=_KbGlobArgs,
            coroutine=_glob_coro,
        )
        grep_tool = StructuredTool.from_function(
            _grep_coro,
            name="kb_grep",
            description=(
                "在知识库文本中搜索正则表达式，返回 'kb_id/路径:行号: 行内容'（行号≠页码，"
                "kb_read 不接受行号）。Wiki 型知识库查询走 wiki 优先两段式：先 scope=wiki "
                "搜编译层；结果不足才 scope=sources 降级查源文本。"
                f" 可用知识库: {kb_hint}"
            ),
            args_schema=_KbGrepArgs,
            coroutine=_grep_coro,
        )
        read_tool = StructuredTool.from_function(
            _read_coro,
            name="kb_read",
            description=(
                "读取知识库文件内容：wiki 页面/普通 .md 直读原文；sources/ 二进制源"
                "（PDF/Word 等）自动读其提取文本（pages='3-5' 按页——仅二进制源的提取文本"
                "有分页标记，.md 源无分页勿传 pages；sections=['标题词'] 按节抽取）；"
                "path 传 glob 模式（如 'wiki/concepts/*.md'）时批量采样读取多个文件。"
            ),
            args_schema=_KbReadArgs,
            coroutine=_read_coro,
        )
        tools = [glob_tool, grep_tool, read_tool]

        if not self._wiki_kb_ids:
            return tools

        async def _guide_coro(kb_id: str | None = None) -> str:
            return self.guide(kb_id)

        async def _write_coro(
            command: str,
            path: str,
            content: str = "",
            old_string: str = "",
            new_string: str = "",
            title: str | None = None,
            description: str | None = None,
            tags: list[str] | None = None,
            kb_id: str | None = None,
        ) -> str:
            return self.write(
                command,
                path,
                content=content,
                old_string=old_string,
                new_string=new_string,
                title=title,
                description=description,
                tags=tags,
                kb_id=kb_id,
            )

        async def _delete_coro(path: str, kb_id: str | None = None) -> str:
            return self.delete(path, kb_id)

        async def _lint_coro(kb_id: str | None = None) -> str:
            return self.lint(kb_id)

        wiki_desc = f"可用 Wiki 知识库: {wiki_hint}"
        tools.append(
            StructuredTool.from_function(
                _guide_coro,
                name="kb_guide",
                description=(
                    "获取 Wiki 维护指南（目录骨架/写作规范/引用格式/ingest 工作流）与本库"
                    "状态（源数/页数/待消化源）。维护/沉淀 wiki 前必须先调用；"
                    "查询不需要——直接从 wiki/overview.md 地图开始即可。"
                    f"{wiki_desc}。"
                ),
                args_schema=_KbGuideArgs,
                coroutine=_guide_coro,
            )
        )
        tools.append(
            StructuredTool.from_function(
                _write_coro,
                name="kb_write",
                description=(
                    "维护 Wiki 页面：create 新建（自动生成 frontmatter，勿带 H1）、"
                    "str_replace 精确替换（old_string 必须唯一）、append 追加。"
                    f"只能写 wiki/ 子树。{wiki_desc}"
                ),
                args_schema=_KbWriteArgs,
                coroutine=_write_coro,
            )
        )
        tools.append(
            StructuredTool.from_function(
                _delete_coro,
                name="kb_delete",
                description=f"删除 wiki/ 下的页面（overview/log 受保护）。{wiki_desc}",
                args_schema=_KbDeleteArgs,
                coroutine=_delete_coro,
            )
        )
        tools.append(
            StructuredTool.from_function(
                _lint_coro,
                name="kb_lint",
                description=(
                    "Wiki 健康检查：脚注卫生/引用源存在性/悬空链接/孤儿页/未引用源。"
                    f"{wiki_desc}"
                ),
                args_schema=_KbLintArgs,
                coroutine=_lint_coro,
            )
        )
        return tools

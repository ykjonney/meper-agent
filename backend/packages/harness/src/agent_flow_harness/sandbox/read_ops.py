"""read 格式化/分页语义 — Local/Docker 两个 Sandbox 共用的单一实现。

职责（对齐主流 coding agent 的 read 语义，如 Claude Code 的 cat -n 风格）：
- 行号格式：1-based 行号右对齐 6 宽 + tab（``f"{n:>6}\\t{line}"``），
  模型可据此引用"第 N 行"；
- 行级分页：offset（1-based 起始行）/ limit（返回行数）切片——大文件
  不再被整体截断砍尾，而是可分页续读；
- 单行截断：单行超 _MAX_LINE_CHARS 截断加标记，防超宽行撑爆上下文；
- 字符预算：总输出不超过 max_chars（Sandbox 的 max_output_chars），
  预算内放不下本次 limit 的全部行时提前截停，由尾部导航提示说明，
  保证 _truncate 兜底不误伤导航信息；
- 尾部导航提示：还有更多行时附 ``[Showing lines X-Y of Z total...]``，
  offset 越界 / 空文件给明确提示。

提示文案英文（与 edit_ops 的 LLM 反馈通道一致）。
"""
from __future__ import annotations

# 单行字符上限（超出截断），对齐主流 read 工具的行宽限制
_MAX_LINE_CHARS = 2000
_LINE_TRUNCATED_SUFFIX = " ... [line truncated]"
# 尾部导航提示预留字符数（max_chars 扣除该量级后再排布行内容）
_NOTE_BUDGET = 256

# 二进制魔数签名（前缀匹配）——read 对二进制文件返回查看引导而非乱码
_BINARY_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image"),
    (b"\xff\xd8\xff", "image"),  # JPEG
    (b"GIF8", "image"),  # GIF87a/89a
    (b"RIFF", "image"),  # WebP（RIFF 容器）
    (b"BM", "image"),  # BMP
    (b"%PDF", "document"),
    (b"PK\x03\x04", "document"),  # zip 家族（docx/xlsx/pptx/zip）
)


def sniff_binary_kind(data: bytes) -> str | None:
    """按魔数嗅探二进制类型：'image' / 'document' / None（可按文本读）。"""
    for magic, kind in _BINARY_SIGNATURES:
        if data.startswith(magic):
            return kind
    return None


def format_read(
    content: str,
    *,
    path: str,
    offset: int = 1,
    limit: int = 2000,
    max_chars: int = 50_000,
) -> str:
    """把文件全文格式化为带行号的分页文本。

    content 为 LF 归一后的全文（read_text 语义）；返回值保证不超过
    max_chars（单行超预算的极端情况除外）。负 offset 视为 1。
    """
    lines = content.split("\n")
    # 尾部换行产生一个空的末元素：文件以 \n 结尾是常态，不计为一行
    if lines and lines[-1] == "":
        lines.pop()
    total = len(lines)
    if total == 0:
        return f"(empty file: {path})"

    if offset < 1:
        offset = 1
    if offset > total:
        return (
            f"[offset {offset} is beyond end of file '{path}' "
            f"({total} lines total). Use a smaller offset.]"
        )
    end = min(offset - 1 + limit, total)

    budget = max(max_chars - _NOTE_BUDGET, 0)
    out: list[str] = []
    used = 0
    truncated_early = False
    for i in range(offset - 1, end):
        line = lines[i]
        if len(line) > _MAX_LINE_CHARS:
            line = line[:_MAX_LINE_CHARS] + _LINE_TRUNCATED_SUFFIX
        text = f"{i + 1:>6}\t{line}"
        if out and used + len(text) + 1 > budget:
            # 预算放不下本行：提前截停（至少保留首行，避免空输出）
            truncated_early = True
            break
        out.append(text)
        used += len(text) + 1
    shown_end = offset - 1 + len(out)

    result = "\n".join(out)
    has_more = shown_end < total or truncated_early
    if has_more:
        resume = shown_end + 1
        result += (
            f"\n\n[Showing lines {offset}-{shown_end} of {total} total lines"
            + (" (output budget reached)" if truncated_early else "")
            + f". Use offset={resume} to continue reading '{path}'.]"
        )
    return result


__all__ = ["format_read", "sniff_binary_kind"]

"""edit 匹配/应用语义 — Local/Docker 两个 Sandbox 共用的单一实现。

职责（对齐 pi coding agent 的 edit 语义）：
- BOM 剥离：模型不会在 old_string 里带不可见 BOM，匹配前剥掉、写回时还原；
- 行尾归一化：CRLF 文件先归一为 LF 再匹配（模型几乎总发 LF），替换后按
  原行尾还原——CRLF 文件不再因行尾不一致而 old_string not found；
- 快照匹配：每条编辑都基于同一份原始内容匹配（非增量），避免前一条
  替换影响后一条的匹配；
- 重叠校验：多条编辑的命中区间不得重叠/嵌套，否则明确报错。

错误文案约定：单项编辑（len(edits)==1）保持历史文案逐字不变（测试与
LLM 反馈通道均依赖）；批量编辑带 edits[i] 前缀定位到具体条目。
"""
from __future__ import annotations

from collections.abc import Sequence

# 单条编辑：(old_string, new_string)
EditPair = tuple[str, str]


def _not_found_msg(path: str, index: int, batch: bool) -> str:
    base = (
        f"old_string not found in '{path}'. "
        "Read the file again and retry with an exact match (including whitespace)."
    )
    if not batch:
        return base
    return (
        f"edits[{index}]: {base} "
        "Note: each edits[] entry is matched against the original file, not "
        "incrementally — another entry may have already replaced this text."
    )


def _not_unique_msg(path: str, index: int, count: int, batch: bool) -> str:
    base = (
        f"old_string appears {count} times in '{path}'. "
        "Provide a longer, more unique old_string, or set replace_all=true."
    )
    if not batch:
        return base
    return f"edits[{index}]: {base}"


def _overlap_msg(path: str, first: int, second: int) -> str:
    return (
        f"edits[{second}] overlaps edits[{first}] in '{path}'. "
        "Each edits[] entry must target a unique, non-overlapping region of "
        "the original file; merge nearby changes into one entry."
    )


def _plan_spans(
    content: str,
    edits: Sequence[EditPair],
    *,
    replace_all: bool,
    path: str,
) -> list[tuple[int, int, str]]:
    """在原始内容上为每条编辑计算命中区间 (start, end, new_text)。

    区间按 start 排序返回；不匹配/不唯一/重叠抛 ValueError（文案见上）。
    replace_all 作用于单条编辑：替换该 old_string 的全部命中。
    """
    batch = len(edits) > 1
    spans: list[tuple[int, int, str, int]] = []  # (start, end, new_text, edit_index)
    for idx, (old, new) in enumerate(edits):
        count = content.count(old)
        if count == 0:
            raise ValueError(_not_found_msg(path, idx, batch))
        if count > 1 and not replace_all:
            raise ValueError(_not_unique_msg(path, idx, count, batch))
        start = 0
        for _ in range(count if replace_all else 1):
            pos = content.index(old, start)
            spans.append((pos, pos + len(old), new, idx))
            start = pos + len(old)
    spans.sort(key=lambda s: (s[0], s[1]))
    for prev, cur in zip(spans, spans[1:]):
        if cur[0] < prev[1]:
            raise ValueError(_overlap_msg(path, prev[3], cur[3]))
    return [(s, e, n) for s, e, n, _ in spans]


def apply_edits(
    content: str,
    edits: Sequence[EditPair],
    *,
    path: str,
    replace_all: bool = False,
) -> tuple[str, str]:
    """在 content 上应用一组编辑，返回 (new_content, success_message)。

    匹配失败/区间重叠抛 ValueError；调用方负责落盘。
    """
    # BOM：剥离后匹配，写回时还原
    had_bom = content.startswith("\ufeff")
    if had_bom:
        content = content[1:]
    # 行尾：CRLF 文件归一为 LF 匹配，最后按原行尾还原
    is_crlf = "\r\n" in content
    if is_crlf:
        content = content.replace("\r\n", "\n")

    norm_edits = [
        (old.replace("\r\n", "\n"), new.replace("\r\n", "\n"))
        for old, new in edits
    ]
    spans = _plan_spans(content, norm_edits, replace_all=replace_all, path=path)

    # 按区间拼装结果（spans 已排序且互不重叠）
    parts: list[str] = []
    cursor = 0
    replacements = 0
    for start, end, new in spans:
        parts.append(content[cursor:start])
        parts.append(new)
        cursor = end
        replacements += 1
    parts.append(content[cursor:])
    result = "".join(parts)

    if is_crlf:
        result = result.replace("\n", "\r\n")
    if had_bom:
        result = "\ufeff" + result

    if len(edits) > 1:
        message = (
            f"Successfully edited '{path}' "
            f"({replacements} replacements across {len(edits)} edits)."
        )
    else:
        occurrences = replacements if replace_all else 1
        message = (
            f"Successfully edited '{path}' "
            f"({occurrences} replacement{'s' if occurrences > 1 else ''})."
        )
    return result, message


__all__ = ["EditPair", "apply_edits"]

"""edit_ops.apply_edits 语义测试 — BOM/行尾归一化、快照匹配、批量重叠校验。

单项编辑的错误/成功文案必须与历史 edit_file 逐字一致（LLM 反馈通道与
存量测试依赖）；批量编辑带 edits[i] 前缀。
"""
from __future__ import annotations

import pytest

from agent_flow_harness.sandbox.edit_ops import apply_edits


# ── 单编辑：历史文案逐字兼容 ──────────────────────────────────────────


def test_single_success_message_exact():
    content, msg = apply_edits("a\nb\nc\n", [("b", "B")], path="f.txt")
    assert content == "a\nB\nc\n"
    assert msg == "Successfully edited 'f.txt' (1 replacement)."


def test_single_not_found_message_exact():
    with pytest.raises(ValueError, match=r"^old_string not found in 'f\.txt'\. ") as ei:
        apply_edits("a\n", [("zzz", "B")], path="f.txt")
    assert "Read the file again" in str(ei.value)


def test_single_multiple_matches_message_exact():
    with pytest.raises(ValueError) as ei:
        apply_edits("x x x", [("x", "y")], path="f.txt")
    assert str(ei.value) == (
        "old_string appears 3 times in 'f.txt'. "
        "Provide a longer, more unique old_string, or set replace_all=true."
    )


def test_single_replace_all():
    content, msg = apply_edits("x x", [("x", "y")], path="f.txt", replace_all=True)
    assert content == "y y"
    assert msg == "Successfully edited 'f.txt' (2 replacements)."


# ── 行尾归一化 ────────────────────────────────────────────────────────


def test_crlf_file_matched_with_lf_old_string():
    """CRLF 文件用 LF 风格 old_string 也能命中，且写回保持 CRLF。"""
    content, msg = apply_edits("a\r\nb\r\nc\r\n", [("a\nb", "X")], path="f.txt")
    assert content == "X\r\nc\r\n"
    assert msg == "Successfully edited 'f.txt' (1 replacement)."


def test_crlf_file_new_string_normalized_to_crlf():
    """new_string 里模型发的 \\n 在 CRLF 文件中写回为 \\r\\n。"""
    content, _ = apply_edits("a\r\nb\r\n", [("a", "1\n2")], path="f.txt")
    assert content == "1\r\n2\r\nb\r\n"


def test_lf_file_unchanged():
    content, _ = apply_edits("a\nb\n", [("a", "X")], path="f.txt")
    assert content == "X\nb\n"


# ── BOM ───────────────────────────────────────────────────────────────


def test_bom_stripped_for_match_and_restored():
    raw = "\ufeff# title\nbody\n"
    content, _ = apply_edits(raw, [("# title", "# TITLE")], path="f.txt")
    assert content == "\ufeff# TITLE\nbody\n"


def test_crlf_and_bom_combined():
    raw = "\ufeffa\r\nb\r\n"
    content, _ = apply_edits(raw, [("a\nb", "X")], path="f.txt")
    assert content == "\ufeffX\r\n"


# ── 批量：快照匹配 + 重叠校验 + 索引化错误 ────────────────────────────


def test_batch_disjoint_edits_all_applied():
    content, msg = apply_edits(
        "one\ntwo\nthree\n", [("one", "ONE"), ("three", "THREE")], path="f.txt"
    )
    assert content == "ONE\ntwo\nTHREE\n"
    assert msg == "Successfully edited 'f.txt' (2 replacements across 2 edits)."


def test_batch_overlap_rejected():
    with pytest.raises(ValueError) as ei:
        apply_edits(
            "hello world\n",
            [("hello", "HELLO"), ("hello world", "X")],
            path="f.txt",
        )
    assert "overlaps edits[0]" in str(ei.value)


def test_batch_not_found_has_index_prefix():
    with pytest.raises(ValueError) as ei:
        apply_edits("a\nb\n", [("a", "A"), ("missing", "M")], path="f.txt")
    assert str(ei.value).startswith("edits[1]: old_string not found in 'f.txt'.")
    assert "another entry may have already replaced this text" in str(ei.value)


def test_batch_not_unique_has_index_prefix():
    with pytest.raises(ValueError) as ei:
        apply_edits("dup dup\na\n", [("dup", "D"), ("a", "A")], path="f.txt")
    assert str(ei.value).startswith("edits[0]: old_string appears 2 times in 'f.txt'.")


def test_batch_replace_all_applies_per_entry():
    content, msg = apply_edits(
        "x a x b\n", [("x", "Y"), ("a", "A")], path="f.txt", replace_all=True
    )
    assert content == "Y A Y b\n"
    assert msg == "Successfully edited 'f.txt' (3 replacements across 2 edits)."


def test_batch_nested_spans_rejected():
    with pytest.raises(ValueError, match="overlaps"):
        apply_edits(
            "abcdef\n",
            [("bc", "X"), ("abcd", "Y")],
            path="f.txt",
        )

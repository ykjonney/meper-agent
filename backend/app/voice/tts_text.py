"""Shared TTS cleanup and conservative per-request chunking.

Aliyun Qwen3-TTS accepts 600 characters; GLM-TTS accepts 1024 (use 1000).
Volcano's 330 characters / 1024 UTF-8 bytes are application safety caps,
not a claim about the Agent Plan bidirectional API's hard limit.
"""

from __future__ import annotations

import re
import unicodedata

TTS_TEXT_LIMITS = {"aliyun": 600, "zhipu": 1000, "volcano": 330}
_SPLIT_PUNCT = "。！？!?，、；：,;: "
_EMOJI_PARTS = re.compile("[0-9#*]\ufe0f?\u20e3|[\ufe0e\ufe0f\U000e0100-\U000e01ef]")


def sanitize_tts_text(text: str) -> str:
    """Drop emoji/control characters without joining words across newlines.

    Preserve language combining marks, punctuation, currency and math symbols.
    Strip keycap emoji and variation selectors as well as pictographic symbols.
    """
    kept: list[str] = []
    for ch in _EMOJI_PARTS.sub("", text):
        category = unicodedata.category(ch)
        if ch.isspace():
            kept.append(" ")
        elif (
            category[0] in ("L", "M", "N", "P")
            or category in ("Sc", "Sm")
            or ch in "©°^~"
        ):
            kept.append(ch)
    return re.sub(r" +", " ", "".join(kept)).strip()


def split_tts_text(text: str, limit: int, *, max_bytes: int | None = None) -> list[str]:
    """Split at nearby punctuation, enforcing character and optional byte caps."""
    if limit <= 0 or (max_bytes is not None and max_bytes < 4):
        raise ValueError("TTS limits must fit at least one Unicode character")
    segments: list[str] = []
    rest = text
    while rest:
        end = min(len(rest), limit)
        if max_bytes is not None:
            byte_count = 0
            for index, ch in enumerate(rest[:end]):
                byte_count += len(ch.encode("utf-8"))
                if byte_count > max_bytes:
                    end = index
                    break
        if end == len(rest):
            segments.append(rest)
            break
        cut = max(rest.rfind(ch, 0, end) for ch in _SPLIT_PUNCT) + 1
        if cut <= 0:
            cut = end
        segment = rest[:cut].rstrip()
        if segment:
            segments.append(segment)
        rest = rest[cut:].lstrip()
    return segments


def prepare_tts_segments(text: str, provider: str) -> list[str]:
    cleaned = sanitize_tts_text(text)
    if not cleaned:
        return []
    limit = TTS_TEXT_LIMITS.get(provider)
    if limit is None:
        return [cleaned]
    return split_tts_text(
        cleaned, limit, max_bytes=1024 if provider == "volcano" else None
    )

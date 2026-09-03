import pytest
from app.voice.tts_text import (
    prepare_tts_segments,
    sanitize_tts_text,
    split_tts_text,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("你好，世界！", "你好，世界！"),
        ("hello\nworld\t下一行", "hello world 下一行"),
        ("你好👨‍👩‍👧‍👦👍🏽🇨🇳1️⃣！", "你好！"),
        ("∑x ≥ 3，￥5 + $2，20°C，e\u0301", "∑x ≥ 3，￥5 + $2，20°C，e\u0301"),
        ("a\x00b\u200bc", "abc"),
        ("x^2 ~ y", "x^2 ~ y"),
        (" \n😀\ufe0f ", ""),
    ],
)
def test_sanitize(text, expected):
    assert sanitize_tts_text(text) == expected


@pytest.mark.parametrize(
    "provider,limit", [("aliyun", 600), ("zhipu", 1000), ("volcano", 330)]
)
def test_character_boundaries(provider, limit):
    text = "文" * (limit * 2 + 1)
    parts = prepare_tts_segments(text, provider)
    assert "".join(parts) == text
    assert all(0 < len(part) <= limit for part in parts)
    assert prepare_tts_segments("文" * limit, provider) == ["文" * limit]


def test_volcano_also_limits_four_byte_characters():
    text = "𠀀" * 400
    parts = prepare_tts_segments(text, "volcano")
    assert "".join(parts) == text
    assert all(len(part.encode("utf-8")) <= 1024 for part in parts)


def test_split_prefers_punctuation_and_handles_empty():
    assert split_tts_text("甲乙，丙丁戊己庚", 5) == ["甲乙，", "丙丁戊己庚"]
    assert prepare_tts_segments("😀", "aliyun") == []
    assert prepare_tts_segments("你好", "other") == ["你好"]
    with pytest.raises(ValueError):
        split_tts_text("text", 0)

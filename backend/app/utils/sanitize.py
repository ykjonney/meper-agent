"""Input sanitization utilities for defense-in-depth against stored XSS.

The Agent platform stores user-authored text (Agent role/task prompts,
descriptions, file notes, etc.) that is later rendered back in the web UI.
While the React frontend escapes content by default, the backend applies
targeted sanitization as a second layer of defense.

The cleaning strategy is **selective**, not full HTML escaping:
- Removes known-dangerous constructs: ``<script>``, ``<iframe>``, inline
  event handlers (``on*="..."``), and dangerous URI schemes
  (``javascript:``, ``vbscript:``, ``data:text/html``).
- **Preserves** plain text, bare ``<`` / ``>`` characters, code samples,
  and ``{{ }}`` Jinja templates. This is essential because ``prompt_slots``
  values (role / task / constraints …) are fed to the LLM and frequently
  contain code, math comparisons (``a < b``), and templating.

This keeps the content usable for LLM prompting while neutralizing the XSS
payloads that actually execute in browsers.
"""
from __future__ import annotations

import re

# ── 危险标签（成对或自闭合）─────────────────────────────────────
# 大小写不敏感、DOTALL（跨行）匹配整个标签块。
_DANGEROUS_TAG_RE = re.compile(
    r"</?(?:script|iframe|object|embed|svg\s+on\w+|math\s+on\w+|"
    r"form|base|meta|link|applet|"
    r"img\s+[^>]*on\w+)[^>]*>",
    re.IGNORECASE | re.DOTALL,
)

# 独立的 <script ...>（无属性也命中）与自闭合 <script .../>。
_SCRIPT_BLOCK_RE = re.compile(
    r"<script[^>]*>.*?</script\s*>",
    re.IGNORECASE | re.DOTALL,
)

# ── 内联事件处理属性 on*="..." ───────────────────────────────────
# 匹配 ` onXyz=` / `\tonXyz=` 这类属性，含被引号包裹或未加引号的值。
_EVENT_HANDLER_RE = re.compile(
    r"\son[a-z]+\s*=\s*(?:\"[^\"]*\"|'[^']*'|[^\s>]+)",
    re.IGNORECASE,
)

# ── 危险协议 URI ────────────────────────────────────────────────
# 匹配 javascript: / vbscript: / data:text/html 等可执行载荷。
# 仅清洗作为 href/src 等属性值或裸协议出现的情况。
_DANGEROUS_URI_RE = re.compile(
    r"(?:javascript|vbscript|data\s*:\s*text\s*/\s*html|livescript|mocha)\s*:",
    re.IGNORECASE,
)

# 清洗后允许返回的安全占位说明，避免静默吞掉内容造成困惑。
_REMOVED_MARKER = ""


def sanitize_text(value: str) -> str:
    """Strip known-dangerous XSS constructs from *value*.

    Removes ``<script>``/``<iframe>`` blocks, inline ``on*=`` event
    handlers, and ``javascript:``/``vbscript:``/``data:text/html`` URIs.
    Preserves plain text, bare ``<``/``>`` (e.g. ``a < b``), code samples,
    and ``{{ }}`` Jinja templates — essential for ``prompt_slots`` content
    that is fed to the LLM.

    Args:
        value: Raw user-supplied text.

    Returns:
        Cleaned text with dangerous constructs removed.
    """
    if not isinstance(value, str) or not value:
        return value if isinstance(value, str) else ""

    cleaned = value
    # Order matters: strip whole script blocks first, then orphan tags,
    # then attribute-level handlers and URI schemes.
    cleaned = _SCRIPT_BLOCK_RE.sub(_REMOVED_MARKER, cleaned)
    cleaned = _DANGEROUS_TAG_RE.sub(_REMOVED_MARKER, cleaned)
    cleaned = _EVENT_HANDLER_RE.sub(_REMOVED_MARKER, cleaned)
    cleaned = _DANGEROUS_URI_RE.sub("blocked:", cleaned)
    return cleaned


def sanitize_dict(value: dict[str, str]) -> dict[str, str]:
    """Sanitize every string value in a ``dict[str, str]``.

    Used for fields like ``prompt_slots`` where each value is free text.
    Keys are returned unchanged (key validation is handled separately).

    Args:
        value: Mapping of free-text values (e.g. ``prompt_slots``).

    Returns:
        New dict with each value passed through :func:`sanitize_text`.
    """
    if not isinstance(value, dict):
        return value
    return {k: sanitize_text(v) for k, v in value.items()}

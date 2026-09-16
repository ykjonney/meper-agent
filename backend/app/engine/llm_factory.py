"""LLM client factory — creates LangChain chat models from Agent documents.

This module owns the **application-layer** concerns only:
- Model-table lookup (``models`` collection) and API-key decryption.
- Agent ``temperature_override`` / legacy ``llm_config`` resolution.

The pure LLM-construction logic (provider selection, auth-kwargs, thinking
adaptation) is delegated to ``agent_flow_harness.llm`` to avoid maintaining
a verbatim copy of that code here.

Resolution strategies:

1. **Model table lookup** (preferred): when ``default_model`` starts with
   ``model_``, it is treated as a ULID ``_id`` referencing a document in the
   ``models`` collection.
2. **Legacy fallback**: plain model name strings use environment-variable
   credentials and auto-detected provider.
"""
from __future__ import annotations

from typing import Any

from loguru import logger

# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


async def get_llm_client(
    agent_doc: dict | None = None,
    enable_thinking: bool = False,
):
    """Construct a LangChain chat model from an Agent document.

    Resolution order:
    1. If ``default_model`` starts with ``model_`` → look up the models
       collection and build a client from the stored config.
    2. Otherwise → fall back to the legacy env-var-based approach.

    Args:
        agent_doc: Agent document (from MongoDB). Reads ``default_model``
            and ``temperature_override`` (runtime-only) from flat top-level
            fields. Falls back to legacy ``llm_config`` nested dict for
            old documents.
        enable_thinking: When True, enable LLM native reasoning for
            supported models. Unsupported models silently ignore this.

    Returns:
        A configured LangChain chat model instance.
    """
    from agent_flow_harness import build_client_from_doc, build_client_from_env

    from app.models.compat import resolve_default_model

    doc = agent_doc or {}
    model_ref: str = resolve_default_model(doc)
    # Temperature: runtime override > model default_params (handled by caller)
    temperature_override = doc.get("temperature_override")

    # 1. Try to resolve as model table _id (ULID prefix "model_")
    if model_ref.startswith("model_"):
        model_doc = await _resolve_model_doc(model_ref)
        if model_doc is not None:
            agent_config = {}
            if temperature_override is not None:
                agent_config["temperature"] = temperature_override
            return build_client_from_doc(model_doc, agent_config, enable_thinking=enable_thinking)
        # Model not found in table → fall through to legacy

        logger.warning(
            "llm_factory_model_not_found",
            model_ref=model_ref,
            message="模型表中未找到模型引用，尝试回退到环境变量",
        )

    # 2. Legacy: model name string (env-var based)
    if model_ref:
        agent_config = {}
        if temperature_override is not None:
            agent_config["temperature"] = temperature_override
        return build_client_from_env(model_ref, agent_config, enable_thinking=enable_thinking)

    # 3. Final fallback
    return build_client_from_env("gpt-4o-mini", {}, enable_thinking=enable_thinking)


async def _resolve_model_doc(model_ref: str) -> dict | None:
    """Look up a model document by _id from the models collection.

    Returns the document with decrypted api_key, or None.
    """
    try:
        from app.services.model_service import ModelService

        return await ModelService.get_model_config_by_id(model_ref)
    except Exception as exc:
        logger.error(
            "llm_factory_resolve_failed",
            model_ref=model_ref,
            error=str(exc),
        )
        return None


async def resolve_chat_model(model_id: str = "", *, temperature: float = 0.2):
    """服务层直接调 LLM 的统一解析入口（工具生成/测试等非 agent 链路）。

    - ``model_`` 前缀 → 查模型表构建客户端；查无此模型抛 ``ValueError``
      （不静默回退——调用方应向用户报错）
    - 空 / 其他 → 平台默认客户端（``get_llm_client`` 兜底）
    """
    if model_id.startswith("model_"):
        model_doc = await _resolve_model_doc(model_id)
        if model_doc is None:
            raise ValueError(f"模型不存在：{model_id}")
        from agent_flow_harness import build_client_from_doc

        return build_client_from_doc(model_doc, {"temperature": temperature})
    return await get_llm_client()


def content_text(resp: Any) -> str:
    """LangChain AIMessage → 纯文本。

    结构化 content（列表块）只取 ``type == "text"`` 的块——thinking /
    signature 等内部推理块对用户不可见，绝不能 ``str(块)`` 裸拼
    （会出现 ``{'signature': ...}`` 这类 dict 原文）。
    """
    content = getattr(resp, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for p in content:
            if isinstance(p, str):
                parts.append(p)
            elif isinstance(p, dict) and p.get("type") == "text" and p.get("text"):
                parts.append(str(p["text"]))
        return "".join(parts)
    return str(content)


# ---------------------------------------------------------------------------
# Public helpers (thin delegates to harness.llm)
#
# Kept for backward compat — model_service.test_connectivity and other
# callers import these directly from llm_factory.
# ---------------------------------------------------------------------------


def build_client_from_doc(
    doc: dict,
    agent_config: dict | None = None,
    enable_thinking: bool = False,
):
    """Build a ChatModel from a model table document (public API).

    Delegates to ``agent_flow_harness.llm.build_client_from_doc``.
    """
    from agent_flow_harness import build_client_from_doc as _harness_build

    return _harness_build(doc, agent_config or {}, enable_thinking=enable_thinking)


def supports_thinking(model_id: str, compatibility: str) -> bool:
    """Check whether a model supports native LLM reasoning.

    Delegates to ``agent_flow_harness.llm.supports_thinking``.
    """
    from agent_flow_harness import supports_thinking as _harness_supports

    return _harness_supports(model_id, compatibility)

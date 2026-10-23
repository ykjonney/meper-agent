"""Conversation context helpers (app layer).

The canonical implementations live in the ``agent_flow_harness`` package.
What stays local is :func:`get_context_window_async`: the app version looks
up the models collection (DB) for ``model_`` references, which the
harness — which has no DB access — cannot do.
"""
from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel

_CONTEXT_WINDOWS: dict[str, int] = {
    "gpt-4o": 128000,
    "gpt-4o-mini": 128000,
    "gpt-4": 8192,
    "gpt-3.5-turbo": 16384,
    "claude-3-5-sonnet": 200000,
    "claude-3-haiku": 200000,
    "claude-opus-4": 200000,
    "claude-sonnet-4": 200000,
    "claude-4": 200000,
}

_DEFAULT_MAX_TOKENS = 128000

def get_context_window(model: str) -> int:
    """Return the context window size for a given model name.

    Checks the hardcoded table first. For model references starting
    with ``model_`` (ULID _id), callers should use
    :func:`get_context_window_async` which looks up the models
    collection.
    """
    for prefix, window in _CONTEXT_WINDOWS.items():
        if model.startswith(prefix):
            return window
    return _DEFAULT_MAX_TOKENS

async def get_context_window_async(model_ref: str) -> int:
    """Async version that also checks the models collection.

    Resolution order:
    1. If ``model_ref`` starts with ``model_`` → look up the models
       collection for ``default_params.context_window``.
    2. Fall back to the hardcoded ``_CONTEXT_WINDOWS`` table.
    3. Final fallback to ``_DEFAULT_MAX_TOKENS``.
    """
    if model_ref.startswith("model_"):
        try:
            from app.services.model_service import ModelService

            doc = await ModelService.get_model_config_by_id(model_ref)
            if doc is not None:
                params = doc.get("default_params", {})
                ctx = params.get("context_window")
                if ctx is not None:
                    return int(ctx)
        except Exception:
            pass  # Fall through to hardcoded lookup

    model_id = model_ref
    for prefix, window in _CONTEXT_WINDOWS.items():
        if model_id.startswith(prefix):
            return window
    return _DEFAULT_MAX_TOKENS

def extract_model_name(llm: BaseChatModel) -> str:
    """Extract the model name from a LangChain chat model instance."""
    model: str = getattr(llm, "model_name", None) or getattr(llm, "model", "") or ""
    return model

__all__ = [
    "extract_model_name",
    "get_context_window",
    "get_context_window_async",
]

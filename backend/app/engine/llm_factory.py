"""LLM client factory — creates LangChain chat models from ``llm_config``.

Supports two resolution strategies:

1. **Model table lookup** (preferred): when ``llm_config.default_model``
   starts with ``model_``, it is treated as a ULID ``_id`` referencing
   a document in the ``models`` collection. The factory decrypts the
   stored API key and constructs a ChatModel with ``base_url``,
   ``api_key``, and ``default_params`` from the model record.

2. **Legacy fallback**: plain model name strings (e.g. ``gpt-4o-mini``)
   use environment-variable credentials and auto-detected provider,
   preserving backward compatibility with existing Agent configs.
"""
from __future__ import annotations

from langchain_anthropic import ChatAnthropic
from langchain_openai import ChatOpenAI
from loguru import logger

# ---------------------------------------------------------------------------
# Provider detection helpers (legacy path only)
# ---------------------------------------------------------------------------

_OPENAI_PREFIXES = ("gpt-", "o1-", "o3-", "o4-")
_ANTHROPIC_PREFIXES = ("claude-",)

# OpenAI reasoning models that support reasoning_effort
_OPENAI_REASONING_PREFIXES = ("o1-", "o3-", "o4-")


def _detect_provider(model: str) -> str:
    """Return ``"openai"``, ``"anthropic"``, or ``"openai"`` (fallback)."""
    if any(model.startswith(p) for p in _ANTHROPIC_PREFIXES):
        return "anthropic"
    return "openai"  # includes custom OpenAI-compatible endpoints


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_KNOWN_PROVIDERS: dict[str, type] = {
    "openai": ChatOpenAI,
    "anthropic": ChatAnthropic,
}


async def get_llm_client(
    llm_config: dict | None = None,
    enable_thinking: bool = False,
) -> ChatOpenAI | ChatAnthropic:
    """Construct a LangChain chat model from an Agent's ``llm_config``.

    Resolution order:
    1. If ``default_model`` starts with ``model_`` → look up the models
       collection and build a client from the stored config.
    2. Otherwise → fall back to the legacy env-var-based approach.

    Args:
        llm_config: Agent's model configuration dict, expected to contain
            ``default_model`` (str) and optionally ``temperature`` (float).
            When ``None`` or empty, defaults to ``gpt-4o-mini``.
        enable_thinking: When True, enable LLM native reasoning for
            supported models (Claude extended thinking / OpenAI o-series
            reasoning_effort). Unsupported models silently ignore this.

    Returns:
        A configured LangChain chat model instance.

    Raises:
        ValueError: If the model's provider cannot be determined or the
            model reference is invalid.
    """
    config = llm_config or {}
    model_ref: str = config.get("default_model") or ""

    # 1. Try to resolve as model table _id (ULID prefix "model_")
    if model_ref.startswith("model_"):
        model_doc = await _resolve_model_doc(model_ref)
        if model_doc is not None:
            return _build_client_from_doc(model_doc, config, enable_thinking=enable_thinking)
        # Model not found in table → fall through to legacy

        logger.warning(
            "llm_factory_model_not_found",
            model_ref=model_ref,
            message="模型表中未找到模型引用，尝试回退到环境变量",
        )

    # 2. Legacy: model name string (env-var based)
    if model_ref:
        return _build_client_from_env(model_ref, config, enable_thinking=enable_thinking)

    # 3. Final fallback
    return _build_client_from_env("gpt-4o-mini", config, enable_thinking=enable_thinking)


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


def build_client_from_doc(
    doc: dict,
    agent_config: dict | None = None,
    enable_thinking: bool = False,
) -> ChatOpenAI | ChatAnthropic:
    """Build a ChatModel from a model table document (public API).

    This is the public counterpart of ``_build_client_from_doc`` for
    use outside the factory (e.g. model test endpoint).

    Args:
        doc: Model document with decrypted ``api_key``, ``base_url``,
            ``model_id``, ``compatibility_type``, ``auth_type``,
            ``auth_header_format``, and ``default_params``.
        agent_config: Optional overrides (e.g. temperature).
        enable_thinking: Enable native LLM reasoning if supported.

    Returns:
        Configured ChatOpenAI or ChatAnthropic instance.
    """
    return _build_client_from_doc(doc, agent_config or {}, enable_thinking=enable_thinking)


def _build_client_from_doc(
    doc: dict,
    agent_config: dict,
    enable_thinking: bool = False,
) -> ChatOpenAI | ChatAnthropic:
    """Build a ChatModel from a model table document.

    Args:
        doc: Model document with decrypted ``api_key``, ``base_url``,
            ``model_id``, ``compatibility_type``, ``auth_type``,
            ``auth_header_format``, and ``default_params``.
        agent_config: Agent's ``llm_config`` overrides (e.g. temperature).
        enable_thinking: Enable native LLM reasoning if supported.

    Returns:
        Configured ChatOpenAI or ChatAnthropic instance.
    """
    compatibility = doc.get("compatibility_type", "openai")
    model_id = doc["model_id"]
    base_url = doc["base_url"]
    api_key = doc["api_key"]  # Already decrypted by get_model_config_by_id
    auth_type = doc.get("auth_type", "bearer")
    auth_header_format = doc.get("auth_header_format", "Bearer {key}")

    # Merge: model defaults < agent overrides
    model_defaults = doc.get("default_params", {})
    temperature = agent_config.get(
        "temperature", model_defaults.get("temperature", 0.7)
    )
    max_tokens = model_defaults.get("max_tokens")

    common_kwargs: dict = {
        "model": model_id,
        "temperature": float(temperature),
    }
    if max_tokens is not None:
        common_kwargs["max_tokens"] = int(max_tokens)

    # Build auth-specific kwargs
    auth_kwargs = _build_auth_kwargs(auth_type, api_key, auth_header_format)

    # Thinking kwargs — only applied when enable_thinking=True
    thinking_kwargs = _build_thinking_kwargs(
        model_id, compatibility, enable_thinking, max_tokens
    )

    if compatibility == "openai":
        return ChatOpenAI(
            **common_kwargs,
            base_url=base_url,
            **auth_kwargs,
            **thinking_kwargs,
        )
    elif compatibility == "anthropic":
        return ChatAnthropic(
            **common_kwargs,
            base_url=base_url,
            **auth_kwargs,
            **thinking_kwargs,
        )
    else:
        raise ValueError(
            f"Unsupported compatibility type: {compatibility}"
        )


def _build_auth_kwargs(
    auth_type: str,
    api_key: str,
    auth_header_format: str,
) -> dict:
    """Construct the correct kwargs for the LangChain chat model.

    LangChain's ChatOpenAI / ChatAnthropic accept ``api_key`` for the
    standard auth path, but providers with non-standard headers require
    ``default_headers`` to inject custom headers instead.

    Args:
        auth_type: One of "bearer", "x_api_key", "api_key_header", "custom".
        api_key: Decrypted plaintext API key.
        auth_header_format: Template string (used when auth_type == "custom").

    Returns:
        Dict of kwargs to spread into the ChatModel constructor.
    """
    if auth_type == "bearer":
        # Standard: Authorization: Bearer {key}
        # LangChain handles this natively via api_key param
        return {"api_key": api_key}

    elif auth_type == "x_api_key":
        # Anthropic native style: x-api-key header
        # ChatAnthropic handles this via api_key param, but for
        # OpenAI-compatible endpoints that expect this header,
        # inject via default_headers.
        return {
            "api_key": api_key,
            "default_headers": {"x-api-key": api_key},
        }

    elif auth_type == "api_key_header":
        # Azure OpenAI style: api-key header
        return {
            "api_key": api_key,
            "default_headers": {"api-key": api_key},
        }

    elif auth_type == "custom":
        # Parse the auth_header_format template.
        # Supports two formats:
        #   1. Plain string with {key}: "Bearer {key}"
        #      → interpreted as Authorization header value
        #   2. JSON object: '{"X-My-Key": "{key}", "X-Extra": "static"}'
        #      → parsed as multiple headers
        headers = _parse_custom_auth_headers(auth_header_format, api_key)
        return {
            "api_key": api_key,
            "default_headers": headers,
        }

    else:
        logger.warning(
            "llm_factory_unknown_auth_type",
            auth_type=auth_type,
            message="未知认证方式，回退到 Bearer",
        )
        return {"api_key": api_key}


def _parse_custom_auth_headers(
    template: str,
    api_key: str,
) -> dict[str, str]:
    """Parse a custom auth header format template into a header dict.

    Supported formats:
    - ``"Bearer {key}"`` → ``{"Authorization": "Bearer sk-xxx"}``
    - ``'{"X-Api-Key": "{key}"}'`` → ``{"X-Api-Key": "sk-xxx"}``
    """
    import json

    substituted = template.replace("{key}", api_key)

    # Try JSON parse first
    try:
        parsed = json.loads(substituted)
        if isinstance(parsed, dict):
            return {str(k): str(v) for k, v in parsed.items()}
    except (json.JSONDecodeError, ValueError):
        pass

    # Fallback: treat as Authorization header value
    return {"Authorization": substituted}


def _build_client_from_env(
    model_name: str,
    agent_config: dict,
    enable_thinking: bool = False,
) -> ChatOpenAI | ChatAnthropic:
    """Legacy fallback: build a ChatModel using environment variable credentials.

    Preserves backward compatibility with Agents that store plain model
    names in ``llm_config.default_model``.
    """
    temperature: float = float(agent_config.get("temperature", 0.7))
    provider = _detect_provider(model_name)

    cls = _KNOWN_PROVIDERS.get(provider)
    if cls is None:
        raise ValueError(f"Unsupported LLM provider for model '{model_name}'")

    # Thinking kwargs — only applied when enable_thinking=True
    thinking_kwargs = _build_thinking_kwargs(
        model_name, provider, enable_thinking, max_tokens=None
    )

    return cls(  # type: ignore[call-arg]
        model=model_name,
        temperature=temperature,
        **thinking_kwargs,
    )


# ---------------------------------------------------------------------------
# Thinking (native LLM reasoning) helpers
# ---------------------------------------------------------------------------

# Default token budget for Claude extended thinking.
_ANTHROPIC_THINKING_BUDGET = 5000


def _build_thinking_kwargs(
    model_id: str,
    provider_or_compatibility: str,
    enable_thinking: bool,
    max_tokens: int | None,
) -> dict:
    """Build kwargs for enabling native LLM reasoning when supported.

    Provider-specific behavior:
    - **Anthropic** (claude-*): pass ``thinking={"type": "enabled",
      "budget_tokens": ...}``. Requires max_tokens > budget_tokens.
    - **OpenAI o-series** (o1-*, o3-*, o4-*): pass ``reasoning_effort="high"``.
    - **Others**: silently return empty dict (graceful degradation).

    Args:
        model_id: The model identifier string (e.g. "claude-sonnet-4", "o3-mini").
        provider_or_compatibility: Either a provider name from ``_detect_provider``
            ("openai"/"anthropic") or a compatibility_type from model doc.
        enable_thinking: Whether the user requested thinking mode.
        max_tokens: Optional max_tokens from model config (used by Anthropic
            to ensure it exceeds the thinking budget).

    Returns:
        Dict of kwargs to spread into the ChatModel constructor. Empty when
        thinking is disabled or unsupported.
    """
    if not enable_thinking:
        # Explicitly disable thinking for providers that default to
        # returning reasoning content (e.g. DeepSeek).
        if provider_or_compatibility == "openai":
            return {"extra_body": {"thinking": {"type": "disabled"}}}
        if provider_or_compatibility == "anthropic":
            return {"thinking": {"type": "disabled"}}
        return {}

    # Anthropic path
    if provider_or_compatibility == "anthropic":
        budget = _ANTHROPIC_THINKING_BUDGET
        # Anthropic requires max_tokens > budget_tokens
        if max_tokens is not None and int(max_tokens) <= budget:
            logger.warning(
                "llm_factory_thinking_max_tokens_low",
                max_tokens=max_tokens,
                budget=budget,
                message=f"max_tokens({max_tokens}) 不足以启用 thinking (需 > {budget})，跳过 thinking",
            )
            return {}

        # Ensure max_tokens is set (required for thinking)
        kwargs: dict = {
            "thinking": {"type": "enabled", "budget_tokens": budget},
        }
        if max_tokens is None:
            # Anthropic requires max_tokens when thinking is enabled
            kwargs["max_tokens"] = budget * 4
        return kwargs

    # OpenAI o-series path
    if provider_or_compatibility == "openai":
        if any(model_id.startswith(p) for p in _OPENAI_REASONING_PREFIXES):
            return {"reasoning_effort": "high"}

        logger.info(
            "llm_factory_thinking_not_supported",
            model_id=model_id,
            message=f"模型 '{model_id}' 不支持原生推理，已降级到普通模式",
        )
        return {}

    # Unknown provider — silently degrade
    logger.info(
        "llm_factory_thinking_unknown_provider",
        provider=provider_or_compatibility,
        message=f"未知 provider '{provider_or_compatibility}'，跳过 thinking",
    )
    return {}


def supports_thinking(model_id: str, compatibility: str) -> bool:
    """Check whether a model supports native LLM reasoning.

    Public helper for UI/API to pre-validate before showing the thinking toggle.
    """
    if compatibility == "anthropic":
        return True  # all Claude models in our catalog support extended thinking
    if compatibility == "openai":
        return any(model_id.startswith(p) for p in _OPENAI_REASONING_PREFIXES)
    return False

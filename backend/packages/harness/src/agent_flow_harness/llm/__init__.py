"""Harness LLM providers and thinking adaptation.

Public surface:

* :func:`build_client_from_doc` / :func:`build_client_from_env` — construct a
  LangChain chat model from a resolved model document or a plain model name.
* :func:`apply_thinking_mode` / :func:`build_thinking_kwargs` /
  :func:`supports_thinking` — native-LLM-reasoning adaptation.
* :func:`detect_provider` — model-name → provider detection.

The harness does not resolve model documents from a database; the application
layer decrypts / fetches the config first, then hands it to the builders.
"""

from agent_flow_harness.llm.providers.openai_compat import (
    build_client_from_doc,
    build_client_from_env,
)
from agent_flow_harness.llm.thinking import (
    apply_thinking_mode,
    build_thinking_kwargs,
    detect_provider,
    supports_thinking,
)

__all__ = [
    "apply_thinking_mode",
    "build_client_from_doc",
    "build_client_from_env",
    "build_thinking_kwargs",
    "detect_provider",
    "supports_thinking",
]

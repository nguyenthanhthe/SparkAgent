"""Pluggable LLM chat adapters.

Every provider — local or remote, real or fake — implements the same
:class:`~brain.adapters.base.ChatAdapter` protocol, so the router and the
bridge never special-case a vendor. Providers: ``mock`` (deterministic,
for tests), ``ollama`` (local GPU), ``openai_compat`` (OpenAI-compatible:
GLM, OpenAI, vLLM, LiteLLM proxies).
"""

from brain.adapters.base import AdapterResponse, ChatAdapter
from brain.adapters.registry import AdapterRegistry, adapter_registry

__all__ = ["AdapterResponse", "ChatAdapter", "AdapterRegistry",
           "adapter_registry"]

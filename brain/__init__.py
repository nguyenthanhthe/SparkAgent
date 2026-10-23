"""Brain — SparkAgent's dual-tier LLM bridge.

Tier 1 (local): NVIDIA Nemotron served by Ollama on the RTX GPU.
Tier 2 (remote): GLM via an OpenAI-compatible chat completions endpoint.
"""

from brain.bridge import Brain, BrainResponse, Tier
from brain.local import OllamaClient
from brain.remote import OpenAICompatClient

__all__ = ["Brain", "BrainResponse", "Tier", "OllamaClient", "OpenAICompatClient"]

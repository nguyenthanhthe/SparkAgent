"""The adapter contract every LLM provider implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AdapterResponse:
    text: str
    model: str
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    elapsed_s: float = 0.0
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int | None:
        if self.prompt_tokens is None and self.completion_tokens is None:
            return None
        return (self.prompt_tokens or 0) + (self.completion_tokens or 0)


@dataclass
class ChatAdapter(ABC):
    """One chat-completions backend.

    Adapters must be cheap to construct (no I/O in ``__init__``); sessions
    and clients are created lazily so unused tiers cost nothing.
    """

    name: str = "adapter"
    model: str = "unknown"

    @abstractmethod
    async def chat(self, messages: list[dict[str, str]],
                   *, temperature: float | None = None,
                   max_tokens: int | None = None,
                   json_mode: bool = False) -> AdapterResponse:
        """Generate one completion. Raise on failure; never return empty."""

    @abstractmethod
    async def healthy(self) -> tuple[bool, str]:
        """Cheap liveness probe: (ok, human detail)."""

    async def close(self) -> None:
        """Release any lazily-created resources."""

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "model": self.model,
                "kind": type(self).__name__}

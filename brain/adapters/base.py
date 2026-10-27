"""The adapter contract every LLM provider implements."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import time
from typing import Any, AsyncIterator


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

    async def ping(self) -> dict[str, Any]:
        """One latency sample around :meth:`healthy` — the per-adapter
        probe surfaced in /api/adapters. Never raises: a probe failure
        is a result (ok=False), not an error."""
        started = time.monotonic()
        try:
            ok, detail = await self.healthy()
        except Exception as exc:   # noqa: BLE001 — probes must not throw
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        return {"ok": ok, "detail": detail,
                "latency_ms": round((time.monotonic() - started) * 1000, 1)}

    async def chat_stream(self, messages: list[dict[str, str]],
                          *, temperature: float | None = None,
                          max_tokens: int | None = None,
                          json_mode: bool = False) -> AsyncIterator[str]:
        """Yield response text incrementally.

        Default fallback: one non-streaming ``chat`` call yielded as a
        single chunk — providers without a streaming transport stay
        usable through the same interface, at full-wait latency.
        """
        response = await self.chat(messages, temperature=temperature,
                                   max_tokens=max_tokens,
                                   json_mode=json_mode)
        yield response.text

    async def close(self) -> None:
        """Release any lazily-created resources."""

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "model": self.model,
                "kind": type(self).__name__}

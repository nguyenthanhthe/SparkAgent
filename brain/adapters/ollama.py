"""Ollama adapter — local GPU inference (Nemotron, Llama, Qwen, …).

Wraps the same /api/chat surface as ``brain.local.OllamaClient`` but as a
first-class :class:`ChatAdapter` with usage extraction and lazy sessions.
"""

from __future__ import annotations

from typing import Any

import aiohttp

from brain.adapters.base import AdapterResponse, ChatAdapter
from kernel.logging import get_logger

logger = get_logger("adapter.ollama")


class OllamaAdapter(ChatAdapter):
    def __init__(self, base_url: str = "http://127.0.0.1:11434",
                 model: str = "nemotron-mini", timeout: float = 180.0,
                 num_ctx: int = 8192, temperature: float = 0.4,
                 keep_alive: str = "10m"):
        self.name = "ollama"
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.num_ctx = num_ctx
        self.temperature = temperature
        self.keep_alive = keep_alive
        self._session: aiohttp.ClientSession | None = None

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "OllamaAdapter":
        return cls(
            base_url=str(config.get("base_url", "http://127.0.0.1:11434")),
            model=str(config.get("model", "nemotron-mini")),
            timeout=float(config.get("timeout", 180)),
            num_ctx=int(config.get("num_ctx", 8192)),
            temperature=float(config.get("temperature", 0.4)))

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout))
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    # ------------------------------------------------------------------- chat
    async def chat(self, messages, *, temperature=None, max_tokens=None,
                   json_mode=False) -> AdapterResponse:
        options: dict[str, Any] = {
            "temperature": self.temperature if temperature is None
            else temperature,
            "num_ctx": self.num_ctx,
        }
        if max_tokens:
            options["num_predict"] = int(max_tokens)
        payload = {"model": self.model, "messages": messages,
                   "stream": False, "keep_alive": self.keep_alive,
                   "options": options}
        if json_mode:
            payload["format"] = "json"

        import time as _time
        started = _time.monotonic()
        session = await self._ensure_session()
        try:
            async with session.post(f"{self.base_url}/api/chat",
                                    json=payload) as resp:
                if resp.status != 200:
                    raise RuntimeError(
                        f"ollama /api/chat HTTP {resp.status}: "
                        f"{(await resp.text())[:200]}")
                data = await resp.json()
        except aiohttp.ClientError as exc:
            raise RuntimeError(f"ollama unreachable: {exc}") from exc

        content = (data.get("message") or {}).get("content")
        if not content:
            raise RuntimeError("ollama returned empty content")
        usage = data.get("prompt_eval_count"), data.get("eval_count")
        return AdapterResponse(
            text=content, model=str(data.get("model", self.model)),
            prompt_tokens=usage[0], completion_tokens=usage[1],
            elapsed_s=_time.monotonic() - started)

    # ----------------------------------------------------------------- health
    async def healthy(self) -> tuple[bool, str]:
        session = await self._ensure_session()
        try:
            timeout = aiohttp.ClientTimeout(total=5.0)
            async with session.get(f"{self.base_url}/api/tags",
                                   timeout=timeout) as resp:
                if resp.status != 200:
                    return False, f"/api/tags HTTP {resp.status}"
                data = await resp.json()
        except aiohttp.ClientError as exc:
            return False, f"ollama unreachable: {exc}"
        names = [m.get("name", "") for m in data.get("models", [])]
        base = self.model.split(":")[0]
        if not any(n == self.model or n.split(":")[0] == base for n in names):
            return False, f"model {self.model!r} not pulled (have {names[:5]})"
        return True, "ok"

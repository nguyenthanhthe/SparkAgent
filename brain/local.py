"""Ollama client — Tier 1 (local GPU inference via Nemotron/CUDA)."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp

from kernel.logging import get_logger

logger = get_logger("brain.local")


class OllamaError(Exception):
    pass


class OllamaClient:
    def __init__(self, base_url: str = "http://127.0.0.1:11434",
                 model: str = "nemotron-mini", timeout: float = 180.0,
                 num_ctx: int = 8192, temperature: float = 0.4):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self.num_ctx = num_ctx
        self.temperature = temperature
        self._session: aiohttp.ClientSession | None = None

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout))
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()

    # ------------------------------------------------------------------- chat
    async def chat(self, messages: list[dict[str, str]],
                   model: str | None = None,
                   temperature: float | None = None) -> str:
        payload: dict[str, Any] = {
            "model": model or self.model,
            "messages": messages,
            "stream": False,
            "keep_alive": "10m",
            "options": {
                "temperature": self.temperature if temperature is None else temperature,
                "num_ctx": self.num_ctx,
            },
        }
        session = await self._ensure_session()
        try:
            async with session.post(f"{self.base_url}/api/chat", json=payload) as resp:
                if resp.status != 200:
                    body = (await resp.text())[:300]
                    raise OllamaError(f"/api/chat HTTP {resp.status}: {body}")
                data = await resp.json()
        except asyncio.TimeoutError as exc:
            raise OllamaError(f"local model timed out after {self.timeout}s") from exc
        except aiohttp.ClientError as exc:
            raise OllamaError(f"cannot reach Ollama at {self.base_url}: {exc}") from exc

        content = (data.get("message") or {}).get("content")
        if not content:
            raise OllamaError(f"empty response from local model: {str(data)[:200]}")
        return content

    # ----------------------------------------------------------------- health
    async def healthy(self) -> tuple[bool, str]:
        """Return (ok, detail). ok requires the server up AND the model pulled."""
        session = await self._ensure_session()
        try:
            timeout = aiohttp.ClientTimeout(total=5.0)
            async with session.get(f"{self.base_url}/api/tags",
                                   timeout=timeout) as resp:
                if resp.status != 200:
                    return False, f"/api/tags HTTP {resp.status}"
                data = await resp.json()
        except (asyncio.TimeoutError, aiohttp.ClientError) as exc:
            return False, f"Ollama unreachable: {exc}"

        names = [m.get("name", "") for m in data.get("models", [])]
        base = self.model.split(":")[0]
        if not any(n == self.model or n.split(":")[0] == base for n in names):
            return False, f"model {self.model!r} not pulled (have: {names})"
        return True, "ok"

    # -------------------------------------------------------------- embedding
    async def embed(self, text: str, model: str | None = None) -> list[float]:
        session = await self._ensure_session()
        try:
            timeout = aiohttp.ClientTimeout(total=30.0)
            async with session.post(
                    f"{self.base_url}/api/embeddings",
                    json={"model": model or self.model, "prompt": text},
                    timeout=timeout) as resp:
                if resp.status != 200:
                    raise OllamaError(f"/api/embeddings HTTP {resp.status}")
                data = await resp.json()
        except asyncio.TimeoutError as exc:
            raise OllamaError("embedding timed out") from exc
        except aiohttp.ClientError as exc:
            raise OllamaError(f"embedding request failed: {exc}") from exc
        vector = data.get("embedding")
        if not vector:
            raise OllamaError("empty embedding response")
        return vector

"""Remote LLM client — Tier 2 (GLM via OpenAI-compatible endpoint).

The API key is fetched lazily from the SecretVault (environment first),
never from configuration files. Retries with exponential backoff on
429/5xx responses.
"""

from __future__ import annotations

import asyncio
import secrets
from typing import Callable

import aiohttp

from kernel.logging import get_logger

logger = get_logger("brain.remote")


class RemoteNotConfigured(Exception):
    """No API key available for the remote tier."""


class RemoteLLMError(Exception):
    pass


class OpenAICompatClient:
    def __init__(self, chat_url: str, api_key_provider: Callable[[], str | None],
                 model: str, timeout: float = 120.0, temperature: float = 0.4,
                 max_retries: int = 3):
        self.chat_url = chat_url
        self._api_key_provider = api_key_provider
        self.model = model
        self.timeout = timeout
        self.temperature = temperature
        self.max_retries = max_retries
        self._session: aiohttp.ClientSession | None = None
        # usage dict from the last successful chat (API-reported token counts)
        self.last_usage: dict = {}

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
                   temperature: float | None = None) -> str:
        api_key = self._api_key_provider()
        if not api_key:
            raise RemoteNotConfigured("no API key configured (set GLM_API_KEY)")

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "stream": False,
        }
        headers = {"Authorization": f"Bearer {api_key}",
                   "Content-Type": "application/json"}
        session = await self._ensure_session()

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                async with session.post(self.chat_url, json=payload,
                                        headers=headers) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        content = self._extract(data)
                        if content:
                            usage = data.get("usage") or {}
                            self.last_usage = {
                                "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                                "completion_tokens": int(usage.get("completion_tokens") or 0),
                                "total_tokens": int(usage.get("total_tokens") or 0)}
                            return content
                        raise RemoteLLMError(
                            f"malformed response: {str(data)[:200]}")
                    body = (await resp.text())[:300]
                    if resp.status in (429, 500, 502, 503, 504) and \
                            attempt < self.max_retries:
                        delay = 2 ** attempt + secrets.randbelow(1000) / 1000.0
                        logger.warning("remote %s HTTP %s, retry %d/%d in %.1fs",
                                       self.model, resp.status, attempt,
                                       self.max_retries, delay)
                        await asyncio.sleep(delay)
                        continue
                    raise RemoteLLMError(f"HTTP {resp.status}: {body}")
            except asyncio.TimeoutError as exc:
                last_error = exc
                if attempt < self.max_retries:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise RemoteLLMError(
                    f"remote timed out after {self.timeout}s") from exc
        raise RemoteLLMError(f"remote failed after {self.max_retries} attempts: "
                             f"{last_error}")

    @staticmethod
    def _extract(data: dict) -> str:
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError):
            return ""

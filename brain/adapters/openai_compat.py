"""OpenAI-compatible chat adapter.

One client covers every endpoint that speaks the /chat/completions
dialect: GLM (open.bigmodel.cn), OpenAI, vLLM, LM Studio, LiteLLM proxies.
The API key is resolved lazily from the vault (environment first) — never
from config files. HTTP is pluggable (``poster``) so unit tests run fully
offline.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from brain.adapters.base import AdapterResponse, ChatAdapter
from kernel.logging import get_logger
from openshell.vault import SecretVault

logger = get_logger("adapter.openai_compat")

DEFAULT_CHAT_URL = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
DEFAULT_MODEL = "glm-5.3"

Poster = Callable[[str, dict[str, str], dict[str, Any]], Awaitable[dict]]


class RemoteNotConfigured(RuntimeError):
    pass


def aiohttp_poster(timeout: float) -> Poster:
    """Real HTTP transport (lazy session, one per adapter)."""
    import aiohttp
    session: dict[str, aiohttp.ClientSession] = {}

    async def post(url: str, headers: dict[str, str],
                   payload: dict[str, Any]) -> dict:
        if not session.get("s") or session["s"].closed:
            session["s"] = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=timeout))
        async with session["s"].post(url, json=payload,
                                     headers=headers) as resp:
            body = await resp.json(content_type=None)
            if resp.status != 200:
                raise _http_error(resp.status, body)
            return body

    async def close_session() -> None:
        existing = session.get("s")
        if existing is not None and not existing.closed:
            await existing.close()

    post.close_session = close_session  # type: ignore[attr-defined]
    return post


def _http_error(status: int, body: Any) -> Exception:
    detail = str(body)[:200]
    if status == 401:
        return PermissionError(f"unauthorized (401): {detail}")
    if status == 429:
        return ConnectionResetError(f"rate limited (429): {detail}")
    if status >= 500:
        return ConnectionResetError(f"server error ({status}): {detail}")
    return RuntimeError(f"HTTP {status}: {detail}")


@dataclass
class OpenAICompatAdapter(ChatAdapter):
    chat_url: str = DEFAULT_CHAT_URL
    model: str = DEFAULT_MODEL
    api_key_name: str = "GLM_API_KEY"
    timeout: float = 120.0
    temperature: float = 0.4
    max_retries: int = 3
    name: str = "openai_compat"
    _poster: Poster | None = None
    _vault: SecretVault | None = None

    @classmethod
    def from_config(cls, config: dict[str, Any],
                    vault: SecretVault | None = None) -> "OpenAICompatAdapter":
        timeout = float(config.get("timeout", 120))
        return cls(
            chat_url=str(config.get("chat_url", DEFAULT_CHAT_URL)),
            model=str(config.get("model", DEFAULT_MODEL)),
            api_key_name=str(config.get("api_key_name", "GLM_API_KEY")),
            timeout=timeout,
            temperature=float(config.get("temperature", 0.4)),
            max_retries=int(config.get("max_retries", 3)),
            _vault=vault,
            _poster=aiohttp_poster(timeout))

    def _api_key(self) -> str | None:
        if self._vault is not None:
            return self._vault.get(self.api_key_name)
        import os
        return os.environ.get(self.api_key_name, "").strip() or None

    # ------------------------------------------------------------------- chat
    async def chat(self, messages, *, temperature=None, max_tokens=None,
                   json_mode=False) -> AdapterResponse:
        api_key = self._api_key()
        if not api_key:
            raise RemoteNotConfigured(
                f"no API key: set the {self.api_key_name} environment "
                f"variable or vault entry")

        payload: dict[str, Any] = {
            "model": self.model, "messages": messages, "stream": False,
            "temperature": self.temperature if temperature is None
            else temperature,
        }
        if max_tokens:
            payload["max_tokens"] = int(max_tokens)
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {api_key}",
                   "Content-Type": "application/json"}

        started = time.monotonic()
        last_error: Exception | None = None
        body: dict | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                body = await self._poster(self.chat_url, headers, payload)
                break
            except PermissionError:
                raise                      # 401: retrying cannot help
            except ConnectionResetError as exc:
                last_error = exc
                if attempt < self.max_retries:
                    delay = 2 ** attempt + secrets.randbelow(500) / 500.0
                    logger.warning("%s HTTP issue (%s), retry %d/%d in %.1fs",
                                   self.model, exc, attempt,
                                   self.max_retries, delay)
                    import asyncio
                    await asyncio.sleep(delay)
        if body is None:
            raise RuntimeError(
                f"{self.model} failed after {self.max_retries} attempts: "
                f"{last_error}")
        return self._parse(body, started)

    def _parse(self, body: dict, started: float) -> AdapterResponse:
        try:
            choice = body["choices"][0]
            text = choice["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"malformed response: {str(body)[:200]}") \
                from exc
        if not text:
            raise RuntimeError(f"empty content: {str(body)[:200]}")
        usage = body.get("usage") or {}
        return AdapterResponse(
            text=text, model=str(body.get("model", self.model)),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            elapsed_s=time.monotonic() - started)

    # ----------------------------------------------------------------- health
    async def healthy(self) -> tuple[bool, str]:
        if not self._api_key():
            return False, f"{self.api_key_name} not set"
        return True, "configured"

    async def close(self) -> None:
        closer = getattr(self._poster, "close_session", None)
        if closer is not None:
            await closer()

"""Deterministic mock adapter for tests and offline development.

Scriptable: queue replies with ``enqueue``; when the queue is empty it
answers with a deterministic function of the prompt (stable hash), so
episodes are reproducible without any network.
"""

from __future__ import annotations

import hashlib
import json
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from brain.adapters.base import AdapterResponse, ChatAdapter


@dataclass
class MockAdapter(ChatAdapter):
    name: str = "mock"
    model: str = "mock-1"
    fail_next: int = 0                      # fail N calls before answering
    replies: deque = field(default_factory=deque)
    calls: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "MockAdapter":
        return cls(model=str(config.get("model", "mock-1")))

    def enqueue(self, *replies: str | Exception) -> None:
        self.replies.extend(replies)

    async def chat(self, messages, *, temperature=None, max_tokens=None,
                   json_mode=False) -> AdapterResponse:
        self.calls.append({"messages": messages, "json_mode": json_mode})
        if self.fail_next > 0:
            self.fail_next -= 1
            raise RuntimeError("mock adapter: induced failure")
        if self.replies:
            reply = self.replies.popleft()
            if isinstance(reply, Exception):
                raise reply
            return AdapterResponse(text=reply, model=self.model,
                                   prompt_tokens=sum(
                                       len(m.get("content", "")) for m in messages),
                                   completion_tokens=len(reply))
        return AdapterResponse(
            text=self._derive(messages, json_mode), model=self.model,
            prompt_tokens=sum(len(m.get("content", "")) for m in messages),
            completion_tokens=32)

    def _derive(self, messages, json_mode: bool) -> str:
        digest_input = json.dumps(messages, sort_keys=True,
                                  ensure_ascii=False)
        seed = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()[:8]
        last_user = next((m["content"] for m in reversed(messages)
                          if m.get("role") == "user"), "")
        if json_mode:
            return json.dumps({"seed": seed, "echo": last_user[:120]})
        return f"[mock:{seed}] {last_user[:120]}"

    async def healthy(self) -> tuple[bool, str]:
        return True, "mock always healthy"

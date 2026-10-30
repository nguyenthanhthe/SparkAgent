"""In-process pub/sub event bus.

Channels in use:
  ``logs``   — formatted log lines (streamed to the web dashboard via SSE)
  ``audit``  — security/audit events (persisted to SQLite by the daemon)
  ``status`` — heartbeat snapshots (GPU/RAM/brain health)
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

logger = logging.getLogger("sparkagent.bus")


class EventBus:
    """Fan-out publish/subscribe with bounded queues and drop-oldest overflow."""

    def __init__(self, maxsize: int = 500):
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        self._maxsize = maxsize
        self._loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------------ setup
    def bind_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Remember the running loop so any thread can publish safely."""
        self._loop = loop

    def subscribe(self, channel: str) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue(maxsize=self._maxsize)
        self._subscribers.setdefault(channel, set()).add(queue)
        return queue

    def unsubscribe(self, channel: str, queue: asyncio.Queue) -> None:
        self._subscribers.get(channel, set()).discard(queue)

    def subscriber_count(self, channel: str | None = None) -> int:
        """Total live subscriptions, or per-channel when ``channel`` is
        given — the observability answer to "is anything even
        listening?" (e.g. an SSE stream against the audit channel)."""
        if channel is not None:
            return len(self._subscribers.get(channel, ()))
        return sum(len(queues) for queues in self._subscribers.values())

    # ---------------------------------------------------------------- publish
    def publish(self, channel: str, data: Any) -> None:
        """Publish from inside the event loop thread."""
        for queue in list(self._subscribers.get(channel, ())):
            self._offer(queue, data)

    def publish_threadsafe(self, channel: str, data: Any) -> None:
        """Publish from any thread; drops the event if no loop is bound yet."""
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        try:
            loop.call_soon_threadsafe(self.publish, channel, data)
        except RuntimeError:
            pass  # loop shutting down

    def _offer(self, queue: asyncio.Queue, data: Any) -> None:
        try:
            queue.put_nowait(data)
        except asyncio.QueueFull:
            try:
                queue.get_nowait()  # drop the oldest entry
                queue.put_nowait(data)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                pass

    # ---------------------------------------------------------------- helpers
    def reader(self, channel: str) -> "BusReader":
        return BusReader(self, channel)


class BusReader:
    """Async iterator + context manager over a bus subscription."""

    def __init__(self, bus: EventBus, channel: str):
        self._bus = bus
        self._channel = channel
        self._queue: asyncio.Queue | None = None

    async def __aenter__(self) -> "BusReader":
        self._queue = self._bus.subscribe(self._channel)
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        if self._queue is not None:
            self._bus.unsubscribe(self._channel, self._queue)

    async def get(self) -> Any:
        if self._queue is None:
            raise RuntimeError("BusReader used outside of 'async with'")
        return await self._queue.get()


AuditFn = Callable[[str, str, str], Any]


async def audit(bus: EventBus, actor: str, action: str, detail: str) -> None:
    """Publish an audit event; the daemon task persists these to SQLite."""
    bus.publish("audit", {"actor": actor, "action": action, "detail": detail})

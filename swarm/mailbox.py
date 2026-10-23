"""Mailbox — bounded per-agent queues with topic filtering.

Agents pull messages addressed to them (or broadcast topics they care
about). Overflow drops the OLDEST message and counts it, so a stuck agent
degrades loudly instead of leaking memory.
"""

from __future__ import annotations

import asyncio
from collections import deque

from kernel.logging import get_logger
from swarm.protocols import AgentMessage, MessageKind

logger = get_logger("swarm.mailbox")


class Mailbox:
    def __init__(self, capacity: int = 200):
        self.capacity = capacity
        self._queues: dict[str, deque] = {}
        self._events: dict[str, asyncio.Event] = {}
        self._dropped = 0
        self._sent = 0

    # ----------------------------------------------------------------- setup
    def register(self, agent_name: str) -> None:
        self._queues.setdefault(agent_name, deque(maxlen=self.capacity))
        self._events.setdefault(agent_name, asyncio.Event())

    def registered(self) -> list[str]:
        return sorted(self._queues)

    # ------------------------------------------------------------------ send
    def deliver(self, message: AgentMessage, to: str) -> bool:
        queue = self._queues.get(to)
        if queue is None:
            logger.debug("mailbox: no agent %r for message %s", to, message.id)
            return False
        if len(queue) >= self.capacity:
            queue.popleft()          # drop oldest under pressure
            self._dropped += 1
        queue.append(message)
        self._sent += 1
        event = self._events.get(to)
        if event is not None:
            event.set()
        return True

    def broadcast(self, message: AgentMessage,
                  skip: str | None = None) -> int:
        delivered = 0
        for name in self._queues:
            if name != skip:
                delivered += int(self.deliver(message, name))
        return delivered

    # ------------------------------------------------------------------ recv
    async def receive(self, agent_name: str,
                      timeout: float | None = None) -> AgentMessage | None:
        """Await the next message for ``agent_name``; None on timeout."""
        queue = self._queues.get(agent_name)
        if queue is None:
            raise KeyError(f"agent {agent_name!r} not registered")
        event = self._events[agent_name]
        while True:
            if queue:
                return queue.popleft()
            if timeout is not None:
                try:
                    await asyncio.wait_for(event.wait(), timeout)
                except asyncio.TimeoutError:
                    return None
            else:
                await event.wait()
            event.clear()

    def try_receive(self, agent_name: str) -> AgentMessage | None:
        queue = self._queues.get(agent_name)
        if queue is None:
            raise KeyError(f"agent {agent_name!r} not registered")
        return queue.popleft() if queue else None

    def pending(self, agent_name: str) -> int:
        queue = self._queues.get(agent_name)
        return len(queue) if queue else 0

    # ----------------------------------------------------------------- stats
    def stats(self) -> dict[str, int]:
        return {"sent": self._sent, "dropped": self._dropped,
                "agents": len(self._queues)}

"""Rate limiting primitives.

``TokenBucket`` — classic bounded burst + steady refill, injectable clock,
O(1) take. ``RateLimiterSet`` — named buckets under one roof (per-source
quotas). ``ConcurrencyGuard`` — max-in-flight slots for async work.
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field

from kernel.clock import Clock
from kernel.errors import RateLimitedError


@dataclass
class TokenBucket:
    capacity: float
    refill_per_second: float
    clock: Clock = field(default_factory=Clock)
    tokens: float | None = None

    def __post_init__(self) -> None:
        if self.capacity <= 0 or self.refill_per_second <= 0:
            raise ValueError("capacity and refill must be positive")
        if self.tokens is None:
            self.tokens = float(self.capacity)
        self._last = self.clock.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = self.clock.monotonic()
        elapsed = max(0.0, now - self._last)
        self._last = now
        self.tokens = min(self.capacity, self.tokens + elapsed *
                          self.refill_per_second)

    def try_take(self, amount: float = 1.0) -> bool:
        with self._lock:
            self._refill()
            if self.tokens >= amount:
                self.tokens -= amount
                return True
            return False

    def take(self, amount: float = 1.0) -> float:
        """Take tokens or raise RateLimitedError with the wait time."""
        with self._lock:
            self._refill()
            if self.tokens >= amount:
                self.tokens -= amount
                return 0.0
            deficit = amount - self.tokens
            wait = deficit / self.refill_per_second
        raise RateLimitedError(
            f"rate limit: need {amount:.2f} tokens, wait {wait:.2f}s",
            retry_after=wait)

    def peek(self) -> float:
        with self._lock:
            self._refill()
            return self.tokens


class RateLimiterSet:
    """Named token buckets (e.g. one per source or per tool)."""

    def __init__(self, capacity: float, refill_per_second: float,
                 clock: Clock | None = None):
        self.capacity = capacity
        self.refill_per_second = refill_per_second
        self.clock = clock or Clock()
        self._buckets: dict[str, TokenBucket] = {}

    def bucket(self, name: str) -> TokenBucket:
        bucket = self._buckets.get(name)
        if bucket is None:
            bucket = TokenBucket(self.capacity, self.refill_per_second,
                                 clock=self.clock)
            self._buckets[name] = bucket
        return bucket

    def try_take(self, name: str, amount: float = 1.0) -> bool:
        return self.bucket(name).try_take(amount)

    def names(self) -> list[str]:
        return sorted(self._buckets)


class ConcurrencyGuard:
    """Bounded in-flight slots for async operations."""

    def __init__(self, limit: int):
        if limit < 1:
            raise ValueError("limit must be >= 1")
        self._semaphore = asyncio.Semaphore(limit)
        self._active = 0
        self._peak = 0
        self._limit = limit

    async def __aenter__(self) -> "ConcurrencyGuard":
        await self._semaphore.acquire()
        self._active += 1
        self._peak = max(self._peak, self._active)
        return self

    async def __aexit__(self, *_exc) -> None:
        self._active -= 1
        self._semaphore.release()

    @property
    def stats(self) -> dict[str, int]:
        return {"active": self._active, "peak": self._peak, "limit": self._limit}

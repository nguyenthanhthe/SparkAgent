"""Generic async retry with exponential backoff and jitter.

Policy is declarative (attempts, base delay, cap, which exceptions count),
clock-injectable for deterministic tests, and respects ``retryable`` /
``retry_after`` from :mod:`kernel.errors`.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Type, TypeVar

from kernel.clock import Clock
from kernel.errors import RateLimitedError, SparkError

T = TypeVar("T")


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 3
    base_delay: float = 0.5
    max_delay: float = 30.0
    multiplier: float = 2.0
    jitter: bool = True
    retry_on: tuple[Type[BaseException], ...] = (Exception,)

    def delay_for(self, attempt: int) -> float:
        """Equal jitter: half fixed + half random, always within
        [0.5x, 1.0x] of the exponential backoff."""
        raw = min(self.max_delay, self.base_delay * self.multiplier ** attempt)
        if self.jitter:
            raw = raw * 0.5 + secrets_uniform(0.0, 1.0) * raw * 0.5
        return raw


def secrets_uniform(low: float, high: float) -> float:
    import secrets
    return low + (secrets.randbelow(1_000_000) / 1_000_000) * (high - low)


@dataclass
class RetryResult:
    value: Any = None
    attempts: int = 0
    errors: list[str] = field(default_factory=list)
    succeeded: bool = False

    def note(self, exc: BaseException) -> None:
        self.errors.append(f"{type(exc).__name__}: {exc}")


async def call_with_retry(fn: Callable[..., Awaitable[T]],
                          *args: Any,
                          policy: RetryPolicy | None = None,
                          clock: Clock | None = None,
                          sleep: Callable[[float], Awaitable[None]] | None = None,
                          **kwargs: Any) -> T:
    """Invoke ``fn`` under ``policy``; re-raise the last failure when spent.

    Retries immediately-respectful of ``RateLimitedError.retry_after`` and
    ``SparkError.retryable`` (non-retryable errors abort without burning
    the remaining attempts).
    """
    policy = policy or RetryPolicy()
    clock = clock or Clock()
    sleep = sleep or clock.sleep
    result = RetryResult()
    last_exc: BaseException | None = None

    for attempt in range(policy.attempts):
        result.attempts = attempt + 1
        try:
            value = await fn(*args, **kwargs)
            result.value, result.succeeded = value, True
            return value
        except policy.retry_on as exc:
            last_exc = exc
            result.note(exc)
            if isinstance(exc, SparkError) and not exc.retryable:
                raise
            if attempt == policy.attempts - 1:
                raise
            delay = policy.delay_for(attempt)
            if isinstance(exc, RateLimitedError):
                delay = max(delay, exc.retry_after)
            await sleep(delay)
    raise last_exc  # pragma: no cover — loop always raises or returns


class RetryBudget:
    """Tracks retry statistics per operation name for dashboards."""

    def __init__(self) -> None:
        self._stats: dict[str, dict[str, int]] = {}

    def record(self, name: str, *, success: bool, attempts: int) -> None:
        entry = self._stats.setdefault(name, {"calls": 0, "retries": 0,
                                              "exhausted": 0})
        entry["calls"] += 1
        entry["retries"] += max(0, attempts - 1)
        if not success:
            entry["exhausted"] += 1

    def snapshot(self) -> dict[str, dict[str, int]]:
        return {name: dict(stats) for name, stats in self._stats.items()}

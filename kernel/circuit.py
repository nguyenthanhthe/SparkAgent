"""Circuit breaker for flaky dependencies (LLM tiers, tools, remotes).

States: CLOSED (normal) -> OPEN (failure threshold tripped, calls fail
fast) -> HALF_OPEN (probe window). Configurable thresholds and reset
timeout; injectable clock for tests. Thread-safe via a lock; async call
sites use ``call``.
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Awaitable, Callable, TypeVar

from kernel.clock import Clock
from kernel.errors import SparkError

T = TypeVar("T")


class CircuitOpenError(SparkError):
    """Raised while the circuit is OPEN — callers should fail over."""

    def __init__(self, name: str, remaining: float):
        super().__init__(f"circuit {name!r} is open for {remaining:.1f}s more",
                         retryable=True)
        self.remaining = remaining


class State(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    name: str
    failure_threshold: int = 5
    reset_timeout: float = 60.0
    half_open_successes: int = 2
    clock: Clock = field(default_factory=Clock)

    def __post_init__(self) -> None:
        self._lock = threading.Lock()
        self._state = State.CLOSED
        self._failures = 0
        self._opened_at = 0.0
        self._half_open_wins = 0
        self.metrics = {"rejected": 0, "failures": 0, "successes": 0,
                        "state_changes": 0}

    # ------------------------------------------------------------------ state
    @property
    def state(self) -> State:
        with self._lock:
            return self._probe_state()

    def _probe_state(self) -> State:
        # caller must hold the lock
        if self._state is State.OPEN:
            if self.clock.monotonic() - self._opened_at >= self.reset_timeout:
                self._transition(State.HALF_OPEN)
                self._half_open_wins = 0
        return self._state

    def _transition(self, new_state: State) -> None:
        self._state = new_state
        self.metrics["state_changes"] += 1

    # ----------------------------------------------------------------- checks
    def acquire(self) -> None:
        """Raise CircuitOpenError unless a call may proceed."""
        with self._lock:
            self._probe_state()
            if self._state is State.OPEN:
                elapsed = self.clock.monotonic() - self._opened_at
                remaining = self.reset_timeout - elapsed
                self.metrics["rejected"] += 1
                raise CircuitOpenError(self.name, remaining)

    def record_success(self) -> None:
        with self._lock:
            self.metrics["successes"] += 1
            if self._state is State.HALF_OPEN:
                self._half_open_wins += 1
                if self._half_open_wins >= self.half_open_successes:
                    self._failures = 0
                    self._transition(State.CLOSED)
            else:
                self._failures = 0

    def record_failure(self) -> None:
        with self._lock:
            self.metrics["failures"] += 1
            if self._state is State.HALF_OPEN:
                self._trip()
                return
            self._failures += 1
            if self._failures >= self.failure_threshold:
                self._trip()

    def _trip(self) -> None:
        self._opened_at = self.clock.monotonic()
        self._transition(State.OPEN)

    # ------------------------------------------------------------------- call
    async def call(self, fn: Callable[..., Awaitable[T]], *args: Any,
                   **kwargs: Any) -> T:
        self.acquire()
        try:
            result = await fn(*args, **kwargs)
        except Exception:
            self.record_failure()
            raise
        self.record_success()
        return result

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {"name": self.name, "state": self._probe_state().value,
                    "failures": self._failures, **self.metrics}

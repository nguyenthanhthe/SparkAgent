"""Injectable time sources.

Any component that schedules, times out, or expires takes a ``Clock`` so
unit tests drive time manually instead of sleeping — the suite stays fast
and deterministic (see TokenBucket/RetryPolicy/ExpiringCache tests).
"""

from __future__ import annotations

import time
from typing import Callable


class Clock:
    """Real-time source; the default everywhere."""

    def now(self) -> float:
        return time.time()

    def monotonic(self) -> float:
        return time.monotonic()

    async def sleep(self, seconds: float) -> None:
        import asyncio
        await asyncio.sleep(seconds)


class FakeClock(Clock):
    """Manual clock: ``advance()`` moves both walls; ``sleep`` yields once."""

    def __init__(self, start: float = 1_000_000.0):
        self._wall = start
        self._mono = 0.0

    def now(self) -> float:
        return self._wall

    def monotonic(self) -> float:
        return self._mono

    def advance(self, seconds: float) -> float:
        self._wall += seconds
        self._mono += seconds
        return self._wall

    async def sleep(self, seconds: float) -> None:
        self.advance(max(0.0, seconds))
        import asyncio
        await asyncio.sleep(0)  # yield to the loop, no real waiting


class Stopwatch:
    """Measures elapsed monotonic time via the injected clock."""

    def __init__(self, clock: Clock | None = None):
        self.clock = clock or Clock()
        self._start = self.clock.monotonic()
        self._laps: list[tuple[str, float]] = []

    def lap(self, label: str) -> float:
        elapsed = self.clock.monotonic() - self._start
        self._laps.append((label, elapsed))
        return elapsed

    @property
    def elapsed(self) -> float:
        return self.clock.monotonic() - self._start

    def report(self) -> dict[str, float]:
        base = {"total_s": round(self.elapsed, 4)}
        base.update({label: round(t, 4) for label, t in self._laps})
        return base


def human_duration(seconds: float) -> str:
    """Render seconds as a compact human string (e.g. '1h02m', '45s', '9ms')."""
    seconds = max(0.0, float(seconds))
    if seconds < 0.001:
        return f"{seconds * 1_000_000:.0f}us"
    if seconds < 1.0:
        return f"{seconds * 1000:.0f}ms"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, sec = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m{sec:02d}s"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h{minutes:02d}m"
    days, hours = divmod(hours, 24)
    return f"{days}d{hours:02d}h"


TimeoutFactory = Callable[[], "Deadline"]


class Deadline:
    """A point in monotonic time; ask ``remaining`` until it hits zero."""

    def __init__(self, seconds: float, clock: Clock | None = None):
        self.clock = clock or Clock()
        self.expiry = self.clock.monotonic() + max(0.0, seconds)

    @property
    def remaining(self) -> float:
        return max(0.0, self.expiry - self.clock.monotonic())

    @property
    def expired(self) -> bool:
        return self.remaining <= 0

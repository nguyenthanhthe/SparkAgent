"""Health check registry for daemon subsystems.

Each subsystem registers an async check returning a :class:`HealthStatus`.
The registry runs them with a timeout and aggregates to the worst status:
any ``down`` → down; else any ``degraded`` → degraded; else ok. Exposed by
the web API and the heartbeat channel.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Awaitable, Callable

from kernel.metrics import MetricsRegistry


class Status(str, Enum):
    OK = "ok"
    DEGRADED = "degraded"
    DOWN = "down"


_LEVEL = {Status.OK: 0, Status.DEGRADED: 1, Status.DOWN: 2}


@dataclass
class HealthReport:
    name: str
    status: Status
    detail: str = ""
    elapsed_s: float = 0.0


@dataclass
class HealthStatus:
    status: Status
    detail: str = ""


CheckFn = Callable[[], Awaitable[HealthStatus]]


@dataclass
class HealthRegistry:
    timeout: float = 5.0
    registry: MetricsRegistry = field(default_factory=MetricsRegistry)

    def __post_init__(self) -> None:
        self._checks: dict[str, CheckFn] = {}

    def register(self, name: str, check: CheckFn) -> None:
        self._checks[name] = check

    def unregister(self, name: str) -> None:
        self._checks.pop(name, None)

    async def _run_one(self, name: str, check: CheckFn) -> HealthReport:
        started = time.perf_counter()
        try:
            result = await asyncio.wait_for(check(), timeout=self.timeout)
            status, detail = result.status, result.detail
        except asyncio.TimeoutError:
            status, detail = Status.DOWN, f"check timed out ({self.timeout}s)"
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — a broken check is 'down'
            status, detail = Status.DOWN, f"{type(exc).__name__}: {exc}"
        elapsed = time.perf_counter() - started
        self.registry.observe("health_check_seconds", elapsed)
        return HealthReport(name, status, detail, round(elapsed, 4))

    async def check_all(self) -> dict:
        reports = await asyncio.gather(
            *(self._run_one(name, check)
              for name, check in sorted(self._checks.items())),
            return_exceptions=False)
        worst = Status.OK
        for report in reports:
            if _LEVEL[report.status] > _LEVEL[worst]:
                worst = report.status
        self.registry.gauge("health_worst_level", _LEVEL[worst])
        return {
            "status": worst.value,
            "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "checks": [{**vars(report), "status": report.status.value}
                       for report in reports],
        }

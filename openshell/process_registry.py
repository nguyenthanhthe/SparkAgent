"""Registry of every process the executor spawns.

Gives the daemon a live view of children (for the dashboard and shutdown),
and a bounded history of completed runs (pid, program, exit, duration) so
post-mortems and audits answer "what ran when?".
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ProcessRecord:
    pid: int
    program: str
    args: str
    started_at: float = field(default_factory=time.time)

    def age_s(self) -> float:
        return time.time() - self.started_at


@dataclass
class FinishedRecord(ProcessRecord):
    exit_code: Optional[int] = None
    duration_s: float = 0.0
    timed_out: bool = False


class ProcessRegistry:
    def __init__(self, max_history: int = 1000):
        self.max_history = max_history
        self._lock = threading.Lock()
        self._live: dict[int, ProcessRecord] = {}
        self._history: list[FinishedRecord] = []
        self._seq = 0

    # ------------------------------------------------------------------- live
    def spawn(self, pid: int, program: str, args: str) -> ProcessRecord:
        with self._lock:
            record = ProcessRecord(pid=pid, program=program, args=args[:500])
            self._live[pid] = record
            return record

    def finish(self, pid: int, exit_code: int | None, timed_out: bool = False) \
            -> FinishedRecord | None:
        with self._lock:
            record = self._live.pop(pid, None)
            if record is None:
                return None
            finished = FinishedRecord(pid=record.pid, program=record.program,
                                      args=record.args,
                                      started_at=record.started_at,
                                      exit_code=exit_code,
                                      duration_s=record.age_s(),
                                      timed_out=timed_out)
            self._seq += 1
            self._history.append(finished)
            if len(self._history) > self.max_history:
                del self._history[: len(self._history) - self.max_history]
            return finished

    def live(self) -> list[dict]:
        with self._lock:
            return [{"pid": r.pid, "program": r.program, "args": r.args,
                     "age_s": round(r.age_s(), 1)}
                    for r in sorted(self._live.values(),
                                    key=lambda r: r.started_at)]

    def live_count(self) -> int:
        with self._lock:
            return len(self._live)

    # --------------------------------------------------------------- history
    def history(self, limit: int = 50) -> list[dict]:
        with self._lock:
            return [{"pid": r.pid, "program": r.program, "args": r.args,
                     "exit_code": r.exit_code, "duration_s":
                         round(r.duration_s, 2), "timed_out": r.timed_out,
                     "started_at": r.started_at}
                    for r in self._history[-limit:]]

    def stats(self) -> dict:
        with self._lock:
            total = len(self._history)
            failures = sum(1 for r in self._history if r.exit_code not in (0,))
            return {"live": len(self._live), "completed": total,
                    "failed": failures,
                    "total_duration_s": round(
                        sum(r.duration_s for r in self._history), 2)}

    def forget_older_than(self, seconds: float) -> int:
        """Drop history entries older than ``seconds`` (housekeeping)."""
        cutoff = time.time() - seconds
        with self._lock:
            keep = [r for r in self._history if r.started_at >= cutoff]
            dropped = len(self._history) - len(keep)
            self._history = keep
            return dropped

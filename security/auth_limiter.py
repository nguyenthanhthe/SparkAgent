"""Auth-attempt rate limiting for the web API.

Tracks failed token authentications per client (remote address). After
``max_failures`` within ``window_seconds``, the client is locked out for
``lockout_seconds`` and receives 429 responses — blunting online token
guessing against the Bearer check in ``interface/web.py``. Successful
authentications reset the failure count.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from typing import Callable


class AuthRateLimiter:
    def __init__(self, max_failures: int = 10, window_seconds: float = 300.0,
                 lockout_seconds: float = 300.0,
                 clock: Callable[[], float] | None = None):
        self.max_failures = max_failures
        self.window = window_seconds
        self.lockout = lockout_seconds
        self._now = clock or time.monotonic
        self._lock = threading.Lock()
        # client -> (deque[failure timestamps], locked_out_until)
        self._clients: dict[str, tuple[deque[float], float]] = {}
        self.stats = {"locked_now": 0, "lockouts_issued": 0,
                      "failures_recorded": 0}

    # ------------------------------------------------------------------- api
    def allowed(self, client_id: str) -> bool:
        """True when the client may attempt authentication now. An
        expired lockout clears the client's state on read — no new
        failures are needed for the lockout to age out."""
        with self._lock:
            entry = self._clients.get(client_id)
            if entry is None:
                return True
            _, locked_until = entry
            if locked_until and self._now() < locked_until:
                return False
            if locked_until:
                del self._clients[client_id]
            return True

    def retry_after(self, client_id: str) -> float:
        """Seconds until the client's lockout lifts (0 if not locked)."""
        with self._lock:
            entry = self._clients.get(client_id)
            if entry is None:
                return 0.0
            _, locked_until = entry
            if not locked_until:
                return 0.0
            return max(0.0, round(locked_until - self._now(), 1))

    def record_failure(self, client_id: str) -> None:
        now = self._now()
        with self._lock:
            failures, locked_until = self._clients.get(
                client_id, (deque(), 0.0))
            if locked_until and now < locked_until:
                return  # already locked; nothing new to count
            failures.append(now)
            self._prune(failures, now)
            self.stats["failures_recorded"] += 1
            if len(failures) >= self.max_failures:
                self._clients[client_id] = (failures, now + self.lockout)
                self.stats["lockouts_issued"] += 1
            else:
                self._clients[client_id] = (failures, 0.0)

    def record_success(self, client_id: str) -> None:
        with self._lock:
            self._clients.pop(client_id, None)

    def snapshot(self) -> dict:
        now = self._now()
        with self._lock:
            locked = sum(1 for _, (_, until) in self._clients.items()
                         if until and now < until)
            self.stats["locked_now"] = locked
            return {**self.stats,
                    "max_failures": self.max_failures,
                    "window_seconds": self.window,
                    "lockout_seconds": self.lockout}

    # -------------------------------------------------------------- internals
    def _prune(self, failures: deque[float], now: float) -> None:
        while failures and now - failures[0] > self.window:
            failures.popleft()

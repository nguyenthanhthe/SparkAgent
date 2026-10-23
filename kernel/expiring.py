"""Generic TTL cache with a max-size bound and lazy eviction.

Used for health snapshots, veto results, DNS checks — anything where a
short-lived value beats recomputation. Clock-injectable for tests; sweep
on write keeps read paths lock-cheap.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Callable

from kernel.clock import Clock


@dataclass
class _Entry:
    value: Any
    expires_at: float


class ExpiringCache:
    def __init__(self, ttl_seconds: float = 60.0, max_entries: int = 256,
                 clock: Clock | None = None):
        if ttl_seconds <= 0:
            raise ValueError("ttl must be positive")
        self.ttl = ttl_seconds
        self.max_entries = max_entries
        self.clock = clock or Clock()
        self._lock = threading.Lock()
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self.stats = {"hits": 0, "misses": 0, "evictions": 0, "expirations": 0}

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self.stats["misses"] += 1
                return None
            if self.clock.now() >= entry.expires_at:
                del self._entries[key]
                self.stats["expirations"] += 1
                self.stats["misses"] += 1
                return None
            self._entries.move_to_end(key)
            self.stats["hits"] += 1
            return entry.value

    def put(self, key: str, value: Any, ttl: float | None = None) -> None:
        expires = self.clock.now() + (ttl or self.ttl)
        with self._lock:
            self._entries[key] = _Entry(value, expires)
            self._entries.move_to_end(key)
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
                self.stats["evictions"] += 1

    def get_or_compute(self, key: str, compute: Callable[[], Any],
                        ttl: float | None = None) -> Any:
        value = self.get(key)
        if value is not None:
            return value
        value = compute()
        self.put(key, value, ttl)
        return value

    def invalidate(self, key: str) -> bool:
        with self._lock:
            return self._entries.pop(key, None) is not None

    def clear(self) -> int:
        with self._lock:
            count = len(self._entries)
            self._entries.clear()
            return count

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def snapshot(self) -> dict:
        return {**self.stats, "size": len(self), "ttl_s": self.ttl,
                "max_entries": self.max_entries}

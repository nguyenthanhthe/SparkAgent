"""Blackboard — shared, versioned knowledge store for a swarm.

Sections are namespaces (findings, decisions, constraints, scratch).
Writes bump a global revision; readers can fetch deltas since their last
seen revision, and section entries are (value, author, timestamp) tuples
so provenance survives synthesis.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field


@dataclass
class Entry:
    value: str
    author: str
    created_at: float = field(default_factory=time.time)


class Blackboard:
    def __init__(self):
        self._lock = threading.Lock()
        self._sections: dict[str, dict[str, Entry]] = {}
        self._revision = 0

    # ------------------------------------------------------------------ write
    def put(self, section: str, key: str, value: str, author: str = "?") -> int:
        if not section or not key:
            raise ValueError("section and key must be non-empty")
        with self._lock:
            bucket = self._sections.setdefault(section, {})
            bucket[key] = Entry(value=str(value)[:4000], author=author)
            self._revision += 1
            return self._revision

    def remove(self, section: str, key: str) -> bool:
        with self._lock:
            bucket = self._sections.get(section)
            if not bucket or key not in bucket:
                return False
            del bucket[key]
            self._revision += 1
            return True

    # ------------------------------------------------------------------- read
    def get(self, section: str, key: str) -> str | None:
        with self._lock:
            entry = self._sections.get(section, {}).get(key)
            return entry.value if entry else None

    def section(self, section: str) -> dict[str, str]:
        with self._lock:
            bucket = self._sections.get(section, {})
            return {key: entry.value for key, entry in bucket.items()}

    def sections(self) -> list[str]:
        with self._lock:
            return sorted(self._sections)

    @property
    def revision(self) -> int:
        with self._lock:
            return self._revision

    def changes_since(self, revision: int) -> dict:
        """Cheap delta protocol: full snapshot + flag (swarms are small)."""
        with self._lock:
            return {"changed": self._revision != revision,
                    "revision": self._revision,
                    "snapshot": {name: {k: e.value for k, e in bucket.items()}
                                 for name, bucket in self._sections.items()}}

    def digest(self) -> dict:
        with self._lock:
            return {"sections": {name: len(bucket)
                                 for name, bucket in self._sections.items()},
                    "revision": self._revision,
                    "total_entries": sum(len(b) for b in
                                         self._sections.values())}

"""LLM response cache.

Identical (model, messages, params) requests hit an in-process LRU with
TTL. Big win for repeated tool-schema-heavy prompts and idempotent queries;
always bypassable per call. Hit rate and token savings feed the dashboard.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

from kernel.logging import get_logger

logger = get_logger("brain.cache")

from kernel.clock import Clock


def cache_key(model: str, messages: list[dict], **params: Any) -> str:
    payload = json.dumps({"model": model, "messages": messages,
                          "params": params}, sort_keys=True,
                         ensure_ascii=False, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class CacheEntry:
    text: str
    usage: dict[str, Any]
    stored_at: float
    hits: int = 0


class ResponseCache:
    def __init__(self, max_entries: int = 256, ttl_seconds: float = 900.0,
                 clock: Clock | None = None):
        self.max_entries = max_entries
        self.ttl = ttl_seconds
        self.clock = clock or Clock()
        self._lock = threading.Lock()
        self._entries: OrderedDict[str, CacheEntry] = OrderedDict()
        self._hits_by_model: dict[str, int] = {}
        self._saved_by_model: dict[str, int] = {}
        self.stats = {"hits": 0, "misses": 0, "stored": 0,
                      "evictions": 0, "expired": 0,
                      "saved_tokens": 0}

    # ------------------------------------------------------------------- api
    def get(self, key: str) -> CacheEntry | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self.stats["misses"] += 1
                return None
            if self.clock.now() - entry.stored_at > self.ttl:
                del self._entries[key]
                self.stats["expired"] += 1
                self.stats["misses"] += 1
                return None
            self._entries.move_to_end(key)
            self.stats["hits"] += 1
            entry.hits += 1
            model = str(entry.usage.get("model") or "unknown")
            self._hits_by_model[model] = \
                self._hits_by_model.get(model, 0) + 1
            self.stats["saved_tokens"] += int(
                entry.usage.get("total_tokens") or 0)
            tokens = int(entry.usage.get("total_tokens") or 0)
            self._saved_by_model[model] = \
                self._saved_by_model.get(model, 0) + tokens
            return entry

    def put(self, key: str, text: str, usage: dict[str, Any] | None = None) \
            -> None:
        with self._lock:
            self._entries[key] = CacheEntry(text, dict(usage or {}),
                                            self.clock.now())
            self._entries.move_to_end(key)
            self.stats["stored"] += 1
            while len(self._entries) > self.max_entries:
                self._entries.popitem(last=False)
                self.stats["evictions"] += 1

    def invalidate(self, key: str) -> bool:
        with self._lock:
            return self._entries.pop(key, None) is not None

    def clear(self) -> int:
        with self._lock:
            count = len(self._entries)
            self._entries.clear()
        logger.debug("response cache cleared: %d entr%s evicted",
                     count, "y" if count == 1 else "ies")
        return count

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._entries)

    def hit_rate(self) -> float:
        total = self.stats["hits"] + self.stats["misses"]
        return self.stats["hits"] / total if total else 0.0

    def snapshot(self) -> dict:
        with self._lock:
            now = self.clock.now()
            ages = [now - entry.stored_at
                    for entry in self._entries.values()]
            oldest = min(ages, default=None)
            hottest = max(
                (item for item in self._entries.items() if item[1].hits > 0),
                key=lambda item: item[1].hits, default=None)
            hottest_key = ({"key_hash": hashlib.sha256(
                                hottest[0].encode("utf-8")).hexdigest()[:12],
                            "hits": hottest[1].hits}
                           if hottest else None)
        avg_age = (round(sum(ages) / len(ages), 1) if ages else None)
        total_hits = sum(self._hits_by_model.values())
        return {**self.stats, "size": self.size,
                "hit_rate": round(self.hit_rate(), 3),
                "oldest_entry_age_s": (round(oldest, 1)
                                       if oldest is not None else None),
                "average_entry_age_s": avg_age,
                "hottest_key": hottest_key,
                "hits_by_model": dict(sorted(
                    self._hits_by_model.items(),
                    key=lambda item: -item[1])),
                # share of all cache hits each model represents — misses
                # are not attributable to a model (the lookup happens
                # before routing), so this is a hits split, not a rate
                "hit_share_by_model": {
                    model: round(hits / total_hits, 3)
                    for model, hits in sorted(self._hits_by_model.items(),
                                              key=lambda item: -item[1])},
                "saved_tokens_by_model": dict(sorted(
                    self._saved_by_model.items(),
                    key=lambda item: -item[1]))}

    def top_hits(self, limit: int = 5) -> list[dict]:
        """Most-hit live entries, keyed by a digest of the cache key
        (never the messages themselves)."""
        with self._lock:
            now = self.clock.now()
            ranked = sorted(
                (entry for entry in self._entries.items()
                 if entry[1].hits > 0),
                key=lambda item: item[1].hits, reverse=True)[:limit]
            return [{"key_hash": hashlib.sha256(
                        key.encode("utf-8")).hexdigest()[:12],
                     "hits": entry.hits,
                     "age_s": round(now - entry.stored_at, 1),
                     "chars": len(entry.text)}
                    for key, entry in ranked]

"""Trend demo: the cache hit-rate trend across snapshot windows.

Each snapshot() call closes a window; the trend compares the window's
hit rate against the previous window's — the same field /api/brain
serves in its cache section.

    python examples/hit_rate_trend_demo.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from brain.cache import ResponseCache   # noqa: E402


def main() -> None:
    cache = ResponseCache(ttl_seconds=10_000)
    cache.put("a", "text", {"model": "m"})
    cache.put("b", "text", {"model": "m"})

    # window 1: one hit, one miss -> rate 0.5, no prior window yet
    cache.get("a")
    cache.get("missing")
    snap = cache.snapshot()
    print(f"window 1: rate={snap['hit_rate']} trend={snap['hit_rate_trend']}")

    # window 2: all hits -> trend improves
    cache.get("a")
    cache.get("b")
    snap = cache.snapshot()
    print(f"window 2: rate={snap['hit_rate']} trend={snap['hit_rate_trend']}")

    # window 3: all misses -> trend drops
    cache.get("nope")
    cache.get("nada")
    snap = cache.snapshot()
    print(f"window 3: rate={snap['hit_rate']} trend={snap['hit_rate_trend']}")


if __name__ == "__main__":
    main()

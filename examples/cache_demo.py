"""Response cache demo: put, hit, and TTL expiry across a fake clock.

Uses the real ResponseCache with an injected FakeClock so the TTL
boundary is deterministic: a stored entry serves repeats, ages out at
the TTL, and the stats tell the story.

    python examples/cache_demo.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from brain.cache import ResponseCache   # noqa: E402
from kernel.clock import FakeClock   # noqa: E402


def main() -> None:
    clock = FakeClock()
    cache = ResponseCache(max_entries=4, ttl_seconds=60, clock=clock)

    cache.put("k1", "answer one", {"model": "glm-5.3", "total_tokens": 42})
    print(f"stored  : size={cache.size}")

    first = cache.get("k1")
    second = cache.get("k1")
    print(f"hits    : {first.text!r} then {second.text!r} "
          f"(hits={cache.stats['hits']})")

    clock.advance(61)                       # past ttl_seconds=60
    print(f"expired : get -> {cache.get('k1')} "
          f"(expired={cache.stats['expired']}, "
          f"hit_rate={cache.hit_rate():.2f})")

    cache.put("k2", "fresh answer", {"model": "glm-5.3"})
    snapshot = cache.snapshot()
    print(f"snapshot: size={snapshot['size']} "
          f"oldest_age={snapshot['oldest_entry_age_s']}s "
          f"hits_by_model={snapshot['hits_by_model']}")


if __name__ == "__main__":
    main()

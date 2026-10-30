"""Response cache snapshot — hottest_key digests the most-hit entry."""

import unittest

from brain.cache import ResponseCache
from kernel.clock import FakeClock


class HottestKeyTests(unittest.TestCase):
    def test_no_hits_means_no_hottest_key(self):
        cache = ResponseCache(clock=FakeClock())
        cache.put("k", "text", {"model": "m"})
        self.assertIsNone(cache.snapshot()["hottest_key"])

    def test_hottest_key_is_the_most_hit_entry(self):
        cache = ResponseCache(clock=FakeClock())
        cache.put("alpha", "a text", {"model": "m"})
        cache.put("beta", "b text", {"model": "m"})
        for _ in range(3):
            cache.get("alpha")
        cache.get("beta")

        import hashlib
        hottest = cache.snapshot()["hottest_key"]
        self.assertEqual(
            hottest["key_hash"],
            hashlib.sha256("alpha".encode()).hexdigest()[:12])
        self.assertEqual(hottest["hits"], 3)

    def test_expired_entry_leaves_the_ranking(self):
        cache = ResponseCache(ttl_seconds=10, clock=FakeClock())
        cache.put("hot", "text", {"model": "m"})
        cache.get("hot")
        cache.clock.advance(11)   # past ttl — next get expires it
        self.assertIsNone(cache.get("hot"))
        self.assertIsNone(cache.snapshot()["hottest_key"])


if __name__ == "__main__":
    unittest.main()

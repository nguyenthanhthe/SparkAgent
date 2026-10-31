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

    def test_saved_tokens_split_per_model(self):
        cache = ResponseCache(clock=FakeClock())
        cache.put("a", "text", {"model": "big", "total_tokens": 100})
        cache.put("b", "text", {"model": "small", "total_tokens": 30})
        cache.get("a")
        cache.get("a")
        cache.get("b")
        saved = cache.snapshot()["saved_tokens_by_model"]
        self.assertEqual(saved, {"big": 200, "small": 30})
        self.assertEqual(cache.snapshot()["saved_tokens"], 230)

    def test_missing_usage_counts_under_unknown(self):
        cache = ResponseCache(clock=FakeClock())
        cache.put("k", "text", None)
        cache.get("k")
        self.assertEqual(cache.snapshot()["saved_tokens_by_model"],
                         {"unknown": 0})

    def test_average_entry_age(self):
        cache = ResponseCache(ttl_seconds=1000, clock=FakeClock())
        self.assertIsNone(cache.snapshot()["average_entry_age_s"])
        cache.put("a", "text", {"model": "m"})
        cache.clock.advance(30)
        cache.put("b", "text", {"model": "m"})
        # a is 30s old, b is 0s old -> average 15s
        self.assertEqual(cache.snapshot()["average_entry_age_s"], 15.0)

    def test_oldest_hit_age(self):
        cache = ResponseCache(ttl_seconds=1000, clock=FakeClock())
        self.assertIsNone(cache.snapshot()["oldest_hit_age_s"])
        cache.put("old", "text", {"model": "m"})
        cache.clock.advance(50)
        cache.put("new", "text", {"model": "m"})
        cache.get("new")     # the only served answer is 0s old
        self.assertEqual(cache.snapshot()["oldest_hit_age_s"], 0.0)
        cache.get("old")     # now the stale one gets a hit too
        self.assertEqual(cache.snapshot()["oldest_hit_age_s"], 50.0)

    def test_hit_rate_trend(self):
        cache = ResponseCache(clock=FakeClock())
        # first snapshot: no prior window -> no trend
        cache.put("k", "text", {"model": "m"})
        cache.get("k")
        self.assertIsNone(cache.snapshot()["hit_rate_trend"])
        # second window identical rate -> trend 0.0
        cache.get("k")
        self.assertEqual(cache.snapshot()["hit_rate_trend"], 0.0)
        # third window all misses -> trend drops by the prior rate
        trend = cache.snapshot()["hit_rate_trend"]
        self.assertEqual(trend, -1.0)

    def test_hit_share_per_model(self):
        cache = ResponseCache(clock=FakeClock())
        cache.put("a", "text", {"model": "big"})
        cache.put("b", "text", {"model": "small"})
        cache.get("a")
        cache.get("a")
        cache.get("a")
        cache.get("b")
        share = cache.snapshot()["hit_share_by_model"]
        self.assertEqual(share, {"big": 0.75, "small": 0.25})
        # no hits -> empty split, not an error
        empty = ResponseCache(clock=FakeClock())
        self.assertEqual(empty.snapshot()["hit_share_by_model"], {})


if __name__ == "__main__":
    unittest.main()

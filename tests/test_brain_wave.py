import unittest

from brain.cache import ResponseCache, cache_key
from brain.context import (ContextBudget, Part, estimate_messages,
                           estimate_tokens, summarize_scratchpad)
from brain.cost import CostTracker, price_for
from kernel.clock import FakeClock


class ResponseCacheTests(unittest.TestCase):
    def test_put_get_roundtrip(self):
        cache = ResponseCache()
        key = cache_key("m", [{"role": "user", "content": "hi"}])
        cache.put(key, "answer", {"total_tokens": 10})
        entry = cache.get(key)
        self.assertEqual(entry.text, "answer")
        self.assertEqual(entry.usage, {"total_tokens": 10})

    def test_miss_and_hit_stats(self):
        cache = ResponseCache()
        cache.get("absent")
        key = cache_key("m", [])
        cache.put(key, "x")
        cache.get(key)
        self.assertEqual(cache.stats["misses"], 1)
        self.assertEqual(cache.stats["hits"], 1)
        self.assertEqual(cache.stats["saved_tokens"], 0)  # no tokens in usage

    def test_ttl_expiry(self):
        clock = FakeClock()
        cache = ResponseCache(ttl_seconds=10, clock=clock)
        key = cache_key("m", [])
        cache.put(key, "x", {"total_tokens": 5})
        clock.advance(11)
        self.assertIsNone(cache.get(key))
        self.assertEqual(cache.stats["expired"], 1)

    def test_lru_eviction(self):
        cache = ResponseCache(max_entries=3)
        for i in range(5):
            cache.put(f"k{i}", str(i))
        self.assertEqual(cache.size, 3)
        self.assertGreaterEqual(cache.stats["evictions"], 2)
        self.assertIsNone(cache.get("k0"))
        self.assertIsNotNone(cache.get("k4"))

    def test_key_sensitivity(self):
        a = cache_key("m", [{"role": "user", "content": "hi"}], temp=0.1)
        b = cache_key("m", [{"role": "user", "content": "hi"}], temp=0.2)
        c = cache_key("other", [{"role": "user", "content": "hi"}], temp=0.1)
        self.assertNotEqual(a, b)
        self.assertNotEqual(a, c)

    def test_hit_rate_and_snapshot(self):
        cache = ResponseCache()
        cache.get("a")            # miss
        cache.put("b", "x")
        cache.get("b")            # hit
        snap = cache.snapshot()
        self.assertEqual(snap["hit_rate"], 0.5)
        self.assertEqual(snap["size"], 1)


class CostTrackerTests(unittest.TestCase):
    def test_price_patterns(self):
        self.assertEqual(price_for("glm-5.3"), (0.60, 2.20))
        self.assertEqual(price_for("nemotron-mini"), (0.0, 0.0))
        self.assertEqual(price_for("gpt-4o-2024"), (2.50, 10.00))
        in_price, out_price = price_for("totally-unknown-model")
        self.assertGreater(in_price, 0)

    def test_record_accumulates(self):
        tracker = CostTracker()
        result = tracker.record("glm-5.3", 1_000_000, 1_000_000, tier="remote")
        self.assertAlmostEqual(result["cost_usd"], 0.60 + 2.20, places=4)
        tracker.record("glm-5.3", 0, 0, tier="remote")
        self.assertAlmostEqual(tracker.today_total(), 2.80, places=4)

    def test_local_model_free(self):
        tracker = CostTracker()
        tracker.record("nemotron-mini", 5_000_000, 5_000_000, tier="local")
        self.assertEqual(tracker.today_total(), 0.0)

    def test_cached_calls_free(self):
        tracker = CostTracker()
        tracker.record("glm-5.3", 1_000_000, 1_000_000, cached=True)
        self.assertEqual(tracker.today_total(), 0.0)

    def test_budget_guard(self):
        tracker = CostTracker()
        self.assertTrue(tracker.within_budget(1.0))
        tracker.record("glm-5.3", 2_000_000, 0)     # 1.20 USD
        self.assertFalse(tracker.within_budget(1.0))

    def test_report_shape(self):
        tracker = CostTracker()
        tracker.record("glm-5.3", 100, 100, tier="remote")
        report = tracker.report()
        self.assertIn("by_model", report)
        self.assertIn("glm-5.3", report["by_model"])
        self.assertEqual(report["by_tier"]["remote"]["calls"], 1)
        self.assertIn("total_usd", report)

    def test_estimate(self):
        tracker = CostTracker()
        self.assertAlmostEqual(
            tracker.estimate("glm-5.3", 1_000_000, 0), 0.60, places=6)


class TokenEstimateTests(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(estimate_tokens(""), 0)

    def test_approximation(self):
        text = "x" * 400
        self.assertAlmostEqual(estimate_tokens(text), 100, delta=2)

    def test_messages_overhead(self):
        messages = [{"role": "user", "content": ""}] * 3
        self.assertEqual(estimate_messages(messages), 3 * 4)  # framing only


class ContextBudgetTests(unittest.TestCase):
    def test_everything_fits_untouched(self):
        budget = ContextBudget(window_tokens=10_000)
        plan = budget.fit([
            Part("system", "sys", priority=1000, shrinkable=False),
            Part("goal", "goal text", priority=900, shrinkable=False),
            Part("memories", "remembered things", priority=300),
        ])
        self.assertTrue(plan.fits)
        self.assertEqual(len(plan.parts), 3)
        self.assertEqual(plan.dropped, [])
        self.assertEqual(plan.trimmed, [])

    def test_low_priority_trimmed_first(self):
        budget = ContextBudget(window_tokens=200, reserve_output_tokens=50)
        big_memory = "m" * 2000          # ~500 tokens alone
        plan = budget.fit([
            Part("system", "s", priority=1000, shrinkable=False),
            Part("goal", "g", priority=900, shrinkable=False),
            Part("memories", big_memory, priority=100),
        ])
        self.assertTrue(plan.fits, f"used={plan.used}")
        self.assertIn("memories", plan.trimmed)
        self.assertNotIn("goal", plan.dropped)
        self.assertNotIn("system", plan.dropped)

    def test_oversized_drops_lowest_priority(self):
        budget = ContextBudget(window_tokens=100, reserve_output_tokens=20)
        parts = [Part("system", "s" * 40, priority=1000, shrinkable=False),
                 Part("goal", "g" * 40, priority=900, shrinkable=False),
                 Part("filler", "f" * 400, priority=100),
                 Part("extra", "e" * 400, priority=50)]
        plan = budget.fit(parts)
        self.assertTrue(plan.fits, f"used={plan.used}")
        self.assertIn("extra", plan.dropped)
        self.assertNotIn("system", plan.dropped)

    def test_invalid_window_rejected(self):
        with self.assertRaises(ValueError):
            ContextBudget(window_tokens=100, reserve_output_tokens=200)

    def test_fit_messages_keeps_contract(self):
        budget = ContextBudget(window_tokens=1000, reserve_output_tokens=200)
        messages, plan = budget.fit_messages(
            system="SYSTEM CONTRACT", goal="do the thing",
            memories="some recalled notes",
            scratchpad=[{"role": "assistant", "content": "step 1"},
                        {"role": "user", "content": "obs 1"}])
        self.assertTrue(plan.fits)
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("SYSTEM CONTRACT", messages[0]["content"])
        self.assertIn("do the thing",
                      "\n".join(m["content"] for m in messages))


class ScratchpadCompressionTests(unittest.TestCase):
    def test_short_scratchpad_untouched(self):
        turns = [{"role": "assistant", "content": "a"}]
        kept, summary = summarize_scratchpad(turns, keep_last=4)
        self.assertEqual(kept, turns)
        self.assertEqual(summary, "")

    def test_long_scratchpad_compressed(self):
        turns = [{"role": "assistant", "content": f"turn {i}"}
                 for i in range(10)]
        kept, summary = summarize_scratchpad(turns, keep_last=4)
        self.assertEqual(len(kept), 5)             # summary + last 4
        self.assertIn("compressed", summary)
        self.assertIn("turn 0", summary)
        self.assertEqual(kept[-1]["content"], "turn 9")


if __name__ == "__main__":
    unittest.main()

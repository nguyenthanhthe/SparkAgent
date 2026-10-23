import unittest

from brain.adapters.mock import MockAdapter
from brain.cache import ResponseCache
from brain.cost import CostTracker
from brain.router import Tier, TierRouter
from kernel.clock import FakeClock


def make_router(adapters_by_name, order=None, **kw):
    ordered = {name: adapters_by_name[name]
               for name in (order or adapters_by_name)}
    tiers = [Tier(name, adapter, priority=i * 10)
             for i, (name, adapter) in enumerate(ordered.items())]
    return TierRouter(tiers, **kw)


class RoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_first_healthy_tier_wins(self):
        primary = MockAdapter()
        fallback = MockAdapter()
        router = make_router({"primary": primary, "fallback": fallback})
        result = await router.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(result.tier, "primary")
        self.assertEqual(len(fallback.calls), 0)

    async def test_failure_falls_through(self):
        primary = MockAdapter(fail_next=1)
        fallback = MockAdapter()
        router = make_router({"primary": primary, "fallback": fallback})
        result = await router.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(result.tier, "fallback")
        self.assertEqual(router.stats["primary"]["failures"], 1)

    async def test_all_fail_raises_with_details(self):
        router = make_router({"a": MockAdapter(fail_next=5),
                              "b": MockAdapter(fail_next=5)})
        with self.assertRaises(RuntimeError) as ctx:
            await router.chat([{"role": "user", "content": "x"}])
        self.assertIn("a:", str(ctx.exception))
        self.assertIn("b:", str(ctx.exception))

    async def test_force_pins_tier(self):
        primary, secondary = MockAdapter(), MockAdapter()
        router = make_router({"primary": primary, "secondary": secondary})
        result = await router.chat([{"role": "user", "content": "x"}],
                                   force="secondary")
        self.assertEqual(result.tier, "secondary")

    async def test_force_unknown_tier_raises(self):
        router = make_router({"a": MockAdapter()})
        with self.assertRaises(ValueError):
            await router.chat([{"role": "user", "content": "x"}],
                              force="nope")

    async def test_unhealthy_tier_skipped(self):
        class NeverReady(MockAdapter):
            async def healthy(self):
                return False, "still booting"

        router = make_router({"a": NeverReady(), "b": MockAdapter()})
        result = await router.chat([{"role": "user", "content": "x"}])
        self.assertEqual(result.tier, "b")

    async def test_veto_skips_tier(self):
        async def veto():
            return False

        router = make_router({"local": MockAdapter(), "remote": MockAdapter()})
        router.tiers[0].veto = veto          # local tier vetoed (priority 0)
        result = await router.chat([{"role": "user", "content": "x"}])
        self.assertEqual(result.tier, "remote")

    async def test_circuit_open_skips_tier(self):
        clock = FakeClock()
        flaky = MockAdapter(fail_next=99)
        router = make_router({"a": flaky, "b": MockAdapter()},
                             failure_threshold=2, reset_timeout=60,
                             clock=clock)
        for _ in range(2):
            await router.chat([{"role": "user", "content": "x"}])
        status = {t["name"]: t["circuit"]["state"]
                  for t in router.status()["tiers"]}
        self.assertEqual(status["a"], "open")
        # next chat must not even try tier a
        calls_before = len(flaky.calls)
        await router.chat([{"role": "user", "content": "x"}])
        self.assertEqual(len(flaky.calls), calls_before)

    async def test_cache_hit_skips_adapters(self):
        adapter = MockAdapter()
        cache = ResponseCache()
        router = make_router({"a": adapter}, cache=cache)
        messages = [{"role": "user", "content": "cached prompt"}]
        first = await router.chat(messages)
        second = await router.chat(messages)
        self.assertFalse(first.from_cache)
        self.assertTrue(second.from_cache)
        self.assertEqual(len(adapter.calls), 1)
        self.assertEqual(router.stats["a"]["cache_hits"], 1)

    async def test_cache_bypass(self):
        cache = ResponseCache()
        router = make_router({"a": MockAdapter()}, cache=cache)
        messages = [{"role": "user", "content": "x"}]
        await router.chat(messages)
        result = await router.chat(messages, use_cache=False)
        self.assertFalse(result.from_cache)

    async def test_cost_tracking_records(self):
        costs = CostTracker()
        adapter = MockAdapter()
        adapter.enqueue("hello world answer")
        router = make_router({"glmish": adapter}, costs=costs)
        await router.chat([{"role": "user", "content": "q"}])
        report = costs.report()
        self.assertEqual(report["by_tier"]["glmish"]["calls"], 1)

    async def test_empty_tiers_rejected(self):
        with self.assertRaises(ValueError):
            TierRouter([])

    async def test_status_shape(self):
        router = make_router({"a": MockAdapter()})
        status = router.status()
        self.assertEqual(status["tiers"][0]["name"], "a")
        self.assertIn("circuit", status["tiers"][0])
        self.assertIn("stats", status["tiers"][0])


if __name__ == "__main__":
    unittest.main()

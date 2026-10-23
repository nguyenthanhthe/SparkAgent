import unittest

from brain.bridge import Brain, Tier
from kernel.bus import EventBus
from kernel.config import Config
from openshell.vault import SecretVault
from tests.test_brain import FakeLocal, FakeRemote


def make_brain(**cfg):
    config = Config({"brain": cfg})
    brain = Brain(config, SecretVault(), EventBus())
    brain.local = FakeLocal(text="local answer")
    brain.remote = FakeRemote(text="remote answer")
    return brain


class BrainCacheTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_by_default(self):
        brain = make_brain()
        self.assertFalse(brain.cache_enabled)
        messages = [{"role": "user", "content": "same"}]
        await brain.chat(messages)
        await brain.chat(messages)
        self.assertEqual(brain.local.calls, 2)   # no cache interference

    async def test_enabled_serves_repeats(self):
        brain = make_brain(cache_responses=True)
        messages = [{"role": "user", "content": "same"}]
        first = await brain.chat(messages)
        second = await brain.chat(messages)
        self.assertEqual(first.tier, Tier.LOCAL)
        self.assertEqual(second.text, first.text)
        self.assertEqual(brain.local.calls, 1)   # second came from cache
        self.assertEqual(brain.cache_hits, 1)

    async def test_forced_calls_bypass_cache(self):
        brain = make_brain(cache_responses=True)
        messages = [{"role": "user", "content": "same"}]
        await brain.chat(messages)
        await brain.chat(messages, force=Tier.LOCAL)
        self.assertEqual(brain.local.calls, 2)

    async def test_json_mode_keys_differ(self):
        brain = make_brain(cache_responses=True)
        messages = [{"role": "user", "content": "same"}]
        await brain.chat(messages)
        await brain.chat(messages, json_mode=True)
        self.assertEqual(brain.local.calls, 2)   # different cache key

    async def test_cache_stats_visible(self):
        brain = make_brain(cache_responses=True, cache_entries=8,
                           cache_ttl=60)
        self.assertEqual(brain.cache.max_entries, 8)
        snapshot = brain.cache.snapshot()
        self.assertIn("hit_rate", snapshot)

    async def test_fallback_result_cached(self):
        # local fails, remote answers -> the remote answer is cached and
        # served next time without retrying the dead local tier
        brain = make_brain(cache_responses=True)
        brain.local = FakeLocal(error="down")
        messages = [{"role": "user", "content": "q"}]
        first = await brain.chat(messages)
        self.assertEqual(first.tier, Tier.REMOTE)
        second = await brain.chat(messages)
        self.assertEqual(second.text, "remote answer")
        self.assertEqual(brain.local.calls, 1)   # only the first attempt


if __name__ == "__main__":
    unittest.main()

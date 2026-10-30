import unittest

from brain.bridge import Brain, BrainUnavailable, Tier
from brain.local import OllamaError
from brain.remote import RemoteNotConfigured
from kernel.bus import EventBus
from kernel.config import Config
from openshell.vault import SecretVault


class FakeLocal:
    model = "fake-local"

    def __init__(self, text=None, error=None):
        self.text, self.error = text, error
        self.calls = 0

    async def chat(self, messages, **kw):
        self.calls += 1
        if self.error:
            raise OllamaError(self.error)
        return self.text

    async def healthy(self):
        return (self.error is None, "fake")

    async def close(self):
        pass


class FakeRemote:
    model = "fake-remote"

    def __init__(self, text=None, error=None):
        self.text, self.error = text, error
        self.calls = 0

    async def chat(self, messages, **kw):
        self.calls += 1
        if self.error:
            if isinstance(self.error, Exception):
                raise self.error
            raise RuntimeError(self.error)
        return self.text

    async def close(self):
        pass


def make_brain(local, remote):
    brain = Brain(Config.load(), SecretVault(), EventBus())
    brain.local = local
    brain.remote = remote
    return brain


class BridgeTests(unittest.TestCase):
    def test_local_preferred(self):
        local, remote = FakeLocal(text="local answer"), FakeRemote(text="remote")
        brain = make_brain(local, remote)
        result = self.run_async(brain.chat([{"role": "user", "content": "hi"}]))
        self.assertEqual(result.tier, Tier.LOCAL)
        self.assertEqual(result.text, "local answer")
        self.assertEqual(remote.calls, 0)

    def test_fallback_to_remote(self):
        local = FakeLocal(error="daemon down")
        remote = FakeRemote(text="remote answer")
        brain = make_brain(local, remote)
        result = self.run_async(brain.chat([{"role": "user", "content": "hi"}]))
        self.assertEqual(result.tier, Tier.REMOTE)
        self.assertEqual(result.text, "remote answer")
        self.assertEqual(local.calls, 1)

    def test_cooldown_skips_local(self):
        local = FakeLocal(error="daemon down")
        remote = FakeRemote(text="remote answer")
        brain = make_brain(local, remote)
        messages = [{"role": "user", "content": "hi"}]
        self.run_async(brain.chat(messages))
        self.run_async(brain.chat(messages))
        # two consecutive failures -> local enters cooldown, next call skips it
        self.run_async(brain.chat(messages))
        self.assertEqual(local.calls, 2)
        self.assertEqual(remote.calls, 3)

    def test_all_tiers_down_raises(self):
        brain = make_brain(FakeLocal(error="down"), FakeRemote(error="no key"))
        with self.assertRaises(BrainUnavailable):
            self.run_async(brain.chat([{"role": "user", "content": "hi"}]))

    def test_force_local_no_fallback(self):
        brain = make_brain(FakeLocal(error="down"), FakeRemote(text="r"))
        with self.assertRaises(OllamaError):
            self.run_async(brain.chat([{"role": "user", "content": "hi"}],
                                      force=Tier.LOCAL))

    def test_resource_guard_vetoes_local(self):
        async def no_vram():
            return False
        local = FakeLocal(text="local")
        remote = FakeRemote(text="remote answer")
        brain = make_brain(local, remote)
        brain.resource_guard = no_vram
        result = self.run_async(brain.chat([{"role": "user", "content": "hi"}]))
        self.assertEqual(result.tier, Tier.REMOTE)
        self.assertEqual(local.calls, 0)

    def test_stats_tracked(self):
        brain = make_brain(FakeLocal(text="ok"), FakeRemote(text="r"))
        self.run_async(brain.chat([{"role": "user", "content": "hi"}]))
        stats = brain.stats()
        self.assertEqual(stats["local"]["requests"], 1)
        self.assertEqual(stats["remote"]["requests"], 0)
        # served counts successful completions, distinct from attempts
        self.assertEqual(stats["local"]["served"], 1)

    def test_served_not_counted_on_failure(self):
        local = FakeLocal(error="daemon down")
        remote = FakeRemote(text="remote answer")
        brain = make_brain(local, remote)
        self.run_async(brain.chat([{"role": "user", "content": "hi"}]))
        stats = brain.stats()
        # bridge semantics: requests counts completed calls, failures
        # counts errors — served tracks completions alongside them
        self.assertEqual(stats["local"]["requests"], 0)
        self.assertEqual(stats["local"]["served"], 0)
        self.assertEqual(stats["local"]["failures"], 1)
        self.assertEqual(stats["remote"]["served"], 1)

    def test_tier_details_carry_served(self):
        brain = make_brain(FakeLocal(text="ok"), FakeRemote(text="r"))
        self.run_async(brain.chat([{"role": "user", "content": "hi"}]))
        details = brain.tier_details()
        self.assertEqual(details["local"]["served"], 1)
        self.assertEqual(details["remote"]["served"], 0)

    def test_health_reports_per_check_duration_ms(self):
        brain = make_brain(FakeLocal(text="ok"), FakeRemote(text="r"))
        health = self.run_async(brain.health())
        for tier in ("local", "remote"):
            self.assertIn("duration_ms", health[tier])
            self.assertGreaterEqual(health[tier]["duration_ms"], 0)

    @staticmethod
    def run_async(coro):
        import asyncio
        return asyncio.run(coro)


if __name__ == "__main__":
    unittest.main()

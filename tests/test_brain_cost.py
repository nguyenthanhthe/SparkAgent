import unittest

from brain.bridge import Brain, Tier
from kernel.bus import EventBus
from kernel.config import Config
from openshell.vault import SecretVault


class UsageLocal:
    model = "nemotron-mini"
    last_usage = {"prompt_tokens": 10, "completion_tokens": 5,
                  "total_tokens": 15}

    def __init__(self):
        self.calls = 0

    async def chat(self, messages, **kw):
        self.calls += 1
        return "local answer"

    async def close(self):
        pass


class UsageRemote:
    model = "glm-5.3-flash"
    last_usage = {"prompt_tokens": 100, "completion_tokens": 50,
                  "total_tokens": 150}

    def __init__(self):
        self.calls = 0

    async def chat(self, messages, **kw):
        self.calls += 1
        return "remote answer"

    async def close(self):
        pass


def make_brain(local, remote):
    brain = Brain(Config.load(), SecretVault(), EventBus())
    brain.local = local
    brain.remote = remote
    return brain


class BrainCostTests(unittest.TestCase):
    def test_local_chat_records_usage(self):
        brain = make_brain(UsageLocal(), UsageRemote())
        self.run_async(brain.chat([{"role": "user", "content": "hi"}]))
        report = brain.cost_report()
        row = report["by_model"]["nemotron-mini"]
        self.assertEqual(row["calls"], 1)
        self.assertEqual(row["prompt_tokens"], 10)
        self.assertEqual(row["completion_tokens"], 5)
        self.assertEqual(row["cost_usd"], 0.0)  # local model: zero price

    def test_remote_chat_records_usage(self):
        local = UsageLocal()
        local.last_usage = {}
        # force remote by disabling local
        brain = make_brain(local, UsageRemote())
        brain.local_enabled = False
        self.run_async(brain.chat([{"role": "user", "content": "hi"}]))
        row = brain.cost_report()["by_model"]["glm-5.3-flash"]
        self.assertEqual(row["calls"], 1)
        self.assertEqual(row["prompt_tokens"], 100)
        self.assertEqual(row["completion_tokens"], 50)
        self.assertGreater(row["cost_usd"], 0.0)

    def test_failed_tier_records_nothing(self):
        class Boom:
            model = "glm-5.3-flash"
            last_usage = {}

            async def chat(self, messages, **kw):
                raise RuntimeError("down")

            async def close(self):
                pass

        brain = make_brain(Boom(), Boom())
        with self.assertRaises(Exception):
            self.run_async(brain.chat([{"role": "user", "content": "hi"}]))
        self.assertEqual(brain.cost_report()["by_model"], {})

    def test_cache_hit_records_cached_call(self):
        brain = make_brain(UsageLocal(), UsageRemote())
        brain.cache_enabled = True
        messages = [{"role": "user", "content": "hi"}]
        self.run_async(brain.chat(messages))
        self.run_async(brain.chat(messages))
        row = brain.cost_report()["by_model"]["nemotron-mini"]
        self.assertEqual(row["calls"], 2)          # both calls accounted
        self.assertEqual(row["prompt_tokens"], 10)  # hit adds no tokens

    def test_cache_entry_stores_total_tokens(self):
        brain = make_brain(UsageLocal(), UsageRemote())
        brain.cache_enabled = True
        self.run_async(brain.chat([{"role": "user", "content": "hi"}]))
        (entry,) = list(brain.cache._entries.values())
        self.assertEqual(entry.usage["total_tokens"], 15)

    @staticmethod
    def run_async(coro):
        import asyncio
        return asyncio.run(coro)


if __name__ == "__main__":
    unittest.main()

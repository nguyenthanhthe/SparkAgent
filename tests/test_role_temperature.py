import unittest

from brain.bridge import Brain, BrainResponse, Tier
from kernel.bus import EventBus
from kernel.config import Config
from openshell.vault import SecretVault
from swarm.delegate import _role_fn


class TempCapturingBrain:
    def __init__(self, cfg=None):
        self.cfg = cfg
        self.calls = []

    async def chat(self, messages, force=None, temperature=None):
        self.calls.append(temperature)
        return BrainResponse(text="ok", tier=Tier.LOCAL, model="fake",
                             elapsed=0.0)


class RoleTemperatureTests(unittest.IsolatedAsyncioTestCase):
    async def test_no_config_keeps_tier_default(self):
        brain = TempCapturingBrain()
        handler = _role_fn(brain, "critic")
        await handler("goal", "context")
        self.assertEqual(brain.calls, [None])

    async def test_configured_role_temperature_passed(self):
        cfg = Config({"swarm": {"temperature": {"critic": 0.1}}})
        brain = TempCapturingBrain(cfg=cfg)
        handler = _role_fn(brain, "critic")
        await handler("goal", "context")
        self.assertEqual(brain.calls, [0.1])

    async def test_other_roles_unaffected(self):
        cfg = Config({"swarm": {"temperature": {"critic": 0.1}}})
        brain = TempCapturingBrain(cfg=cfg)
        handler = _role_fn(brain, "planner")
        await handler("goal", "context")
        self.assertEqual(brain.calls, [None])


class BrainTemperatureTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_forwards_temperature_to_client(self):
        seen = {}

        class Client:
            model = "fake"

            async def chat(self, messages, temperature=None):
                seen["temperature"] = temperature
                return "ok"

        brain = Brain(Config.load(), SecretVault(), EventBus())
        brain.local = Client()
        brain.remote = Client()
        response = await brain.chat([{"role": "user", "content": "q"}],
                                    temperature=0.9)
        self.assertEqual(response.text, "ok")
        self.assertEqual(seen["temperature"], 0.9)


if __name__ == "__main__":
    unittest.main()

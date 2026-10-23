import unittest

from brain.bridge import BrainResponse, Tier
from kernel.bus import EventBus
from kernel.errors import ToolFailure
from tools.registry import ToolContext, ToolRegistry
from swarm.delegate import register_swarm_tools


class RoleAwareBrain:
    """Offline brain: replies keyed by the system-prompt role."""

    def __init__(self, replies: dict[str, str]):
        self.replies = replies
        self.calls: list[str] = []

    async def chat(self, messages, force=None):
        system = messages[0]["content"]
        for key, reply in self.replies.items():
            if key in system:
                self.calls.append(key)
                return BrainResponse(text=reply, tier=Tier.LOCAL,
                                     model="fake", elapsed=0.0)
        return BrainResponse(text="generic answer", tier=Tier.LOCAL,
                             model="fake", elapsed=0.0)


PLANNER = RoleAwareBrain.__name__  # readability anchor


def make_registry(brain):
    registry = ToolRegistry(EventBus())
    register_swarm_tools(registry, brain)
    return registry, ToolContext(source="agent")


class SwarmToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_swarm_delegate_pipeline(self):
        brain = RoleAwareBrain({
            "PLANNER": '["step one", "step two"]',
            "WORKER": "work complete with detailed findings",
            "CRITIC": "solid overall",
            "SYNTHESIZER": "the final synthesized answer",
        })
        registry, ctx = make_registry(brain)
        result = await registry.call(
            "swarm_delegate", {"goal": "analyze the system"}, ctx)
        import json
        parsed = json.loads(result)
        self.assertTrue(parsed["ok"])
        self.assertEqual(parsed["answer"], "the final synthesized answer")
        self.assertEqual(parsed["plan"], ["step one", "step two"])
        self.assertIn("PLANNER", brain.calls)
        self.assertIn("SYNTHESIZER", brain.calls)

    async def test_delegate_planner_failure_survives(self):
        brain = RoleAwareBrain({})   # everything -> "generic answer"
        registry, ctx = make_registry(brain)
        result = await registry.call(
            "swarm_delegate", {"goal": "no plan possible"}, ctx)
        import json
        parsed = json.loads(result)
        # planner produces unparseable plan -> graceful failure
        self.assertFalse(parsed["ok"])

    async def test_debate_tool(self):
        brain = RoleAwareBrain({"debater": "position argued"})
        registry, ctx = make_registry(brain)
        result = await registry.call(
            "debate", {"question": "tabs or spaces?", "rounds": 1}, ctx)
        import json
        parsed = json.loads(result)
        self.assertIn("position argued", parsed["answer"])
        self.assertEqual(parsed["rounds"], 1)

    async def test_consensus_majority(self):
        replies = iter(["Paris", "Paris", "London"])

        class VotingBrain:
            async def chat(self, messages, force=None):
                return BrainResponse(text=next(replies), tier=Tier.LOCAL,
                                     model="fake", elapsed=0.0)

        registry, ctx = make_registry(VotingBrain())
        import json
        result = json.loads(await registry.call(
            "consensus", {"question": "capital of France?", "voters": 3},
            ctx))
        self.assertTrue(result["decided"])
        self.assertEqual(result["winner"], "Paris")

    async def test_consensus_divergence_reported(self):
        replies = iter(["a", "b", "c"])

        class DivergingBrain:
            async def chat(self, messages, force=None):
                return BrainResponse(text=next(replies), tier=Tier.LOCAL,
                                     model="fake", elapsed=0.0)

        registry, ctx = make_registry(DivergingBrain())
        import json
        result = json.loads(await registry.call(
            "consensus", {"question": "ambiguous?", "voters": 3}, ctx))
        self.assertFalse(result["decided"])
        self.assertIn("diverged", result["note"])

    async def test_validation_rejects_bad_args(self):
        brain = RoleAwareBrain({})
        registry, ctx = make_registry(brain)
        with self.assertRaises(ToolFailure):
            await registry.call("swarm_delegate", {"goal": ""}, ctx)
        with self.assertRaises(ToolFailure):
            await registry.call("swarm_delegate",
                                {"goal": "x", "workers": 99}, ctx)


if __name__ == "__main__":
    unittest.main()

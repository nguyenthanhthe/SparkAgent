import json
import unittest

from brain.bridge import BrainResponse, Tier
from kernel.bus import EventBus
from tools.registry import ToolContext, ToolRegistry
from swarm.delegate import register_swarm_tools


class RoleBrain:
    def __init__(self):
        self.model = "fake"

    async def chat(self, messages, force=None):
        system = messages[0]["content"]
        if "PLANNER" in system:
            return BrainResponse(text='["step one", "step two"]',
                                 tier=Tier.LOCAL, model="fake", elapsed=0)
        if "WORKER" in system:
            return BrainResponse(text="work done", tier=Tier.LOCAL,
                                 model="fake", elapsed=0)
        if "CRITIC" in system:
            return BrainResponse(text="solid", tier=Tier.LOCAL,
                                 model="fake", elapsed=0)
        return BrainResponse(text="final answer here", tier=Tier.LOCAL,
                             model="fake", elapsed=0)


class SwarmStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_swarm_delegate_emits_progress_events(self):
        bus = EventBus()
        queue = bus.subscribe("logs")
        registry = ToolRegistry(bus)
        register_swarm_tools(registry, RoleBrain(), bus=bus)
        ctx = ToolContext(source="agent")
        result = await registry.call(
            "swarm_delegate", {"goal": "analyze things"}, ctx)
        parsed = json.loads(result)
        self.assertTrue(parsed["ok"])

        collected = []
        while not queue.empty():
            collected.append(queue.get_nowait())
        stages = [line for line in collected if line.startswith("[swarm]")]
        joined = "\n".join(stages)
        self.assertIn("[swarm] start:", joined)
        self.assertIn("[swarm] plan:", joined)
        self.assertIn("[swarm] done:", joined)

    async def test_debate_emits_events(self):
        bus = EventBus()
        queue = bus.subscribe("logs")
        registry = ToolRegistry(bus)
        register_swarm_tools(registry, RoleBrain(), bus=bus)
        await registry.call(
            "debate", {"question": "tabs or spaces?", "rounds": 1},
            ToolContext(source="agent"))
        collected = []
        while not queue.empty():
            collected.append(queue.get_nowait())
        joined = "\n".join(collected)
        self.assertIn("[swarm] debate: starting", joined)
        self.assertIn("settled", joined)

    async def test_swarm_channel_structured_debate_events(self):
        bus = EventBus()
        swarm_q = bus.subscribe("swarm")
        registry = ToolRegistry(bus)
        register_swarm_tools(registry, RoleBrain(), bus=bus)
        await registry.call(
            "debate", {"question": "tabs or spaces?", "rounds": 2},
            ToolContext(source="agent"))
        events = []
        while not swarm_q.empty():
            events.append(swarm_q.get_nowait())
        round_events = [e for e in events
                        if e["stage"] == "debate" and "round" in e]
        self.assertEqual([e["round"] for e in round_events], [1, 2])
        self.assertEqual(round_events[0]["rounds"], 2)
        self.assertTrue(any(e["stage"] == "debate" and e["detail"] == "settled"
                            for e in events))

    async def test_swarm_channel_consensus_voter_progress(self):
        bus = EventBus()
        swarm_q = bus.subscribe("swarm")
        registry = ToolRegistry(bus)
        register_swarm_tools(registry, RoleBrain(), bus=bus)
        await registry.call(
            "consensus", {"question": "capital of France?", "voters": 3},
            ToolContext(source="agent"))
        events = []
        while not swarm_q.empty():
            events.append(swarm_q.get_nowait())
        voters = [e["voter"] for e in events
                  if e["stage"] == "consensus" and "voter" in e]
        self.assertEqual(voters, [1, 2, 3])

    async def test_no_bus_still_works(self):
        registry = ToolRegistry()
        register_swarm_tools(registry, RoleBrain(), bus=None)
        result = await registry.call(
            "swarm_delegate", {"goal": "x"}, ToolContext(source="agent"))
        self.assertIn("final answer", result)


if __name__ == "__main__":
    unittest.main()

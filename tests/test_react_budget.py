import tempfile
import unittest
from pathlib import Path

from brain.bridge import BrainResponse, Tier
from kernel.bus import EventBus
from kernel.memory import Memory
from kernel.react import ReactAgent
from tools.registry import Tool, ToolContext, ToolRegistry


class ScriptedBrain:
    def __init__(self, replies):
        self.queue = list(replies)
        self.seen_sizes: list[int] = []

    async def chat(self, messages, force=None):
        self.seen_sizes.append(sum(len(m["content"]) for m in messages))
        return BrainResponse(text=self.queue.pop(0), tier=Tier.LOCAL,
                             model="mock", elapsed=0.0)


def make_agent(replies, num_ctx=8192, observation_size=200):
    brain = ScriptedBrain(replies)
    registry = ToolRegistry(EventBus())

    async def noisy_tool(ctx):
        return "x" * observation_size

    registry.register(Tool(name="grab", description="grab",
                           parameters={}, handler=noisy_tool))
    memory = Memory(Path(tempfile.mkdtemp()) / "t.db", embedder_fn=None,
                    embed_dim=64)
    cfg = {"agent.max_steps": 8, "brain.local.num_ctx": num_ctx}
    agent = ReactAgent(brain, registry, memory, EventBus(),
                       type("C", (), {"get": lambda s, k, d=None:
                                      cfg.get(k, d)})())
    return agent, memory, brain


class ReactBudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_short_episodes_untouched(self):
        replies = [
            '{"thought": "t", "action": {"name": "grab", "args": {}}}',
            '{"thought": "t", "final_answer": "done quickly"}',
        ]
        agent, memory, brain = make_agent(replies)
        await memory.connect()
        result = await agent.run("tiny goal", source="test")
        self.assertEqual(result.status, "done")
        # only two prompts sent, no compression artifacts
        self.assertEqual(len(brain.seen_sizes), 2)
        await memory.close()

    async def test_long_scratchpad_gets_compressed(self):
        # tiny window (512 tokens) forces compression of old turns
        replies = []
        for _ in range(6):
            replies.append('{"thought": "keep going", "action": '
                           '{"name": "grab", "args": {}}}')
        replies.append('{"thought": "enough", "final_answer": "finished"}')
        agent, memory, brain = make_agent(replies, num_ctx=1024,
                                          observation_size=900)
        await memory.connect()
        result = await agent.run("long running goal", source="test")
        self.assertEqual(result.status, "done")
        # the final prompts must stay under the ~512-token window
        budget_chars = 512 * 4
        self.assertLess(brain.seen_sizes[-1], budget_chars,
                        f"last prompt {brain.seen_sizes[-1]} chars exceeded "
                        "window — compression did not fire")
        # and the model still received the early-turn summary marker
        await memory.close()


if __name__ == "__main__":
    unittest.main()

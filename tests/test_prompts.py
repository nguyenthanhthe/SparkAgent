"""Golden tests for the ReAct system-prompt contract.

The system prompt is a compatibility surface: models are tuned against
it, and logged episodes depend on its wording. These tests pin the
contract clauses so any change is a conscious, reviewed edit — not
drift.
"""

import unittest
from pathlib import Path

from kernel.bus import EventBus
from kernel.memory import Memory
from kernel.react import ReactAgent
from tools.registry import Tool, ToolRegistry

GOLDEN = Path(__file__).parent / "golden"


def make_agent(registry=None):
    registry = registry or ToolRegistry(EventBus())
    registry.register(Tool(name="demo", description="demo tool",
                           parameters={}, handler=lambda ctx: "ok"))
    cfg_values = {"agent.name": "sparkagent", "agent.max_steps": 12,
                  "brain.local.num_ctx": 8192}
    agent = ReactAgent(
        object(), registry,
        Memory(Path("unused.db"), embedder_fn=None),
        EventBus(),
        type("C", (), {"get": lambda s, k, d=None:
                       cfg_values.get(k, d)})())
    return agent


class PromptContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_system_prompt_contract_clauses(self):
        prompt = make_agent().build_system_prompt("goal")
        # the non-negotiable clauses
        self.assertIn("Reply with EXACTLY ONE JSON object", prompt)
        self.assertIn('"thought"', prompt)
        self.assertIn('"final_answer"', prompt)
        self.assertIn('"action"', prompt)
        self.assertIn("One action per turn", prompt)
        self.assertIn("Never fabricate tool output", prompt)
        # tools must be listed with parameters
        self.assertIn("- demo: demo tool", prompt)
        self.assertIn("parameters", prompt)
        # placeholders present before wiring
        self.assertIn("Relevant long-term memories", prompt)

    async def test_memory_block_replacement_target_exists(self):
        prompt = make_agent().build_system_prompt("goal")
        # run() replaces this placeholder with recalled memories
        self.assertIn("(memory unavailable at startup)", prompt)

    async def test_prompt_bounded(self):
        prompt = make_agent().build_system_prompt("x" * 5000)
        self.assertLess(len(prompt), 40_000)

    async def test_observation_guard_documented(self):
        import kernel.react as react
        self.assertTrue(callable(react.guard_observation))


if __name__ == "__main__":
    unittest.main()

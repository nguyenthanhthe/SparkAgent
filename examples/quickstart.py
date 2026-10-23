"""Quickstart: run one ReAct episode fully offline.

Demonstrates the pieces every episode touches — memory, tools, brain —
using the deterministic mock adapter, so it runs on any machine with zero
setup:

    python examples/quickstart.py
"""

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from brain.adapters.mock import MockAdapter          # noqa: E402
from brain.bridge import BrainResponse, Tier         # noqa: E402
from kernel.bus import EventBus                      # noqa: E402
from kernel.memory import Memory                     # noqa: E402
from kernel.react import ReactAgent                  # noqa: E402
from tools.registry import Tool, ToolContext, ToolRegistry  # noqa: E402


def build_registry() -> ToolRegistry:
    registry = ToolRegistry(EventBus())

    async def system_status(ctx: ToolContext) -> dict:
        return {"gpu": "RTX 4050", "vram_free_mb": 6144, "cpu": "12%"}

    registry.register(Tool(
        name="system_status",
        description="Report GPU/VRAM/CPU status.",
        parameters={}, handler=system_status))
    return registry


async def main() -> None:
    memory = Memory(Path(tempfile.mkdtemp()) / "demo.db",
                    embedder_fn=None, embed_dim=128)
    await memory.connect()
    await memory.remember("The GPU fans were cleaned on October 20th",
                          kind="fact")

    class MockBrain:
        """Two scripted turns: one tool call, then the final answer."""

        def __init__(self):
            self.adapter = MockAdapter()
            self.adapter.enqueue(
                '{"thought": "check hardware first", "action": '
                '{"name": "system_status", "args": {}}}',
                '{"thought": "hardware verified", "final_answer": '
                '"GPU healthy with 6GB free; fans were cleaned recently."}',
            )

        async def chat(self, messages, force=None):
            response = await self.adapter.chat(messages)
            return BrainResponse(text=response.text, tier=Tier.LOCAL,
                                 model="mock", elapsed=0.0)

    brain = MockBrain()
    agent = ReactAgent(brain, build_registry(), memory, EventBus(),
                       type("C", (), {"get": lambda s, k, d=None: d})())
    result = await agent.run("check the system and summarize gpu health")
    print("status :", result.status)
    print("steps  :", result.steps)
    print("answer :", result.answer)
    await memory.close()


if __name__ == "__main__":
    asyncio.run(main())

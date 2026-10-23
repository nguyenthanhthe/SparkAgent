import asyncio
import tempfile
import unittest
from pathlib import Path

from brain.bridge import BrainResponse, Tier
from kernel.bus import EventBus
from kernel.memory import Memory
from kernel.react import EpisodeResult, ReactAgent, extract_json
from tools.registry import Tool, ToolContext, ToolRegistry


class FakeBrain:
    """Scripted brain: pops one canned reply per chat() call."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    async def chat(self, messages, force=None):
        self.calls += 1
        if not self.replies:
            raise RuntimeError("scripted brain exhausted")
        text = self.replies.pop(0)
        if isinstance(text, Exception):
            raise text
        return BrainResponse(text=text, tier=Tier.LOCAL, model="fake",
                             elapsed=0.0)


class ExtractJsonTests(unittest.TestCase):
    def test_plain_json(self):
        parsed = extract_json('{"thought": "t", "final_answer": "a"}')
        self.assertEqual(parsed["final_answer"], "a")

    def test_fenced_json(self):
        parsed = extract_json('```json\n{"thought": "t", "final_answer": "a"}\n```')
        self.assertEqual(parsed["final_answer"], "a")

    def test_json_with_prose_around(self):
        parsed = extract_json('Sure! Here is my reply:\n'
                              '{"thought": "t", "action": {"name": "x", '
                              '"args": {"a": 1}}}\nHope that helps.')
        self.assertEqual(parsed["action"]["name"], "x")

    def test_nested_braces_in_strings(self):
        parsed = extract_json('{"thought": "literal } brace", "final_answer": "ok"}')
        self.assertEqual(parsed["final_answer"], "ok")

    def test_garbage_returns_none(self):
        self.assertIsNone(extract_json("no json here at all"))
        self.assertIsNone(extract_json(""))
        self.assertIsNone(extract_json("{unterminated"))


def make_agent(replies):
    brain = FakeBrain(replies)
    registry = ToolRegistry(EventBus())
    db = Path(tempfile.mkdtemp()) / "test.db"
    memory = Memory(db, embedder_fn=None, embed_dim=128)
    cfg = type("C", (), {"get": lambda self, k, d=None: d})()
    agent = ReactAgent(brain, registry, memory, EventBus(), cfg)
    registry.register(Tool(
        name="echo", description="echo the text back",
        parameters={"text": {"type": "string", "required": True}},
        handler=lambda ctx, text: f"echo: {text}"))
    return agent, memory


class ReactEpisodeTests(unittest.IsolatedAsyncioTestCase):
    async def test_successful_episode(self):
        replies = [
            '{"thought": "use echo", "action": {"name": "echo", '
            '"args": {"text": "hello"}}}',
            '{"thought": "done", "final_answer": "echoed successfully"}',
        ]
        agent, memory = make_agent(replies)
        await memory.connect()
        result = await agent.run("echo hello", source="test")
        self.assertEqual(result.status, "done")
        self.assertEqual(result.answer, "echoed successfully")
        self.assertEqual(result.steps, 2)
        episodes = await memory.recent_episodes()
        self.assertEqual(episodes[0]["status"], "done")
        self.assertEqual(episodes[0]["steps"], 2)

    async def test_tool_error_becomes_observation(self):
        replies = [
            '{"thought": "call missing tool", "action": {"name": "nope", '
            '"args": {}}}',
            '{"thought": "recover", "final_answer": "recovered anyway"}',
        ]
        agent, memory = make_agent(replies)
        await memory.connect()
        result = await agent.run("test recovery", source="test")
        self.assertEqual(result.status, "done")
        self.assertEqual(result.steps, 2)

    async def test_parse_errors_fail_episode(self):
        replies = ["garbage one", "garbage two", "garbage three"]
        agent, memory = make_agent(replies)
        await memory.connect()
        result = await agent.run("unparseable", source="test")
        self.assertEqual(result.status, "failed")
        self.assertIn("not parseable", result.answer)

    async def test_max_steps_fails_episode(self):
        action = ('{"thought": "again", "action": {"name": "echo", '
                  '"args": {"text": "x"}}}')
        agent_cfg = {"agent.max_steps": 3}
        brain_replies = [action] * 10
        brain = FakeBrain(brain_replies)
        registry = ToolRegistry(EventBus())
        memory = Memory(Path(tempfile.mkdtemp()) / "t.db", embedder_fn=None,
                        embed_dim=64)
        cfg = type("C", (), {"get": lambda self, k, d=None: agent_cfg.get(k, d)})()
        agent = ReactAgent(brain, registry, memory, EventBus(), cfg)
        registry.register(Tool(name="echo", description="echo",
                               parameters={},
                               handler=lambda ctx, **kw: "ok"))
        await memory.connect()
        result = await agent.run("loop forever", source="test")
        self.assertEqual(result.status, "failed")
        self.assertIn("max_steps", result.answer)


if __name__ == "__main__":
    unittest.main()

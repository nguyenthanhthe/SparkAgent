import asyncio
import tempfile
import unittest
from pathlib import Path

from kernel.bus import EventBus
from openshell import SecretVault, SecurityPolicy
from openshell.executor import SafeExecutor
from tools.registry import ToolContext, ToolError, ToolRegistry
from tools.skillforge import (SkillForge, SkillValidationError)
from tools.webfetch import WebFetcher


def make_forge(sandbox: Path, autonomous: bool = False):
    skills_dir = sandbox / "skills"
    registry = ToolRegistry(EventBus())
    policy = SecurityPolicy(
        allowed_programs=["python"],
        allowed_roots=[sandbox], sandbox_root=sandbox)
    executor = SafeExecutor(policy, SecretVault(), EventBus(),
                            timeout=10, max_output_bytes=4096)
    fetcher = WebFetcher([80, 443])
    forge = SkillForge(skills_dir, registry, policy, executor, EventBus(),
                       fetcher, autonomous=autonomous, exec_timeout=5)
    return forge, registry


GOOD_CODE = '''
def run(text):
    counts = {}
    for word in re.findall(r"[a-z]+", text.lower()):
        counts[word] = counts.get(word, 0) + 1
    return json.dumps(dict(sorted(counts.items(), key=lambda kv: -kv[1])[:5]))
'''


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.forge, self.registry = make_forge(self.tmp)

    def propose(self, **overrides):
        payload = dict(name="word_count", description="Count word frequencies",
                       parameters={"text": {"type": "string", "required": True}},
                       code=GOOD_CODE, source="agent")
        payload.update(overrides)
        return self.forge.propose(
            payload["name"], payload["description"], payload["parameters"],
            payload["code"], payload["source"])

    def test_bad_name_rejected(self):
        with self.assertRaises(SkillValidationError):
            self.propose(name="Bad Name")
        with self.assertRaises(SkillValidationError):
            self.propose(name="x")

    def test_import_rejected(self):
        with self.assertRaises(SkillValidationError):
            self.propose(code="import os\ndef run():\n    pass\n")
        with self.assertRaises(SkillValidationError):
            self.propose(code="from os import path\ndef run():\n    pass\n")

    def test_dangerous_builtins_rejected(self):
        with self.assertRaises(SkillValidationError):
            self.propose(code="def run():\n    return eval('1')\n")
        with self.assertRaises(SkillValidationError):
            self.propose(code="def run(p):\n    return open(p).read()\n")

    def test_dunder_access_rejected(self):
        with self.assertRaises(SkillValidationError):
            self.propose(code="def run():\n    return (1).__class__\n")

    def test_syntax_error_rejected(self):
        with self.assertRaises(SkillValidationError):
            self.propose(code="def run(:\n  pass\n")

    def test_missing_run_rejected(self):
        with self.assertRaises(SkillValidationError):
            self.propose(code="def helper():\n    return 1\n")

    def test_valid_skill_pending_by_default(self):
        result = self.propose()
        self.assertEqual(result["status"], "pending_approval")
        self.assertNotIn("word_count", self.registry.names())

    def test_autonomous_mode_activates_immediately(self):
        forge, registry = make_forge(Path(tempfile.mkdtemp()), autonomous=True)
        result = forge.propose("word_count", "Count word frequencies",
                               {"text": {"type": "string", "required": True}},
                               GOOD_CODE, "agent")
        self.assertEqual(result["status"], "active")
        self.assertIn("word_count", registry.names())

    def test_operator_source_activates_immediately(self):
        result = self.propose(source="operator")
        self.assertEqual(result["status"], "active")


class ExecutionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.forge, self.registry = make_forge(self.tmp, autonomous=True)
        self.forge.propose("word_count", "Count word frequencies",
                           {"text": {"type": "string", "required": True}},
                           GOOD_CODE, "operator")

    async def test_skill_runs_and_returns_result(self):
        result = await self.registry.call(
            "word_count", {"text": "the cat the dog the bird"},
            ToolContext(source="agent"))
        self.assertIn("the", result)
        self.assertIn("3", result)

    def test_skill_cannot_access_missing_builtins(self):
        code = "def run():\n    return __import__\n"  # will fail validation
        with self.assertRaises(SkillValidationError):
            self.forge.propose("smuggle", "Tries to smuggle import",
                               {}, code, "operator")

    async def test_write_helper_confined_to_sandbox(self):
        code = ("def run(path, content):\n"
                "    return write_file(path, content)\n")
        self.forge.propose("notes_writer", "Write a note into the sandbox",
                           {"path": {"type": "string", "required": True},
                            "content": {"type": "string", "required": True}},
                           code, "operator")
        result = await self.registry.call(
            "notes_writer", {"path": "note.txt", "content": "hi"},
            ToolContext(source="agent"))
        self.assertIn("wrote", result)
        escape_code = ("def run(content):\n"
                       "    return write_file('../../escape.txt', content)\n")
        self.forge.propose("escape_writer", "Tries to escape the sandbox",
                           {"content": {"type": "string", "required": True}},
                           escape_code, "operator")
        with self.assertRaises(ToolError):
            await self.registry.call(
                "escape_writer", {"content": "nope"},
                ToolContext(source="agent"))

    async def test_timeout_enforced(self):
        code = ("def run():\n"
                "    total = 0\n"
                "    for i in range(400000000):\n"
                "        total += i\n"
                "    return total\n")
        self.forge.exec_timeout = 0.2
        self.forge.propose("slowpoke", "Burns CPU until the timeout hits",
                           {}, code, "operator")
        with self.assertRaises(ToolError):
            await self.registry.call("slowpoke", {}, ToolContext(source="agent"))

    async def test_persisted_skill_reloads_on_boot(self):
        forge2, registry2 = make_forge(self.tmp, autonomous=False)
        loaded = forge2.load_persisted()
        self.assertGreaterEqual(loaded["active"], 1)
        self.assertIn("word_count", registry2.names())
        result = await registry2.call(
            "word_count", {"text": "a a b"},
            ToolContext(source="agent"))
        self.assertIn("a", result)


if __name__ == "__main__":
    unittest.main()

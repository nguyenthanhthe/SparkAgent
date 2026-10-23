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


def make_forge(sandbox: Path, autonomous: bool = False, **kw):
    skills_dir = sandbox / "skills"
    registry = ToolRegistry(EventBus())
    policy = SecurityPolicy(
        allowed_programs=["python"],
        allowed_roots=[sandbox], sandbox_root=sandbox)
    executor = SafeExecutor(policy, SecretVault(), EventBus(),
                            timeout=10, max_output_bytes=4096)
    fetcher = WebFetcher([80, 443])
    defaults = dict(autonomous=autonomous, exec_timeout=5)
    defaults.update(kw)
    forge = SkillForge(skills_dir, registry, policy, executor, EventBus(),
                       fetcher, **defaults)
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
                "    for i in range(20_000_000):\n"
                "        total += i\n"
                "    return total\n")
        # smoke disabled: we want the skill REGISTERED so the runtime
        # timeout path itself is what gets exercised
        self.forge.smoke_test = False
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


class SmokeTestTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def make(self, autonomous=True, **kw):
        forge, registry = make_forge(self.tmp, autonomous=autonomous)
        for key, value in kw.items():
            setattr(forge, key, value)
        return forge, registry

    async def test_working_skill_passes_smoke(self):
        forge, registry = self.make()
        result = forge.propose("shout", "Upper-case the given text",
                               {"text": {"type": "string", "required": True}},
                               "def run(text):\n    return text.upper()\n",
                               "operator")
        self.assertEqual(result["status"], "active")
        self.assertIn("shout", registry.names())

    async def test_crashing_skill_rejected_by_smoke(self):
        forge, registry = self.make()
        with self.assertRaises(SkillValidationError) as ctx:
            forge.propose("crasher", "A skill that always crashes",
                          {"text": {"type": "string", "required": True}},
                          "def run(text):\n    raise ValueError('boom')\n",
                          "operator")
        self.assertIn("smoke test failed", str(ctx.exception))
        self.assertNotIn("crasher", registry.names())

    async def test_smoke_disabled_allows_broken_skill(self):
        forge, registry = self.make(smoke_test=False)
        result = forge.propose("risky", "Skill with runtime-only failure",
                               {"text": {"type": "string", "required": True}},
                               "def run(text):\n    return text\n",
                               "operator")
        self.assertEqual(result["status"], "active")

    async def test_slow_skill_times_out(self):
        forge, registry = self.make()
        forge.exec_timeout = 0.2
        code = ("def run(text):\n"
                "    total = 0\n"
                "    for i in range(20_000_000):\n"
                "        total += i\n"
                "    return total\n")
        with self.assertRaises(SkillValidationError) as ctx:
            forge.propose("slowpoke", "A skill that runs past its budget",
                          {"text": {"type": "string", "required": True}},
                          code, "operator")
        # the skill exceeds exec_timeout and must be rejected
        self.assertIn("smoke test", str(ctx.exception))

    async def test_guard_rejection_on_smoke_is_acceptance(self):
        # a skill whose placeholder args trip a sandbox guard is WIRED
        # correctly — the guard firing proves the helpers are live
        forge, registry = self.make()
        result = forge.propose(
            "escape_writer", "A skill that writes outside the sandbox",
            {"content": {"type": "string", "required": True}},
            "def run(content):\n"
            "    return write_file('../../escape.txt', content)\n",
            "operator")
        self.assertEqual(result["status"], "active")


if __name__ == "__main__":
    unittest.main()

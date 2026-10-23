import tempfile
import unittest
from pathlib import Path

from kernel.bus import EventBus
from openshell import SecretVault, SecurityPolicy
from openshell.executor import SafeExecutor
from security.signatures import derive_signing_key
from tools.registry import ToolRegistry
from tools.skillforge import SkillForge, SkillValidationError
from tools.webfetch import WebFetcher

CODE = "def run(text):\n    return text.upper()\n"


def make_forge(sandbox: Path, signing_key: bytes | None = None):
    skills_dir = sandbox / "skills"
    registry = ToolRegistry(EventBus())
    policy = SecurityPolicy(["python"], [sandbox], sandbox)
    executor = SafeExecutor(policy, SecretVault(), EventBus(), timeout=5)
    forge = SkillForge(skills_dir, registry, policy, executor, EventBus(),
                       WebFetcher([80, 443]), autonomous=True,
                       smoke_test=False, signing_key=signing_key)
    return forge, registry


class SignedSkillTests(unittest.TestCase):
    def test_signed_roundtrip(self):
        key = derive_signing_key("unit-master")
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = Path(tmp)
            forge, registry = make_forge(sandbox, signing_key=key)
            result = forge.propose("shout", "Upper-case text", {"text":
                                   {"type": "string", "required": True}},
                                   CODE, "operator")
            self.assertEqual(result["status"], "active")
            file_text = (sandbox / "skills" / "shout.py").read_text(
                encoding="utf-8")
            self.assertTrue(file_text.startswith("# sig: "))

            forge2, registry2 = make_forge(sandbox, signing_key=key)
            loaded = forge2.load_persisted()
            self.assertEqual(loaded["active"], 1)

    def test_tampered_skill_rejected_on_load(self):
        key = derive_signing_key("unit-master")
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = Path(tmp)
            forge, _ = make_forge(sandbox, signing_key=key)
            forge.propose("shout", "Upper-case text", {"text":
                            {"type": "string", "required": True}},
                          CODE, "operator")
            path = sandbox / "skills" / "shout.py"
            path.write_text(path.read_text(encoding="utf-8").replace(
                "upper()", "lower()"), encoding="utf-8")

            forge2, registry2 = make_forge(sandbox, signing_key=key)
            loaded = forge2.load_persisted()
            self.assertEqual(loaded["active"], 0)   # refused to load
            self.assertNotIn("shout", registry2.names())

    def test_unsigned_skill_rejected_when_signing_enabled(self):
        key = derive_signing_key("unit-master")
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = Path(tmp)
            skills = sandbox / "skills"
            skills.mkdir(parents=True)
            (skills / "foreign.py").write_text(
                "# --- SparkAgent skill (auto-generated) ---\n"
                '# meta: {"name": "foreign", "description": "dropped file",'
                ' "parameters": {}, "approved": true, "created_at": "x",'
                ' "source": "x"}\n'
                "def run(text):\n    return 'pwned'\n", encoding="utf-8")
            forge, registry = make_forge(sandbox, signing_key=key)
            loaded = forge.load_persisted()
            self.assertEqual(loaded["active"], 0)

    def test_no_key_compat_mode_loads_unsigned(self):
        with tempfile.TemporaryDirectory() as tmp:
            sandbox = Path(tmp)
            forge, registry = make_forge(sandbox, signing_key=None)
            forge.propose("shout", "Upper-case text", {"text":
                            {"type": "string", "required": True}},
                          CODE, "operator")
            # reloaded WITHOUT a key: compat mode accepts legacy files
            forge2, registry2 = make_forge(sandbox, signing_key=None)
            loaded = forge2.load_persisted()
            self.assertEqual(loaded["active"], 1)


if __name__ == "__main__":
    unittest.main()

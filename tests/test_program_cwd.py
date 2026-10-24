import tempfile
import unittest
from pathlib import Path

from openshell import SecurityError, SecurityPolicy
from openshell.executor import SafeExecutor
from kernel.bus import EventBus
from openshell import SecretVault


def make_policy(sandbox: Path, program_cwd=None):
    return SecurityPolicy(["python", "git"], [sandbox, sandbox.parent],
                          sandbox, program_cwd=program_cwd)


class ValidateWorkdirTests(unittest.TestCase):
    def setUp(self):
        self.sandbox = Path(tempfile.mkdtemp())
        self.project = self.sandbox.parent

    def test_unrestricted_by_default(self):
        policy = make_policy(self.sandbox)
        policy.validate_workdir("python", self.sandbox)      # no raise
        policy.validate_workdir("git", self.project)         # no raise

    def test_restricted_program_confined(self):
        repo = Path(tempfile.mkdtemp())
        policy = make_policy(self.sandbox, program_cwd={"git": [repo]})
        policy.validate_workdir("git", repo)                 # allowed root
        policy.validate_workdir("git", repo / "subdir")      # nested ok
        with self.assertRaises(SecurityError) as ctx:
            policy.validate_workdir("git", self.sandbox)
        self.assertIn("may only run from", str(ctx.exception))

    def test_other_programs_unaffected(self):
        repo = Path(tempfile.mkdtemp())
        policy = make_policy(self.sandbox, program_cwd={"git": [repo]})
        policy.validate_workdir("python", self.sandbox)      # unrestricted

    def test_default_cwd_is_sandbox(self):
        repo = Path(tempfile.mkdtemp())
        policy = make_policy(self.sandbox, program_cwd={"git": [repo]})
        # sandbox (the executor default) is not in git's roots
        with self.assertRaises(SecurityError):
            policy.validate_workdir("git", policy.sandbox_root)


class ExecutorWorkdirTests(unittest.IsolatedAsyncioTestCase):
    async def test_blocked_cwd_returns_blocked_result(self):
        sandbox = Path(tempfile.mkdtemp())
        other = Path(tempfile.mkdtemp())
        policy = make_policy(sandbox, program_cwd={"python": [sandbox]})
        executor = SafeExecutor(policy, SecretVault(), EventBus(),
                                timeout=5)
        result = await executor.run("python", ["-c", "print(1)"],
                                    cwd=other)
        self.assertIsNotNone(result.blocked_reason)
        self.assertIn("may only run from", result.blocked_reason)
        self.assertEqual(executor.registry.stats()["completed"], 0)

    async def test_allowed_cwd_runs(self):
        sandbox = Path(tempfile.mkdtemp())
        policy = make_policy(sandbox, program_cwd={"python": [sandbox]})
        executor = SafeExecutor(policy, SecretVault(), EventBus(),
                                timeout=10)
        result = await executor.run("python", ["-c", "print(7)"],
                                    cwd=sandbox)
        self.assertTrue(result.ok)


if __name__ == "__main__":
    unittest.main()

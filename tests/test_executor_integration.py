import asyncio
import os
import tempfile
import unittest
from pathlib import Path

from kernel.bus import EventBus
from openshell import SecretVault, SecurityPolicy
from openshell.executor import SafeExecutor


def make_executor(sanitize=True):
    sandbox = Path(tempfile.mkdtemp())
    policy = SecurityPolicy(["python"], [sandbox], sandbox)
    return SafeExecutor(policy, SecretVault(), EventBus(), timeout=15,
                        sanitize_child_env=sanitize)


class ExecutorIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_child_secrets_never_inherit(self):
        os.environ["UNITTEST_CHILD_SECRET"] = "leak-canary-xyz"
        try:
            executor = make_executor(sanitize=True)
            result = await executor.run(
                "python", ["-c",
                           "import os; print('CANARY' if "
                           "'UNITTEST_CHILD_SECRET' in os.environ else 'CLEAN')"])
            self.assertIn("CLEAN", result.stdout)
            self.assertNotIn("CANARY", result.stdout)
        finally:
            del os.environ["UNITTEST_CHILD_SECRET"]

    async def test_child_path_still_works(self):
        executor = make_executor(sanitize=True)
        result = await executor.run("python", ["-c", "print(6*7)"])
        self.assertTrue(result.ok)
        self.assertIn("42", result.stdout)

    async def test_process_registry_tracks_run(self):
        executor = make_executor()
        await executor.run("python", ["-c", "print(1)"])
        self.assertEqual(executor.registry.live_count(), 0)
        history = executor.registry.history(limit=5)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["program"], "python")
        self.assertEqual(history[0]["exit_code"], 0)

    async def test_blocked_commands_not_registered_as_processes(self):
        executor = make_executor()
        await executor.run("python", ["-c", "shutdown /s"])
        self.assertEqual(executor.registry.stats()["completed"], 0)


if __name__ == "__main__":
    unittest.main()

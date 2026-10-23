import tempfile
import unittest
from pathlib import Path

from kernel.bus import EventBus
from openshell import SecretVault, SecurityPolicy
from openshell.executor import SafeExecutor


def make_executor(**kw):
    sandbox = Path(tempfile.mkdtemp())
    policy = SecurityPolicy(["python", "git"], [sandbox], sandbox)
    defaults = dict(timeout=5)
    defaults.update(kw)
    return SafeExecutor(policy, SecretVault(), EventBus(), **defaults)


class DryRunTests(unittest.IsolatedAsyncioTestCase):
    async def test_allowed_command(self):
        executor = make_executor()
        report = await executor.dry_run("python", ["-c", "print(1)"])
        self.assertEqual(report["decision"], "allowed")
        self.assertTrue(report["executable"])
        self.assertEqual(report["rate_limit"], "unlimited")

    async def test_denied_by_allowlist(self):
        executor = make_executor()
        report = await executor.dry_run("cmd", ["/c", "dir"])
        self.assertEqual(report["decision"], "blocked")
        self.assertIn("allowlist", report["reason"])
        self.assertIsNone(report["executable"])

    async def test_denied_by_denylist(self):
        executor = make_executor()
        report = await executor.dry_run("python", ["-c", "format C: /y"])
        self.assertEqual(report["decision"], "blocked")
        self.assertIn("denylist", report["reason"])

    async def test_rate_limit_reported(self):
        executor = make_executor(execs_per_minute=1)
        await executor.run("python", ["-c", "print(1)"])   # drain bucket
        report = await executor.dry_run("python", ["-c", "print(2)"])
        self.assertEqual(report["decision"], "allowed")
        self.assertEqual(report["rate_limit"],
                         "would be rate-limited this minute")

    async def test_dry_run_spawns_nothing(self):
        executor = make_executor()
        await executor.dry_run("python", ["-c", "print(1)"])
        self.assertEqual(executor.registry.live_count(), 0)
        self.assertEqual(executor.registry.stats()["completed"], 0)


if __name__ == "__main__":
    unittest.main()

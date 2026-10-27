import tempfile
import unittest
from pathlib import Path

from kernel.bus import EventBus
from openshell import SecretVault, SecurityPolicy
from openshell.executor import SafeExecutor


def make_executor(execs_per_minute=0.0):
    sandbox = Path(tempfile.mkdtemp())
    policy = SecurityPolicy(["python"], [sandbox], sandbox)
    return SafeExecutor(policy, SecretVault(), EventBus(),
                        execs_per_minute=execs_per_minute)


class ExecutorRateLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_by_default(self):
        executor = make_executor(execs_per_minute=0)
        for _ in range(3):
            result = await executor.run("python", ["-c", "print(1)"])
            self.assertTrue(result.ok)

    async def test_budget_exhaustion_blocks(self):
        executor = make_executor(execs_per_minute=6)   # capacity 6, ~0.1/s
        first = await executor.run("python", ["-c", "print(1)"])
        self.assertTrue(first.ok)
        # drain the remaining burst budget synchronously
        for _ in range(5):
            self.assertTrue(await executor.run("python", ["-c", "print(1)"]))
        blocked = await executor.run("python", ["-c", "print(1)"])
        self.assertIsNone(blocked.exit_code)
        self.assertIn("rate limit", blocked.blocked_reason)

    async def test_limits_are_per_program(self):
        executor = make_executor(execs_per_minute=1)
        result = await executor.run("python", ["-c", "print(1)"])
        self.assertTrue(result.ok)
        # 'python' bucket is now empty; git hits the allowlist first —
        # its (policy) rejection must not mention rate limiting
        result = await executor.run("git", ["status"])
        self.assertIn("allowlist", result.blocked_reason or "")

    async def test_rate_limited_run_not_counted_as_process(self):
        executor = make_executor(execs_per_minute=1)
        await executor.run("python", ["-c", "print(1)"])
        await executor.run("python", ["-c", "print(1)"])   # rate-limited
        # only the first (allowed) run became a tracked process
        self.assertEqual(executor.registry.stats()["completed"], 1)

    async def test_veto_increments_metrics_counter(self):
        import openshell.executor as executor_mod
        from kernel.metrics import MetricsRegistry
        registry = MetricsRegistry()
        original = executor_mod.REGISTRY
        executor_mod.REGISTRY = registry
        try:
            executor = make_executor(execs_per_minute=1)
            await executor.run("python", ["-c", "print(1)"])
            await executor.run("python", ["-c", "print(1)"])   # rate-limited
            self.assertGreaterEqual(
                registry.counter("exec_ratelimit_blocked_total"), 1.0)
        finally:
            executor_mod.REGISTRY = original


if __name__ == "__main__":
    unittest.main()

"""Per-program wall-clock budget — admission-gate veto on over-budget runs."""

import asyncio
import tempfile
import unittest
from pathlib import Path

from kernel.bus import EventBus
from openshell import SecretVault, SecurityPolicy
from openshell.executor import SafeExecutor


class ProgramTimeoutBudgetTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.policy = SecurityPolicy(["python"], [self.root], self.root)

    def make_executor(self, budgets):
        return SafeExecutor(self.policy, SecretVault(), EventBus(),
                            timeout=60.0, program_timeouts=budgets)

    def test_over_budget_run_blocked(self):
        executor = self.make_executor({"python": 5.0})

        async def scenario():
            return await executor.run("python", ["-c", "print(1)"],
                                      timeout=120.0)
        result = asyncio.run(scenario())
        self.assertIsNone(result.exit_code)
        self.assertIn("time budget", result.blocked_reason)
        self.assertIn("5", result.blocked_reason)

    def test_within_budget_run_allowed(self):
        executor = self.make_executor({"python": 30.0})

        async def scenario():
            return await executor.run("python", ["-c", "print('ok')"],
                                      timeout=10.0)
        result = asyncio.run(scenario())
        self.assertNotIn("time budget", result.blocked_reason or "")

    def test_unbudgeted_program_unaffected(self):
        executor = self.make_executor({"git": 5.0})

        async def scenario():
            return await executor.run("python", ["-c", "print('ok')"],
                                      timeout=120.0)
        result = asyncio.run(scenario())
        self.assertNotIn("time budget", result.blocked_reason or "")

    def test_case_insensitive_program_match(self):
        executor = self.make_executor({"Python": 5.0})

        async def scenario():
            return await executor.run("PYTHON", ["-c", "print(1)"],
                                      timeout=60.0)
        result = asyncio.run(scenario())
        self.assertIn("time budget", result.blocked_reason)

    def test_default_timeout_vetoed_when_over_budget(self):
        executor = self.make_executor({"python": 5.0})

        async def scenario():
            return await executor.run("python", ["-c", "print(1)"])
        result = asyncio.run(scenario())
        self.assertIn("time budget", result.blocked_reason)

    def test_block_publishes_audit_event(self):
        executor = self.make_executor({"python": 1.0})
        events = []
        executor.bus = type("B", (), {"publish": staticmethod(
            lambda channel, event: events.append((channel, event)))})()

        async def scenario():
            return await executor.run("python", ["-c", "print(1)"],
                                      timeout=10.0)
        asyncio.run(scenario())
        channels = [channel for channel, _event in events]
        self.assertIn("audit", channels)


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path

from kernel.bus import EventBus
from kernel.metrics import REGISTRY
from openshell import SecretVault, SecurityPolicy
from openshell.executor import SafeExecutor, _metric_safe


class ExecMetricTests(unittest.IsolatedAsyncioTestCase):
    async def test_per_program_histogram_observed(self):
        sandbox = Path(tempfile.mkdtemp())
        policy = SecurityPolicy(["python"], [sandbox], sandbox)
        executor = SafeExecutor(policy, SecretVault(), EventBus(), timeout=15)
        before = REGISTRY.histogram("exec_seconds_python")
        before_count = before["count"] if before else 0
        result = await executor.run("python", ["-c", "print(1)"])
        self.assertTrue(result.ok)
        hist = REGISTRY.histogram("exec_seconds_python")
        self.assertIsNotNone(hist)
        self.assertEqual(hist["count"], before_count + 1)
        self.assertGreaterEqual(hist["sum"], 0.0)

    async def test_metric_safe_slug(self):
        self.assertEqual(_metric_safe("python"), "python")
        self.assertEqual(_metric_safe("Python3.11"), "python3_11")
        self.assertEqual(_metric_safe("a b/c"), "a_b_c")
        self.assertEqual(_metric_safe("///"), "unknown")


if __name__ == "__main__":
    unittest.main()

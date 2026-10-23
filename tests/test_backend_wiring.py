import unittest

from kernel.config import Config
from kernel.daemon import AgentDaemon
from openshell.executor import SafeExecutor
from openshell.sandbox_backend import OpenShellExecutor


class BackendWiringTests(unittest.IsolatedAsyncioTestCase):
    async def test_auto_backend_uses_openshell_executor(self):
        daemon = AgentDaemon(Config.load())   # backend defaults to auto
        self.assertIsInstance(daemon.executor, OpenShellExecutor)
        # no runtime here -> probes absent and falls back per-run
        executor = daemon.executor
        self.assertFalse(await executor.ensure_ready())
        self.assertEqual(executor.describe_backend()["backend"],
                         "policy-fallback")

    async def test_policy_backend_explicit(self):
        daemon = AgentDaemon(Config({"openshell": {"backend": "policy"}}))
        self.assertIsInstance(daemon.executor, SafeExecutor)
        self.assertNotIsInstance(daemon.executor, OpenShellExecutor)

    async def test_sandbox_name_from_config(self):
        daemon = AgentDaemon(Config({"openshell":
                                     {"sandbox_name": "lab-node"}}))
        self.assertEqual(daemon.executor.sandbox_name, "lab-node")

    async def test_tools_still_registered_with_backend(self):
        daemon = AgentDaemon(Config.load())
        names = daemon.registry.names()
        for expected in ("system_status", "calculate", "swarm_delegate"):
            self.assertIn(expected, names)


if __name__ == "__main__":
    unittest.main()

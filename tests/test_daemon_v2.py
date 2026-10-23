import unittest

from kernel.config import Config
from kernel.daemon import AgentDaemon


class DaemonV2WiringTests(unittest.IsolatedAsyncioTestCase):
    async def test_daemon_wires_security_and_tools(self):
        daemon = AgentDaemon(Config.load())
        tools = daemon.registry.names()
        for expected in ("calculate", "text_analysis", "json_query",
                         "csv_analyze", "statistics", "remember",
                         "recall_memory", "ask_human", "system_status",
                         "web_fetch", "skill_create", "swarm_delegate",
                         "debate", "consensus", "extract_entities",
                         "graph_query"):
            self.assertIn(expected, tools, f"missing tool {expected}")
        self.assertIsNotNone(daemon.approvals)
        self.assertIsNotNone(daemon.quarantine)
        self.assertTrue(daemon.quarantine.root.exists())

    async def test_status_includes_new_sections(self):
        daemon = AgentDaemon(Config.load())
        status = daemon.status()
        for key in ("approvals_pending", "guard_stats", "executor",
                    "sandbox_profile", "version"):
            self.assertIn(key, status)
        self.assertEqual(status["version"], "0.2.0")
        self.assertEqual(status["sandbox_profile"], "standard")

    async def test_rate_limit_wired_from_config(self):
        daemon = AgentDaemon(Config.load())
        self.assertIsNotNone(daemon.executor._limiters)  # default 30/min
        limited = AgentDaemon(Config({"openshell": {"execs_per_minute": 0}}))
        self.assertIsNone(limited.executor._limiters)

    async def test_health_checks_registered_and_run(self):
        daemon = AgentDaemon(Config.load())
        await daemon.memory.connect()
        try:
            daemon._register_health_checks()
            report = await daemon.health.check_all()
            names = {check["name"] for check in report["checks"]}
            self.assertIn("memory", names)
            self.assertIn("executor", names)
            # brain check degrades (no LLM configured in tests), not down
            self.assertIn(report["status"], ("ok", "degraded"))
        finally:
            await daemon.memory.close()

    async def test_ask_human_creates_approval_request(self):
        daemon = AgentDaemon(Config.load())
        await daemon.memory.connect()
        try:
            from tools.registry import ToolContext
            ctx = ToolContext(source="agent", memory=daemon.memory)
            result = await daemon.registry.call(
                "ask_human", {"question": "verify the deployment?"}, ctx)
            self.assertIn("operator", result)
            pending = daemon.approvals.pending()
            self.assertEqual(len(pending), 1)
        finally:
            await daemon.memory.close()


if __name__ == "__main__":
    unittest.main()

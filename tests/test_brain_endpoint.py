import tempfile
import unittest
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from interface.web import build_web_app
from kernel.config import Config
from kernel.daemon import AgentDaemon


class BrainEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_brain_report_shape(self):
        db = Path(tempfile.mkdtemp()) / "t.db"
        daemon = AgentDaemon(Config({"memory": {"db_path": str(db)}}))
        await daemon.memory.connect()
        client = TestClient(TestServer(build_web_app(daemon)))
        await client.start_server()
        try:
            daemon.costs.record("glm-5.3", 1000, 500, tier="remote")
            response = await client.get("/api/brain")
            self.assertEqual(response.status, 200)
            body = await response.json()
            for key in ("health", "tier_stats", "cache", "costs",
                        "costs_last_7_days", "budget", "lifecycle"):
                self.assertIn(key, body)
            self.assertIn("shutdown_drained_tasks", body["lifecycle"])
            self.assertGreaterEqual(body["lifecycle"]["shutdown_drained_tasks"],
                                    0)
            self.assertIn("hit_rate", body["cache"])
            self.assertIn("bridge_hits", body["cache"])
            self.assertIn("local", body["health"])
            self.assertIn("glm-5.3", body["costs"]["by_model"])
            self.assertIn("total_usd", body["costs"])
            self.assertGreaterEqual(body["budget"]["today_usd"], 0)
            window = body["costs_last_7_days"]
            self.assertEqual(len(window), 7)
            self.assertGreaterEqual(window[max(window)], 0)
        finally:
            await client.close()
            await daemon.memory.close()

    async def test_adapters_endpoint_aggregates_router_status(self):
        db = Path(tempfile.mkdtemp()) / "t.db"
        daemon = AgentDaemon(Config({"memory": {"db_path": str(db)}}))
        await daemon.memory.connect()
        client = TestClient(TestServer(build_web_app(daemon)))
        await client.start_server()
        try:
            response = await client.get("/api/adapters")
            self.assertEqual(response.status, 200)
            body = await response.json()
            self.assertIn("local", body["tiers"])
            self.assertIn("remote", body["tiers"])
            self.assertIn("hit_rate", body["cache"])
            for name in ("mock", "ollama", "openai_compat"):
                self.assertIn(name, body["catalog"]["available"])
            self.assertIn("stats", body)
            for tier in ("local", "remote"):
                self.assertIn(tier, body["stats"])
                self.assertIn("last_error", body["stats"][tier])
                self.assertIn("cooldown_remaining_s", body["stats"][tier])
            # per-adapter latency probes: mock always answers, the others
            # report honestly whatever their liveness is
            self.assertIn("ping", body)
            self.assertTrue(body["ping"]["mock"]["ok"])
            self.assertIn("latency_ms", body["ping"]["mock"])
            self.assertIn("checked_at", body["ping"])
        finally:
            await client.close()
            await daemon.memory.close()


if __name__ == "__main__":
    unittest.main()

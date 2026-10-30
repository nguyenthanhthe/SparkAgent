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
                        "costs_last_7_days", "budget", "lifecycle",
                        "adapters"):
                self.assertIn(key, body)
            # the adapters section merges the recorded ping history —
            # mock has been probed by earlier endpoint calls in other
            # tests only per-daemon; here the registry starts empty but
            # the section shape must hold
            self.assertIn("available", body["adapters"])
            self.assertIn("recent_ms", body["adapters"])
            self.assertIsInstance(body["adapters"]["recent_ms"], dict)
            self.assertIn("shutdown_drained_tasks", body["lifecycle"])
            self.assertGreaterEqual(body["lifecycle"]["shutdown_drained_tasks"],
                                    0)
            self.assertIn("T", body["lifecycle"]["started_at"])
            self.assertIn("hit_rate", body["cache"])
            self.assertIn("bridge_hits", body["cache"])
            self.assertIn("local", body["health"])
            self.assertIn("glm-5.3", body["costs"]["by_model"])
            self.assertIn("total_usd", body["costs"])
            self.assertGreaterEqual(body["budget"]["today_usd"], 0)
            self.assertGreater(body["budget"]["daily_limit_usd"], 0)
            window = body["costs_last_7_days"]
            self.assertEqual(len(window), 7)
            self.assertGreaterEqual(window[max(window)], 0)
        finally:
            await client.close()
            await daemon.memory.close()

    async def test_adapters_ping_opt_out(self):
        db = Path(tempfile.mkdtemp()) / "t.db"
        daemon = AgentDaemon(Config(
            {"memory": {"db_path": str(db)},
             "interface": {"ping_skip": ["mock"]}}))
        await daemon.memory.connect()
        client = TestClient(TestServer(build_web_app(daemon)))
        await client.start_server()
        try:
            body = await (await client.get("/api/adapters")).json()
            self.assertIsNone(body["ping"]["mock"]["ok"])
            self.assertIn("skipped", body["ping"]["mock"]["detail"])
        finally:
            await client.close()
            await daemon.memory.close()

    async def test_brain_adapters_section_merges_ping_history(self):
        db = Path(tempfile.mkdtemp()) / "t.db"
        daemon = AgentDaemon(Config({"memory": {"db_path": str(db)}}))
        await daemon.memory.connect()
        client = TestClient(TestServer(build_web_app(daemon)))
        await client.start_server()
        try:
            # probe mock once so latency_history grows by exactly one
            # sample (the registry is a process-global singleton, other
            # tests may have probed it already — assert relative growth)
            from brain.adapters import adapter_registry
            before = list(adapter_registry.latency_history.get("mock", []))
            await adapter_registry.ping("mock", {}, daemon.vault)
            after = adapter_registry.latency_history["mock"]
            self.assertEqual(len(after), len(before) + 1)

            body = await (await client.get("/api/brain")).json()
            recent = body["adapters"]["recent_ms"]
            self.assertIn("mock", recent)
            self.assertEqual(recent["mock"], after)
            # catalog names ride along, history is keyed by adapter name
            self.assertIn("mock", body["adapters"]["available"])
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
            self.assertIn("models", body["catalog"])
            self.assertTrue(body["catalog"]["models"]["openai_compat"])
        finally:
            await client.close()
            await daemon.memory.close()


if __name__ == "__main__":
    unittest.main()

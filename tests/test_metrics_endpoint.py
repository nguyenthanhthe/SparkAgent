"""JSON /api/metrics endpoint — counters/gauges/histograms snapshot."""

import unittest

from kernel.config import Config
from kernel.daemon import AgentDaemon


class MetricsEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def _setup(self):
        from aiohttp.test_utils import TestClient, TestServer
        from interface.web import build_web_app
        daemon = AgentDaemon(Config.load())
        await daemon.memory.connect()
        app = build_web_app(daemon)
        server = TestServer(app)
        client = TestClient(server)
        await client.start_server()
        return daemon, client

    async def test_json_metrics_snapshot(self):
        from kernel.metrics import REGISTRY
        REGISTRY.incr("test_json_metrics_calls", 3)
        daemon, client = await self._setup()
        try:
            response = await client.get("/api/metrics")
            self.assertEqual(response.status, 200)
            body = await response.json()
            self.assertIn("counters", body)
            self.assertIn("gauges", body)
            self.assertIn("histograms", body)
            self.assertGreaterEqual(body["counters"].get(
                "test_json_metrics_calls", 0), 3.0)
            self.assertIsInstance(body["uptime_s"], int)
        finally:
            await client.close()
            await daemon.memory.close()

    async def test_metrics_listed_in_openapi(self):
        from interface.openapi import build_spec
        spec = build_spec()
        self.assertIn("/api/metrics", spec["paths"])
        self.assertIn("/metrics", spec["paths"])


if __name__ == "__main__":
    unittest.main()

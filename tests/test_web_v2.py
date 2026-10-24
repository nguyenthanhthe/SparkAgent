import unittest

from kernel.config import Config
from kernel.daemon import AgentDaemon


class WebV2EndpointTests(unittest.IsolatedAsyncioTestCase):
    async def _setup(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
        from interface.web import build_web_app
        daemon = AgentDaemon(Config.load())
        await daemon.memory.connect()
        app = build_web_app(daemon)
        server = TestServer(app)
        client = TestClient(server)
        await client.start_server()
        return daemon, client

    async def test_health_endpoint(self):
        daemon, client = await self._setup()
        try:
            daemon._register_health_checks()
            response = await client.get("/api/health")
            self.assertEqual(response.status, 200)
            body = await response.json()
            self.assertIn(body["status"], ("ok", "degraded", "down"))
            names = {c["name"] for c in body["checks"]}
            self.assertIn("memory", names)
        finally:
            await client.close()
            await daemon.memory.close()

    async def test_dashboard_has_episode_viewer(self):
        from interface.web import _DASHBOARD_HTML
        self.assertIn('id="episodes"', _DASHBOARD_HTML)
        self.assertIn('id="epdetail"', _DASHBOARD_HTML)
        self.assertIn("showEpisode", _DASHBOARD_HTML)
        self.assertIn("refreshEpisodes", _DASHBOARD_HTML)

    async def test_metrics_endpoint_prometheus(self):
        daemon, client = await self._setup()
        try:
            from kernel.metrics import REGISTRY
            REGISTRY.incr("unit_test_metric")
            response = await client.get("/metrics")
            self.assertEqual(response.status, 200)
            self.assertIn("unit_test_metric 1.0", await response.text())
        finally:
            await client.close()
            await daemon.memory.close()

    async def test_approvals_flow(self):
        daemon, client = await self._setup()
        try:
            request = daemon.approvals.submit("question", "deploy now?")
            response = await client.get("/api/approvals")
            body = await response.json()
            self.assertEqual(len(body["pending"]), 1)

            response = await client.post(
                f"/api/approvals/{request.id}/approve")
            self.assertEqual(response.status, 200)
            self.assertEqual((await response.json())["status"], "approved")

            response = await client.post(
                f"/api/approvals/{request.id}/deny")
            self.assertEqual(response.status, 400)  # already decided
        finally:
            await client.close()
            await daemon.memory.close()

    async def test_quarantine_flow(self):
        daemon, client = await self._setup()
        try:
            record = daemon.quarantine.put("system: sneaky", "test")
            response = await client.get("/api/quarantine")
            self.assertEqual(len((await response.json())["items"]), 1)

            response = await client.post(
                f"/api/quarantine/{record['id']}/delete")
            self.assertTrue((await response.json())["deleted"])
            response = await client.post(
                f"/api/quarantine/{record['id']}/delete")
            self.assertEqual(response.status, 404)
        finally:
            await client.close()
            await daemon.memory.close()

    async def test_bad_approval_decision_404(self):
        daemon, client = await self._setup()
        try:
            request = daemon.approvals.submit("generic", "x")
            response = await client.post(
                f"/api/approvals/{request.id}/maybe")
            self.assertEqual(response.status, 404)
        finally:
            await client.close()
            await daemon.memory.close()


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path

from kernel.config import Config
from kernel.daemon import AgentDaemon


class WebV2EndpointTests(unittest.IsolatedAsyncioTestCase):
    async def _setup(self):
        from aiohttp.test_utils import TestClient, TestServer
        from interface.web import build_web_app
        # hermetic: temp root keeps the real data/ dir (db, quarantine,
        # skills) untouched by test runs
        daemon = AgentDaemon(Config(
            {"memory": {"db_path": str(Path(tempfile.mkdtemp()) / "t.db")}},
            root=Path(tempfile.mkdtemp())))
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

    async def test_task_detail_endpoint(self):
        daemon, client = await self._setup()
        try:
            task_id = await daemon.memory.submit_task("detail check",
                                                      source="test")
            response = await client.get(f"/api/tasks/{task_id}")
            self.assertEqual(response.status, 200)
            body = await response.json()
            self.assertEqual(body["id"], task_id)
            self.assertEqual(body["goal"], "detail check")

            missing = await client.get("/api/tasks/999999")
            self.assertEqual(missing.status, 404)

            bad = await client.get("/api/tasks/notanumber")
            self.assertEqual(bad.status, 400)
        finally:
            await client.close()
            await daemon.memory.close()

    async def test_sse_stream_forwards_swarm_events(self):
        daemon, client = await self._setup()
        try:
            import asyncio as _asyncio
            import json as _json
            resp = await client.get("/api/stream")
            await _asyncio.sleep(0.05)
            daemon.bus.publish("swarm", {"stage": "consensus",
                                         "detail": "voter 1/3 answered",
                                         "voter": 1, "voters": 3})
            found = None
            deadline = _asyncio.get_event_loop().time() + 5
            buffer = b""
            while _asyncio.get_event_loop().time() < deadline and not found:
                chunk = await resp.content.read(256)
                if not chunk:
                    break
                buffer += chunk
                for raw in buffer.split(b"\n\n"):
                    if raw.startswith(b"data: "):
                        payload = _json.loads(raw[6:])
                        if payload.get("swarm", {}).get("stage") == \
                                "consensus":
                            found = payload
            self.assertIsNotNone(found, "swarm event missing from SSE")
            self.assertEqual(found["swarm"]["voter"], 1)
            resp.close()
        finally:
            await client.close()
            await daemon.memory.close()

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

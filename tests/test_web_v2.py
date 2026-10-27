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

    async def test_dashboard_has_task_drawer(self):
        from interface.web import _DASHBOARD_HTML
        self.assertIn('id="taskdetail"', _DASHBOARD_HTML)
        self.assertIn("showTask", _DASHBOARD_HTML)
        self.assertIn("blocked_by", _DASHBOARD_HTML)

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

    async def test_quarantine_reason_filter(self):
        daemon, client = await self._setup()
        try:
            hit = daemon.quarantine.put("injection body",
                                        "prompt-injection risk")
            daemon.quarantine.put("oversized body",
                                  "oversized skill proposal")
            response = await client.get(
                "/api/quarantine?reason=prompt-injection")
            items = (await response.json())["items"]
            self.assertEqual([i["id"] for i in items], [hit["id"]])
            # comma-separated needles act as OR
            response = await client.get(
                "/api/quarantine?reason=prompt-injection,oversized")
            self.assertEqual(len((await response.json())["items"]), 2)
            response = await client.get("/api/quarantine")
            self.assertEqual(len((await response.json())["items"]), 2)
        finally:
            await client.close()
            await daemon.memory.close()

    async def test_backup_listing_endpoint(self):
        from ops.backup import create_backup
        daemon, client = await self._setup()
        try:
            data = daemon.cfg.root / "data"
            data.mkdir(parents=True, exist_ok=True)
            (data / "sparkagent.db").write_bytes(b"x")
            create_backup(data, daemon.cfg.root / "backups", tag="nightly")
            response = await client.get("/api/backup")
            self.assertEqual(response.status, 200)
            body = await response.json()
            self.assertEqual(len(body["archives"]), 1)
            archive = body["archives"][0]
            self.assertTrue(archive["name"].startswith("sparkagent-backup-"))
            self.assertEqual(archive["tag"], "nightly")
            self.assertGreaterEqual(archive["age_s"], 0)
        finally:
            await client.close()
            await daemon.memory.close()

    async def test_pause_resume_publish_scheduler_events(self):
        daemon, client = await self._setup()
        try:
            task_id = await daemon.memory.submit_task("demo", "test")
            queue = daemon.bus.subscribe("scheduler")
            for action, event in (("pause", "task_paused"),
                                  ("resume", "task_resumed")):
                response = await client.post(
                    f"/api/tasks/{task_id}/{action}")
                self.assertEqual(response.status, 200)
                events = []
                while not queue.empty():
                    events.append(queue.get_nowait())
                self.assertEqual([e["event"] for e in events], [event])
                self.assertEqual(events[0]["task_id"], task_id)
        finally:
            await client.close()
            await daemon.memory.close()

    async def test_memory_forget_endpoint_audited(self):
        daemon, client = await self._setup()
        try:
            await daemon.memory.remember("note to forget", kind="note",
                                         key="forget-me")
            response = await client.delete("/api/memories/forget-me")
            self.assertEqual(response.status, 200)
            # second delete: nothing left
            response = await client.delete("/api/memories/forget-me")
            self.assertEqual(response.status, 404)
            rows = await daemon.memory.recent_audit(limit=5)
            self.assertTrue(any(r["action"] == "memory.forget"
                                for r in rows))
        finally:
            await client.close()
            await daemon.memory.close()

    async def test_status_includes_quarantine_stats(self):
        daemon, client = await self._setup()
        try:
            daemon.quarantine.put("payload body", "test reason")
            response = await client.get("/api/status")
            stats = (await response.json())["quarantine"]
            self.assertEqual(stats["items"], 1)
            self.assertEqual(stats["bytes"], len(b"payload body"))
        finally:
            await client.close()
            await daemon.memory.close()

    async def test_tasks_list_marks_blocked_rows(self):
        daemon, client = await self._setup()
        try:
            first = await daemon.memory.submit_task("upstream", "test")
            second = await daemon.memory.submit_task(
                "downstream", "test", depends_on=[first])
            response = await client.get("/api/tasks")
            rows = {r["id"]: r
                    for r in (await response.json())["items"]}
            self.assertNotIn("blocked_by", rows[first])
            self.assertEqual(rows[second]["blocked_by"], [first])
        finally:
            await client.close()
            await daemon.memory.close()

    async def test_quarantine_item_endpoint(self):
        daemon, client = await self._setup()
        try:
            record = daemon.quarantine.put("suspect body", "test")
            response = await client.get(f"/api/quarantine/{record['id']}")
            body = await response.json()
            self.assertEqual(body["record"]["reason"], "test")
            self.assertEqual(body["content"], "suspect body")
            response = await client.get("/api/quarantine/unknown-id")
            self.assertEqual(response.status, 404)
        finally:
            await client.close()
            await daemon.memory.close()

    async def test_tasks_list_status_filter(self):
        daemon, client = await self._setup()
        try:
            tid = await daemon.memory.submit_task("filtered", "test")
            response = await client.get("/api/tasks?status=pending")
            rows = (await response.json())["items"]
            self.assertIn(tid, {r["id"] for r in rows})
            response = await client.get("/api/tasks?status=done")
            self.assertEqual((await response.json())["items"], [])
            response = await client.get("/api/tasks?status=weird")
            self.assertEqual(response.status, 400)
        finally:
            await client.close()
            await daemon.memory.close()

    async def test_docs_endpoint_allowlisted(self):
        daemon, client = await self._setup()
        try:
            # temp test root has no docs/ — deployed installs get the text
            response = await client.get("/api/docs/runbook-backups")
            self.assertEqual(response.status, 404)
            response = await client.get("/api/docs/../../secrets")
            self.assertEqual(response.status, 404)
            response = await client.get("/api/docs/not-a-runbook")
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

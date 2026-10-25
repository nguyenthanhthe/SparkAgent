"""Quarantine restore-with-approval — two-step release through the queue."""

import tempfile
import unittest
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from interface.web import build_web_app
from kernel.config import Config
from kernel.daemon import AgentDaemon


class QuarantineRestoreTests(unittest.IsolatedAsyncioTestCase):
    async def _setup(self):
        db = Path(tempfile.mkdtemp()) / "t.db"
        daemon = AgentDaemon(Config({"memory": {"db_path": str(db)}}))
        await daemon.memory.connect()
        client = TestClient(TestServer(build_web_app(daemon)))
        await client.start_server()
        item = daemon.quarantine.put("suspicious payload",
                                     reason="prompt injection",
                                     meta={"source": "web"})
        return daemon, client, item

    async def test_restore_requires_approval_first(self):
        daemon, client, item = await self._setup()
        try:
            response = await client.post(f"/api/quarantine/"
                                         f"{item['id']}/restore")
            self.assertEqual(response.status, 200)
            body = await response.json()
            self.assertEqual(body["status"], "pending_approval")
            # item still quarantined
            self.assertIn(item["id"],
                          str(daemon.quarantine.list(limit=10)))
        finally:
            await client.close()
            await daemon.memory.close()

    async def test_approved_restore_releases_content(self):
        daemon, client, item = await self._setup()
        try:
            first = await (await client.post(
                f"/api/quarantine/{item['id']}/restore")).json()
            decision = await client.post(
                f"/api/approvals/{first['approval_id']}/approve")
            self.assertEqual(decision.status, 200)
            second = await (await client.post(
                f"/api/quarantine/{item['id']}/restore")).json()
            self.assertEqual(second["status"], "restored")
            self.assertEqual(second["released"], "suspicious payload")
        finally:
            await client.close()
            await daemon.memory.close()

    async def test_restore_unknown_item_404(self):
        daemon, client, _item = await self._setup()
        try:
            response = await client.post("/api/quarantine/nope/restore")
            self.assertEqual(response.status, 404)
        finally:
            await client.close()
            await daemon.memory.close()

    async def test_denied_request_requeues_fresh_approval(self):
        daemon, client, item = await self._setup()
        try:
            first = await (await client.post(
                f"/api/quarantine/{item['id']}/restore")).json()
            await client.post(f"/api/approvals/{first['approval_id']}/deny")
            second = await (await client.post(
                f"/api/quarantine/{item['id']}/restore")).json()
            self.assertEqual(second["status"], "pending_approval")
            self.assertNotEqual(second["approval_id"],
                                first["approval_id"])
        finally:
            await client.close()
            await daemon.memory.close()


if __name__ == "__main__":
    unittest.main()

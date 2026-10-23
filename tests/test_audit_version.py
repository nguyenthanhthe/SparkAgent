import tempfile
import unittest
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from interface.web import build_web_app
from kernel.config import Config
from kernel.daemon import AgentDaemon


class AuditVersionEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def _client(self):
        db = Path(tempfile.mkdtemp()) / "t.db"
        daemon = AgentDaemon(Config({"memory": {"db_path": str(db)}}))
        await daemon.memory.connect()
        client = TestClient(TestServer(build_web_app(daemon)))
        await client.start_server()
        return daemon, client

    async def test_audit_rows_redacted_and_paginated(self):
        daemon, client = await self._client()
        try:
            for i in range(3):
                await daemon.memory.audit("test", "tick", f"row {i}")
            secret_marker = "sk-AUDITSECRETVALUE12345"
            await daemon.memory.audit("executor", "exec.start",
                                      f"python -c 'x={secret_marker}'")
            response = await client.get("/api/audit?limit=2")
            self.assertEqual(response.status, 200)
            body = await response.json()
            self.assertEqual(len(body["items"]), 2)
            self.assertTrue(body["has_more"])
            # newest row (the secret one) must be masked on page 1
            joined = str(body["items"])
            self.assertNotIn(secret_marker, joined)
            self.assertIn("REDACTED", joined)
        finally:
            await client.close()
            await daemon.memory.close()

    async def test_version_endpoint(self):
        daemon, client = await self._client()
        try:
            response = await client.get("/api/version")
            self.assertEqual(response.status, 200)
            body = await response.json()
            self.assertEqual(body["api"], "v2")
            self.assertIn("version", body)
            self.assertIn("python", body)
        finally:
            await client.close()
            await daemon.memory.close()

    async def test_audit_bad_params(self):
        daemon, client = await self._client()
        try:
            response = await client.get("/api/audit?limit=zero")
            self.assertEqual(response.status, 400)
        finally:
            await client.close()
            await daemon.memory.close()


if __name__ == "__main__":
    unittest.main()

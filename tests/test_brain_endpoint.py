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
            for key in ("health", "tier_stats", "costs", "budget"):
                self.assertIn(key, body)
            self.assertIn("local", body["health"])
            self.assertIn("glm-5.3", body["costs"]["by_model"])
            self.assertIn("total_usd", body["costs"])
            self.assertGreaterEqual(body["budget"]["today_usd"], 0)
        finally:
            await client.close()
            await daemon.memory.close()


if __name__ == "__main__":
    unittest.main()

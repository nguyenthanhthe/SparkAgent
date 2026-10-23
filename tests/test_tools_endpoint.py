import tempfile
import unittest
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from interface.web import build_web_app
from kernel.config import Config
from kernel.daemon import AgentDaemon


class ToolsEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_lists_all_registered_tools(self):
        db = Path(tempfile.mkdtemp()) / "t.db"
        daemon = AgentDaemon(Config({"memory": {"db_path": str(db)}}))
        await daemon.memory.connect()
        client = TestClient(TestServer(build_web_app(daemon)))
        await client.start_server()
        try:
            response = await client.get("/api/tools")
            self.assertEqual(response.status, 200)
            body = await response.json()
            self.assertEqual(body["count"], len(body["tools"]))
            names = {tool["name"] for tool in body["tools"]}
            for expected in ("calculate", "web_fetch", "swarm_delegate",
                             "skill_create", "graph_query"):
                self.assertIn(expected, names)
            dangerous = [t for t in body["tools"] if t["dangerous"]]
            self.assertTrue(dangerous)          # skill_create etc.
            example = body["tools"][0]
            for key in ("name", "description", "parameters", "source"):
                self.assertIn(key, example)
        finally:
            await client.close()
            await daemon.memory.close()


if __name__ == "__main__":
    unittest.main()

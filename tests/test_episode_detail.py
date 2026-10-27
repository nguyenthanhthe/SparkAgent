import asyncio
import tempfile
import unittest
from pathlib import Path

from kernel.memory import Memory


def run(coro):
    return asyncio.run(coro)


class EpisodeDetailTests(unittest.TestCase):
    def setUp(self):
        self.db = Path(tempfile.mkdtemp()) / "t.db"
        self.mem = Memory(self.db, embedder_fn=None, embed_dim=64)

    def tearDown(self):
        if self.mem._conn:
            self.mem._conn.close()

    def seed(self) -> int:
        async def scenario():
            await self.mem.connect()
            eid = await self.mem.start_episode("replay me", "test")
            await self.mem.log_step(eid, 1, "action",
                                    '{"tool": "web_fetch"}')
            await self.mem.log_step(eid, 2, "observation", "OK: page text")
            await self.mem.log_step(eid, 3, "final", "all done here")
            await self.mem.finish_episode(eid, "done", "all done here",
                                          "local", 3)
            return eid
        return run(scenario())

    def test_detail_with_steps(self):
        eid = self.seed()
        detail = run(self.mem.episode_detail(eid))
        self.assertEqual(detail["goal"], "replay me")
        self.assertEqual(detail["status"], "done")
        self.assertEqual(len(detail["step_log"]), 3)
        self.assertEqual(detail["step_count"], 3)
        self.assertEqual(detail["step_log"][0]["idx"], 1)
        self.assertEqual(detail["step_log"][2]["kind"], "final")

    def test_unknown_episode_returns_none(self):
        self.seed()
        self.assertIsNone(run(self.mem.episode_detail(9999)))


class EpisodeDetailEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def _client(self):
        from aiohttp.test_utils import TestClient, TestServer
        from kernel.config import Config
        from kernel.daemon import AgentDaemon
        from interface.web import build_web_app
        daemon = AgentDaemon(Config.load())
        await daemon.memory.connect()
        client = TestClient(TestServer(build_web_app(daemon)))
        await client.start_server()
        return daemon, client

    async def test_endpoint_replay(self):
        daemon, client = await self._client()
        try:
            eid = await daemon.memory.start_episode("api replay", "test")
            await daemon.memory.log_step(eid, 1, "action", "called tool")
            await daemon.memory.finish_episode(eid, "done", "answer",
                                               "local", 1)
            response = await client.get(f"/api/episodes/{eid}")
            self.assertEqual(response.status, 200)
            body = await response.json()
            self.assertEqual(body["goal"], "api replay")
            self.assertEqual(body["step_log"][0]["content"], "called tool")
        finally:
            await client.close()
            await daemon.memory.close()

    async def test_endpoint_404_and_400(self):
        daemon, client = await self._client()
        try:
            response = await client.get("/api/episodes/99999")
            self.assertEqual(response.status, 404)
            response = await client.get("/api/episodes/notanumber")
            self.assertEqual(response.status, 400)
        finally:
            await client.close()
            await daemon.memory.close()


if __name__ == "__main__":
    unittest.main()

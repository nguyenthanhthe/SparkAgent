"""/api/memories combined filters — kind list and episode tag."""

import tempfile
import unittest
from pathlib import Path

from aiohttp.test_utils import TestClient, TestServer

from interface.web import build_web_app
from kernel.config import Config
from kernel.daemon import AgentDaemon


class MemoriesFilterTests(unittest.IsolatedAsyncioTestCase):
    async def _setup(self):
        db = Path(tempfile.mkdtemp()) / "t.db"
        daemon = AgentDaemon(Config({"memory": {"db_path": str(db)}}))
        await daemon.memory.connect()
        client = TestClient(TestServer(build_web_app(daemon)))
        await client.start_server()
        return daemon, client

    async def test_kind_filter_restricts_hits(self):
        daemon, client = await self._setup()
        try:
            await daemon.memory.remember("gpu thermal notes from ops",
                                         kind="note", key="note-1")
            episode_id = await daemon.memory.start_episode(
                "gpu thermal episode", source="test")
            await daemon.memory.finish_episode(episode_id, "done",
                                               "answer", "local", 1)
            await daemon.memory.remember("gpu thermal episode summary",
                                         kind="episode",
                                         key=f"episode:{episode_id}")
            tagged = await (await client.get(
                "/api/memories?q=thermal&kind=episode")).json()
            self.assertTrue(tagged)
            self.assertTrue(all(h["kind"] == "episode" for h in tagged))
            untagged = await (await client.get(
                "/api/memories?q=thermal&kind=note")).json()
            self.assertTrue(untagged)
            self.assertTrue(all(h["kind"] == "note" for h in untagged))
        finally:
            await client.close()
            await daemon.memory.close()

    async def test_tag_filter_scopes_to_episode(self):
        daemon, client = await self._setup()
        try:
            await daemon.memory.remember("thermal unrelated note",
                                         kind="note", key="note-1")
            episode_id = await daemon.memory.start_episode(
                "fix the thermal issue", source="test")
            await daemon.memory.finish_episode(episode_id, "done",
                                               "answer", "local", 1)
            await daemon.memory.remember("thermal fix episode summary",
                                         kind="episode",
                                         key=f"episode:{episode_id}")
            hits = await (await client.get(
                f"/api/memories?q=thermal&tag=gpu")).json()
            for hit in hits:
                self.assertEqual(hit["key"], f"episode:{episode_id}")
        finally:
            await client.close()
            await daemon.memory.close()

    async def test_tag_without_matches_returns_empty(self):
        daemon, client = await self._setup()
        try:
            await daemon.memory.remember("thermal note", key="n")
            body = await (await client.get(
                "/api/memories?q=thermal&tag=nosuchtag")).json()
            self.assertEqual(body, [])
        finally:
            await client.close()
            await daemon.memory.close()

    async def test_combined_kind_and_tag(self):
        daemon, client = await self._setup()
        try:
            await daemon.memory.remember("thermal plain note", kind="note",
                                         key="note-1")
            episode_id = await daemon.memory.start_episode(
                "thermal episode body", source="test")
            await daemon.memory.finish_episode(episode_id, "done",
                                               "answer", "local", 1)
            await daemon.memory.remember("thermal episode summary",
                                         kind="episode",
                                         key=f"episode:{episode_id}")
            hits = await (await client.get(
                "/api/memories?q=thermal&kind=note&tag=gpu")).json()
            # the tag scopes to the episode, then the kind filter drops it
            self.assertEqual(hits, [])
        finally:
            await client.close()
            await daemon.memory.close()


if __name__ == "__main__":
    unittest.main()

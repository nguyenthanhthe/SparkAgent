import asyncio
import tempfile
import unittest
from pathlib import Path

from kernel.memory import Memory, extract_tags


def run(coro):
    return asyncio.run(coro)


class ExtractTagsTests(unittest.TestCase):
    def test_basic_extraction(self):
        self.assertEqual(extract_tags("check #gpu load on the #server"),
                         ["gpu", "server"])

    def test_case_and_dedup(self):
        self.assertEqual(extract_tags("#GPU and #gpu and #Gpu"),
                         ["gpu"])

    def test_invalid_patterns_ignored(self):
        self.assertEqual(extract_tags("# a #1x #-no #ok"), ["ok"])

    def test_cap_and_empty(self):
        self.assertEqual(extract_tags("#a #b #c #d #e #f #g"),
                         ["a", "b", "c", "d", "e"])
        self.assertEqual(extract_tags("no tags here"), [])


class EpisodeTagTests(unittest.TestCase):
    def setUp(self):
        self.db = Path(tempfile.mkdtemp()) / "t.db"
        self.mem = Memory(self.db, embedder_fn=None, embed_dim=64)
        run(self.mem.connect())

    def tearDown(self):
        if self.mem._conn:
            self.mem._conn.close()

    def test_tags_persisted_from_goal(self):
        async def scenario():
            eid = await self.mem.start_episode("audit #security of #web",
                                               "operator")
            await self.mem.finish_episode(eid, "done", "ok", "local", 1)
            episodes = await self.mem.recent_episodes()
            self.assertEqual(episodes[0]["tags"], ["security", "web"])
        run(scenario())

    def test_tag_filter(self):
        async def scenario():
            for goal in ("fix #gpu thermal", "write #docs page",
                         "tune #gpu fans"):
                eid = await self.mem.start_episode(goal, "operator")
                await self.mem.finish_episode(eid, "done", "x", "local", 1)
            gpu = await self.mem.recent_episodes(tag="gpu")
            self.assertEqual(len(gpu), 2)
            docs = await self.mem.recent_episodes(tag="#docs")  # # ok too
            self.assertEqual(len(docs), 1)
        run(scenario())

    def test_untagged_episodes_have_empty_list(self):
        async def scenario():
            eid = await self.mem.start_episode("plain goal", "operator")
            await self.mem.finish_episode(eid, "done", "x", "local", 1)
            episodes = await self.mem.recent_episodes()
            self.assertEqual(episodes[0]["tags"], [])
        run(scenario())

    def test_migration_idempotent(self):
        # reopening the same db must not re-alter or fail
        self.mem._conn.close()
        run(self.mem.connect())
        rows = self.mem._conn.execute("PRAGMA table_info(episodes)")
        tag_columns = [r["name"] for r in rows if r["name"] == "tags"]
        self.assertEqual(len(tag_columns), 1)


if __name__ == "__main__":
    unittest.main()

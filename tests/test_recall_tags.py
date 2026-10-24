import asyncio
import tempfile
import unittest
from pathlib import Path

from kernel.memory import Memory


def run(coro):
    return asyncio.run(coro)


class RecallTagEnrichmentTests(unittest.TestCase):
    def setUp(self):
        self.db = Path(tempfile.mkdtemp()) / "t.db"
        self.mem = Memory(self.db, embedder_fn=None, embed_dim=128)

    def tearDown(self):
        if self.mem._conn:
            self.mem._conn.close()

    def seed(self):
        async def scenario():
            await self.mem.connect()
            episode_id = await self.mem.start_episode(
                "debug #gpu #thermal throttling", source="test")
            await self.mem.finish_episode(episode_id, "success", "done",
                                          "local", 3)
            await self.mem.remember("gpu thermal episode recap",
                                    kind="episode",
                                    key=f"episode:{episode_id}")
            await self.mem.remember("unrelated note about python", kind="note")
        run(scenario())

    def test_episode_linked_hit_carries_tags(self):
        self.seed()
        hits = run(self.mem.recall("gpu thermal episode"))
        tagged = [h for h in hits if h.key and h.key.startswith("episode:")]
        self.assertTrue(tagged, "episode-linked hit missing")
        self.assertEqual(tagged[0].tags, ["gpu", "thermal"])

    def test_non_episode_hits_have_no_tags(self):
        self.seed()
        hits = run(self.mem.recall("python note"))
        for hit in hits:
            if not (hit.key or "").startswith("episode:"):
                self.assertIsNone(hit.tags)

    def test_missing_episode_yields_empty_tags(self):
        async def scenario():
            await self.mem.connect()
            await self.mem.remember("orphan episode recap", kind="episode",
                                    key="episode:99999")
        run(scenario())
        hits = run(self.mem.recall("orphan episode"))
        self.assertTrue(hits)
        self.assertEqual(hits[0].tags, [])


if __name__ == "__main__":
    unittest.main()

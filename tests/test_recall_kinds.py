import asyncio
import tempfile
import unittest
from pathlib import Path

from kernel.memory import Memory


def run(coro):
    return asyncio.run(coro)


class RecallKindFilterTests(unittest.TestCase):
    def setUp(self):
        self.db = Path(tempfile.mkdtemp()) / "t.db"
        self.mem = Memory(self.db, embedder_fn=None, embed_dim=128)

    def tearDown(self):
        if self.mem._conn:
            self.mem._conn.close()

    def seed(self):
        async def scenario():
            await self.mem.connect()
            await self.mem.remember("gpu thermal throttling data",
                                    kind="digest")
            await self.mem.remember("gpu thermal preference: cap at 85c",
                                    kind="preference")
            await self.mem.remember("gpu thermal episode summary",
                                    kind="episode")
        run(scenario())

    def test_filter_by_single_kind(self):
        self.seed()
        hits = run(self.mem.recall("gpu thermal", kinds=["digest"]))
        self.assertTrue(hits)
        self.assertEqual({h.kind for h in hits}, {"digest"})

    def test_filter_by_multiple_kinds(self):
        self.seed()
        hits = run(self.mem.recall("gpu thermal",
                                   kinds=["digest", "episode"]))
        self.assertEqual({h.kind for h in hits}, {"digest", "episode"})

    def test_no_filter_returns_all(self):
        self.seed()
        hits = run(self.mem.recall("gpu thermal"))
        self.assertEqual(len(hits), 3)

    def test_unknown_kind_returns_empty(self):
        self.seed()
        self.assertEqual(run(self.mem.recall("gpu thermal",
                                             kinds=["nonexistent"])), [])

    def test_results_still_ranked(self):
        self.seed()
        hits = run(self.mem.recall("throttling", kinds=["digest"]))
        self.assertTrue(hits[0].text.startswith("gpu thermal throttling"))


if __name__ == "__main__":
    unittest.main()

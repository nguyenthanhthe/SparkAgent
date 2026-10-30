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

    def test_exclude_kinds_drops_the_kind(self):
        self.seed()
        hits = run(self.mem.recall("gpu thermal", exclude_kinds=["digest"]))
        self.assertTrue(hits)
        self.assertNotIn("digest", {h.kind for h in hits})
        self.assertEqual(len(hits), 2)

    def test_exclude_kinds_complements_kinds(self):
        self.seed()
        hits = run(self.mem.recall("gpu thermal", kinds=["digest", "note",
                                                         "preference"],
                                   exclude_kinds=["note", "preference"]))
        self.assertEqual({h.kind for h in hits}, {"digest"})

    def test_exclude_kinds_keeps_digest_marker_default(self):
        # digest markers stay bookkeeping-excluded unless asked via kinds,
        # even when the caller excludes other kinds
        async def scenario():
            await self.mem.connect()
            await self.mem.remember("gpu thermal digest marker",
                                    kind="digest-marker")
            await self.mem.remember("gpu thermal episode", kind="episode")
        run(scenario())
        hits = run(self.mem.recall("gpu thermal",
                                   exclude_kinds=["episode"]))
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()

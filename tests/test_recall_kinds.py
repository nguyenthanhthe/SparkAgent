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

    def test_created_after_keeps_only_recent_rows(self):
        async def scenario():
            await self.mem.connect()
            old_id = await self.mem.remember("gpu thermal old data",
                                             kind="note")
            # backdate the stored stamp directly — the SQL bound does the
            # time travel, not the clock
            self.mem._conn.execute(
                "UPDATE memories SET created_at = '2020-01-01T00:00:00' "
                "WHERE id = ?", (old_id,))
            self.mem._conn.commit()
            await self.mem.remember("gpu thermal new data", kind="note")
        run(scenario())
        hits = run(self.mem.recall("gpu thermal",
                                   created_after="2026-01-01"))
        self.assertEqual(len(hits), 1)
        self.assertIn("new data", hits[0].text)
        # date-only and datetime bounds behave the same at midnight
        hits_dt = run(self.mem.recall("gpu thermal",
                                      created_after="2025-12-31T23:59:59"))
        self.assertEqual(len(hits_dt), 1)

    def test_ids_filter_pins_the_candidate_pool(self):
        async def scenario():
            await self.mem.connect()
            first = await self.mem.remember("gpu thermal data one")
            await self.mem.remember("gpu thermal data two")
            third = await self.mem.remember("gpu thermal data three")
            hits = await self.mem.recall("gpu thermal",
                                         ids=[first, third])
            self.assertEqual({h.id for h in hits}, {first, third})
            # an empty ids list is treated as no filter
            hits_all = await self.mem.recall("gpu thermal", ids=[])
            self.assertEqual(len(hits_all), 3)
        run(scenario())

    def test_recall_exposes_candidate_pool_size(self):
        async def scenario():
            await self.mem.connect()
            for i in range(3):
                await self.mem.remember(f"gpu thermal note {i}")
            self.assertIsNone(self.mem.last_recall_pool_size)
            await self.mem.recall("gpu thermal")
            self.assertEqual(self.mem.last_recall_pool_size, 3)
            await self.mem.recall("gpu thermal", kinds=["nonexistent"])
            self.assertEqual(self.mem.last_recall_pool_size, 0)
        run(scenario())

    def test_created_after_validates_format(self):
        async def scenario():
            await self.mem.connect()
            await self.mem.remember("gpu thermal data")
        run(scenario())
        for bad in ("not-a-date", "2026-13-01", "2026-01-01T99:00"):
            with self.assertRaises(ValueError) as ctx:
                run(self.mem.recall("gpu thermal", created_after=bad))
            self.assertIn("created_after", str(ctx.exception))
            self.assertIn(bad, str(ctx.exception))


if __name__ == "__main__":
    unittest.main()

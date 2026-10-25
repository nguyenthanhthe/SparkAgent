"""Graph-boosted recall — entity-graph proximity nudges hybrid ranking."""

import asyncio
import tempfile
import unittest
from pathlib import Path

from memory_search.graph_boost import GraphBooster
from memory_search.graph_store import GraphStore
from kernel.memory import Memory


class GraphBoosterTests(unittest.TestCase):
    def setUp(self):
        self.graph = GraphStore()
        self.graph.add("sparkagent", "deployed_on", "rtx4050")
        self.graph.add("rtx4050", "runs", "nemotron")
        self.booster = GraphBooster(self.graph, weight=0.05)

    def test_query_node_yields_neighbors(self):
        related = self.booster.related_entities("how is sparkagent doing")
        self.assertIn("sparkagent", related)
        self.assertIn("rtx4050", related["sparkagent"])
        self.assertIn("nemotron", related["sparkagent"])

    def test_unrelated_query_empty(self):
        self.assertEqual(self.booster.related_entities("weather today"), {})

    def test_boost_counts_related_mentions(self):
        text = "the rtx4050 thermals are ok, says rtx4050 monitoring"
        boost = self.booster.boost("sparkagent", text)
        self.assertAlmostEqual(boost, 0.10)  # two mentions of rtx4050

    def test_boost_capped(self):
        text = " ".join(["rtx4050"] * 50)
        boost = self.booster.boost("sparkagent", text)
        self.assertEqual(boost, self.booster.max_boost)

    def test_no_overlap_no_boost(self):
        self.assertEqual(self.booster.boost("sparkagent", "nothing here"),
                         0.0)

    def test_empty_graph_no_boost(self):
        booster = GraphBooster(GraphStore())
        self.assertEqual(booster.boost("sparkagent", "sparkagent"), 0.0)


class GraphBoostRecallTests(unittest.TestCase):
    def test_boost_raises_hit_scores(self):
        async def scenario():
            db = Path(tempfile.mkdtemp()) / "t.db"
            mem = Memory(db, embedder_fn=None, embed_dim=64)
            await mem.connect()
            graph = GraphStore()
            graph.add("postgres", "blocked_by", "migration-7")
            try:
                await mem.remember(
                    "migration-7 migration-7 migration-7 rollout overnight",
                    key="a")
                await mem.remember("unrelated coffee machine note", key="b")
                plain = {h.text: h.score
                         for h in await mem.recall("postgres migration")}
                mem.graph_store = graph
                boosted = {h.text: h.score
                           for h in await mem.recall("postgres migration")}
                self.assertGreater(
                    boosted["migration-7 migration-7 migration-7 rollout "
                            "overnight"],
                    plain["migration-7 migration-7 migration-7 rollout "
                          "overnight"])
            finally:
                await mem.close()
        asyncio.run(scenario())

    def test_recall_without_graph_unchanged(self):
        async def scenario():
            db = Path(tempfile.mkdtemp()) / "t.db"
            mem = Memory(db, embedder_fn=None, embed_dim=64)
            await mem.connect()
            try:
                await mem.remember("alpha beta gamma", key="a")
                hits = await mem.recall("alpha")
                self.assertEqual(len(hits), 1)
                self.assertIsNone(mem.graph_store)
            finally:
                await mem.close()
        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()

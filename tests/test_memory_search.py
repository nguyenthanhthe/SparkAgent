import tempfile
import time
import unittest
from pathlib import Path

from memory_search.bm25 import BM25Index, tokenize
from memory_search.graph_store import GraphStore
from memory_search.hybrid import HybridRanker


class BM25Tests(unittest.TestCase):
    def test_rare_terms_win(self):
        index = BM25Index()
        index.add("d1", "the gpu runs hot during inference")
        index.add("d2", "error 0x80070005 blocked the update")
        index.add("d3", "gpu tuning guide for laptop")
        hits = index.search("0x80070005")
        self.assertEqual(hits[0][0], "d2")
        hits = index.search("gpu hot")
        self.assertEqual(hits[0][0], "d1")

    def test_no_overlap_empty(self):
        index = BM25Index()
        index.add("d1", "alpha beta")
        self.assertEqual(index.search("zzz"), [])

    def test_remove(self):
        index = BM25Index()
        index.add("d1", "unique tokens here")
        self.assertTrue(index.remove("d1"))
        self.assertFalse(index.remove("d1"))
        self.assertEqual(index.search("unique"), [])

    def test_re_add_replaces(self):
        index = BM25Index()
        index.add("d1", "old content")
        index.add("d1", "brand new content only")
        self.assertEqual(len(index), 1)
        self.assertEqual(index.search("brand")[0][0], "d1")
        self.assertEqual(index.search("old"), [])

    def test_stats(self):
        index = BM25Index()
        index.add("d1", "one two three")
        stats = index.stats()
        self.assertEqual(stats["docs"], 1)
        self.assertGreater(stats["vocabulary"], 0)

    def test_tokenize_drops_stopwords(self):
        self.assertNotIn("the", tokenize("the quick fox"))
        self.assertIn("quick", tokenize("the quick fox"))


class HybridRankerTests(unittest.TestCase):
    def test_lexical_only_when_no_vector(self):
        ranker = HybridRanker()
        ranker.add("d1", "gpu thermals are high")
        ranker.add("d2", "meeting notes unrelated")
        hits = ranker.search("gpu thermals")
        self.assertEqual(hits[0].doc_id, "d1")
        self.assertIsNotNone(hits[0].lexical_rank)
        self.assertIsNone(hits[0].vector_rank)

    def test_rrf_fusion_prefers_dual_agreement(self):
        def vector(query, top):
            # vector index returns d2 first, d1 second
            return [("d2", 0.9), ("d1", 0.85)]

        ranker = HybridRanker(vector_search=vector)
        ranker.add("d1", "gpu thermal throttling analysis")
        ranker.add("d2", "gpu thermal overview summary")
        ranker.add("d3", "unrelated cooking recipe")
        hits = ranker.search("gpu thermal")
        # d2: lexical rank 2 + vector rank 1; d1: lexical rank 1 + vector rank 2
        # both agree on both channels -> both beat d3; check ordering sane
        self.assertLessEqual(hits[0].fused_score, 2 / 61.0 + 0.1)
        top_ids = {h.doc_id for h in hits[:2]}
        self.assertEqual(top_ids, {"d1", "d2"})

    def test_vector_failure_degrades_to_lexical(self):
        def broken(query, top):
            raise RuntimeError("vector index offline")

        ranker = HybridRanker(vector_search=broken)
        ranker.add("d1", "specific error code 0x1234")
        hits = ranker.search("error code 0x1234")
        self.assertEqual(hits[0].doc_id, "d1")

    def test_recency_boost_breaks_ties(self):
        now = time.time()
        ranker = HybridRanker(recency_weight=0.5)
        ranker.add("old", "gpu thermal result", timestamp=now - 90 * 86400)
        ranker.add("new", "gpu thermal result", timestamp=now)
        hits = ranker.search("gpu thermal")
        self.assertEqual(hits[0].doc_id, "new")

    def test_remove_and_len(self):
        ranker = HybridRanker()
        ranker.add("d1", "text")
        self.assertEqual(len(ranker), 1)
        ranker.remove("d1")
        self.assertEqual(len(ranker), 0)

    def test_stats_shape(self):
        ranker = HybridRanker()
        self.assertFalse(ranker.stats()["vector_enabled"])


class GraphStoreTests(unittest.TestCase):
    def test_add_and_neighbors(self):
        graph = GraphStore()
        graph.add("sparkagent", "uses", "ollama", source="ep1")
        graph.add("sparkagent", "uses", "sqlite")
        graph.add("ollama", "serves", "nemotron")
        neighbors = graph.neighbors("sparkagent")
        self.assertEqual(len(neighbors), 2)
        self.assertIn("ollama", graph.nodes())
        self.assertEqual(graph.edge_count(), 3)

    def test_dedupe_exact_triples(self):
        graph = GraphStore()
        graph.add("a", "rel", "b", weight=1.0)
        graph.add("a", "rel", "b", weight=3.0, source="ep2")
        self.assertEqual(graph.edge_count(), 1)
        edge = graph.relations("a", "b")[0]
        self.assertEqual(edge.weight, 3.0)   # weight upgraded, one edge

    def test_inverse_lookup(self):
        graph = GraphStore()
        graph.add("x", "depends_on", "y")
        neighbors = graph.neighbors("y")
        self.assertEqual(len(neighbors), 1)
        self.assertIn("depends_on", graph.facts_about("y")[0])

    def test_traverse_two_hops(self):
        graph = GraphStore()
        graph.add("a", "to", "b")
        graph.add("b", "to", "c")
        graph.add("c", "to", "d")
        reached = graph.traverse("a", max_hops=2)
        self.assertIn("b", reached)
        self.assertIn("c", reached)
        self.assertNotIn("d", reached)       # three hops away

    def test_traverse_respects_node_cap(self):
        graph = GraphStore()
        for i in range(30):
            graph.add("hub", "link", f"node-{i}")
        reached = graph.traverse("hub", max_hops=1, max_nodes=10)
        self.assertLessEqual(len(reached), 10)

    def test_remove_edge(self):
        graph = GraphStore()
        edge = graph.add("a", "r", "b")
        self.assertTrue(graph.remove(edge.id))
        self.assertFalse(graph.remove(edge.id))
        self.assertEqual(graph.edge_count(), 0)

    def test_invalid_nodes_rejected(self):
        graph = GraphStore()
        with self.assertRaises(ValueError):
            graph.add("", "r", "b")
        with self.assertRaises(ValueError):
            graph.add("a", "r", "x" * 300)

    def test_persistence_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "graph.json"
            graph = GraphStore()
            graph.add("a", "r1", "b", source="s")
            graph.add("b", "r2", "c")
            count = graph.save(path)
            self.assertEqual(count, 2)

            restored = GraphStore()
            loaded = restored.load(path)
            self.assertEqual(loaded, 2)
            self.assertEqual(restored.edge_count(), 2)
            self.assertTrue(restored.relations("a", "b"))

    def test_load_missing_file_zero(self):
        self.assertEqual(GraphStore().load(Path("no/such/file.json")), 0)


if __name__ == "__main__":
    unittest.main()

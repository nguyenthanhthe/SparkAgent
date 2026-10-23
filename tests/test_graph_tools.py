import unittest

from kernel.errors import ToolFailure
from memory_search.graph_store import GraphStore
from tools.graph_tools import extract_triples, register_tools
from tools.registry import ToolContext, ToolRegistry
from kernel.bus import EventBus


class ExtractionTests(unittest.TestCase):
    def test_uses_relation(self):
        text = "SparkAgent uses Ollama for local inference on the GPU."
        triples = extract_triples(text)
        self.assertIn(("sparkagent", "uses", "ollama"), triples)

    def test_is_a_relation(self):
        text = "Ollama is a local model server with a REST API."
        triples = extract_triples(text)
        self.assertIn(("ollama", "isa", "local model server"), triples)

    def test_caused_by_relation(self):
        text = "The outage was caused by a failed CUDA driver update."
        triples = extract_triples(text)
        self.assertTrue(any(t[0] == "the outage" and t[1] == "caused_by"
                            for t in triples))

    def test_pronouns_rejected(self):
        text = "It uses that daily. This is a test."
        self.assertEqual(extract_triples(text), [])

    def test_dedupe(self):
        text = ("The agent uses sqlite. The agent uses sqlite. "
                "The agent uses sqlite.")
        triples = extract_triples(text)
        uses = [t for t in triples if t[1] == "uses"]
        self.assertEqual(len(uses), 1)


class GraphToolTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.graph = GraphStore()
        self.registry = ToolRegistry(EventBus())
        register_tools(self.registry, self.graph)
        self.ctx = ToolContext(source="agent")

    async def test_extract_stores_triples(self):
        result = await self.registry.call(
            "extract_entities",
            {"text": "SparkAgent uses sqlite for memory and is a "
                     "local agent framework.", "source": "docs"}, self.ctx)
        self.assertIn('"added":1', result.replace(" ", ""))
        facts = self.graph.facts_about("sparkagent")
        self.assertTrue(any("uses--> sqlite" in f for f in facts))

    async def test_graph_query_facts(self):
        self.graph.add("a", "uses", "b")
        result = await self.registry.call(
            "graph_query", {"node": "a", "operation": "facts"}, self.ctx)
        self.assertIn("a --uses--> b", result)

    async def test_graph_query_traverse(self):
        self.graph.add("a", "to", "b")
        self.graph.add("b", "to", "c")
        result = await self.registry.call(
            "graph_query", {"node": "a", "operation": "traverse",
                            "hops": 2}, self.ctx)
        self.assertIn("c", result)

    async def test_graph_query_stats(self):
        result = await self.registry.call(
            "graph_query", {"node": "x", "operation": "stats"}, self.ctx)
        self.assertIn("edge", result.lower())

    async def test_bad_operation_rejected(self):
        self.graph.add("a", "r", "b")
        with self.assertRaises(ToolFailure):
            await self.registry.call(
                "graph_query", {"node": "a", "operation": "frobnicate"},
                self.ctx)

    async def test_empty_extraction(self):
        result = await self.registry.call(
            "extract_entities", {"text": "nothing relational here at all"},
            self.ctx)
        self.assertIn('"added":0', result.replace(" ", ""))


if __name__ == "__main__":
    unittest.main()

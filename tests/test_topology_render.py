"""Swarm topology catalog — names, descriptions, mermaid diagrams, API."""

import unittest

from swarm.render import markdown_section, topology_catalog, topology_mermaid
from swarm.topologies import map_reduce, parallel, sequential, star

EXPECTED_TOPOLOGIES = {"sequential", "parallel", "star", "debate",
                       "map_reduce"}


class CatalogTests(unittest.TestCase):
    def test_all_five_topologies_listed(self):
        names = {entry["name"] for entry in topology_catalog()}
        self.assertEqual(names, EXPECTED_TOPOLOGIES)

    def test_entries_have_description_and_mermaid(self):
        for entry in topology_catalog():
            self.assertTrue(entry["description"])
            self.assertIn("flowchart", entry["mermaid"])

    def test_catalog_copies_are_independent(self):
        catalog = topology_catalog()
        catalog[0]["name"] = "mutated"
        self.assertIn("sequential", {e["name"] for e in topology_catalog()})

    def test_mermaid_by_name(self):
        diagram = topology_mermaid("debate")
        self.assertIsNotNone(diagram)
        self.assertIn("proponent", diagram)
        self.assertIn("opponent", diagram)
        self.assertIsNone(topology_mermaid("nope"))

    def test_diagram_labels_match_implementations(self):
        # sequential labels stages; parallel/workers; star hub+spokes
        self.assertIn("stage 1", topology_mermaid("sequential"))
        self.assertIn("worker 1", topology_mermaid("parallel"))
        self.assertIn("hub", topology_mermaid("star"))
        self.assertIn("reducer", topology_mermaid("map_reduce"))

    def test_committed_topology_doc_in_sync(self):
        from pathlib import Path
        doc = Path(__file__).resolve().parents[1] / "docs" / "topologies.md"
        self.assertTrue(doc.exists(), "docs/topologies.md missing")
        self.assertEqual(doc.read_text(encoding="utf-8"),
                         markdown_section(),
                         "docs/topologies.md is stale — regenerate from "
                         "swarm.render.markdown_section()")


class TopologyEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_api_swarm_lists_topologies(self):
        from aiohttp.test_utils import TestClient, TestServer
        from interface.web import build_web_app
        from kernel.config import Config
        from kernel.daemon import AgentDaemon
        daemon = AgentDaemon(Config.load())
        await daemon.memory.connect()
        app = build_web_app(daemon)
        server = TestServer(app)
        client = TestClient(server)
        await client.start_server()
        try:
            response = await client.get("/api/swarm")
            self.assertEqual(response.status, 200)
            body = await response.json()
            names = {t["name"] for t in body["topologies"]}
            self.assertEqual(names, EXPECTED_TOPOLOGIES)
        finally:
            await client.close()
            await daemon.memory.close()


if __name__ == "__main__":
    unittest.main()

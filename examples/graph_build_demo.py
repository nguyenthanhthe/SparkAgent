"""Entity-graph demo: mine triples from text, persist, query.

    python examples/graph_build_demo.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory_search.graph_store import GraphStore      # noqa: E402
from tools.graph_tools import extract_triples         # noqa: E402

TEXT = """SparkAgent uses Ollama for local GPU inference. SparkAgent is a
local agent framework. Ollama serves nemotron models on the RTX card.
The kernel uses sqlite for memory. SparkAgent depends on asyncio.
A nightly outage was caused by a failed CUDA driver update.
The scheduler is part of the kernel."""


def main() -> None:
    graph = GraphStore()
    triples = extract_triples(TEXT)
    print(f"extracted {len(triples)} triples:")
    for subject, relation, obj in triples:
        graph.add(subject, relation, obj, source="demo")
        print(f"  {subject} --{relation}--> {obj}")

    print("\nfacts about sparkagent:")
    for fact in graph.facts_about("sparkagent"):
        print(" ", fact)

    print("\n2-hop neighborhood of nemotron:")
    for node in sorted(graph.traverse("nemotron", max_hops=2)):
        print(" ", node)

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "graph.json"
        saved = graph.save(path)
        restored = GraphStore()
        restored.load(path)
        print(f"\npersisted {saved} edges; restored "
              f"{restored.edge_count()}")


if __name__ == "__main__":
    main()

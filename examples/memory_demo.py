"""Memory demo: hybrid recall, consolidation, and the entity graph.

    python examples/memory_demo.py
"""

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from memory_search.graph_store import GraphStore          # noqa: E402
from memory_search.hybrid import HybridRanker             # noqa: E402
from memory_search.summarizer import consolidate          # noqa: E402


def main() -> None:
    ranker = HybridRanker()
    now = time.time()
    docs = [
        ("m1", "GPU thermal throttling observed at 95C under sustained "
               "inference load", now - 20 * 86400),
        ("m2", "Weekly ops meeting decided to batch episodes overnight",
         now - 2 * 86400),
        ("m3", "CUDA error 0x80070005 during model load; fixed by "
               "driver update 552.44", now - 5 * 86400),
        ("m4", "Recipe: slow-roast tomatoes with olive oil", now - 30 * 86400),
    ]
    for doc_id, text, ts in docs:
        ranker.add(doc_id, text, timestamp=ts)

    print("query: 'thermal throttling'  ->",
          [h.doc_id for h in ranker.search("thermal throttling", top=3)])
    print("query: '0x80070005'          ->",
          [h.doc_id for h in ranker.search("0x80070005", top=3)])
    print("query: 'driver update fixed' ->",
          [h.doc_id for h in ranker.search("driver update fixed", top=3)])

    print("\nconsolidation:")
    digest = consolidate([
        {"goal": "check gpu temperature", "final_answer":
         "GPU runs 70c idle and 95c under sustained inference load"},
        {"goal": "update display drivers",
         "final_answer": "Updated to driver 552.44; CUDA errors gone"},
    ])
    print(digest)

    print("\nentity graph:")
    graph = GraphStore()
    graph.add("sparkagent", "uses", "ollama", source="ep1")
    graph.add("sparkagent", "uses", "sqlite", source="ep1")
    graph.add("ollama", "serves", "nemotron", source="ep2")
    for fact in graph.facts_about("sparkagent"):
        print(" ", fact)
    print("2 hops from nemotron:", sorted(graph.traverse("nemotron",
                                                         max_hops=2)))


if __name__ == "__main__":
    main()

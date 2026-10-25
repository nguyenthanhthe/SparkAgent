"""Graph-boosted recall — nudge memories that mention entities connected
to the query's graph nodes.

The entity graph (``memory_search.graph_store``) accumulates
subject–predicate–object triples extracted from episodes. When a recall
query names a node that lives in the graph, its one-hop neighbors are
related context; memories whose text mentions those related entities are
likely relevant even when lexical and vector signals are weak.

``GraphBooster`` is deterministic and offline: it never calls out, only
re-ranks candidates it is given. The boost is additive and deliberately
small (default weight 0.05 per related-entity mention, capped) so graph
evidence refines hybrid ranking without dominating it.
"""

from __future__ import annotations

import re

from memory_search.graph_store import GraphStore

_TOKEN = re.compile(r"[a-z0-9][a-z0-9_-]{1,}")


class GraphBooster:
    """Score candidates by graph-proximity to query entities."""

    def __init__(self, graph: GraphStore, weight: float = 0.05,
                 max_boost: float = 0.5):
        self.graph = graph
        self.weight = weight
        self.max_boost = max_boost

    def related_entities(self, query: str,
                         max_hops: int = 2) -> dict[str, set[str]]:
        """Map each graph node named in the query to entities within
        ``max_hops`` of it (one hop = direct neighbors, two = their
        neighbors)."""
        tokens = {m.group(0) for m in _TOKEN.finditer(query.lower())}
        related: dict[str, set[str]] = {}
        for node in self.graph.nodes():
            if node.lower() in tokens:
                neighbors = set(self.graph.traverse(node,
                                                    max_hops=max_hops))
                neighbors.discard(node)
                if neighbors:
                    related[node] = neighbors
        return related

    def boost(self, query: str, text: str) -> float:
        """Boost for one candidate document (0 when nothing connects)."""
        related = self.related_entities(query)
        if not related:
            return 0.0
        lowered = text.lower()
        entities = {entity for neighbors in related.values()
                    for entity in neighbors}
        mentions = sum(lowered.count(entity.lower()) for entity in entities)
        return min(self.weight * mentions, self.max_boost)

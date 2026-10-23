"""Entity graph store — lightweight subject-predicate-object memory.

Extracted entities and relations (e.g. "sparkagent --uses--> ollama") live
in a directed multigraph with adjacency indexes. Queries: neighbors,
k-hop traversal, relation lookup, and reverse questions ("what uses X?").
Persistence is JSON-lines; scale target is thousands of edges, not
millions — SQLite/NetworkX can take over when needed.
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from kernel.correlation import new_id


@dataclass(frozen=True)
class Edge:
    subject: str
    predicate: str
    obj: str
    weight: float = 1.0
    source: str = "?"          # provenance (episode id, tool, …)
    id: str = field(default_factory=new_id)


class GraphStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._edges: dict[str, Edge] = {}
        self._out: dict[str, set[str]] = {}    # node -> edge ids
        self._in: dict[str, set[str]] = {}     # node -> edge ids

    # ------------------------------------------------------------------ write
    def add(self, subject: str, predicate: str, obj: str,
            weight: float = 1.0, source: str = "?") -> Edge:
        subject, predicate, obj = (subject.strip().lower(),
                                   predicate.strip().lower(),
                                   obj.strip().lower())
        if not subject or not predicate or not obj:
            raise ValueError("subject/predicate/object must be non-empty")
        for node in (subject, obj):
            if len(node) > 200:
                raise ValueError(f"node too long: {node[:50]}…")
        with self._lock:
            for edge_id in self._out.get(subject, ()):   # dedupe exact triples
                edge = self._edges[edge_id]
                if edge.predicate == predicate and edge.obj == obj:
                    self._edges[edge_id] = Edge(subject, predicate, obj,
                                                max(weight, edge.weight),
                                                source, edge_id)
                    return self._edges[edge_id]
            edge = Edge(subject, predicate, obj, weight, source)
            self._edges[edge.id] = edge
            self._out.setdefault(subject, set()).add(edge.id)
            self._in.setdefault(obj, set()).add(edge.id)
            return edge

    def remove(self, edge_id: str) -> bool:
        with self._lock:
            edge = self._edges.pop(edge_id, None)
            if edge is None:
                return False
            self._out.get(edge.subject, set()).discard(edge_id)
            self._in.get(edge.obj, set()).discard(edge_id)
            return True

    # ------------------------------------------------------------------- read
    def neighbors(self, node: str) -> list[Edge]:
        node = node.strip().lower()
        with self._lock:
            edge_ids = self._out.get(node, set()) | self._in.get(node, set())
            return sorted((self._edges[eid] for eid in edge_ids),
                          key=lambda e: e.predicate)

    def relations(self, subject: str, obj: str) -> list[Edge]:
        subject, obj = subject.strip().lower(), obj.strip().lower()
        with self._lock:
            return [edge for edge in self._edges.values()
                    if edge.subject == subject and edge.obj == obj]

    def traverse(self, start: str, max_hops: int = 2,
                 max_nodes: int = 50) -> dict[str, list[Edge]]:
        """BFS out from ``start``; returns node -> incoming discovery edges."""
        start = start.strip().lower()
        visited: dict[str, list[Edge]] = {start: []}
        frontier = [start]
        for _hop in range(max_hops):
            next_frontier: list[str] = []
            for node in frontier:
                for edge in self.neighbors(node):
                    target = edge.obj if edge.subject == node else edge.subject
                    if target not in visited:
                        visited[target] = visited.get(target, []) + [edge]
                        next_frontier.append(target)
                        if len(visited) >= max_nodes:
                            return visited
            frontier = next_frontier
            if not frontier:
                break
        return visited

    def nodes(self) -> list[str]:
        with self._lock:
            return sorted(set(self._out) | set(self._in))

    def edge_count(self) -> int:
        with self._lock:
            return len(self._edges)

    # ------------------------------------------------------------ persistence
    def save(self, path: Path) -> int:
        with self._lock:
            edges = [vars(edge) for edge in self._edges.values()]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(edges, ensure_ascii=False, indent=1),
                        encoding="utf-8")
        return len(edges)

    def load(self, path: Path) -> int:
        if not path.exists():
            return 0
        records = json.loads(path.read_text(encoding="utf-8"))
        for record in records:
            self.add(record["subject"], record["predicate"], record["obj"],
                     weight=float(record.get("weight", 1.0)),
                     source=record.get("source", "?"))
        return len(records)

    def facts_about(self, node: str) -> list[str]:
        """Human-readable sentence per incident edge."""
        lines = []
        for edge in self.neighbors(node):
            if edge.subject == node:
                lines.append(f"{node} --{edge.predicate}--> {edge.obj}")
            else:
                lines.append(f"{edge.obj} --{edge.predicate}--> {node} "
                             f"(inverse of {edge.subject})")
        return lines

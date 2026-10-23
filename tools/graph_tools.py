"""Entity-graph tools — heuristic triple extraction + graph queries.

``extract_entities`` mines (subject, relation, object) triples from free
text with deterministic patterns (X uses/depends on/isa Y, "X's Y", appos
lists) and files them into a :class:`~memory_search.graph_store.GraphStore`.
``graph_query`` exposes neighbors, traversal, and facts lookup to the
agent. Everything is case-insensitive with provenance kept.
"""

from __future__ import annotations

import re
from typing import Any

from kernel.validation import require_int, require_str
from memory_search.graph_store import GraphStore
from tools.registry import Tool, ToolContext, ToolRegistry

MAX_TEXT_CHARS = 20_000

# Short noun phrase: 1-4 words, stopping before common prepositions,
# conjunctions, and auxiliaries so objects don't swallow sentence tails.
_NP = (r"[a-z][\w-]*"
       r"(?: (?!for\b|on\b|in\b|with\b|and\b|but\b|or\b|to\b|at\b|by\b"
       r"|of\b|was\b|is\b|are\b|were\b|the\b|that\b|daily\b|when\b"
       r"|because\b)[a-z][\w-]*){0,3}")

_RELATION_PATTERNS: tuple[tuple[str, re.Pattern], ...] = (
    ("uses", re.compile(
        rf"\b({_NP})\s+(?:uses|runs on|requires|depends on)\s+({_NP})",
        re.IGNORECASE)),
    ("isa", re.compile(
        rf"\b({_NP})\s+(?:is a|is an|are a|are an)\s+({_NP})",
        re.IGNORECASE)),
    ("located_in", re.compile(
        rf"\b({_NP})\s+(?:located in|based in|lives in)\s+({_NP})",
        re.IGNORECASE)),
    ("part_of", re.compile(
        rf"\b({_NP})\s+(?:part of|belongs to|member of)\s+({_NP})",
        re.IGNORECASE)),
    ("caused_by", re.compile(
        rf"\b({_NP})(?:\s+(?:was|were|is|are|has|had))?\s+"
        rf"(?:caused by|due to|because of)\s+({_NP})",
        re.IGNORECASE)),
)

_STOPWORD_ENTITY = {"it", "this", "that", "there", "here", "they",
                    "these", "those", "the", "a", "an", "he", "she", "we",
                    "and", "or", "but", "not", "which", "who"}
_TRAILING_AUX = ("was", "is", "are", "were", "has", "had", "will", "that")


def extract_triples(text: str) -> list[tuple[str, str, str]]:
    """Mine candidate triples; ordering follows pattern priority."""
    triples: list[tuple[str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for relation, pattern in _RELATION_PATTERNS:
        for match in pattern.finditer(text):
            subject = _clean_entity(match.group(1))
            obj = _clean_entity(match.group(2))
            if not subject or not obj or subject == obj:
                continue
            if subject in _STOPWORD_ENTITY or obj in _STOPWORD_ENTITY:
                continue
            key = (subject, relation, obj)
            if key not in seen:
                seen.add(key)
                triples.append(key)
    return triples


def _clean_entity(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value).strip(" .,-;:").lower()
    words = cleaned.split()
    while words and words[-1] in _TRAILING_AUX:
        words.pop()
    return " ".join(words)[:80]


def register_tools(registry: ToolRegistry, graph: GraphStore) -> None:
    async def extract_entities(ctx: ToolContext, text: str,
                               source: str = "text") -> dict:
        text = require_str(text, "text", max_len=MAX_TEXT_CHARS)
        triples = extract_triples(text)
        added = 0
        for subject, relation, obj in triples:
            graph.add(subject, relation, obj,
                      source=str(source)[:60] or "text")
            added += 1
        return {"triples": [{"s": s, "p": p, "o": o}
                            for s, p, o in triples],
                "added": added}

    registry.register(Tool(
        name="extract_entities",
        description=("Extract subject-relation-object triples from text "
                     "(uses/isa/located_in/part_of/caused_by patterns) and "
                     "store them in the entity graph for later queries."),
        parameters={"text": {"type": "string", "required": True},
                    "source": {"type": "string", "required": False,
                               "desc": "provenance label (e.g. an URL)"}},
        handler=extract_entities))

    async def graph_query(ctx: ToolContext, node: str,
                          operation: str = "facts",
                          hops: int = 2) -> Any:
        node = require_str(node, "node", min_len=1, max_len=200)
        require_int(hops, "hops", minimum=1, maximum=3)
        if operation == "facts":
            return {"facts": graph.facts_about(node)}
        if operation == "neighbors":
            return {"neighbors": [{"subject": e.subject,
                                   "predicate": e.predicate,
                                   "object": e.obj}
                                  for e in graph.neighbors(node)]}
        if operation == "traverse":
            reached = graph.traverse(node, max_hops=hops)
            return {"reached": sorted(reached)}
        if operation == "stats":
            return {"nodes": len(graph.nodes()),
                    "edges": graph.edge_count(),
                    "sample_nodes": graph.nodes()[:30]}
        from kernel.errors import ToolFailure
        raise ToolFailure(
            f"unknown operation {operation!r} (facts|neighbors|traverse|stats)")

    registry.register(Tool(
        name="graph_query",
        description=("Query the entity graph: facts about a node, its "
                     "neighbors, k-hop traversal, or store stats. "
                     "operation: facts|neighbors|traverse|stats."),
        parameters={"node": {"type": "string", "required": True},
                    "operation": {"type": "string", "required": False},
                    "hops": {"type": "integer", "required": False}},
        handler=graph_query))

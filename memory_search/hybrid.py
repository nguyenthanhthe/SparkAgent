"""Hybrid search — reciprocal-rank fusion of lexical and vector results.

RRF is robust to incomparable score scales (BM25 scores are unbounded,
cosines live in [-1, 1]): each ranker contributes ``1 / (k + rank)`` and
the fused order is simply the summed contribution. Recency boosts recent
memories slightly so stale duplicates lose ties.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from memory_search.bm25 import BM25Index

RRF_K = 60.0
RECENCY_HALF_LIFE_DAYS = 14.0


@dataclass
class SearchHit:
    doc_id: str
    text: str
    lexical_rank: int | None = None
    vector_rank: int | None = None
    fused_score: float = 0.0
    recency_bonus: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


VectorSearch = Callable[[str, int], list[tuple[str, float]]]


class HybridRanker:
    """Fuse BM25 + vector recall over the same document corpus."""

    def __init__(self, vector_search: VectorSearch | None = None,
                 recency_weight: float = 0.1):
        self.bm25 = BM25Index()
        self._texts: dict[str, str] = {}
        self._meta: dict[str, dict] = {}
        self._timestamps: dict[str, float] = {}
        self._vector_search = vector_search
        self.recency_weight = recency_weight

    # ------------------------------------------------------------------- api
    def add(self, doc_id: str, text: str, metadata: dict | None = None,
            timestamp: float | None = None) -> None:
        self.bm25.add(doc_id, text)
        self._texts[doc_id] = text
        self._meta[doc_id] = dict(metadata or {})
        self._timestamps[doc_id] = timestamp if timestamp is not None \
            else time.time()

    def remove(self, doc_id: str) -> bool:
        removed = self.bm25.remove(doc_id)
        self._texts.pop(doc_id, None)
        self._meta.pop(doc_id, None)
        self._timestamps.pop(doc_id, None)
        return removed

    def __len__(self) -> int:
        return len(self._texts)

    # ---------------------------------------------------------------- search
    def search(self, query: str, top: int = 5,
               lexical_top: int = 20, vector_top: int = 20) -> list[SearchHit]:
        lexical = self.bm25.search(query, top=lexical_top)
        vector: list[tuple[str, float]] = []
        if self._vector_search is not None:
            try:
                vector = self._vector_search(query, vector_top)
            except Exception:  # noqa: BLE001 — vector failures degrade to BM25
                vector = []

        contributions: dict[str, float] = {}
        lexical_ranks: dict[str, int] = {}
        vector_ranks: dict[str, int] = {}
        for rank, (doc_id, _score) in enumerate(lexical, start=1):
            contributions[doc_id] = contributions.get(doc_id, 0.0) \
                + 1.0 / (RRF_K + rank)
            lexical_ranks[doc_id] = rank
        for rank, (doc_id, _score) in enumerate(vector, start=1):
            contributions[doc_id] = contributions.get(doc_id, 0.0) \
                + 1.0 / (RRF_K + rank)
            vector_ranks[doc_id] = rank

        now = time.time()
        hits: list[SearchHit] = []
        for doc_id, fused in contributions.items():
            if doc_id not in self._texts:   # vector index out of sync
                continue
            age_days = max(0.0, (now - self._timestamps.get(doc_id, now))
                           / 86400.0)
            recency = 0.5 ** (age_days / RECENCY_HALF_LIFE_DAYS)
            bonus = self.recency_weight * recency
            hits.append(SearchHit(
                doc_id=doc_id, text=self._texts[doc_id],
                lexical_rank=lexical_ranks.get(doc_id),
                vector_rank=vector_ranks.get(doc_id),
                fused_score=round(fused + bonus, 6),
                recency_bonus=round(bonus, 6),
                metadata=self._meta.get(doc_id, {})))
        hits.sort(key=lambda h: -h.fused_score)
        return hits[:top]

    def stats(self) -> dict:
        return {**self.bm25.stats(), "vector_enabled":
                self._vector_search is not None}

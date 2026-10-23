"""BM25 (Okapi) keyword ranking — exact-lexical recall for memory.

Complements vector recall: hashes miss rare identifiers and acronyms that
BM25 nails ("RTX 4050", "error 0x80070005"). Pure Python, incremental
add/remove, k1/b tunable.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field

_TOKEN_RE = re.compile(r"[a-z0-9]+")
STOPWORDS = {"the", "a", "an", "and", "or", "of", "to", "for", "in", "on",
             "is", "are", "was", "be", "by", "it", "this", "that", "with",
             "as", "at", "from"}


def tokenize(text: str, drop_stopwords: bool = True) -> list[str]:
    tokens = _TOKEN_RE.findall(text.lower())
    if drop_stopwords:
        tokens = [t for t in tokens if t not in STOPWORDS]
    return tokens


@dataclass
class _Doc:
    doc_id: str
    tokens: list[str]
    term_freq: Counter = field(default_factory=Counter)

    def __post_init__(self) -> None:
        self.term_freq = Counter(self.tokens)


class BM25Index:
    def __init__(self, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self._docs: dict[str, _Doc] = {}
        self._doc_freq: Counter = Counter()
        self._total_len = 0

    # ------------------------------------------------------------------- api
    def add(self, doc_id: str, text: str) -> None:
        if doc_id in self._docs:
            self.remove(doc_id)
        doc = _Doc(doc_id, tokenize(text))
        self._docs[doc_id] = doc
        self._total_len += len(doc.tokens)
        for term in set(doc.tokens):
            self._doc_freq[term] += 1

    def remove(self, doc_id: str) -> bool:
        doc = self._docs.pop(doc_id, None)
        if doc is None:
            return False
        self._total_len -= len(doc.tokens)
        for term in set(doc.tokens):
            self._doc_freq[term] -= 1
            if self._doc_freq[term] <= 0:
                del self._doc_freq[term]
        return True

    def __len__(self) -> int:
        return len(self._docs)

    # ------------------------------------------------------------------ query
    def search(self, query: str, top: int = 10) -> list[tuple[str, float]]:
        """Return (doc_id, score) descending; empty when no term overlaps."""
        terms = tokenize(query)
        if not terms or not self._docs:
            return []
        avg_len = self._total_len / len(self._docs) or 1.0
        scores: dict[str, float] = {}
        for term in terms:
            df = self._doc_freq.get(term, 0)
            if not df:
                continue
            idf = math.log(1 + (len(self._docs) - df + 0.5) / (df + 0.5))
            for doc_id, doc in self._docs.items():
                tf = doc.term_freq.get(term, 0)
                if not tf:
                    continue
                norm = tf * (self.k1 + 1) / (
                    tf + self.k1 * (1 - self.b + self.b * len(doc.tokens)
                                    / avg_len))
                scores[doc_id] = scores.get(doc_id, 0.0) + idf * norm
        ranked = sorted(scores.items(), key=lambda kv: -kv[1])
        return ranked[:top]

    def stats(self) -> dict:
        return {"docs": len(self._docs),
                "vocabulary": len(self._doc_freq),
                "avg_doc_len": round(self._total_len / len(self._docs), 1)
                if self._docs else 0.0}

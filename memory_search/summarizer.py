"""Deterministic extractive summarizer for memory consolidation.

No LLM required: sentences are scored by query-term overlap, TF-IDF
salience, and position, then the top-k non-redundant sentences form the
digest. Used by the housekeeping loop to compact finished episodes into
distilled long-term memories.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Sequence

from memory_search.bm25 import tokenize

_SENTENCE_RE = re.compile(r"[^.!?\n]+[.!?]?")
_MAX_SENTENCE_WORDS = 60
_MIN_SENTENCE_WORDS = 4


@dataclass
class ScoredSentence:
    text: str
    score: float
    index: int


@dataclass
class Digest:
    summary: str
    sentences: list[ScoredSentence] = field(default_factory=list)
    dropped_redundant: int = 0


def split_sentences(text: str) -> list[str]:
    sentences = []
    for raw in _SENTENCE_RE.findall(text):
        cleaned = re.sub(r"\s+", " ", raw).strip()
        word_count = len(cleaned.split())
        if _MIN_SENTENCE_WORDS <= word_count <= _MAX_SENTENCE_WORDS:
            sentences.append(cleaned)
    return sentences


def summarize(text: str, top: int = 3, query: str = "",
              redundancy_threshold: float = 0.6) -> Digest:
    """Extract ``top`` sentences best representing ``text`` (or ``query``)."""
    sentences = split_sentences(text)
    if not sentences:
        return Digest(summary=text.strip()[:400])

    doc_freq: dict[str, int] = {}
    tokenized = [tokenize(sentence) for sentence in sentences]
    for tokens in tokenized:
        for term in set(tokens):
            doc_freq[term] = doc_freq.get(term, 0) + 1
    query_terms = set(tokenize(query)) if query else None

    scored: list[ScoredSentence] = []
    for index, tokens in enumerate(tokenized):
        if not tokens:
            continue
        salience = sum(1.0 / doc_freq.get(term, 1) for term in set(tokens))
        salience /= len(tokens)
        position_bonus = 1.2 if index == 0 else (1.05 if index == 1 else 1.0)
        score = salience * position_bonus
        if query_terms:
            overlap = len(query_terms & set(tokens)) / len(query_terms or {1})
            score *= (0.3 + overlap)
        length_norm = min(1.0, len(tokens) / 10 + 0.5)
        scored.append(ScoredSentence(sentences[index],
                                     round(score * length_norm, 6), index))

    scored.sort(key=lambda s: -s.score)
    selected: list[ScoredSentence] = []
    dropped = 0
    for candidate in scored:
        if len(selected) >= top:
            break
        candidate_terms = set(tokenize(candidate.text))
        redundant = False
        for chosen in selected:
            chosen_terms = set(tokenize(chosen.text))
            if not candidate_terms or not chosen_terms:
                continue
            overlap = len(candidate_terms & chosen_terms) / \
                max(1, len(candidate_terms | chosen_terms))
            if overlap > redundancy_threshold:
                redundant = True
                break
        if redundant:
            dropped += 1
            continue
        selected.append(candidate)

    selected.sort(key=lambda s: s.index)     # restore narrative order
    summary = " ".join(s.text for s in selected)
    return Digest(summary=summary, sentences=selected,
                  dropped_redundant=dropped)


def consolidate(episodes: Sequence[dict], query: str = "",
                per_episode: int = 1, header: str = "Consolidated digest") \
        -> str:
    """Compact a batch of episodes (dicts with goal/final_answer) into one
    distilled memory text."""
    parts = [f"# {header} ({len(episodes)} episodes)"]
    for episode in episodes:
        goal = str(episode.get("goal", "")).strip()
        answer = str(episode.get("final_answer", "")).strip()
        if not goal and not answer:
            continue
        combined = f"Goal: {goal}. Outcome: {answer}"
        digest = summarize(combined, top=per_episode, query=query)
        if digest.summary:
            parts.append(f"- {digest.summary}")
    return "\n".join(parts)[:4000]

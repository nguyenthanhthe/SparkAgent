"""Consensus — majority voting across independent answers.

Normalizes answers (case/whitespace) and elects the canonical form with
a quorum threshold. Weighted voters (e.g. a critic counts more) are
supported; ties return no winner with per-option tallies for debugging.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable


def normalize_answer(text: str) -> str:
    """Lowercase, strip punctuation noise and collapse whitespace."""
    cleaned = re.sub(r"\s+", " ", text.strip().lower())
    cleaned = re.sub(r"[。，,.!?:;\"']+$", "", cleaned)
    return cleaned


@dataclass
class VoteResult:
    winner: str | None = None
    tally: dict[str, float] = field(default_factory=dict)
    quorum: float = 0.0
    total_weight: float = 0.0

    @property
    def decided(self) -> bool:
        return self.winner is not None


def vote(answers: Iterable[tuple[str, float]], quorum: float = 0.5) -> VoteResult:
    """Elect the canonical answer reaching ``quorum`` of total weight.

    ``answers`` is an iterable of ``(answer_text, weight)``; the winner is
    returned verbatim from the first answer that matches the canonical
    form (normalization must not destroy the display form).
    """
    items = [(text, float(weight)) for text, weight in answers
             if text and text.strip()]
    result = VoteResult(quorum=quorum,
                        total_weight=sum(w for _, w in items))
    if not items:
        return result

    canonical: dict[str, str] = {}          # normalized -> display form
    tally: dict[str, float] = defaultdict(float)
    for text, weight in items:
        key = normalize_answer(text)
        if key not in canonical:
            canonical[key] = text
        tally[key] += weight

    result.tally = dict(sorted(tally.items(), key=lambda kv: -kv[1]))
    threshold = result.total_weight * quorum
    best_key, best_weight = next(iter(result.tally.items()))
    if best_weight >= threshold and threshold > 0:
        result.winner = canonical[best_key]
    return result


def consensus_summary(votes: VoteResult) -> dict:
    return {"decided": votes.decided, "winner": votes.winner,
            "quorum": votes.quorum,
            "tally": votes.tally, "total_weight": votes.total_weight}


def disagreement_score(votes: VoteResult) -> float:
    """0.0 = unanimous, 1.0 = completely fragmented."""
    if votes.total_weight <= 0:
        return 0.0
    top = max(votes.tally.values()) if votes.tally else 0.0
    return round(1.0 - top / votes.total_weight, 4)

"""Critic — heuristic quality review of candidate answers.

Deterministic checks (goal-coverage, substance, structure, injection
risk) produce a numeric score and actionable findings; used standalone or
as the critic stage input-shaper in the orchestrator.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

_WORD_RE = re.compile(r"[a-z0-9]+")
_STOP = {"the", "a", "an", "and", "or", "of", "to", "for", "in", "on",
         "with", "is", "are", "was", "were", "be", "by", "it", "this",
         "that", "as", "at", "from", "your", "you", "my"}


@dataclass
class Critique:
    score: float                     # 0..1
    findings: list[str] = field(default_factory=list)
    passed: bool = False             # score >= threshold

    def to_dict(self) -> dict[str, Any]:
        return {"score": round(self.score, 3), "passed": self.passed,
                "findings": self.findings}


def critique(goal: str, answer: str, threshold: float = 0.6,
             min_words: int = 10) -> Critique:
    findings: list[str] = []
    score = 1.0

    words = _WORD_RE.findall(answer.lower())
    if len(words) < min_words:
        findings.append(f"answer too short ({len(words)} words < {min_words})")
        score -= 0.3

    goal_terms = {w for w in _WORD_RE.findall(goal.lower())
                  if w not in _STOP and len(w) > 2}
    if goal_terms:
        present = {w for w in goal_terms if w in answer.lower()}
        coverage = len(present) / len(goal_terms)
        if coverage < 0.34:
            missing = sorted(goal_terms - present)[:8]
            findings.append(f"goal terms missing: {missing}")
            score -= 0.5 * (1 - coverage)   # low coverage must fail alone
        elif coverage >= 0.75:
            score = min(1.0, score + 0.05)

    if re.search(r"\b(i don'?t know|cannot answer|no idea)\b",
                 answer.lower()):
        findings.append("answer contains a give-up phrase")
        score -= 0.5                      # give-up must fail alone
    if re.search(r"\b(lorem ipsum|placeholder|TODO|as an ai)\b",
                 answer.lower()):
        findings.append("answer contains template/filler text")
        score -= 0.3
    if not answer.strip():
        findings.append("answer is empty")
        score = 0.0

    from security.promptguard import scan
    injection = scan(answer)
    if injection.verdict != "pass":
        findings.append(f"injection risk in answer "
                        f"({injection.verdict}, score {injection.score})")
        score -= 0.3

    score = max(0.0, min(1.0, score))
    return Critique(score=score, findings=findings, passed=score >= threshold)


def critique_feedback(critique_result: Critique) -> str:
    """Render findings as instructions for a revision pass."""
    if critique_result.passed:
        return "The answer passes review. No changes needed."
    lines = ["The answer needs revision:"]
    lines += [f"- {finding}" for finding in critique_result.findings]
    return "\n".join(lines)

"""Context-window budgeting.

ReAct scratchpads grow; models reject over-long prompts. The budgeter
estimates tokens (chars/4 by default, per-message overhead included),
fits parts into a fixed window, and sheds load in policy order: trim
memory context first, then compress old scratchpad turns, never the
goal or the output contract.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

CHARS_PER_TOKEN = 4.0
PER_MESSAGE_OVERHEAD = 4   # role/name framing tokens, conservative


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, int(len(text) / CHARS_PER_TOKEN) + 1)


def estimate_messages(messages: list[dict[str, str]]) -> int:
    total = PER_MESSAGE_OVERHEAD * len(messages)
    for message in messages:
        total += estimate_tokens(message.get("content", ""))
    return total


@dataclass
class Part:
    name: str
    content: str
    priority: int = 50            # higher survives longer
    role: str = "user"
    shrinkable: bool = True


@dataclass
class BudgetPlan:
    total_budget: int
    used: int = 0
    parts: list[dict[str, Any]] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    trimmed: list[str] = field(default_factory=list)

    @property
    def fits(self) -> bool:
        return self.used <= self.total_budget


class ContextBudget:
    def __init__(self, window_tokens: int, reserve_output_tokens: int = 1024,
                 min_keep_chars: int = 200):
        if window_tokens <= reserve_output_tokens:
            raise ValueError("window must exceed reserved output tokens")
        self.window = window_tokens
        self.reserve = reserve_output_tokens
        self.min_keep = min_keep_chars

    @property
    def input_budget(self) -> int:
        return self.window - self.reserve

    # ---------------------------------------------------------------- fitting
    def fit(self, parts: list[Part]) -> BudgetPlan:
        """Fit parts into the budget, trimming low-priority shrinkables."""
        plan = BudgetPlan(total_budget=self.input_budget)
        sized = []
        for part in parts:
            tokens = estimate_tokens(part.content) + PER_MESSAGE_OVERHEAD
            sized.append((part, tokens))

        total = sum(tokens for _, tokens in sized)
        if total <= self.input_budget:
            for part, tokens in sized:
                plan.parts.append(self._entry(part, tokens, "kept"))
            plan.used = total
            return plan

        # Phase 1: trim shrinkable parts, lowest priority first, but keep
        # at least min_keep_chars (25% floor) of each.
        shrink_order = sorted((i for i, (p, _) in enumerate(sized)
                               if p.shrinkable),
                              key=lambda i: sized[i][0].priority)
        working = [list(item) for item in sized]
        remaining = total
        for index in shrink_order:
            if remaining <= self.input_budget:
                break
            part, tokens = working[index]
            keep_chars = max(self.min_keep,
                             int(len(part.content) * 0.25))
            cut_content = part.content[:keep_chars] + "\n…[trimmed]"
            new_tokens = estimate_tokens(cut_content) + PER_MESSAGE_OVERHEAD
            if new_tokens < tokens:
                remaining -= tokens - new_tokens
                plan.trimmed.append(part.name)
                working[index] = [Part(part.name, cut_content,
                                       part.priority, part.role,
                                       part.shrinkable), new_tokens]

        # Phase 2: drop lowest-priority parts entirely until it fits.
        drop_order = sorted(range(len(working)),
                            key=lambda i: working[i][0].priority)
        for index in drop_order:
            if remaining <= self.input_budget:
                break
            part, tokens = working[index]
            plan.dropped.append(part.name)
            remaining -= tokens
            working[index] = [part, 0]

        for part, tokens in working:
            if tokens > 0:
                plan.parts.append(self._entry(part, tokens, "kept"))
        plan.used = remaining
        return plan

    @staticmethod
    def _entry(part: Part, tokens: int, action: str) -> dict:
        return {"name": part.name, "role": part.role, "action": action,
                "tokens": tokens, "content": part.content}

    def fit_messages(self, system: str, goal: str, memories: str,
                     scratchpad: list[dict[str, str]]) -> tuple[list[dict],
                                                                BudgetPlan]:
        """Convenience: build fitted chat messages from ReAct ingredients."""
        parts = [
            Part("system", system, priority=1000, role="system",
                 shrinkable=False),
            Part("goal", f"Goal: {goal}", priority=900, shrinkable=False),
            Part("memories", memories, priority=300),
        ]
        for index, turn in enumerate(scratchpad):
            parts.append(Part(f"turn_{index}",
                              f"{turn['role']}: {turn['content']}",
                              priority=100 + index,
                              role=turn["role"]))
        plan = self.fit(parts)
        messages = [{"role": p["role"], "content": p["content"]}
                    for p in plan.parts]
        return messages, plan


def summarize_scratchpad(scratchpad: list[dict[str, str]],
                         keep_last: int = 4) -> tuple[list[dict], str]:
    """Compress old turns into one summary note; keep the tail verbatim."""
    if len(scratchpad) <= keep_last:
        return scratchpad, ""
    head, tail = scratchpad[:-keep_last], scratchpad[-keep_last:]
    lines = []
    for turn in head:
        content = turn["content"]
        content = content[:160].replace("\n", " ")
        lines.append(f"[{turn['role']}] {content}")
    summary = ("Earlier steps (compressed):\n" + "\n".join(lines))
    return ([{"role": "user", "content": summary}] + tail), summary

"""Declarative rule engine for authorization decisions.

Rules match over a flat attribute dict (subject, action, resource, …) with
exact and wildcard matchers. First match wins; a terminal default decides
when nothing matches. This generalizes openshell's fixed checks so policies
can live in config and be unit-tested as data.
"""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable


class Decision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"


@dataclass(frozen=True)
class Action:
    """The thing being authorized: verb + free-form attributes."""

    verb: str
    attributes: dict[str, Any] = field(default_factory=dict)

    def match(self, key: str) -> Any:
        return self.attributes.get(key)


@dataclass(frozen=True)
class Rule:
    name: str
    decision: Decision
    verb: str | None = None                 # None matches any verb
    where: dict[str, str] = field(default_factory=dict)
    priority: int = 100
    description: str = ""

    def matches(self, action: Action) -> bool:
        if self.verb is not None and not _match(self.verb, action.verb):
            return False
        for key, pattern in self.where.items():
            value = action.attributes.get(key)
            if value is None:
                return False
            if not _match(str(pattern), str(value)):
                return False
        return True


def _match(pattern: str, value: str) -> bool:
    """Exact match, or fnmatch wildcard if the pattern has wildcards."""
    if "*" in pattern or "?" in pattern or "[" in pattern:
        return fnmatch.fnmatchcase(value, pattern)
    return pattern == value


class PolicyDecisionError(Exception):
    def __init__(self, rule: Rule, action: Action):
        self.rule = rule
        self.action = action
        super().__init__(
            f"denied by rule {rule.name!r} for {action.verb} "
            f"{ {k: v for k, v in action.attributes.items()} }")


class PolicyEngine:
    """Ordered rule set; higher priority evaluates first."""

    def __init__(self, default: Decision = Decision.DENY,
                 rules: Iterable[Rule] | None = None):
        self.default = default
        self._rules: list[Rule] = sorted(rules or [], key=lambda r: -r.priority)

    def add(self, rule: Rule) -> None:
        self._rules.append(rule)
        self._rules.sort(key=lambda r: -r.priority)

    def decide(self, action: Action) -> tuple[Decision, Rule | None]:
        for rule in self._rules:
            if rule.matches(action):
                return rule.decision, rule
        return self.default, None

    def check(self, action: Action) -> None:
        decision, rule = self.decide(action)
        if decision is Decision.DENY:
            raise PolicyDecisionError(rule or Rule("default", Decision.DENY),
                                      action)

    def rules_summary(self) -> list[dict]:
        return [{"name": r.name, "decision": r.decision.value,
                 "verb": r.verb, "where": r.where, "priority": r.priority}
                for r in self._rules]


def policy_from_config(entries: list[dict],
                       default: str = "deny") -> PolicyEngine:
    """Build an engine from ``security.policy_rules`` config entries."""
    rules = []
    for entry in entries:
        rules.append(Rule(
            name=str(entry.get("name", "rule")),
            decision=Decision(str(entry.get("decision", "allow")).lower()),
            verb=entry.get("verb"),
            where=dict(entry.get("where") or {}),
            priority=int(entry.get("priority", 100)),
            description=str(entry.get("description", ""))))
    return PolicyEngine(default=Decision(default.lower()), rules=rules)

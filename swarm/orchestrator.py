"""Swarm orchestrator — planner / workers / critic / synthesizer pipeline.

All intelligence is injected: each role is an async callable
``(goal, context) -> str`` (in production the brain; in tests a stub).
The orchestrator owns the *protocol*: how work is decomposed, executed in
parallel, reviewed, and synthesized — plus the mailbox/blackboard wiring
so every intermediate artifact is observable.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from kernel.async_utils import gather_limit
from kernel.correlation import new_id, trace
from kernel.logging import get_logger
from swarm.blackboard import Blackboard
from swarm.mailbox import Mailbox
from swarm.protocols import AgentMessage, MessageKind, Sender

logger = get_logger("swarm.orchestrator")

BrainFn = Callable[[str, str], Awaitable[str]]

_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)


class BudgetExceeded(Exception):
    pass


@dataclass
class SwarmReport:
    goal: str
    trace_id: str
    plan: list[str] = field(default_factory=list)
    worker_results: dict[str, str] = field(default_factory=dict)
    critique: str = ""
    answer: str = ""
    success: bool = False
    steps: int = 0
    role_calls: int = 0
    budget_exceeded: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {**vars(self), "steps": self.steps}


def _parse_plan(raw: str, max_steps: int = 6) -> list[str]:
    """Extract a step list from planner output.

    Preference order: JSON array > explicitly marked list items
    (``1.``/``-``) > two-or-more substantive plain lines. A single
    unstructured sentence is NOT a plan.
    """
    match = _JSON_ARRAY_RE.search(raw)
    if match:
        try:
            parsed = json.loads(match.group(0))
            steps = [str(item).strip() for item in parsed
                     if str(item).strip()]
            if steps:
                return steps[:max_steps]
        except json.JSONDecodeError:
            pass
    marker_re = re.compile(r"^\s*(?:\d+[.)]|[-*])\s+(.{4,})$")
    marked = [match.group(1).strip() for match in
              (marker_re.match(line) for line in raw.splitlines()) if match]
    if marked:
        return marked[:max_steps]
    plain = [line.strip() for line in raw.splitlines()
             if len(line.strip()) > 8]
    return plain[:max_steps] if len(plain) >= 2 else []


class Orchestrator:
    def __init__(self, planner: BrainFn, worker: BrainFn, critic: BrainFn,
                 synthesizer: BrainFn, *, worker_count: int = 2,
                 max_steps: int = 6, mailbox: Mailbox | None = None,
                 blackboard: Blackboard | None = None,
                 max_role_calls: int = 12):
        self.planner = planner
        self.worker = worker
        self.critic = critic
        self.synthesizer = synthesizer
        self.worker_count = max(1, worker_count)
        self.max_steps = max_steps
        self.max_role_calls = max(4, max_role_calls)
        self.mailbox = mailbox or Mailbox()
        self.blackboard = blackboard or Blackboard()

    def _budgeted(self, report: SwarmReport, fn: BrainFn) -> BrainFn:
        """Wrap a role function with the per-run call budget."""
        async def wrapper(goal: str, context: str) -> str:
            if report.role_calls >= self.max_role_calls:
                report.budget_exceeded = True
                raise BudgetExceeded(
                    f"swarm budget of {self.max_role_calls} role calls "
                    "exhausted")
            report.role_calls += 1
            return await fn(goal, context)
        return wrapper

    # ------------------------------------------------------------------ run
    async def run(self, goal: str) -> SwarmReport:
        report = SwarmReport(goal=goal, trace_id=new_id())
        planner = self._budgeted(report, self.planner)
        worker = self._budgeted(report, self.worker)
        critic = self._budgeted(report, self.critic)
        synthesizer = self._budgeted(report, self.synthesizer)
        with trace("swarm.episode", trace_id=report.trace_id) as span:
            span.attributes["goal"] = goal[:200]
            try:
                # 1. plan
                plan_raw = await planner(goal, "")
                report.plan = _parse_plan(plan_raw, self.max_steps)
                report.steps += 1
                self.blackboard.put("plan", "steps",
                                    json.dumps(report.plan),
                                    author="planner")
                self._emit("planner", MessageKind.RESULT,
                           {"plan": report.plan})
                if not report.plan:
                    report.answer = "planner produced no actionable steps"
                    return report

                # 2. workers execute steps in parallel
                steps = report.plan
                assignments = [steps[index % len(steps)]
                               for index in range(self.worker_count)]

                async def work(index: int, assignment: str) -> tuple[str, str]:
                    context = self._worker_context(report)
                    try:
                        result = await worker(assignment, context)
                    except BudgetExceeded:
                        raise
                    except Exception as exc:  # noqa: BLE001
                        result = f"(worker failed: {exc})"
                    return f"worker-{index}", result

                pairs = await gather_limit(
                    [work(i, a) for i, a in enumerate(assignments)],
                    limit=self.worker_count)
                for name, result in pairs:
                    report.worker_results[name] = result
                    self.blackboard.put("results", name, result, author=name)
                report.steps += 1

                # 3. critic reviews
                report.critique = await critic(goal,
                                               self._critique_input(report))
                report.steps += 1
                self.blackboard.put("review", "critique", report.critique,
                                    author="critic")

                # 4. synthesize final answer
                report.answer = await synthesizer(
                    goal, self._final_input(report))
                report.steps += 1
                report.success = bool(report.answer.strip()) and \
                    "synthesizer failed" not in report.answer.lower()
            except BudgetExceeded as exc:
                report.answer = (f"swarm stopped early: {exc}. Partial "
                                 "results are on the blackboard.")
                report.success = False
                self._emit("orchestrator", MessageKind.CONTROL,
                           {"budget": "exceeded"})
        return report

    # -------------------------------------------------------------- contexts
    def _worker_context(self, report: SwarmReport) -> str:
        plan_text = "\n".join(f"{i+1}. {step}" for i, step in
                              enumerate(report.plan))
        return f"Full plan:\n{plan_text}\nDo your assigned step well."

    def _critique_input(self, report: SwarmReport) -> str:
        results = "\n\n".join(f"[{name}]\n{text}"
                              for name, text in report.worker_results.items())
        return f"Plan: {report.plan}\n\nResults:\n{results}"

    def _final_input(self, report: SwarmReport) -> str:
        results = "\n\n".join(report.worker_results.values())
        return (f"Plan: {report.plan}\n\nResults:\n{results}\n\n"
                f"Critique: {report.critique}\n\nWrite the final answer.")

    def _emit(self, role: str, kind: MessageKind, payload: dict) -> None:
        message = AgentMessage(kind=kind, sender=Sender(role, role),
                               payload=payload, trace_id=new_id())
        self.mailbox.broadcast(message, skip=role)

"""Swarm tools — multi-agent execution exposed to the ReAct loop.

``swarm_delegate`` runs the full planner/worker/critic/synthesizer
pipeline for complex goals; ``debate`` runs adversarial self-debate for
questions with tradeoffs. Both route every role through the same Brain
(tier routing, caching, and cost accounting apply automatically).
"""

from __future__ import annotations

import json

from kernel.validation import require_int, require_str
from swarm.consensus import consensus_summary, vote
from swarm.orchestrator import Orchestrator
from swarm.topologies import debate as debate_topology
from tools.registry import Tool, ToolContext, ToolRegistry

ROLE_PROMPTS = {
    "planner": "You are the PLANNER. Given the goal, output a JSON array "
               "of 2-4 concrete, ordered steps. Output ONLY the array.",
    "worker": "You are a WORKER agent. Complete your assigned step "
              "thoroughly and report what you did and found.",
    "critic": "You are the CRITIC. Review the results against the goal. "
              "List gaps, errors, and the single most important fix.",
    "synthesizer": "You are the SYNTHESIZER. Combine plan, results, and "
                   "critique into one clear final answer for the user.",
    "debater": "You are a careful debater. Argue your assigned position "
               "with evidence, then acknowledge the strongest counterpoint.",
}

MAX_GOAL_CHARS = 2000


def _role_fn(brain, role: str):
    async def handler(goal: str, context: str) -> str:
        messages = [
            {"role": "system", "content": ROLE_PROMPTS[role]},
            {"role": "user",
             "content": f"Goal: {goal}\n\nContext:\n{context or '(none)'}"},
        ]
        try:
            response = await brain.chat(messages)
        except Exception as exc:  # noqa: BLE001 — role failure surfaces in report
            return f"[{role} failed: {type(exc).__name__}: {exc}]"
        return response.text
    return handler


def register_swarm_tools(registry: ToolRegistry, brain, bus=None) -> None:

    def _emit(stage: str, detail: str) -> None:
        if bus is not None:
            bus.publish("logs", f"[swarm] {stage}: {detail[:160]}")

    async def swarm_delegate(ctx: ToolContext, goal: str,
                             workers: int = 2) -> dict:
        goal = require_str(goal, "goal", max_len=MAX_GOAL_CHARS)
        workers = require_int(workers, "workers", minimum=1, maximum=4)
        _emit("start", f"pipeline for {goal[:80]} with {workers} workers")

        class EmittingOrchestrator(Orchestrator):
            async def run(self, goal_text):
                from swarm.protocols import AgentMessage, MessageKind, Sender
                _emit("plan", "planner decomposing goal")
                report = await super().run(goal_text)
                for name in report.worker_results:
                    _emit("worker", f"{name} finished")
                _emit("critic", report.critique[:100])
                _emit("done", f"success={report.success}")
                return report

        orchestrator = EmittingOrchestrator(
            planner=_role_fn(brain, "planner"),
            worker=_role_fn(brain, "worker"),
            critic=_role_fn(brain, "critic"),
            synthesizer=_role_fn(brain, "synthesizer"),
            worker_count=workers)
        report = await orchestrator.run(goal)
        return {"ok": report.success, "answer": report.answer,
                "plan": report.plan,
                "critique": report.critique[:400],
                "steps": report.steps}

    registry.register(Tool(
        name="swarm_delegate",
        description=("Run a multi-agent pipeline (planner, workers, critic, "
                     "synthesizer) for complex goals that benefit from "
                     "decomposition and review. Returns the synthesized "
                     "answer plus the plan and critique."),
        parameters={"goal": {"type": "string", "required": True},
                    "workers": {"type": "integer", "required": False,
                                "desc": "parallel workers (1-4)"}},
        handler=swarm_delegate, dangerous=False))

    async def debate(ctx: ToolContext, question: str,
                     rounds: int = 2) -> dict:
        question = require_str(question, "question", max_len=MAX_GOAL_CHARS)
        rounds = require_int(rounds, "rounds", minimum=1, maximum=3)
        _emit("debate", f"starting {rounds} rounds on {question[:60]}")
        result = await debate_topology(question,
                                       _role_fn(brain, "debater"),
                                       rounds=rounds)
        _emit("debate", "settled")
        return {"answer": result.output,
                "rounds": len(result.stages)}

    registry.register(Tool(
        name="debate",
        description=("Run an adversarial self-debate (for/against) on a "
                     "question with tradeoffs, returning a settled answer."),
        parameters={"question": {"type": "string", "required": True},
                    "rounds": {"type": "integer", "required": False}},
        handler=debate, dangerous=False))

    async def consensus(ctx: ToolContext, question: str,
                        voters: int = 3) -> dict:
        question = require_str(question, "question", max_len=MAX_GOAL_CHARS)
        voters = require_int(voters, "voters", minimum=2, maximum=5)

        async def one_voter() -> str:
            messages = [
                {"role": "system", "content": "Answer concisely and "
                                              "independently."},
                {"role": "user", "content": question}]
            try:
                return (await brain.chat(messages)).text
            except Exception as exc:  # noqa: BLE001
                return f"(voter failed: {exc})"

        answers = [await one_voter() for _ in range(voters)]
        votes = vote([(text, 1.0) for text in answers], quorum=0.5)
        summary = consensus_summary(votes)
        summary["answers"] = [text[:200] for text in answers]
        summary["note"] = ("No majority — answers diverged; synthesize "
                           "carefully" if not votes.decided else "Majority "
                           "reached")
        return summary

    registry.register(Tool(
        name="consensus",
        description=("Ask the model N independent times and majority-vote "
                     "the answers. Use for facts where reliability matters."),
        parameters={"question": {"type": "string", "required": True},
                    "voters": {"type": "integer", "required": False}},
        handler=consensus, dangerous=False))

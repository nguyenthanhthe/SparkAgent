"""Swarm demo: planner/worker/critic/synthesizer with stub brains.

Shows the coordination protocol — plan parsing, parallel workers,
critique, synthesis — plus the blackboard artifacts every stage writes:

    python examples/swarm_demo.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from swarm.orchestrator import Orchestrator   # noqa: E402


async def main() -> None:
    async def planner(goal, context):
        return ('["measure current gpu load", '
                '"compare load against thermal budget", '
                '"draft mitigation steps"]')

    async def worker(step, context):
        return f"[{step}] completed: found 62% utilization, 71C, nominal."

    async def critic(goal, context):
        return "Results cover measurement and comparison; add a concrete \
mitigation example."

    async def synthesizer(goal, context):
        return ("GPU load 62% / 71C is within budget. Mitigation: cap "
                "batch size during long episodes and clean filters monthly.")

    orch = Orchestrator(planner, worker, critic, synthesizer,
                        worker_count=2)
    report = await orch.run("assess gpu load and propose mitigations")

    print("plan    :", report.plan)
    print("workers :", list(report.worker_results))
    print("critique:", report.critique[:80])
    print("answer  :", report.answer)
    print("success :", report.success)
    print("board   :", orch.blackboard.digest())


if __name__ == "__main__":
    asyncio.run(main())

"""Retry-audit demo: the task.retry audit trail, offline.

One task hits two transient failures then succeeds; each requeue lands
on the audit channel with its backoff — the trail an operator reads
when asking "why did this task run three times?".

    python examples/retry_audit_demo.py
"""

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def _run() -> list[dict]:
    from kernel.bus import EventBus
    from kernel.memory import Memory
    from kernel.scheduler import Scheduler

    memory = Memory(Path(tempfile.mkdtemp()) / "t.db", embedder_fn=None,
                    embed_dim=64)
    await memory.connect()
    bus = EventBus()
    audit_queue = bus.subscribe("audit")
    calls = {"n": 0}

    class FlakyAgent:
        async def run(self, goal, source=None):
            calls["n"] += 1
            if calls["n"] < 3:
                class R:
                    status = "failed"
                    answer = "all LLM tiers failed — both tiers down"
                    steps = 1
                return R()

            class R:
                status = "done"
                answer = "recovered"
                steps = 2
            return R()

    scheduler = Scheduler(memory, lambda: FlakyAgent(), bus,
                          poll_seconds=1)
    task_id = await scheduler.submit("flaky goal", "demo")
    task = (await memory.list_tasks(task_id=task_id))[0]
    for attempt in range(3):
        task["consecutive_failures"] = attempt
        await memory.mark_task_running(task_id)
        await scheduler._run_task(task)
    await memory.close()

    trail = []
    while not audit_queue.empty():
        event = audit_queue.get_nowait()
        if event["action"] in ("task.submit", "task.retry"):
            trail.append({"actor": event["actor"],
                          "action": event["action"],
                          "detail": event["detail"]})
    return trail


def main() -> None:
    print("audit trail (submit + retries, newest last):")
    for event in asyncio.run(_run()):
        print(f"  [{event['actor']}] {event['action']}: "
              f"{event['detail']}")


if __name__ == "__main__":
    main()

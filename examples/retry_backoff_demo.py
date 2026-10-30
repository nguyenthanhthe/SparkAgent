"""Retry demo: the scheduler's transient-failure backoff schedule.

Renders the exact backoff the scheduler computes per consecutive
failure (30s doubling, capped at 300s) and walks one task through two
transient failures and a success — the same path `_run_task` takes.

    python examples/retry_backoff_demo.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kernel.scheduler import Scheduler   # noqa: E402


def schedule() -> list[tuple[int, int]]:
    return [(attempt, min(300, 30 * 2 ** min(attempt, 4)))
            for attempt in range(5)]


async def _walk() -> list[str]:
    import asyncio
    import tempfile
    from pathlib import Path as _Path

    from kernel.bus import EventBus
    from kernel.memory import Memory

    memory = Memory(_Path(tempfile.mkdtemp()) / "t.db", embedder_fn=None,
                    embed_dim=64)
    await memory.connect()
    bus = EventBus()
    queue = bus.subscribe("scheduler")
    lines = []

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
    task_id = await memory.submit_task("flaky goal", "demo")
    task = (await memory.list_tasks(task_id=task_id))[0]
    for attempt in range(3):
        task["consecutive_failures"] = attempt
        await memory.mark_task_running(task_id)
        await scheduler._run_task(task)
        while not queue.empty():
            event = queue.get_nowait()
            if event["event"] == "task_finished":
                backoff = event.get("retry_backoff_s")
                lines.append(
                    f"attempt {attempt + 1}: {event['status']}"
                    + (f" — requeued in {backoff}s" if backoff
                       else " — done"))
    await memory.close()
    return lines


def main() -> None:
    print("backoff schedule (30s doubling, cap 300s):")
    for attempt, seconds in schedule():
        print(f"  consecutive_failures={attempt} -> retry in {seconds}s")
    print("\nwalkthrough:")
    import asyncio
    for line in asyncio.run(_walk()):
        print(f"  {line}")


if __name__ == "__main__":
    main()

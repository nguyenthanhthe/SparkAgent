"""Task board demo: per-status task tallies rendered offline.

The board that the scheduler refreshes every poll tick
(``task_status_counts`` in the scheduler stats) and that surfaces on
telegram ``/status`` and the dashboard's scheduler panel — driven here
against a throwaway SQLite so the shape is visible without a daemon.

    python examples/task_board_demo.py
"""

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kernel.bus import EventBus   # noqa: E402
from kernel.memory import Memory  # noqa: E402
from kernel.scheduler import Scheduler  # noqa: E402


def render(counts: dict[str, int]) -> str:
    return " / ".join(f"{n} {status}"
                      for status, n in sorted(counts.items()))


async def main() -> None:
    db = Path(tempfile.mkdtemp()) / "board.db"
    memory = Memory(db, embedder_fn=None, embed_dim=64)
    await memory.connect()
    scheduler = Scheduler(memory, lambda: None, EventBus(), poll_seconds=1)
    # stub the runner: this demo drives the board, it does not execute
    # episodes (a real Scheduler would run them via the brain callable)
    async def _no_run(task):
        pass
    scheduler._run_task = _no_run

    print("board before any tick: (no key — status surfaces omit the line)")
    print(f"  task_status_counts present: "
          f"{'task_status_counts' in scheduler.stats}")

    plants = await memory.submit_task("water the plants", source="demo")
    one = await memory.submit_task("one-shot errand", source="demo")
    recurring = await memory.submit_task(
        "heartbeat", source="demo", interval_seconds=3600)
    print("\nafter submit, before tick:")
    print(f"  {render(await memory.task_status_counts())}")

    await scheduler._tick()   # claims the two immediately-due tasks
    print("\nafter one tick (due one-shots claimed → running):")
    print(f"  {render(scheduler.stats['task_status_counts'])}")

    await memory.finish_task(one, success=True)
    await memory.finish_task(recurring, success=True)   # re-arms pending
    await memory.finish_task(plants, success=False)     # settles failed
    print("\nafter finishing all (recurring re-arms, one-shot fails):")
    print(f"  {render(await memory.task_status_counts())}")

    await memory.close()
    print("\nsurfaces: telegram /status 'tasks:' line · dashboard "
          "scheduler panel 'task board' row · /api/status scheduler block")


if __name__ == "__main__":
    asyncio.run(main())

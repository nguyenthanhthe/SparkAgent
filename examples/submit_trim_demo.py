"""Submit-trim demo: whitespace goal handling, rendered offline.

What the scheduler's submit path does with padded and whitespace-only
goals — trimming, audit mirroring, and the whitespace-only rejection —
the exact contract `tests/test_task_retry.py` pins.

    python examples/submit_trim_demo.py
"""

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def _run() -> list[tuple[str, str]]:
    from kernel.bus import EventBus
    from kernel.memory import Memory
    from kernel.scheduler import Scheduler

    memory = Memory(Path(tempfile.mkdtemp()) / "t.db", embedder_fn=None,
                    embed_dim=64)
    await memory.connect()
    bus = EventBus()
    audit = bus.subscribe("audit")
    scheduler = Scheduler(memory, lambda: None, bus, poll_seconds=1)

    trail: list[tuple[str, str]] = []
    for raw in ("  digest the telemetry  ", "   ", "\t\n"):
        try:
            task_id = await scheduler.submit(raw, "operator")
            row = (await memory.list_tasks(task_id=task_id))[0]
            trail.append(("stored", f"#{row['id']} goal={row['goal']!r}"))
        except ValueError as exc:
            trail.append(("rejected", str(exc)))

    while not audit.empty():
        entry = audit.get_nowait()
        if entry["action"] == "task.submit":
            trail.append(("audit", entry["detail"]))
    await memory.close()
    return trail


def main() -> None:
    for label, line in asyncio.run(_run()):
        print(f"{label}: {line}")


if __name__ == "__main__":
    main()

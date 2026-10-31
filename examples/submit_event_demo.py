"""Submit-event demo: task_submitted fan-out on the scheduler channel.

Two listeners watch the channel; one submit with dependencies fans the
event to both — the signal dashboards use to refresh without polling.

    python examples/submit_event_demo.py
"""

import asyncio
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


async def _run() -> list[tuple[str, dict]]:
    from kernel.bus import EventBus
    from kernel.memory import Memory
    from kernel.scheduler import Scheduler

    memory = Memory(Path(tempfile.mkdtemp()) / "t.db", embedder_fn=None,
                    embed_dim=64)
    await memory.connect()
    bus = EventBus()
    dashboard = bus.subscribe("scheduler")
    sse_stream = bus.subscribe("scheduler")
    scheduler = Scheduler(memory, lambda: None, bus, poll_seconds=1)

    upstream = await scheduler.submit("fetch the report", "operator")
    await scheduler.submit("email the report", "operator",
                           depends_on=[upstream])
    await memory.close()

    trail = []
    for name, queue in (("dashboard", dashboard),
                        ("sse-stream", sse_stream)):
        while not queue.empty():
            trail.append((name, queue.get_nowait()))
    return trail


def main() -> None:
    seen = {}
    for name, event in asyncio.run(_run()):
        seen.setdefault(name, []).append(event)
    for name, events in seen.items():
        print(f"{name}:")
        for event in events:
            print(f"  {event['event']} #{event['task_id']} "
                  f"(source={event['source']}, "
                  f"depends_on={event['depends_on']})")


if __name__ == "__main__":
    main()

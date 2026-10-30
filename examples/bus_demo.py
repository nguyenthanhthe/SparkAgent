"""Bus demo: publish/subscribe fan-out and subscriber_count, offline.

A synthetic producer publishes to the ``scheduler`` channel; two
subscribers fan out; one unsubscribes and the count drops — the same
EventBus surface the daemon, the dashboard streams, and the audit
persist loop use.

    python examples/bus_demo.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kernel.bus import EventBus   # noqa: E402


async def main() -> None:
    bus = EventBus()
    bus.bind_loop(asyncio.get_running_loop())
    dashboard = bus.subscribe("scheduler")
    logger = bus.subscribe("scheduler")
    print(f"subscribers: {bus.subscriber_count()} "
          f"(dashboard + logger on 'scheduler')")

    bus.publish("scheduler", {"event": "task_started", "task_id": 1})
    bus.publish("subscriber_count", None)   # wrong channel: nobody hears it
    for name, queue in (("dashboard", dashboard), ("logger", logger)):
        print(f"{name:10s} heard: {queue.get_nowait()}")

    bus.publish_threadsafe("scheduler",
                           {"event": "task_finished", "task_id": 1})
    await asyncio.sleep(0)   # let the loop run the scheduled callback
    print(f"threadsafe publish delivered: {dashboard.get_nowait()} "
          f"(loop is bound; unbound, it would be dropped)")

    bus.unsubscribe("scheduler", logger)
    print(f"after unsubscribe: {bus.subscriber_count()} subscriber(s), "
          f"per-channel {bus.subscriber_count('scheduler')}")

    bus.publish("scheduler", {"event": "task_cancelled", "task_id": 2})
    print(f"dashboard heard: {dashboard.get_nowait()}")
    late = []
    while not logger.empty():
        late.append(logger.get_nowait())
    print(f"logger (unsubscribed) received nothing new: "
          f"{not any(e['event'] == 'task_cancelled' for e in late)}")


if __name__ == "__main__":
    asyncio.run(main())

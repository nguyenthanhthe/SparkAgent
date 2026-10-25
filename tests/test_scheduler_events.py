"""Scheduler blocked/released events — dependency transitions on the bus."""

import asyncio
import tempfile
import unittest
from pathlib import Path

from kernel.bus import EventBus
from kernel.memory import Memory
from kernel.scheduler import Scheduler


def collect_events(bus: EventBus, queue) -> list[dict]:
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    return events


class BlockedEventsTests(unittest.IsolatedAsyncioTestCase):
    async def test_blocked_then_released_transitions(self):
        memory = Memory(Path(tempfile.mkdtemp()) / "t.db", embedder_fn=None,
                        embed_dim=64)
        await memory.connect()
        try:
            bus = EventBus()
            queue = bus.subscribe("scheduler")
            scheduler = Scheduler(memory, lambda: None, bus,
                                  poll_seconds=1)
            first = await memory.submit_task("first", "test")
            second = await memory.submit_task("second", "test",
                                              depends_on=[first])

            # _publish_block_changes directly: a full _tick would also
            # *execute* due tasks, and this test drives the task state
            # machine by hand
            await scheduler._publish_block_changes()
            events = collect_events(bus, queue)
            self.assertEqual([e["event"] for e in events],
                             ["task_blocked"])
            self.assertEqual(events[0]["task_id"], second)
            self.assertEqual(events[0]["blocked_by"], [first])

            # still blocked — no duplicate event
            await scheduler._publish_block_changes()
            self.assertEqual(collect_events(bus, queue), [])

            # release: upstream finishes
            await memory.mark_task_running(first)
            await memory.finish_task(first, success=True)
            await scheduler._publish_block_changes()
            events = collect_events(bus, queue)
            self.assertEqual([e["event"] for e in events],
                             ["task_released"])
            self.assertEqual(events[0]["task_id"], second)
        finally:
            await memory.close()

    async def test_no_events_without_dependencies(self):
        memory = Memory(Path(tempfile.mkdtemp()) / "t.db", embedder_fn=None,
                        embed_dim=64)
        await memory.connect()
        try:
            bus = EventBus()
            queue = bus.subscribe("scheduler")
            scheduler = Scheduler(memory, lambda: None, bus,
                                  poll_seconds=1)
            await memory.submit_task("solo", "test")
            await scheduler._publish_block_changes()
            self.assertEqual(collect_events(bus, queue), [])
        finally:
            await memory.close()

    async def test_blocked_pending_tasks_lists_unsatisfied(self):
        memory = Memory(Path(tempfile.mkdtemp()) / "t.db", embedder_fn=None,
                        embed_dim=64)
        await memory.connect()
        try:
            first = await memory.submit_task("first", "test")
            second = await memory.submit_task("second", "test",
                                              depends_on=[first])
            await memory.pause_resume(first, enabled=False)
            # paused upstream is not 'done', so the dependent stays blocked
            blocked = await memory.blocked_pending_tasks()
            self.assertEqual([t["id"] for t in blocked], [second])
            self.assertEqual(blocked[0]["blocked_by"], [first])
        finally:
            await memory.close()


if __name__ == "__main__":
    unittest.main()

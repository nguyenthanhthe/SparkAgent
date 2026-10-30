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
            # blocked-task count tracks the scan for /api/status
            self.assertEqual(scheduler.stats["blocked_tasks"], 1)

            # still blocked — no duplicate event
            await scheduler._publish_block_changes()
            self.assertEqual(collect_events(bus, queue), [])
            self.assertEqual(scheduler.stats["blocked_tasks"], 1)

            # release: upstream finishes
            await memory.mark_task_running(first)
            await memory.finish_task(first, success=True)
            await scheduler._publish_block_changes()
            events = collect_events(bus, queue)
            self.assertEqual([e["event"] for e in events],
                             ["task_released"])
            self.assertEqual(events[0]["task_id"], second)
            self.assertEqual(scheduler.stats["blocked_tasks"], 0)
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

    async def test_tick_records_inflight_gauge(self):
        import kernel.scheduler as scheduler_mod
        from kernel.metrics import MetricsRegistry
        registry = MetricsRegistry()
        original = scheduler_mod.REGISTRY
        scheduler_mod.REGISTRY = registry
        memory = Memory(Path(tempfile.mkdtemp()) / "t.db", embedder_fn=None,
                        embed_dim=64)
        try:
            await memory.connect()
            scheduler = Scheduler(memory, lambda: None, EventBus(),
                                  poll_seconds=1)
            await scheduler._tick()   # nothing due: gauge lands at 0
            self.assertEqual(registry.gauge_value("scheduler_inflight"), 0.0)
            self.assertEqual(registry.gauge_value("scheduler_blocked"), 0.0)
        finally:
            scheduler_mod.REGISTRY = original
            await memory.close()


class TaskStartedEventTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_task_publishes_started(self):
        memory = Memory(Path(tempfile.mkdtemp()) / "t.db", embedder_fn=None,
                        embed_dim=64)

        class FakeAgent:
            async def run(self, goal, source=None):
                return type("R", (), {"status": "done", "answer": "ok",
                                      "steps": 4, "tier": "local"})()

        try:
            await memory.connect()
            task_id = await memory.submit_task("publish me", "test")
            task = (await memory.list_tasks(task_id=task_id))[0]
            bus = EventBus()
            queue = bus.subscribe("scheduler")
            scheduler = Scheduler(memory, lambda: FakeAgent(), bus,
                                  poll_seconds=1)
            await scheduler._run_task(task)
            events = []
            while not queue.empty():
                events.append(queue.get_nowait())
            started = [e for e in events if e["event"] == "task_started"]
            self.assertEqual(len(started), 1)
            self.assertEqual(started[0]["task_id"], task_id)
            self.assertEqual(started[0]["source"], "test")
            self.assertEqual(started[0]["priority"], 5)
            finished = [e for e in events if e["event"] == "task_finished"]
            self.assertEqual(len(finished), 1)
            self.assertEqual(finished[0]["status"], "done")
            self.assertEqual(finished[0]["source"], "test")
            self.assertEqual(finished[0]["steps"], 4)
            self.assertEqual(finished[0]["model_tier"], "local")
            self.assertIsNone(finished[0]["retry_backoff_s"])
            self.assertGreaterEqual(finished[0]["duration_s"], 0)
        finally:
            await memory.close()

    async def test_finished_event_carries_source_on_crash(self):
        memory = Memory(Path(tempfile.mkdtemp()) / "t.db", embedder_fn=None,
                        embed_dim=64)

        class ExplodingAgent:
            async def run(self, goal, source=None):
                raise RuntimeError("episode blew up")

        try:
            await memory.connect()
            task_id = await memory.submit_task("crash me", "cron")
            task = (await memory.list_tasks(task_id=task_id))[0]
            bus = EventBus()
            queue = bus.subscribe("scheduler")
            scheduler = Scheduler(memory, lambda: ExplodingAgent(), bus,
                                  poll_seconds=1)
            await scheduler._run_task(task)
            events = []
            while not queue.empty():
                events.append(queue.get_nowait())
            finished = [e for e in events if e["event"] == "task_finished"]
            self.assertEqual(len(finished), 1)
            self.assertEqual(finished[0]["source"], "cron")
            self.assertEqual(finished[0]["status"], "failed")
        finally:
            await memory.close()

    async def test_tick_claims_nothing_once_stopping(self):
        memory = Memory(Path(tempfile.mkdtemp()) / "t.db", embedder_fn=None,
                        embed_dim=64)
        try:
            await memory.connect()
            task_id = await memory.submit_task("should not run", "test")
            scheduler = Scheduler(memory, lambda: None, EventBus(),
                                  poll_seconds=1)
            scheduler.stop()
            await scheduler._tick()
            row = (await memory.list_tasks(task_id=task_id))[0]
            self.assertEqual(row["status"], "pending")   # unclaimed
            self.assertEqual(scheduler.stats["episodes_done"], 0)
        finally:
            await memory.close()


class ShutdownDrainTests(unittest.IsolatedAsyncioTestCase):
    async def test_drained_tasks_counted_on_stop(self):
        import kernel.scheduler as scheduler_mod
        from kernel.metrics import MetricsRegistry
        registry = MetricsRegistry()
        original = scheduler_mod.REGISTRY
        scheduler_mod.REGISTRY = registry
        memory = Memory(Path(tempfile.mkdtemp()) / "t.db", embedder_fn=None,
                        embed_dim=64)

        class FakeAgent:
            async def run(self, goal, source=None):
                await asyncio.sleep(0.2)
                return type("R", (), {"status": "done", "answer": "ok"})()

        try:
            await memory.connect()
            await memory.submit_task("long running", "test")
            scheduler = Scheduler(memory, lambda: FakeAgent(), EventBus(),
                                  poll_seconds=0.05, concurrency=2)
            loop_task = asyncio.create_task(scheduler.run_forever())
            for _ in range(50):                     # wait for the claim
                await asyncio.sleep(0.05)
                if scheduler._inflight:
                    break
            self.assertTrue(scheduler._inflight)
            scheduler.stop()
            await asyncio.wait_for(loop_task, timeout=5)
            self.assertGreaterEqual(
                registry.counter("shutdown_drained_tasks"), 1.0)
        finally:
            scheduler_mod.REGISTRY = original
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

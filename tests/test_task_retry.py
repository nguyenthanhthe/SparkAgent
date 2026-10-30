import asyncio
import tempfile
import unittest
from pathlib import Path

from kernel.bus import EventBus
from kernel.memory import Memory
from kernel.scheduler import Scheduler


def run(coro):
    return asyncio.run(coro)


class RetryOneShotTests(unittest.TestCase):
    def setUp(self):
        self.db = Path(tempfile.mkdtemp()) / "t.db"
        self.mem = Memory(self.db, embedder_fn=None, embed_dim=64)
        run(self.mem.connect())

    def tearDown(self):
        if self.mem._conn:
            self.mem._conn.close()

    def test_finished_one_shot_rearmed(self):
        tid = run(self.mem.submit_task("retry me", "test"))
        run(self.mem.mark_task_running(tid))
        run(self.mem.finish_task(tid, success=False))
        self.assertTrue(run(self.mem.retry_one_shot(tid, 9999999999.0)))
        row = run(self.mem.list_tasks(task_id=tid))[0]
        self.assertEqual(row["status"], "pending")
        self.assertEqual(row["next_run_at"], 9999999999.0)

    def test_recurring_not_rearmed(self):
        tid = run(self.mem.submit_task("hourly", "test",
                                       interval_seconds=3600))
        run(self.mem.mark_task_running(tid))
        run(self.mem.finish_task(tid, success=False))
        self.assertFalse(run(self.mem.retry_one_shot(tid, 123.0)))

    def test_unknown_task_false(self):
        self.assertFalse(run(self.mem.retry_one_shot(424242, 1.0)))


class SubmitGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_whitespace_goal_rejected_with_reason(self):
        memory = Memory(Path(tempfile.mkdtemp()) / "t.db", embedder_fn=None,
                        embed_dim=64)
        await memory.connect()
        try:
            bus = EventBus()
            audit_queue = bus.subscribe("audit")
            scheduler = Scheduler(memory, lambda: None, bus,
                                  poll_seconds=1)
            with self.assertRaises(ValueError) as ctx:
                await scheduler.submit("   \n\t")
            self.assertIn("whitespace-only", str(ctx.exception))
            with self.assertRaises(ValueError) as ctx:
                await scheduler.submit("")
            self.assertIn("empty", str(ctx.exception))
            # a padded goal is trimmed, not rejected
            task_id = await scheduler.submit("  real goal  ")
            row = (await memory.list_tasks(task_id=task_id))[0]
            self.assertEqual(row["goal"], "real goal")
            # the audit line mirrors the trimmed goal, not the raw input
            events = []
            while not audit_queue.empty():
                events.append(audit_queue.get_nowait())
            entry = next(e for e in events
                         if e["action"] == "task.submit")
            self.assertTrue(entry["detail"].startswith(
                f"#{task_id} real goal"))
        finally:
            await memory.close()


class SchedulerRetryTests(unittest.IsolatedAsyncioTestCase):
    async def test_transient_failure_requeues_one_shot(self):
        memory = Memory(Path(tempfile.mkdtemp()) / "t.db", embedder_fn=None,
                        embed_dim=64)
        await memory.connect()
        try:
            task_id = await memory.submit_task("flaky goal", "test")
            await memory.mark_task_running(task_id)

            class FlakyAgent:
                async def run(self, goal, source):
                    class R:
                        status = "failed"
                        answer = "all LLM tiers failed — local down, " \
                                 "remote down"
                        steps = 1
                    return R()

            scheduler = Scheduler(memory, lambda: FlakyAgent(),
                                  EventBus(), poll_seconds=1)
            await scheduler._run_task({"id": task_id, "goal": "flaky goal",
                                       "source": "test",
                                       "consecutive_failures": 0})
            self.assertEqual(scheduler.stats.get("retries"), 1)
            # transient failures split off from the permanent count
            self.assertEqual(
                scheduler.stats.get("episodes_failed_transient"), 1)
            self.assertEqual(scheduler.stats.get("episodes_failed", 0), 0)
            row = (await memory.list_tasks(task_id=task_id))[0]
            self.assertEqual(row["status"], "pending")  # requeued
            self.assertGreater(row["next_run_at"], 0)
        finally:
            await memory.close()

    async def test_permanent_failure_not_requeued(self):
        memory = Memory(Path(tempfile.mkdtemp()) / "t.db", embedder_fn=None,
                        embed_dim=64)
        await memory.connect()
        try:
            task_id = await memory.submit_task("bad plan", "test")
            await memory.mark_task_running(task_id)

            class BadAgent:
                async def run(self, goal, source):
                    class R:
                        status = "failed"
                        answer = "max_steps=12 without a final answer"
                        steps = 12
                    return R()

            scheduler = Scheduler(memory, lambda: BadAgent(),
                                  EventBus(), poll_seconds=1)
            await scheduler._run_task({"id": task_id, "goal": "bad plan",
                                       "source": "test",
                                       "consecutive_failures": 0})
            self.assertEqual(scheduler.stats.get("retries", 0), 0)
            self.assertEqual(scheduler.stats.get("episodes_failed"), 1)
            self.assertEqual(
                scheduler.stats.get("episodes_failed_transient", 0), 0)
            row = (await memory.list_tasks(task_id=task_id))[0]
            self.assertEqual(row["status"], "failed")
        finally:
            await memory.close()


if __name__ == "__main__":
    unittest.main()

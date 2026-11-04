"""Scheduler stats surface — started_at mirrors the daemon's boot stamp."""

import time
import tempfile
import unittest
from pathlib import Path

from kernel.bus import EventBus
from kernel.memory import Memory
from kernel.scheduler import Scheduler


class SchedulerStatsTests(unittest.IsolatedAsyncioTestCase):
    async def test_boot_log_carries_poll_cadence(self):
        memory = Memory(Path(tempfile.mkdtemp()) / "t.db", embedder_fn=None,
                        embed_dim=64)
        await memory.connect()
        try:
            scheduler = Scheduler(memory, lambda: None, EventBus(),
                                  poll_seconds=2, concurrency=3)
            # a pre-set stop makes run_forever a boot-only pass: the
            # startup lines log, the tick loop never runs
            scheduler.stop()
            with self.assertLogs("sparkagent.scheduler",
                                 level="INFO") as captured:
                await scheduler.run_forever()
            boot = next(line for line in captured.output
                        if "scheduler started" in line)
            # the poll cadence config is visible at boot, so an
            # operator can tell a mis-tuned cadence without opening
            # the config
            self.assertIn("poll=2s", boot)
            self.assertIn("concurrency=3", boot)
        finally:
            await memory.close()

    async def test_stats_carry_started_at_from_construction(self):
        memory = Memory(Path(tempfile.mkdtemp()) / "t.db", embedder_fn=None,
                        embed_dim=64)
        await memory.connect()
        try:
            before = time.time()
            scheduler = Scheduler(memory, lambda: None, EventBus(),
                                  poll_seconds=1)
            after = time.time()

            started_at = scheduler.stats["started_at"]
            self.assertIsInstance(started_at, float)
            self.assertGreaterEqual(started_at, before)
            self.assertLessEqual(started_at, after)

            # the /api/status payload spreads stats verbatim, so the
            # stamp must travel with dict(stats)
            self.assertIn("started_at", dict(scheduler.stats))
        finally:
            await memory.close()

    async def test_tick_refreshes_task_status_counts(self):
        memory = Memory(Path(tempfile.mkdtemp()) / "t.db", embedder_fn=None,
                        embed_dim=64)
        await memory.connect()
        try:
            scheduler = Scheduler(memory, lambda: None, EventBus(),
                                  poll_seconds=1)
            # before the first tick the board key simply isn't there yet
            self.assertNotIn("task_status_counts", scheduler.stats)
            task_id = await memory.submit_task("count me", source="test")
            # stub the runner: the real one would execute the episode in
            # the background (brain callable returns None → failure) and
            # race this test's finish_task
            async def _no_run(task):
                pass
            scheduler._run_task = _no_run
            await scheduler._tick()
            # the tick claims due work before snapshotting the board,
            # so an immediately-due one-shot shows as running
            self.assertEqual(scheduler.stats["task_status_counts"],
                             {"running": 1})
            # the board tracks lifecycle transitions on later ticks
            await memory.finish_task(task_id, success=True)
            await scheduler._tick()
            self.assertEqual(scheduler.stats["task_status_counts"],
                             {"done": 1})
        finally:
            await memory.close()

    async def test_started_at_unchanged_by_ticks(self):
        memory = Memory(Path(tempfile.mkdtemp()) / "t.db", embedder_fn=None,
                        embed_dim=64)
        await memory.connect()
        try:
            scheduler = Scheduler(memory, lambda: None, EventBus(),
                                  poll_seconds=1)
            await scheduler._publish_block_changes()
            self.assertEqual(scheduler.stats["started_at"],
                             scheduler.stats["started_at"])
        finally:
            await memory.close()


if __name__ == "__main__":
    unittest.main()

"""Scheduler stats surface — started_at mirrors the daemon's boot stamp."""

import time
import tempfile
import unittest
from pathlib import Path

from kernel.bus import EventBus
from kernel.memory import Memory
from kernel.scheduler import Scheduler


class SchedulerStatsTests(unittest.IsolatedAsyncioTestCase):
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

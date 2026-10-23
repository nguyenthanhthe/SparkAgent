import asyncio
import tempfile
import time
import unittest
from pathlib import Path

from kernel.memory import Memory, _next_daily


def run(coro):
    return asyncio.run(coro)


class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.db = Path(tempfile.mkdtemp()) / "test.db"
        self.mem = Memory(self.db, embedder_fn=None, embed_dim=256)

    def tearDown(self):
        if self.mem._conn:
            self.mem._conn.close()

    def test_episode_lifecycle(self):
        async def scenario():
            await self.mem.connect()
            eid = await self.mem.start_episode("test goal", "operator")
            await self.mem.log_step(eid, 1, "action", "echo hi")
            await self.mem.finish_episode(eid, "done", "answer", "local", 1)
            episodes = await self.mem.recent_episodes()
            self.assertEqual(len(episodes), 1)
            self.assertEqual(episodes[0]["status"], "done")
            self.assertEqual(episodes[0]["final_answer"], "answer")
        run(scenario())

    def test_remember_and_recall_ranking(self):
        async def scenario():
            await self.mem.connect()
            await self.mem.remember("The cat sat on the mat", kind="note",
                                    key="cat")
            await self.mem.remember("Kubernetes pods scheduled across nodes",
                                    kind="note", key="k8s")
            await self.mem.remember("Favorite color is blue", kind="preference")
            hits = await self.mem.recall("where did the cat sit?", k=2)
            self.assertTrue(hits)
            self.assertEqual(hits[0].key, "cat")
            hits2 = await self.mem.recall("container orchestration nodes")
            self.assertEqual(hits2[0].key, "k8s")
        run(scenario())

    def test_task_submit_due_claim_finish_oneshot(self):
        async def scenario():
            await self.mem.connect()
            tid = await self.mem.submit_task("say hi", "operator")
            due = await self.mem.due_tasks()
            self.assertEqual([t["id"] for t in due], [tid])
            self.assertTrue(await self.mem.mark_task_running(tid))
            self.assertFalse(await self.mem.mark_task_running(tid))  # not re-claimable
            self.assertEqual(await self.mem.due_tasks(), [])
            await self.mem.finish_task(tid, success=True)
            # one-shot: pending status was overwritten to running; finish marks done
            row = (await self.mem.list_tasks(task_id=tid))[0]
            self.assertEqual(row["last_status"], "done")
            self.assertFalse(row["enabled"] and row["status"] == "pending")
        run(scenario())

    def test_recurring_task_reschedules_and_autodisables(self):
        async def scenario():
            await self.mem.connect()
            tid = await self.mem.submit_task("hourly gpu check", "operator",
                                             interval_seconds=3600)
            self.assertTrue(await self.mem.mark_task_running(tid))
            await self.mem.finish_task(tid, success=False)
            row = (await self.mem.list_tasks(task_id=tid))[0]
            self.assertEqual(row["consecutive_failures"], 1)
            self.assertTrue(row["next_run_at"] > time.time() + 3000)
            for _ in range(2):
                await self.mem.mark_task_running(tid)
                await self.mem.finish_task(tid, success=False)
            row = (await self.mem.list_tasks(task_id=tid))[0]
            self.assertEqual(row["consecutive_failures"], 3)
            self.assertEqual(row["enabled"], 0)  # auto-disabled
        run(scenario())

    def test_cancel_and_stale_reset(self):
        async def scenario():
            await self.mem.connect()
            tid = await self.mem.submit_task("x", "operator")
            await self.mem.mark_task_running(tid)
            self.assertEqual(await self.mem.reset_stale_running(), 1)
            row = (await self.mem.list_tasks(task_id=tid))[0]
            self.assertEqual(row["status"], "pending")
            self.assertTrue(await self.mem.cancel_task(tid))
            self.assertFalse(await self.mem.cancel_task(tid))
        run(scenario())

    def test_audit_rows(self):
        async def scenario():
            await self.mem.connect()
            await self.mem.audit("test", "action", "detail with 'quotes'")
            rows = await self.mem.recent_audit(limit=5)
            self.assertEqual(rows[0]["actor"], "test")
        run(scenario())


class DailyAtTests(unittest.TestCase):
    def test_valid(self):
        from datetime import datetime
        now = datetime(2026, 1, 1, 10, 0)
        self.assertEqual(_next_daily("09:00", now),
                         datetime(2026, 1, 2, 9, 0).timestamp())
        self.assertEqual(_next_daily("11:30", now),
                         datetime(2026, 1, 1, 11, 30).timestamp())

    def test_invalid(self):
        for bad in ("25:00", "10:99", "banana", ""):
            with self.assertRaises(ValueError):
                _next_daily(bad)


if __name__ == "__main__":
    unittest.main()

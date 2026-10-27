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

    def test_forget_deletes_by_key(self):
        async def scenario():
            await self.mem.connect()
            await self.mem.remember("transient note", kind="note",
                                    key="temp")
            self.assertTrue(await self.mem.forget("temp"))
            # second call: nothing left to remove
            self.assertFalse(await self.mem.forget("temp"))
            self.assertFalse(await self.mem.forget(""))
            hits = await self.mem.recall("transient note", k=5)
            self.assertEqual(hits, [])
        run(scenario())

    def test_recall_excludes_digest_markers_by_default(self):
        async def scenario():
            await self.mem.connect()
            await self.mem.remember("[digested] check thermals",
                                    kind="digest-marker", key="episode:1")
            await self.mem.remember("thermals checked and nominal",
                                    kind="fact")
            hits = await self.mem.recall("check thermals", k=5)
            self.assertEqual([h.kind for h in hits], ["fact"])
            explicit = await self.mem.recall("check thermals", k=5,
                                             kinds=["digest-marker"])
            self.assertEqual([h.kind for h in explicit],
                             ["digest-marker"])
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
        now = datetime(2026, 1, 1, 10, 0)     # Thursday
        self.assertEqual(_next_daily("09:00", now),
                         datetime(2026, 1, 2, 9, 0).timestamp())
        self.assertEqual(_next_daily("11:30", now),
                         datetime(2026, 1, 1, 11, 30).timestamp())

    def test_invalid(self):
        for bad in ("25:00", "10:99", "banana", ""):
            with self.assertRaises(ValueError):
                _next_daily(bad)

    def test_multiple_times_pick_soonest(self):
        from datetime import datetime
        now = datetime(2026, 1, 1, 10, 0)     # Thursday
        self.assertEqual(_next_daily("09:00,11:00", now),
                         datetime(2026, 1, 1, 11, 0).timestamp())

    def test_weekday_filter_skips_weekend(self):
        from datetime import datetime
        friday_evening = datetime(2026, 1, 2, 18, 0)      # Friday 18:00
        # mon-fri@09:00 from Friday evening -> Monday 09:00
        self.assertEqual(_next_daily("mon-fri@09:00", friday_evening),
                         datetime(2026, 1, 5, 9, 0).timestamp())

    def test_specific_weekdays(self):
        from datetime import datetime
        wednesday = datetime(2026, 1, 7, 12, 0)           # Wednesday
        # mon,wed,fri@08:00 from Wed noon -> Friday 08:00
        self.assertEqual(_next_daily("mon,wed,fri@08:00", wednesday),
                         datetime(2026, 1, 9, 8, 0).timestamp())

    def test_spec_parse_shape(self):
        from kernel.memory import parse_daily_spec
        days, times = parse_daily_spec("mon-fri@09:00,17:30")
        self.assertEqual(days, {0, 1, 2, 3, 4})
        self.assertEqual(times, [(9, 0), (17, 30)])
        days, times = parse_daily_spec("08:00")
        self.assertEqual(len(days), 7)
        self.assertEqual(times, [(8, 0)])

    def test_spec_parse_errors(self):
        from kernel.memory import parse_daily_spec
        for bad in ("funday@09:00", "mon@99:00", "@09:00", ""):
            with self.assertRaises(ValueError):
                parse_daily_spec(bad)


if __name__ == "__main__":
    unittest.main()

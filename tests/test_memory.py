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
            await self.mem.remember("transient note two", kind="note",
                                    key="temp")
            self.assertEqual(await self.mem.forget("temp"), 2)
            # second call: nothing left to remove — absent, not invalid
            self.assertEqual(await self.mem.forget("temp"), 0)
            # an empty key is a caller bug, not a miss
            with self.assertRaises(ValueError):
                await self.mem.forget("")
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

    def test_remember_rejects_empty_text(self):
        async def scenario():
            await self.mem.connect()
            with self.assertRaises(ValueError):
                await self.mem.remember("")
            with self.assertRaises(ValueError):
                await self.mem.remember("   ")
            await self.mem.remember("real note")   # unaffected
        run(scenario())

    def test_rename_key_refuses_existing_target(self):
        async def scenario():
            await self.mem.connect()
            await self.mem.remember("keep me", key="good-key")
            await self.mem.remember("fix me", key="typo")
            with self.assertRaises(ValueError) as ctx:
                await self.mem.rename_key("typo", "good-key")
            self.assertIn("already exists", str(ctx.exception))
            # the refused rename leaves both keys intact
            self.assertEqual(await self.mem.count(key_contains="typo"), 1)
            self.assertEqual(await self.mem.count(key_contains="good-key"),
                             1)
        run(scenario())

    def test_count_key_substring_filter(self):
        async def scenario():
            await self.mem.connect()
            await self.mem.remember("note one", kind="note", key="ep:1")
            await self.mem.remember("note two", kind="note", key="ep:2")
            await self.mem.remember("digest", kind="digest", key="ep:1")
            self.assertEqual(await self.mem.count(), 3)
            self.assertEqual(await self.mem.count(key_contains="ep:1"), 2)
            self.assertEqual(await self.mem.count(kind="note",
                                                  key_contains="ep:2"), 1)
            self.assertEqual(await self.mem.count(key_contains="nope"), 0)
        run(scenario())

    def test_remember_reports_created_at_stamp(self):
        async def scenario():
            await self.mem.connect()
            # default return stays the plain row id
            plain = await self.mem.remember("plain note")
            self.assertIsInstance(plain, int)
            stamped = await self.mem.remember("stamped note",
                                              with_stamp=True)
            self.assertIsInstance(stamped, dict)
            self.assertIsInstance(stamped["id"], int)
            self.assertIn("T", stamped["created_at"])
            # the persisted row really carries the reported stamp
            row = self.mem._conn.execute(
                "SELECT created_at FROM memories WHERE id = ?",
                (stamped["id"],)).fetchone()
            self.assertEqual(row["created_at"], stamped["created_at"])
        run(scenario())

    def test_recall_zero_snippet_width_skips_windowing(self):
        async def scenario():
            await self.mem.connect()
            await self.mem.remember("gpu thermal data " * 10)
            hits = await self.mem.recall("gpu thermal", k=1,
                                         snippet_width=0)
            self.assertIsNone(hits[0].snippet)
        run(scenario())

    def test_recall_highlight_needle_override(self):
        async def scenario():
            await self.mem.connect()
            await self.mem.remember(
                "gpu thermal cap is 85c and the fan curve follows it")
            hits = await self.mem.recall("gpu thermal", k=1)
            self.assertIn("**", hits[0].snippet)   # query terms marked
            plain = hits[0].snippet
            hits = await self.mem.recall("gpu thermal", k=1,
                                         highlight="fan")
            self.assertIn("**fan**", hits[0].snippet)
            self.assertNotEqual(plain, hits[0].snippet)
        run(scenario())

    def test_recall_snippet_width_param(self):
        async def scenario():
            await self.mem.connect()
            await self.mem.remember("long text about gpu " * 20,
                                    kind="note")
            narrow = await self.mem.recall("gpu", k=1, snippet_width=60)
            wide = await self.mem.recall("gpu", k=1, snippet_width=400)
            self.assertLessEqual(len(narrow[0].snippet), 76)
            self.assertGreater(len(wide[0].snippet),
                               len(narrow[0].snippet))
        run(scenario())

    def test_recall_dedupes_same_key(self):
        async def scenario():
            await self.mem.connect()
            await self.mem.remember("gpu temperature runs high", kind="note",
                                    key="gpu")
            await self.mem.remember("gpu temperature spikes at noon",
                                    kind="note", key="gpu")
            hits = await self.mem.recall("gpu temperature", k=5)
            keys = [h.key for h in hits if h.key == "gpu"]
            self.assertEqual(len(keys), 1)   # best score kept, dupe dropped
        run(scenario())

    def test_rename_key_repairs_mistyped_key(self):
        async def scenario():
            await self.mem.connect()
            await self.mem.remember("note one", kind="note", key="gppu")
            await self.mem.remember("note two", kind="fact", key="gppu")
            moved = await self.mem.rename_key("gppu", "gpu")
            self.assertEqual(moved, 2)
            with self.assertRaises(ValueError):
                await self.mem.rename_key("gpu", "gpu")
            with self.assertRaises(ValueError):
                await self.mem.rename_key("", "x")
            hits = await self.mem.recall("note one", k=5)
            self.assertEqual(hits[0].key, "gpu")
        run(scenario())

    def test_count_by_kind(self):
        async def scenario():
            await self.mem.connect()
            await self.mem.remember("a note", kind="note")
            await self.mem.remember("a fact", kind="fact")
            await self.mem.remember("another note", kind="note")
            self.assertEqual(await self.mem.count(), 3)
            self.assertEqual(await self.mem.count("note"), 2)
            self.assertEqual(await self.mem.count("fact"), 1)
            self.assertEqual(await self.mem.count("nothing"), 0)
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

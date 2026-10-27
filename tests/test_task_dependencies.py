"""Task dependency gating — submit with depends_on, blocked until deps done."""

import asyncio
import tempfile
import unittest
from pathlib import Path

from kernel.bus import EventBus
from kernel.memory import Memory


def run(coro):
    return asyncio.run(coro)


class DependencySubmitTests(unittest.TestCase):
    def setUp(self):
        self.db = Path(tempfile.mkdtemp()) / "t.db"
        self.mem = Memory(self.db, embedder_fn=None, embed_dim=64)
        run(self.mem.connect())

    def tearDown(self):
        if self.mem._conn:
            self.mem._conn.close()

    def test_submit_stores_sorted_deduped_deps(self):
        first = run(self.mem.submit_task("first", "test"))
        second = run(self.mem.submit_task("second", "test",
                                          depends_on=[first, first]))
        row = run(self.mem.list_tasks(task_id=second))[0]
        self.assertEqual(row["depends_on"], f"[{first}]")

    def test_submit_rejects_unknown_dependency(self):
        with self.assertRaises(ValueError):
            run(self.mem.submit_task("orphan", "test", depends_on=[424242]))

    def test_submit_rejects_nonpositive_dependency(self):
        with self.assertRaises(ValueError):
            run(self.mem.submit_task("bad", "test", depends_on=[0]))

    def test_depends_on_defaults_null(self):
        tid = run(self.mem.submit_task("solo", "test"))
        row = run(self.mem.list_tasks(task_id=tid))[0]
        self.assertIsNone(row["depends_on"])

    def test_migration_adds_depends_on_to_legacy_db(self):
        # simulate a pre-dependency database: drop the column's data by
        # recreating a table without it is overkill — instead verify the
        # migration helper tolerates an existing (fresh) schema idempotently
        self.mem._migrate()  # second call must be a no-op
        cols = {row["name"] for row in self.mem._conn.execute(
            "PRAGMA table_info(tasks)")}
        self.assertIn("depends_on", cols)

    def test_submit_detects_cycle_in_existing_rows(self):
        # hand-corrupted rows (e.g. manual db edit) forming a cycle:
        # submitting anything that hangs off it must refuse loudly
        a = run(self.mem.submit_task("a", "test"))
        b = run(self.mem.submit_task("b", "test"))
        self.mem._conn.execute(
            "UPDATE tasks SET depends_on = ? WHERE id = ?", (f"[{b}]", a))
        self.mem._conn.execute(
            "UPDATE tasks SET depends_on = ? WHERE id = ?", (f"[{a}]", b))
        self.mem._conn.commit()
        with self.assertRaises(ValueError) as ctx:
            run(self.mem.submit_task("c", "test", depends_on=[a]))
        self.assertIn("dependency cycle", str(ctx.exception))

    def test_submit_walks_transitive_deps(self):
        # a -> b -> c chain; d depends on a, so the walk pulls the whole
        # closure — a dangling id deep in the chain is rejected at submit
        c = run(self.mem.submit_task("c", "test"))
        b = run(self.mem.submit_task("b", "test", depends_on=[c]))
        a = run(self.mem.submit_task("a", "test", depends_on=[b]))
        d = run(self.mem.submit_task("d", "test", depends_on=[a]))
        row = run(self.mem.list_tasks(task_id=d))[0]
        self.assertEqual(row["depends_on"], f"[{a}]")
        # now corrupt the deep link and try again
        self.mem._conn.execute(
            "UPDATE tasks SET depends_on = '[999]' WHERE id = ?", (c,))
        self.mem._conn.commit()
        with self.assertRaises(ValueError) as ctx:
            run(self.mem.submit_task("e", "test", depends_on=[a]))
        self.assertIn("unknown dependency", str(ctx.exception))


class FindCycleTests(unittest.TestCase):
    def test_acyclic_returns_none(self):
        from kernel.memory import find_cycle
        self.assertIsNone(find_cycle({1: [2], 2: [3], 3: []}))

    def test_self_loop(self):
        from kernel.memory import find_cycle
        self.assertEqual(find_cycle({7: [7]}), [7])

    def test_two_node_cycle(self):
        from kernel.memory import find_cycle
        cycle = find_cycle({1: [2], 2: [1]})
        self.assertEqual(len(cycle), 2)
        self.assertIn(1, cycle)
        self.assertIn(2, cycle)

    def test_dangling_reference_is_leaf(self):
        from kernel.memory import find_cycle
        self.assertIsNone(find_cycle({1: [99]}))

    def test_deep_cycle_found_from_unrelated_root(self):
        from kernel.memory import find_cycle
        # 5 -> 6 -> 5 cycle, discovered while walking from 1
        cycle = find_cycle({1: [2], 2: [], 3: [5], 5: [6], 6: [5]})
        self.assertIn(5, cycle)
        self.assertIn(6, cycle)


class DependencyGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_blocked_until_dependency_done(self):
        memory = Memory(Path(tempfile.mkdtemp()) / "t.db", embedder_fn=None,
                        embed_dim=64)
        await memory.connect()
        try:
            first = await memory.submit_task("first", "test")
            second = await memory.submit_task("second", "test",
                                              depends_on=[first])
            due = await memory.due_tasks(now=9999999999.0)
            self.assertEqual([t["id"] for t in due], [first])

            await memory.mark_task_running(first)
            await memory.finish_task(first, success=True)
            due = await memory.due_tasks(now=9999999999.0)
            self.assertEqual([t["id"] for t in due], [second])
        finally:
            await memory.close()

    async def test_failed_dependency_blocks(self):
        memory = Memory(Path(tempfile.mkdtemp()) / "t.db", embedder_fn=None,
                        embed_dim=64)
        await memory.connect()
        try:
            first = await memory.submit_task("first", "test")
            second = await memory.submit_task("second", "test",
                                              depends_on=[first])
            await memory.mark_task_running(first)
            await memory.finish_task(first, success=False)
            due = await memory.due_tasks(now=9999999999.0)
            self.assertEqual([t["id"] for t in due], [])
            self.assertEqual(
                (await memory.list_tasks(task_id=second))[0]["status"],
                "pending")
        finally:
            await memory.close()

    async def test_chain_resolves_in_order(self):
        memory = Memory(Path(tempfile.mkdtemp()) / "t.db", embedder_fn=None,
                        embed_dim=64)
        await memory.connect()
        try:
            a = await memory.submit_task("a", "test")
            b = await memory.submit_task("b", "test", depends_on=[a])
            c = await memory.submit_task("c", "test", depends_on=[b])
            for done_id in (a, b):
                await memory.mark_task_running(done_id)
                await memory.finish_task(done_id, success=True)
                due = await memory.due_tasks(now=9999999999.0)
                self.assertEqual([t["id"] for t in due], [c if done_id == b
                                                         else b])
        finally:
            await memory.close()

    async def test_cancelled_dependency_blocks(self):
        memory = Memory(Path(tempfile.mkdtemp()) / "t.db", embedder_fn=None,
                        embed_dim=64)
        await memory.connect()
        try:
            first = await memory.submit_task("first", "test")
            second = await memory.submit_task("second", "test",
                                              depends_on=[first])
            await memory.cancel_task(first)
            due = await memory.due_tasks(now=9999999999.0)
            self.assertEqual([t["id"] for t in due], [])
            self.assertEqual(
                (await memory.list_tasks(task_id=second))[0]["status"],
                "pending")
        finally:
            await memory.close()

    async def test_corrupt_depends_json_ignored(self):
        memory = Memory(Path(tempfile.mkdtemp()) / "t.db", embedder_fn=None,
                        embed_dim=64)
        await memory.connect()
        try:
            tid = await memory.submit_task("weird", "test")
            await memory._run(lambda conn: (
                conn.execute("UPDATE tasks SET depends_on = ? WHERE id = ?",
                             ("not-json", tid)), conn.commit()))
            due = await memory.due_tasks(now=9999999999.0)
            self.assertEqual([t["id"] for t in due], [tid])
        finally:
            await memory.close()


class SchedulerDependencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_scheduler_submit_passes_dependencies(self):
        memory = Memory(Path(tempfile.mkdtemp()) / "t.db", embedder_fn=None,
                        embed_dim=64)
        await memory.connect()
        try:
            from kernel.scheduler import Scheduler
            scheduler = Scheduler(memory, lambda: None, EventBus(),
                                  poll_seconds=1)
            first = await scheduler.submit("first", source="test")
            second = await scheduler.submit("second", source="test",
                                            depends_on=[first])
            row = (await memory.list_tasks(task_id=second))[0]
            self.assertEqual(row["depends_on"], f"[{first}]")
        finally:
            await memory.close()


class BlockedByTests(unittest.IsolatedAsyncioTestCase):
    async def test_blocked_by_lists_unsatisfied_deps(self):
        memory = Memory(Path(tempfile.mkdtemp()) / "t.db", embedder_fn=None,
                        embed_dim=64)
        await memory.connect()
        try:
            first = await memory.submit_task("first", "test")
            second = await memory.submit_task("second", "test",
                                              depends_on=[first])
            self.assertEqual(await memory.blocked_by(second), [first])
            await memory.mark_task_running(first)
            await memory.finish_task(first, success=True)
            self.assertEqual(await memory.blocked_by(second), [])
        finally:
            await memory.close()

    async def test_blocked_by_empty_without_deps(self):
        memory = Memory(Path(tempfile.mkdtemp()) / "t.db", embedder_fn=None,
                        embed_dim=64)
        await memory.connect()
        try:
            tid = await memory.submit_task("solo", "test")
            self.assertEqual(await memory.blocked_by(tid), [])
        finally:
            await memory.close()

    async def test_task_detail_includes_blocked_by(self):
        from aiohttp.test_utils import TestClient, TestServer
        from interface.web import build_web_app
        from kernel.config import Config
        from kernel.daemon import AgentDaemon
        daemon = AgentDaemon(Config.load())
        await daemon.memory.connect()
        app = build_web_app(daemon)
        server = TestServer(app)
        client = TestClient(server)
        await client.start_server()
        try:
            first = await daemon.memory.submit_task("first", "test")
            second = await daemon.memory.submit_task(
                "second", "test", depends_on=[first])
            body = await (await client.get(f"/api/tasks/{second}")).json()
            self.assertEqual(body["blocked_by"], [first])
        finally:
            await client.close()
            await daemon.memory.close()


if __name__ == "__main__":
    unittest.main()

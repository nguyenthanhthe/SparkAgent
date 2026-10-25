"""sqlite_query tool — read-only agent-database lookups."""

import asyncio
import tempfile
import unittest
from pathlib import Path

from kernel.errors import ToolFailure
from kernel.memory import Memory
from tools.registry import ToolContext, ToolRegistry
from tools.sqlite_query import register_tools


def make_ctx():
    return ToolContext(source="test", episode_id=None)


class SqliteQueryTests(unittest.TestCase):
    def setUp(self):
        async def build():
            db = Path(tempfile.mkdtemp()) / "t.db"
            mem = Memory(db, embedder_fn=None, embed_dim=64)
            await mem.connect()
            await mem.submit_task("check the flux capacitor", "test")
            await mem.submit_task("water the plants", "test")
            await mem.audit("tester", "test.action", "detail here")
            return mem
        self.mem = asyncio.run(build())
        self.registry = ToolRegistry()
        register_tools(self.registry, self.mem.db_path)
        self.tool = self.registry.get("sqlite_query")

    def tearDown(self):
        if self.mem._conn:
            self.mem._conn.close()

    def call(self, **args):
        return asyncio.run(self.tool.handler(make_ctx(), **args))

    def test_list_tasks(self):
        result = self.call(table="tasks")
        self.assertEqual(result["count"], 2)
        goals = {row["goal"] for row in result["rows"]}
        self.assertIn("check the flux capacitor", goals)

    def test_where_filter_and_projection(self):
        result = self.call(table="tasks", columns=["goal"],
                           where={"goal": "water the plants"})
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["rows"][0]["goal"], "water the plants")
        self.assertNotIn("status", result["rows"][0])

    def test_order_by_descending(self):
        result = self.call(table="tasks", order_by="id", descending=True,
                           limit=1)
        first = result["rows"][0]
        all_ids = [r["id"] for r in self.call(table="tasks")["rows"]]
        self.assertEqual(first["id"], max(all_ids))

    def test_unknown_table_rejected(self):
        with self.assertRaises(ToolFailure):
            self.call(table="sqlite_master")

    def test_unknown_column_projection_rejected(self):
        with self.assertRaises(ToolFailure):
            self.call(table="tasks", columns=["nope"])

    def test_row_cap_clamped(self):
        result = self.call(table="tasks", limit=10000)
        self.assertLessEqual(result["count"], 100)

    def test_where_term_cap_enforced(self):
        with self.assertRaises(ToolFailure):
            self.call(table="tasks",
                      where={"a": 1, "b": 2, "c": 3, "d": 4, "e": 5})

    def test_audit_rows_visible(self):
        result = self.call(table="audit", limit=5)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["rows"][0]["actor"], "tester")

    def test_write_impossible_by_connection_mode(self):
        # even if a write slipped into the API, mode=ro refuses it
        import sqlite3
        connection = sqlite3.connect(
            f"file:{self.mem.db_path}?mode=ro", uri=True)
        with self.assertRaises(sqlite3.OperationalError):
            connection.execute(
                "INSERT INTO audit (created_at, actor, action) "
                "VALUES ('2026-01-01', 'x', 'y')")
        connection.close()


if __name__ == "__main__":
    unittest.main()

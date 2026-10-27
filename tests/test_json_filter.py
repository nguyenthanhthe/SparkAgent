"""json_query mode=filter — numeric comparison terms over list rows."""

import unittest

from kernel.errors import ToolFailure
from tools.json_tool import filter_rows

ROWS = [
    {"name": "alice", "age": 30, "status": "active"},
    {"name": "bob", "age": 22, "status": "done"},
    {"name": "carol", "age": 41, "status": "active"},
]


class FilterRowsTests(unittest.TestCase):
    def test_numeric_gte(self):
        result = filter_rows(ROWS, "age>=30")
        self.assertEqual([r["name"] for r in result], ["alice", "carol"])

    def test_numeric_lt(self):
        result = filter_rows(ROWS, "age<30")
        self.assertEqual([r["name"] for r in result], ["bob"])

    def test_string_equality(self):
        result = filter_rows(ROWS, "status=active")
        self.assertEqual([r["name"] for r in result], ["alice", "carol"])

    def test_string_inequality(self):
        result = filter_rows(ROWS, "status!=active")
        self.assertEqual([r["name"] for r in result], ["bob"])

    def test_combined_terms_are_and(self):
        result = filter_rows(ROWS, "status=active;age>35")
        self.assertEqual([r["name"] for r in result], ["carol"])

    def test_missing_key_never_matches(self):
        result = filter_rows(ROWS, "department=ops")
        self.assertEqual(result, [])

    def test_null_value_excluded(self):
        result = filter_rows([{"age": None}, {"age": 5}], "age>0")
        self.assertEqual(len(result), 1)

    def test_bad_term_rejected(self):
        with self.assertRaises(ValueError):
            filter_rows(ROWS, "age 30")

    def test_too_many_terms_rejected(self):
        where = ";".join(f"age>{i}" for i in range(9))
        with self.assertRaises(ValueError):
            filter_rows(ROWS, where)


class JsonQueryFilterToolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import json
        from tools.registry import ToolContext, ToolRegistry
        from tools import stdlib_tools
        self.registry = ToolRegistry()
        stdlib_tools.register_tools(self.registry)
        self.ctx = ToolContext()
        self.rows_json = json.dumps(ROWS)

    async def test_tool_filter_mode(self):
        result = await self.registry.call(
            "json_query", {"data": self.rows_json, "mode": "filter",
                           "where": "age>=30"}, self.ctx)
        self.assertIn("alice", result)
        self.assertIn("carol", result)
        self.assertNotIn("bob", result)

    async def test_tool_filter_needs_list(self):
        from kernel.errors import ToolFailure
        with self.assertRaises(ToolFailure):
            await self.registry.call(
                "json_query", {"data": '{"a": 1}', "mode": "filter",
                               "where": "a=1"}, self.ctx)

    async def test_tool_filter_bad_term(self):
        from kernel.errors import ToolFailure
        with self.assertRaises(ToolFailure):
            await self.registry.call(
                "json_query", {"data": self.rows_json, "mode": "filter",
                               "where": "nope"}, self.ctx)


if __name__ == "__main__":
    unittest.main()

"""json_query mode=filter — numeric comparison terms over list rows."""

import unittest

from kernel.errors import ToolFailure
from tools.json_tool import filter_rows, first_row, group_rows, \
    pluck, sort_rows, stats, unique_values

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

    def test_boolean_coercion(self):
        rows = [{"enabled": True}, {"enabled": False}]
        self.assertEqual(len(filter_rows(rows, "enabled=1")), 1)
        self.assertEqual(len(filter_rows(rows, "enabled=true")), 1)
        self.assertEqual(len(filter_rows(rows, "enabled=0")), 1)
        self.assertEqual(len(filter_rows(rows, "enabled!=1")), 1)

    def test_contains_operator(self):
        result = filter_rows(ROWS, "name~=lic")
        self.assertEqual([r["name"] for r in result], ["alice"])
        # case-insensitive
        result = filter_rows(ROWS, "name~=BOB")
        self.assertEqual([r["name"] for r in result], ["bob"])
        # substring of the needle never matches
        self.assertEqual(filter_rows(ROWS, "name~=zorro"), [])

    def test_bad_term_rejected(self):
        with self.assertRaises(ValueError):
            filter_rows(ROWS, "age 30")

    def test_too_many_terms_rejected(self):
        where = ";".join(f"age>{i}" for i in range(9))
        with self.assertRaises(ValueError):
            filter_rows(ROWS, where)


class SortRowsTests(unittest.TestCase):
    def test_numeric_ascending_and_descending(self):
        rows = [{"n": 3}, {"n": 1}, {"n": 2}]
        self.assertEqual([r["n"] for r in sort_rows(rows, "n")], [1, 2, 3])
        self.assertEqual([r["n"] for r in sort_rows(rows, "n", True)],
                         [3, 2, 1])

    def test_numeric_strings_not_lexical(self):
        rows = [{"n": 10}, {"n": 9}]
        self.assertEqual([r["n"] for r in sort_rows(rows, "n")], [9, 10])

    def test_string_sort(self):
        rows = [{"s": "b"}, {"s": "a"}]
        self.assertEqual([r["s"] for r in sort_rows(rows, "s")], ["a", "b"])

    def test_missing_keys_sort_last_even_descending(self):
        rows = [{"n": 2}, {"x": 0}, {"n": 1}]
        self.assertEqual([r.get("n") for r in sort_rows(rows, "n")],
                         [1, 2, None])
        self.assertEqual([r.get("n") for r in sort_rows(rows, "n", True)],
                         [2, 1, None])

    def test_dotted_key(self):
        rows = [{"m": {"v": 2}}, {"m": {"v": 1}}]
        self.assertEqual([r["m"]["v"] for r in sort_rows(rows, "m.v")],
                         [1, 2])


class JsonQuerySortToolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from tools.registry import ToolContext, ToolRegistry
        from tools import stdlib_tools
        self.registry = ToolRegistry()
        stdlib_tools.register_tools(self.registry)
        self.ctx = ToolContext()

    async def test_tool_sort_mode(self):
        import json
        result = await self.registry.call(
            "json_query", {"data": json.dumps([{"n": 2}, {"n": 1}]),
                           "mode": "sort", "sort_by": "n"}, self.ctx)
        self.assertIn("1", result)
        self.assertTrue(result.index("1") < result.index("2"))

    async def test_tool_sort_needs_list(self):
        from kernel.errors import ToolFailure
        with self.assertRaises(ToolFailure):
            await self.registry.call(
                "json_query", {"data": '{"a": 1}', "mode": "sort",
                               "sort_by": "a"}, self.ctx)


class FirstRowTests(unittest.TestCase):
    def test_first_and_last(self):
        self.assertEqual(first_row(ROWS)["name"], "alice")
        self.assertEqual(first_row(ROWS, last=True)["name"], "carol")

    def test_filter_applied_before_pick(self):
        row = first_row(ROWS, where="status=active;age>35")
        self.assertEqual(row["name"], "carol")
        self.assertIsNone(first_row(ROWS, where="age>999"))

    def test_empty_list_is_none(self):
        self.assertIsNone(first_row([]))
        self.assertIsNone(first_row([], last=True))


class JsonQueryFirstLastToolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import json
        from tools.registry import ToolContext, ToolRegistry
        from tools import stdlib_tools
        self.registry = ToolRegistry()
        stdlib_tools.register_tools(self.registry)
        self.ctx = ToolContext()
        self.rows_json = json.dumps(ROWS)

    async def test_tool_first_with_where(self):
        result = await self.registry.call(
            "json_query", {"data": self.rows_json, "mode": "first",
                           "where": "status=done"}, self.ctx)
        self.assertIn("bob", result)

    async def test_tool_last(self):
        result = await self.registry.call(
            "json_query", {"data": self.rows_json, "mode": "last"},
            self.ctx)
        self.assertIn("carol", result)

    async def test_tool_no_match_is_null(self):
        result = await self.registry.call(
            "json_query", {"data": self.rows_json, "mode": "first",
                           "where": "age>999"}, self.ctx)
        self.assertIn("null", result)


class GroupRowsTests(unittest.TestCase):
    def test_counts_per_value_descending(self):
        groups = group_rows(ROWS, "status")
        self.assertEqual(groups, {"active": 2, "done": 1})

    def test_missing_key_bucket(self):
        groups = group_rows([{"a": 1}, {"status": "x"}], "status")
        self.assertEqual(groups.get("x"), 1)
        self.assertEqual(groups.get(""), 1)

    def test_non_dict_rows_bucket_empty(self):
        groups = group_rows(["bare", {"status": "y"}], "status")
        self.assertEqual(groups, {"y": 1, "": 1})


class JsonQueryGroupToolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import json
        from tools.registry import ToolContext, ToolRegistry
        from tools import stdlib_tools
        self.registry = ToolRegistry()
        stdlib_tools.register_tools(self.registry)
        self.ctx = ToolContext()
        self.rows_json = json.dumps(ROWS)

    async def test_tool_group_mode(self):
        result = await self.registry.call(
            "json_query", {"data": self.rows_json, "mode": "group",
                           "sort_by": "status"}, self.ctx)
        self.assertIn("active", result)
        self.assertIn("2", result)

    async def test_tool_group_applies_where_first(self):
        result = await self.registry.call(
            "json_query", {"data": self.rows_json, "mode": "group",
                           "sort_by": "status", "where": "age>=30"},
            self.ctx)
        self.assertIn("active", result)
        self.assertNotIn("done", result)

    async def test_tool_sort_applies_where_first(self):
        result = await self.registry.call(
            "json_query", {"data": self.rows_json, "mode": "sort",
                           "sort_by": "age", "where": "status=done"},
            self.ctx)
        self.assertIn("bob", result)
        self.assertNotIn("alice", result)

    async def test_tool_pluck_applies_where_first(self):
        result = await self.registry.call(
            "json_query", {"data": self.rows_json, "mode": "pluck",
                           "sort_by": "name", "where": "status=done"},
            self.ctx)
        self.assertIn("bob", result)
        self.assertNotIn("alice", result)

    async def test_tool_unique_applies_where_first(self):
        result = await self.registry.call(
            "json_query", {"data": self.rows_json, "mode": "unique",
                           "sort_by": "name", "where": "age>=30"},
            self.ctx)
        self.assertIn("alice", result)
        self.assertNotIn("bob", result)

    async def test_tool_group_needs_list(self):
        from kernel.errors import ToolFailure
        with self.assertRaises(ToolFailure):
            await self.registry.call(
                "json_query", {"data": '{"a": 1}', "mode": "group",
                               "sort_by": "a"}, self.ctx)


class UniqueValuesTests(unittest.TestCase):
    def test_distinct_sorted(self):
        rows = [{"s": "b"}, {"s": "a"}, {"s": "b"}, {"x": 1}]
        self.assertEqual(unique_values(rows, "s"), ["a", "b"])

    def test_dotted_key_and_numbers(self):
        rows = [{"m": {"v": 2}}, {"m": {"v": 10}}, {"m": {"v": 2}}]
        self.assertEqual(unique_values(rows, "m.v"), ["10", "2"])


class PluckTests(unittest.TestCase):
    def test_extracts_in_order(self):
        rows = [{"n": 3}, {"n": 1}, {"n": 2}]
        self.assertEqual(pluck(rows, "n"), [3, 1, 2])

    def test_missing_keys_become_none(self):
        self.assertEqual(pluck([{"n": 1}, {"x": 2}, "bare"], "n"),
                         [1, None, None])

    def test_dotted_key(self):
        rows = [{"m": {"v": "a"}}, {"m": {"v": "b"}}]
        self.assertEqual(pluck(rows, "m.v"), ["a", "b"])


class StatsNestingTests(unittest.TestCase):
    def test_nesting_summarizes_nested_dicts(self):
        data = {"a": {"b": {"c": 1}}, "d": 2}
        nesting = stats(data)["nesting"]
        self.assertEqual(nesting["a"], 1)
        self.assertEqual(nesting["a.b"], 1)
        self.assertNotIn("d", nesting)          # scalar, not a dict
        self.assertEqual(stats([1, 2])["nesting"], {})

    def test_nesting_depth_capped(self):
        deep = {"l1": {"l2": {"l3": {"l4": {"l5": 1}}}}}
        nesting = stats(deep)["nesting"]
        self.assertIn("l1.l2.l3", nesting)      # depth 3 is the cap
        self.assertNotIn("l1.l2.l3.l4", nesting)


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
